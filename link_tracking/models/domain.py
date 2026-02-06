from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
import uuid


class Domain(models.Model):
    """
    Short link domain (e.g., go.novaura.io).
    Optionally linked to marketing_tracking.URLDomain.
    """

    class Purpose(models.TextChoices):
        PRIMARY = 'primary', 'Primary'
        BACKUP = 'backup', 'Backup'
        QUARANTINE = 'quarantine', 'Quarantine'
        CLIENT = 'client', 'Client-Specific'

    class Status(models.TextChoices):
        HEALTHY = 'healthy', 'Healthy'
        DEGRADED = 'degraded', 'Degraded'
        FLAGGED = 'flagged', 'Flagged'
        DISABLED = 'disabled', 'Disabled'

    # Optional FK to existing URLDomain (marketing_tracking)
    url_domain = models.OneToOneField(
        'marketing_tracking.URLDomain',
        on_delete=models.SET_NULL,
        related_name='short_link_domain',
        null=True,
        blank=True,
        help_text='Associated URLDomain from marketing_tracking (if applicable)',
    )

    # Primary fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain_name = models.CharField(
        max_length=255,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}$',
                message='Enter a valid domain name',
            )
        ],
        help_text='e.g., go.novaura.io',
    )
    purpose = models.CharField(
        max_length=20,
        choices=Purpose.choices,
        default=Purpose.PRIMARY,
    )
    active = models.BooleanField(
        default=False,
        help_text='If false, links on this domain will not redirect',
    )

    # Health monitoring
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.HEALTHY,
    )
    health_score = models.FloatField(
        default=100.0,
        help_text='0-100, computed from carrier/safe browsing checks',
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)

    carrier_status = models.JSONField(
        default=dict,
        blank=True,
        help_text='Per-carrier flags: {carrier: {status, last_check, notes}}',
    )
    safe_browsing_status = models.JSONField(
        default=dict,
        blank=True,
        help_text='Results from Google Safe Browsing / VirusTotal',
    )

    # Domain warming
    warming_started_at = models.DateTimeField(null=True, blank=True)
    warming_completed_at = models.DateTimeField(null=True, blank=True)

    class WarmingPhase(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not Started'
        TEST = 'test', 'Test Traffic (Week 1-2)'
        RAMP = 'ramp', 'Ramp Up (Week 3-4)'
        PRODUCTION = 'production', 'Production (Week 5+)'

    warming_phase = models.CharField(
        max_length=20,
        choices=WarmingPhase.choices,
        default=WarmingPhase.NOT_STARTED,
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='link_tracking_domains_created',
    )

    class Meta:
        managed = False
        db_table = 'link_tracking_domains'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['domain_name']),
            models.Index(fields=['active', 'status']),
        ]

    def __str__(self):
        return f"{self.domain_name} ({self.get_purpose_display()})"

    def is_warming_complete(self):
        if not self.warming_started_at:
            return False
        days_since_start = (timezone.now() - self.warming_started_at).days
        return days_since_start >= 35 and self.health_score > 80

    def days_since_warming_started(self):
        if not self.warming_started_at:
            return 0
        return (timezone.now() - self.warming_started_at).days
