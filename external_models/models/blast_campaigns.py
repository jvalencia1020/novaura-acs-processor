from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from .nurturing_campaign_base import CampaignScheduleBase, CampaignProgressBase


class BlastCampaignSchedule(CampaignScheduleBase):
    """Schedule settings for blast campaigns"""
    campaign = models.OneToOneField('LeadNurturingCampaign', on_delete=models.CASCADE, related_name='blast_schedule')
    send_time = models.DateTimeField()
    timezone = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Timezone for blast scheduling (defaults to CRM campaign timezone)"
    )

    class Meta:
        managed = False
        db_table = 'acs_blastcampaignschedule'


class BlastCampaignProgress(CampaignProgressBase):
    """Tracks progress for blast campaigns"""
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE, related_name='blast_campaign_progress')
    message_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'blast_campaign_progress'
        indexes = [
            models.Index(fields=['message_sent']),
            models.Index(fields=['sent_at']),
        ] 