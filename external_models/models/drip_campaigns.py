from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from .nurturing_campaign_base import CampaignScheduleBase, CampaignProgressBase
from .channel_configs import EmailConfig, SMSConfig, VoiceConfig, ChatConfig


class DripCampaignMessageStep(models.Model):
    """Defines the message content and timing for each step in the drip sequence"""
    TIME_UNIT_CHOICES = [
        ('minutes', 'Minutes'),
        ('hours', 'Hours'),
        ('days', 'Days'),
    ]

    drip_schedule = models.ForeignKey(
        'DripCampaignSchedule',
        on_delete=models.CASCADE,
        related_name='message_steps'
    )
    order = models.PositiveIntegerField(help_text="Step number in the sequence, starting from 1")
    
    delay_units = models.PositiveIntegerField(default=1, help_text="How many units to delay after the previous message")
    delay_unit_type = models.CharField(
        max_length=10,
        choices=TIME_UNIT_CHOICES,
        default='hours',
        help_text="Unit of time for the delay"
    )
    
    # Channel config relationships
    email_config = models.OneToOneField(EmailConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    sms_config = models.OneToOneField(SMSConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    voice_config = models.OneToOneField(VoiceConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    chat_config = models.OneToOneField(ChatConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        managed = False
        db_table = 'acs_dripcampaignmessagestep'
        unique_together = [('drip_schedule', 'order')]
        ordering = ['order']

    def __str__(self):
        return f"Step {self.order} - {self.delay_units} {self.delay_unit_type}"

    def get_delay_timedelta(self):
        if self.delay_unit_type == 'minutes':
            return timedelta(minutes=self.delay_units)
        elif self.delay_unit_type == 'hours':
            return timedelta(hours=self.delay_units)
        elif self.delay_unit_type == 'days':
            return timedelta(days=self.delay_units)
        return timedelta()  # fallback

    def clean(self):
        super().clean()
        
        # Get the active channel config
        channel_config = self.get_channel_config()
        
        # Check that at least one channel config is provided
        if not any([self.email_config, self.sms_config, self.voice_config, self.chat_config]):
            raise ValidationError("At least one channel config must be provided")
        
        # Check that only one channel config is provided
        configs = [self.email_config, self.sms_config, self.voice_config, self.chat_config]
        if sum(1 for config in configs if config is not None) > 1:
            raise ValidationError("Only one channel config can be provided per step")
        
        # For drip campaigns, content is in the channel config
        if not self.template and not (channel_config and hasattr(channel_config, 'content') and channel_config.content):
            raise ValidationError("Either template or channel config content must be provided")

    def get_channel_config(self):
        """Get the active channel config for this step"""
        if self.email_config:
            return self.email_config
        elif self.sms_config:
            return self.sms_config
        elif self.voice_config:
            return self.voice_config
        elif self.chat_config:
            return self.chat_config
        return None

    def delete(self, *args, **kwargs):
        """Override delete to ensure channel configs are deleted"""
        # Delete associated channel configs
        if self.email_config:
            try:
                self.email_config.delete()
            except Exception as e:
                raise Exception(f"Error deleting email config: {str(e)}")
                
        if self.sms_config:
            try:
                self.sms_config.delete()
            except Exception as e:
                raise Exception(f"Error deleting SMS config: {str(e)}")
                
        if self.voice_config:
            try:
                self.voice_config.delete()
            except Exception as e:
                raise Exception(f"Error deleting voice config: {str(e)}")
                
        if self.chat_config:
            try:
                self.chat_config.delete()
            except Exception as e:
                raise Exception(f"Error deleting chat config: {str(e)}")
        
        try:
            # Call the parent delete method
            super().delete(*args, **kwargs)
        except Exception as e:
            raise Exception(f"Error deleting step: {str(e)}")


class DripCampaignSchedule(CampaignScheduleBase):
    """Schedule settings for drip campaigns"""
    campaign = models.OneToOneField('LeadNurturingCampaign', on_delete=models.CASCADE, related_name='drip_schedule')
    start_time = models.TimeField()
    end_time = models.TimeField()
    exclude_weekends = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'acs_dripcampaignschedule'

    def clean(self):
        super().clean()
        if self.start_time >= self.end_time:
            raise ValidationError("End time must be after start time")
        
        # Validate that message steps are properly ordered
        steps = self.message_steps.all()
        if steps.exists():
            step_numbers = set(step.order for step in steps)
            expected_numbers = set(range(1, len(step_numbers) + 1))
            if step_numbers != expected_numbers:
                raise ValidationError("Message steps must be ordered consecutively starting from 1")


class DripCampaignProgress(CampaignProgressBase):
    """Tracks progress for drip campaigns"""
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE, related_name='drip_campaign_progress')
    last_interval = models.DateTimeField(null=True, blank=True)
    current_step = models.ForeignKey(
        'DripCampaignMessageStep',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='progress'
    )
    next_scheduled_interval = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'drip_campaign_progress'
        indexes = [
            models.Index(fields=['last_interval']),
            models.Index(fields=['next_scheduled_interval']),
        ] 