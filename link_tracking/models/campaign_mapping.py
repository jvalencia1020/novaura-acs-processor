from django.conf import settings
from django.db import models
from external_models.models.external_references import Campaign


class LinkCampaignCrmCampaignMapping(models.Model):
    """
    Maps a link_tracking LinkCampaign to one or more crm.Campaign(s)
    for attribution and reporting. One LinkCampaign can be used in multiple CRM campaigns
    over time. Use start_date/end_date to record when each mapping was in effect;
    end_date is null for the current mapping(s).
    """

    link_campaign = models.ForeignKey(
        'link_tracking.LinkCampaign',
        on_delete=models.CASCADE,
        related_name='crm_campaign_mappings',
    )
    crm_campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='link_tracking_campaign_mappings',
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
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        managed = False
        db_table = 'link_tracking_link_campaign_crm_campaign_mappings'
        unique_together = [['link_campaign', 'crm_campaign']]
        ordering = ['-start_date', '-created_at']

    def __str__(self):
        return f"{self.link_campaign.campaign_id} → {self.crm_campaign.name}"

    @property
    def is_current(self):
        """Alias for is_active (for API backward compatibility)."""
        return self.is_active
