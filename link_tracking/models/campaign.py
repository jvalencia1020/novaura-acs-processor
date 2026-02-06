from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from external_models.models.external_references import Account, Campaign
import uuid


class GlobalUTMPolicy(models.Model):
    """
    Singleton model for organization-wide UTM defaults.
    """

    default_utm_params = models.JSONField(
        default=dict,
        help_text='Organization-wide UTM defaults (e.g., always utm_source=sms)',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )

    class Meta:
        managed = False
        db_table = 'link_tracking_global_utm_policy'
        verbose_name = 'Global UTM Policy'
        verbose_name_plural = 'Global UTM Policy'

    def save(self, *args, **kwargs):
        if not self.pk and GlobalUTMPolicy.objects.exists():
            raise ValidationError('Only one Global UTM Policy can exist')
        super().save(*args, **kwargs)

    @classmethod
    def get_instance(cls):
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance

    def __str__(self):
        return "Global UTM Policy"


class LinkCampaign(models.Model):
    """
    Link-tracking campaign with UTM template, scoped to an account.
    CRM campaigns are associated via LinkCampaignCrmCampaignMapping (many-to-many).
    """

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='link_tracking_campaigns',
        null=True,
        blank=True,
        help_text='Account this link campaign belongs to (required for new campaigns; backfill existing)',
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    campaign_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text='Short-link campaign identifier (e.g., spring24)',
    )

    utm_template = models.JSONField(
        default=dict,
        help_text='Campaign-level UTM template. Supports: ${slug}, ${campaign_id}, ${keyword}, ${channel}, etc.',
    )

    active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='link_tracking_link_campaigns_created',
    )

    class Meta:
        managed = False
        db_table = 'link_tracking_campaigns'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['campaign_id']),
            models.Index(fields=['active']),
            models.Index(fields=['account']),
        ]
        # campaign_id unique per account (same id can exist in different accounts)
        unique_together = [['account', 'campaign_id']]

    def __str__(self):
        return f"{self.name} ({self.campaign_id})"

    def link_count(self):
        return self.links.count()

    def active_link_count(self):
        return self.links.filter(active=True).count()
