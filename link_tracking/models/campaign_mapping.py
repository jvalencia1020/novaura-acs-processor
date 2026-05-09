from django.conf import settings
from django.db import models
from django.db.models import Q
from external_models.models.external_references import Campaign
# LeadNurturingCampaign: use string ref below to avoid circular import (external_models -> journeys -> link_tracking -> campaign_mapping -> external_models)


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
    media_campaign = models.ForeignKey(
        'planning.MediaCampaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name='link_campaign_crm_mappings',
        help_text=(
            'Optional planning media campaign attribution; must belong to the same '
            'CRM campaign as this mapping when set.'
        ),
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
        constraints = [
            models.UniqueConstraint(
                fields=['link_campaign', 'crm_campaign', 'media_campaign'],
                name='uniq_link_crm_media_campaign',
            ),
            models.UniqueConstraint(
                fields=['link_campaign', 'crm_campaign'],
                condition=Q(media_campaign__isnull=True),
                name='uniq_link_crm_no_media_campaign',
            ),
        ]
        indexes = [
            models.Index(fields=['link_campaign', 'crm_campaign', 'media_campaign']),
            models.Index(fields=['crm_campaign', 'media_campaign', 'is_active']),
        ]
        ordering = ['-start_date', '-created_at']

    def __str__(self):
        return f"{self.link_campaign.campaign_id} → {self.crm_campaign.name}"

    def clean(self):
        super().clean()
        if self.media_campaign_id:
            if not self.crm_campaign_id:
                raise ValidationError(
                    {'media_campaign': 'CRM campaign is required when media campaign is set.'}
                )
            if self.media_campaign.crm_campaign_id != self.crm_campaign_id:
                raise ValidationError(
                    {'media_campaign': 'Media campaign must belong to the selected CRM campaign.'}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_current(self):
        """Alias for is_active (for API backward compatibility)."""
        return self.is_active


class LinkCampaignNurturingCampaignMapping(models.Model):
    """
    Maps a link_tracking LinkCampaign to one or more acs.LeadNurturingCampaign(s)
    for scoping links to nurturing campaigns. One LinkCampaign can be used in multiple
    nurturing campaigns. Use start_date/end_date and is_active for current vs historical.
    """

    link_campaign = models.ForeignKey(
        'link_tracking.LinkCampaign',
        on_delete=models.CASCADE,
        related_name='nurturing_campaign_mappings',
    )
    nurturing_campaign = models.ForeignKey(
        'external_models.LeadNurturingCampaign',
        on_delete=models.CASCADE,
        related_name='link_campaign_mappings',
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
        db_table = 'link_tracking_link_campaign_nurturing_mappings'
        unique_together = [['link_campaign', 'nurturing_campaign']]
        ordering = ['-start_date', '-created_at']

    def __str__(self):
        return f"{self.link_campaign.campaign_id} → {self.nurturing_campaign.name}"

    @property
    def is_current(self):
        """Alias for is_active (for API backward compatibility)."""
        return self.is_active