from django.db import models

class CampaignScheduleBase(models.Model):
    """Base model for campaign scheduling"""
    business_hours_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        managed = False


class CampaignProgressBase(models.Model):
    """Base model for campaign progress tracking"""
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        managed = False 