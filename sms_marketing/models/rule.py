from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from marketing_tracking.models import Keyword


class SmsKeywordRule(models.Model):
    """
    Defines keyword → action mapping for SMS campaigns.
    """
    MATCH_TYPE_CHOICES = [
        ('exact', 'Exact Match'),
        ('starts_with', 'Starts With'),
        ('contains', 'Contains'),
    ]

    campaign = models.ForeignKey(
        'SmsKeywordCampaign',
        on_delete=models.CASCADE,
        related_name='rules',
        help_text='Campaign this rule belongs to'
    )
    keyword = models.ForeignKey(
        Keyword,
        on_delete=models.CASCADE,
        related_name='sms_keyword_rules',
        help_text='Keyword inventory item for this rule'
    )
    match_type = models.CharField(
        max_length=20,
        choices=MATCH_TYPE_CHOICES,
        default='exact',
        help_text='How to match the keyword'
    )
    priority = models.IntegerField(
        default=0,
        help_text='Priority for matching (higher = more priority)'
    )
    requires_not_opted_out = models.BooleanField(
        default=True,
        help_text='Require subscriber to not be opted out'
    )
    action_type = models.CharField(
        max_length=50,
        help_text='Type of action to take when keyword matches'
    )
    action_config = models.JSONField(
        blank=True,
        null=True,
        help_text='Configuration for the action'
    )

    # Short link to substitute into outbound messages (SMS processor uses this)
    short_link = models.ForeignKey(
        'link_tracking.Link',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_keyword_rules',
        help_text='Short link to insert into messages when sending for this rule',
    )

    # Keyword-level default messages (used as fallback when action_config doesn't specify)
    # Priority: action_config.* > rule.* > campaign.* > program.* > default
    # Note: opt_out_message and help_text are campaign-level only (not keyword-specific)
    initial_reply = models.TextField(
        blank=True,
        null=True,
        help_text='Initial reply message for this keyword (used when action_config.welcome_message is not set)'
    )
    confirmation_message = models.TextField(
        blank=True,
        null=True,
        help_text='Default confirmation message for double opt-in for this keyword (used when action_config.confirmation_message is not set)'
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this rule is active'
    )

    # Audit / lifecycle fields (soft end instead of hard delete)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_sms_keyword_rules',
        help_text='User who created this rule (if created via API/admin)'
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When this rule was ended (soft-deleted/unassigned/reassigned)'
    )
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ended_sms_keyword_rules',
        help_text='User who ended this rule (if ended via API/admin)'
    )
    end_reason = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='Reason this rule ended (e.g., deleted, reassigned)'
    )
    replaced_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replaced_rules',
        help_text='If ended due to reassignment, points to the replacement rule'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'sms_keyword_rule'
        constraints = [
            # Allow historical (ended) rules to coexist, but enforce only one current rule
            # per campaign+keyword.
            models.UniqueConstraint(
                fields=['campaign', 'keyword'],
                condition=Q(ended_at__isnull=True),
                name='uniq_active_sms_keyword_rule_campaign_keyword'
            )
        ]
        indexes = [
            models.Index(fields=['campaign', 'is_active']),
            models.Index(fields=['campaign', 'keyword']),
            models.Index(fields=['keyword', 'match_type']),
            models.Index(fields=['ended_at'], name='sms_keyword_rule_ended_at_idx'),
        ]
        ordering = ['-priority', 'keyword__keyword']

    def __str__(self):
        keyword_text = self.keyword.keyword if self.keyword else 'N/A'
        return f"{keyword_text} ({self.campaign.name})"

    def clean(self):
        """Validate rule data"""
        super().clean()
        if not self.campaign:
            raise ValidationError("Campaign is required")
        if not self.keyword:
            raise ValidationError("Keyword is required")
        if not self.action_type:
            raise ValidationError("Action type is required")
        
        # Validate that keyword's endpoint matches campaign's endpoint
        if self.keyword and self.campaign and self.campaign.endpoint:
            if self.keyword.endpoint != self.campaign.endpoint:
                raise ValidationError(
                    f"Keyword endpoint '{self.keyword.endpoint.value if self.keyword.endpoint else 'N/A'}' does not match "
                    f"campaign endpoint '{self.campaign.endpoint.value}'"
                )

    @property
    def is_ended(self) -> bool:
        return self.ended_at is not None

