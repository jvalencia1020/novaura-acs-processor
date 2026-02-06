from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings

from external_models.models.external_references import Account, Campaign
from external_models.models.communications import ContactEndpoint
from external_models.models.messages import MessageTemplate
from external_models.models.nurturing_campaigns import LeadNurturingCampaign

class SmsKeywordCampaignCrmCampaign(models.Model):
    """
    Intermediate model for many-to-many relationship between SMS campaigns and CRM campaigns.
    Use start_date/end_date to record when each mapping was in effect; is_active marks current vs historical.
    """
    sms_campaign = models.ForeignKey(
        'SmsKeywordCampaign',
        on_delete=models.CASCADE,
        related_name='crm_campaign_relations'
    )
    crm_campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='sms_campaign_relations'
    )
    is_primary = models.BooleanField(
        default=False,
        help_text='Indicates if this is the primary CRM campaign for the SMS campaign'
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        help_text='When this mapping became effective. Null means from creation.',
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text='When this mapping ended. Null means still current.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Explicitly mark this mapping as active (in use) or inactive (historical).',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_sms_crm_campaigns'
    )

    class Meta:
        managed = False
        db_table = 'sms_keyword_campaign_crm_campaign'
        unique_together = ('sms_campaign', 'crm_campaign')
        indexes = [
            models.Index(fields=['sms_campaign', 'crm_campaign']),
            models.Index(fields=['is_primary']),
        ]
        ordering = ['-start_date', '-assigned_at']

    def __str__(self):
        return f"{self.sms_campaign.name} → {self.crm_campaign.name}"

    @property
    def is_current(self):
        """Alias for is_active (for API backward compatibility)."""
        return self.is_active


class SmsKeywordCampaign(models.Model):
    """
    Container for keyword rules tied to CRM campaigns and SMS endpoint.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('archived', 'Archived'),
    ]

    OPT_IN_MODE_CHOICES = [
        ('single', 'Single Opt-in'),
        ('double', 'Double Opt-in'),
        ('none', 'No Opt-in'),
    ]

    # Required relationships
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='sms_keyword_campaigns',
        help_text='Account this campaign belongs to'
    )
    endpoint = models.ForeignKey(
        ContactEndpoint,
        on_delete=models.CASCADE,
        related_name='sms_keyword_campaigns',
        help_text='SMS endpoint for this campaign'
    )

    # Basic fields
    name = models.CharField(
        max_length=255,
        help_text='Campaign name'
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text='Campaign description'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        help_text='Campaign status'
    )
    priority = models.IntegerField(
        default=0,
        help_text='Priority for keyword matching (higher = more priority)'
    )

    # Opt-in configuration
    opt_in_mode = models.CharField(
        max_length=20,
        choices=OPT_IN_MODE_CHOICES,
        default='single',
        help_text='Opt-in mode for this campaign'
    )

    # Campaign-level default messages
    welcome_message = models.TextField(
        blank=True,
        null=True,
        help_text='Default welcome message (used when action_config.welcome_message is not set)'
    )
    opt_out_message = models.TextField(
        blank=True,
        null=True,
        help_text='Default opt-out confirmation message'
    )
    help_text = models.TextField(
        blank=True,
        null=True,
        help_text='Default help message (used when action_config.help_text is not set)'
    )
    confirmation_message = models.TextField(
        blank=True,
        null=True,
        help_text='Default confirmation message for double opt-in (used when action_config.confirmation_message is not set)'
    )

    # Opted-in fallback reply (used when NO keyword rule matches)
    # Priority recommendation for processor:
    # 1) opted_in_fallback_template (rendered) -> 2) opted_in_fallback_message -> 3) fallback_action_*
    opted_in_fallback_message = models.TextField(
        blank=True,
        null=True,
        help_text='Reply message for opted-in users when no keyword rule matches (fallback for opted-in users)'
    )
    opted_in_fallback_template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_marketing_opted_in_fallback_campaigns',
        help_text='ACS SMS template to render as reply for opted-in users when no keyword rule matches'
    )

    # Fallback configuration
    fallback_action_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='Action type when no keyword matches'
    )
    fallback_action_config = models.JSONField(
        blank=True,
        null=True,
        help_text='Configuration for fallback action'
    )

    # Optional program
    program = models.ForeignKey(
        'SmsProgram',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaigns',
        help_text='Optional program this campaign belongs to'
    )

    # Localization
    default_language = models.CharField(
        max_length=10,
        default='en',
        help_text='Default language code'
    )
    timezone = models.CharField(
        max_length=50,
        default='US/Eastern',
        help_text='Timezone for this campaign'
    )

    # Follow-up nurturing campaign
    follow_up_nurturing_campaign = models.ForeignKey(
        LeadNurturingCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_keyword_campaigns',
        help_text='Optional nurturing campaign for responders'
    )

    # Many-to-many relationship to CRM campaigns
    crm_campaigns = models.ManyToManyField(
        Campaign,
        through='SmsKeywordCampaignCrmCampaign',
        related_name='sms_keyword_campaigns',
        help_text='Associated CRM campaigns'
    )

    # Metadata
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_sms_keyword_campaigns'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'sms_keyword_campaign'
        indexes = [
            models.Index(fields=['account', 'status']),
            models.Index(fields=['endpoint', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['follow_up_nurturing_campaign']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.account.name})"

    def clean(self):
        """Validate campaign data"""
        super().clean()
        if not self.account:
            raise ValidationError("Account is required")
        if not self.endpoint:
            raise ValidationError("Endpoint is required")
        
        # Validate follow-up nurturing campaign belongs to same account
        if self.follow_up_nurturing_campaign:
            if self.follow_up_nurturing_campaign.account != self.account:
                raise ValidationError(
                    "Follow-up nurturing campaign must belong to the same account"
                )

    def get_active_rules_count(self):
        """Get count of active rules"""
        return self.rules.filter(is_active=True, ended_at__isnull=True).count()

    def get_rules_count(self):
        """Get total count of rules"""
        return self.rules.filter(ended_at__isnull=True).count()

    def get_primary_crm_campaign(self):
        """Get the primary CRM campaign if set"""
        relation = self.crm_campaign_relations.filter(is_primary=True).first()
        return relation.crm_campaign if relation else None
