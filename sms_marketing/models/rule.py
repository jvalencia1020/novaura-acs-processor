from django.db import models
from django.core.exceptions import ValidationError


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
        'marketing_tracking.Keyword',
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
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this rule is active'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'sms_keyword_rule'
        unique_together = ('campaign', 'keyword')
        indexes = [
            models.Index(fields=['campaign', 'is_active']),
            models.Index(fields=['campaign', 'keyword']),
            models.Index(fields=['keyword', 'match_type']),
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

