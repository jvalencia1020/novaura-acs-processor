from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from .nurturing_campaign_base import CampaignScheduleBase, CampaignProgressBase
from .channel_configs import EmailConfig, SMSConfig, VoiceConfig, ChatConfig


class ReminderCampaignSchedule(CampaignScheduleBase):
    """Schedule settings for reminder campaigns"""
    campaign = models.OneToOneField('LeadNurturingCampaign', on_delete=models.CASCADE, related_name='reminder_schedule')

    # New field to determine if we should use relative scheduling
    use_relative_schedule = models.BooleanField(
        default=False,
        help_text="If True, reminders will be scheduled relative to appointment time. If False, use absolute time of day."
    )

    class Meta:
        managed = False
        db_table = 'acs_remindercampaignschedule'


class ReminderTime(models.Model):
    """Individual reminder times for reminder campaigns"""
    schedule = models.ForeignKey(ReminderCampaignSchedule, on_delete=models.CASCADE, related_name='reminder_times')

    # Fields for absolute scheduling (specific time of day)
    days_before = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Days before the target date (for absolute scheduling)"
    )
    time = models.TimeField(
        null=True,
        blank=True,
        help_text="Time of day to send reminder (for absolute scheduling)"
    )

    # Fields for relative scheduling (time before appointment)
    days_before_relative = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Days before the appointment"
    )
    hours_before = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Hours before the appointment"
    )
    minutes_before = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Minutes before the appointment"
    )

    class Meta:
        managed = False
        db_table = 'acs_remindertime'
        ordering = ['days_before', 'days_before_relative', 'hours_before', 'minutes_before']
        unique_together = [
            ['schedule', 'days_before', 'time'],  # For absolute scheduling
            ['schedule', 'days_before_relative', 'hours_before', 'minutes_before']  # For relative scheduling
        ]

    def clean(self):
        """Validate reminder time configuration"""
        super().clean()

        # Check that either absolute or relative scheduling is used, not both
        absolute_fields = bool(self.days_before is not None and self.time is not None)
        relative_fields = bool(
            self.days_before_relative is not None or
            self.hours_before is not None or
            self.minutes_before is not None
        )

        if absolute_fields and relative_fields:
            raise ValidationError(
                "Cannot mix absolute and relative scheduling. Use either days_before/time "
                "or days/hours/minutes before."
            )

        # For absolute scheduling
        if self.schedule and not self.schedule.use_relative_schedule:
            if not absolute_fields:
                raise ValidationError(
                    "Absolute scheduling requires both days_before and time to be set"
                )
            if relative_fields:
                raise ValidationError(
                    "Cannot use relative scheduling fields when schedule is set to absolute"
                )

        # For relative scheduling
        if self.schedule and self.schedule.use_relative_schedule:
            if absolute_fields:
                raise ValidationError(
                    "Cannot use absolute scheduling fields when schedule is set to relative"
                )
            if not any([
                self.days_before_relative is not None,
                self.hours_before is not None,
                self.minutes_before is not None
            ]):
                raise ValidationError(
                    "At least one relative time field (days, hours, or minutes) must be set"
                )

        # Ensure all relative fields are 0 or greater
        if self.days_before_relative is not None and self.days_before_relative < 0:
            raise ValidationError("days_before_relative cannot be negative")
        if self.hours_before is not None and self.hours_before < 0:
            raise ValidationError("hours_before cannot be negative")
        if self.minutes_before is not None and self.minutes_before < 0:
            raise ValidationError("minutes_before cannot be negative")

    def get_total_minutes_before(self):
        """
        Calculate total minutes before the appointment for relative scheduling

        Returns:
            int: Total number of minutes before the appointment
        """
        if not self.schedule.use_relative_schedule:
            return None

        total_minutes = 0
        if self.days_before_relative:
            total_minutes += self.days_before_relative * 24 * 60
        if self.hours_before:
            total_minutes += self.hours_before * 60
        if self.minutes_before:
            total_minutes += self.minutes_before

        return total_minutes

    def __str__(self):
        if self.schedule.use_relative_schedule:
            parts = []
            if self.days_before_relative:
                parts.append(f"{self.days_before_relative} days")
            if self.hours_before:
                parts.append(f"{self.hours_before} hours")
            if self.minutes_before:
                parts.append(f"{self.minutes_before} minutes")
            return f"Reminder {' '.join(parts)} before appointment"
        else:
            return f"Reminder {self.days_before} days before at {self.time}"


class ReminderMessage(models.Model):
    """Individual messages for a reminder time"""
    reminder_time = models.ForeignKey(ReminderTime, on_delete=models.CASCADE, related_name='messages')
    template = models.CharField(max_length=255, blank=True, null=True)
    
    # Channel configuration fields
    email_config = models.ForeignKey(EmailConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='reminder_messages')
    sms_config = models.ForeignKey(SMSConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='reminder_messages')
    voice_config = models.ForeignKey(VoiceConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='reminder_messages')
    chat_config = models.ForeignKey(ChatConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='reminder_messages')

    class Meta:
        managed = False
        db_table = 'acs_remindermessage'

    def clean(self):
        """Validate that exactly one channel config is set"""
        configs = [
            self.email_config,
            self.sms_config,
            self.voice_config,
            self.chat_config
        ]
        if sum(1 for config in configs if config is not None) != 1:
            raise ValidationError("Exactly one channel configuration must be set")

    def get_channel_config(self):
        """Get the active channel config for this reminder message"""
        if self.email_config:
            return self.email_config
        elif self.sms_config:
            return self.sms_config
        elif self.voice_config:
            return self.voice_config
        elif self.chat_config:
            return self.chat_config
        return None

    def __str__(self):
        channel = next(
            (name for name, config in [
                ('Email', self.email_config),
                ('SMS', self.sms_config),
                ('Voice', self.voice_config),
                ('Chat', self.chat_config)
            ] if config is not None),
            'Unknown'
        )
        return f"{channel} Message for {self.reminder_time}"


class ReminderCampaignProgress(CampaignProgressBase):
    """Tracks progress for reminder campaigns"""
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE, related_name='reminder_campaign_progress')
    
    # Fields for absolute scheduling
    days_before = models.PositiveIntegerField(null=True, blank=True)
    time = models.TimeField(null=True, blank=True)
    
    # Fields for relative scheduling
    days_before_relative = models.PositiveIntegerField(null=True, blank=True)
    hours_before = models.PositiveIntegerField(null=True, blank=True)
    minutes_before = models.PositiveIntegerField(null=True, blank=True)
    
    # Tracking fields
    sent_at = models.DateTimeField()
    next_scheduled_reminder = models.DateTimeField(null=True, blank=True)
    reminder_time = models.ForeignKey(ReminderTime, on_delete=models.SET_NULL, null=True, related_name='progress_entries')

    class Meta:
        managed = False
        db_table = 'reminder_campaign_progress'
        indexes = [
            models.Index(fields=['days_before']),
            models.Index(fields=['sent_at']),
            models.Index(fields=['next_scheduled_reminder']),
        ]

    def clean(self):
        """Validate reminder progress configuration"""
        super().clean()

        # Check that either absolute or relative scheduling is used, not both
        absolute_fields = bool(self.days_before is not None and self.time is not None)
        relative_fields = bool(
            self.days_before_relative is not None or
            self.hours_before is not None or
            self.minutes_before is not None
        )

        if absolute_fields and relative_fields:
            raise ValidationError(
                "Cannot mix absolute and relative scheduling. Use either days_before/time "
                "or days/hours/minutes before."
            )

        # Ensure all relative fields are 0 or greater
        if self.days_before_relative is not None and self.days_before_relative < 0:
            raise ValidationError("days_before_relative cannot be negative")
        if self.hours_before is not None and self.hours_before < 0:
            raise ValidationError("hours_before cannot be negative")
        if self.minutes_before is not None and self.minutes_before < 0:
            raise ValidationError("minutes_before cannot be negative")

    def get_total_minutes_before(self):
        """
        Calculate total minutes before the appointment for relative scheduling

        Returns:
            int: Total number of minutes before the appointment
        """
        if not any([self.days_before_relative, self.hours_before, self.minutes_before]):
            return None

        total_minutes = 0
        if self.days_before_relative:
            total_minutes += self.days_before_relative * 24 * 60
        if self.hours_before:
            total_minutes += self.hours_before * 60
        if self.minutes_before:
            total_minutes += self.minutes_before

        return total_minutes

    def __str__(self):
        if any([self.days_before_relative, self.hours_before, self.minutes_before]):
            parts = []
            if self.days_before_relative:
                parts.append(f"{self.days_before_relative} days")
            if self.hours_before:
                parts.append(f"{self.hours_before} hours")
            if self.minutes_before:
                parts.append(f"{self.minutes_before} minutes")
            return f"Reminder {' '.join(parts)} before appointment"
        else:
            return f"Reminder {self.days_before} days before at {self.time}" 