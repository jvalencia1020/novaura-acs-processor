import uuid
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db.models import Sum
from external_models.models import Account, Campaign
from targeting.mixins import HasTargetingMixin


class MediaCampaign(HasTargetingMixin, models.Model):
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('paused', 'Paused'),
    ]

    ATTRIBUTION_MODEL_CHOICES = [
        ('first_click', 'First Click'),
        ('last_click', 'Last Click'),
        ('linear', 'Linear'),
        ('time_decay', 'Time Decay'),
        ('position_based', 'Position Based'),
        ('data_driven', 'Data Driven'),
    ]

    # UUID for API and stable references (Phase 1 omnichannel)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    # Core campaign setup fields
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True, help_text="Abbreviated campaign identifier")
    description = models.TextField()
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    crm_campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='media_campaigns')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_ongoing = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning')
    category = models.CharField(max_length=50, blank=True)
    media_type = models.ForeignKey(
        'catalog.MediaType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_campaigns',
        db_index=True,
        help_text='Catalog media type (e.g. Connected TV, Display).',
    )

    # Optional campaign configuration fields
    timezone = models.CharField(
        max_length=50,
        blank=True,
        default='US/Eastern',
        help_text='Timezone for the campaign (e.g., US/Eastern)'
    )
    attribution_model = models.CharField(
        max_length=20,
        choices=ATTRIBUTION_MODEL_CHOICES,
        blank=True,
        help_text='Attribution model for tracking conversions'
    )
    lookback_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Number of days to look back for attribution'
    )
    is_archived = models.BooleanField(
        default=False,
        help_text='Whether this campaign is archived'
    )

    # Override mixin's targeting_configuration to set related_name
    targeting_configuration = models.ForeignKey(
        "targeting.TargetingConfiguration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_campaigns',
        help_text='Targeting configuration for this media campaign'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'planning_mediacampaign'
        constraints = [
            models.CheckConstraint(
                check=models.Q(is_ongoing=False) | models.Q(end_date__isnull=True),
                name="check_media_campaign_ongoing_no_end_date"
            )
        ]

    def clean(self):
        """Validate campaign data"""
        super().clean()

        # Date validation
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("Campaign end date must be after start date")

        # is_ongoing validation
        if self.is_ongoing and self.end_date is not None:
            raise ValidationError("Ongoing campaigns cannot have an end date")

    def __str__(self):
        return self.name
