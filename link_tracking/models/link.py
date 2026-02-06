from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator, MinValueValidator
from django.core.exceptions import ValidationError
import uuid


class Link(models.Model):
    """
    Short link configuration.
    """

    class SlugType(models.TextChoices):
        SYSTEM = 'system', 'System Generated'
        VANITY = 'vanity', 'Vanity/Custom'

    class Channel(models.TextChoices):
        SMS = 'sms', 'SMS'
        EMAIL = 'email', 'Email'
        VOICE = 'voice', 'Voice'
        QR = 'qr', 'QR Code'
        OTHER = 'other', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    slug_type = models.CharField(
        max_length=10,
        choices=SlugType.choices,
        default=SlugType.SYSTEM,
    )
    slug_original = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Original slug as entered by user (for vanity slugs)',
    )
    slug_canonical = models.CharField(
        max_length=255,
        db_index=True,
        help_text='Canonical slug (uppercase, normalized)',
    )

    domain = models.ForeignKey(
        'Domain',
        on_delete=models.PROTECT,
        related_name='links',
    )
    campaign = models.ForeignKey(
        'LinkCampaign',
        on_delete=models.PROTECT,
        related_name='links',
    )

    campaign_identifier = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Campaign identifier (denormalized for performance)',
    )
    keyword = models.CharField(
        max_length=100,
        blank=True,
        help_text='Optional keyword text for UTM/attribution (e.g. HELP, LAW)',
    )
    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        default=Channel.SMS,
    )

    destination_url = models.TextField(
        help_text='Final destination URL (can include existing query params)',
    )
    fallback_url = models.TextField(
        blank=True,
        help_text='URL to redirect to if link is disabled/expired',
    )

    append_query_params = models.BooleanField(
        default=True,
        help_text='If false, destination URL is used as-is (passthrough mode)',
    )
    utm_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text='Override campaign/global UTM params for this link',
    )
    dynamic_param_allowlist = models.JSONField(
        default=list,
        blank=True,
        help_text='List of dynamic params runtime should append (default: ["click_id"])',
    )

    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Link expires after this timestamp',
    )
    max_clicks = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text='Circuit breaker: disable after N clicks',
    )

    signature_required = models.BooleanField(
        default=False,
        help_text='If true, require HMAC signature in query params',
    )
    signature_secret_ref = models.CharField(
        max_length=255,
        blank=True,
        help_text='Reference to AWS Secrets Manager secret (not the secret itself)',
    )

    routing_rules = models.JSONField(
        default=dict,
        blank=True,
        help_text='Routing logic (A/B test, geo, time-based, etc.)',
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text='Arbitrary tags for filtering/organization',
    )

    runtime_version = models.IntegerField(
        default=1,
        help_text='Increments on each publish to DynamoDB',
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='link_tracking_links_created',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='link_tracking_links_updated',
    )

    class Meta:
        managed = False
        db_table = 'link_tracking_links'
        ordering = ['-created_at']
        unique_together = [['domain', 'slug_canonical']]
        indexes = [
            models.Index(fields=['slug_canonical']),
            models.Index(fields=['campaign_identifier']),
            models.Index(fields=['active']),
            models.Index(fields=['domain', 'slug_canonical']),
        ]

    def __str__(self):
        return f"{self.domain.domain_name}/{self.slug_canonical}"

    def clean(self):
        super().clean()

        if self.slug_type == self.SlugType.VANITY:
            if not self.slug_original:
                raise ValidationError({'slug_original': 'Vanity slugs require original slug'})

            if not self.slug_original.replace('-', '').replace('_', '').isalnum():
                raise ValidationError({
                    'slug_original': 'Vanity slugs can only contain letters, numbers, hyphens, and underscores',
                })

            if len(self.slug_original) < 2 or len(self.slug_original) > 24:
                raise ValidationError({
                    'slug_original': 'Vanity slugs must be 2-24 characters',
                })

            reserved_words = [
                'admin', 'api', 'health', 'robots.txt', 'favicon.ico',
                'stop', 'help', 'unsubscribe', 'privacy', 'terms',
            ]
            if self.slug_original.lower() in reserved_words:
                raise ValidationError({
                    'slug_original': f'"{self.slug_original}" is a reserved word',
                })

        if not self.destination_url.startswith(('http://', 'https://')):
            raise ValidationError({
                'destination_url': 'Destination URL must start with http:// or https://',
            })

        if self.dynamic_param_allowlist:
            allowed_params = ['click_id', 'ab_variant', 'geo', 'click_ts', 'sms_msg_id']
            invalid = [p for p in self.dynamic_param_allowlist if p not in allowed_params]
            if invalid:
                raise ValidationError({
                    'dynamic_param_allowlist': f'Invalid params: {invalid}. Allowed: {allowed_params}',
                })

    def save(self, *args, **kwargs):
        if self.campaign:
            self.campaign_identifier = self.campaign.campaign_id or ''

        if self.slug_original:
            self.slug_canonical = self.slug_original.upper().strip()
        elif not self.slug_canonical and (self.campaign_identifier and self.domain_id):
            from link_tracking.services.slug_generator import SlugGenerator
            generator = SlugGenerator()
            self.slug_canonical = generator.generate_unique_slug(
                self.domain_id, self.campaign_identifier
            )

        if not self.dynamic_param_allowlist:
            self.dynamic_param_allowlist = ['click_id']

        super().save(*args, **kwargs)

    def get_full_url(self):
        """Return the full short URL (domain + slug_canonical)."""
        return f"https://{self.domain.domain_name}/{self.slug_canonical}"

    @property
    def short_link(self):
        """
        Alias for get_full_url() for ACS template variable replacement.
        When context['link'] is this Link instance, {{link.short_link}} resolves to this value.
        """
        return self.get_full_url()
