from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import pytz
from datetime import datetime, timedelta
from .external_references import Account, Campaign, Lead
from .journeys import JourneyEvent
from .blast_campaigns import BlastCampaignProgress
from .drip_campaigns import DripCampaignProgress
from .reminder_campaigns import ReminderCampaignProgress
from bulkcampaign_processor.utils.variable_replacement import replace_variables

class LeadNurturingCampaign(models.Model):
    CAMPAIGN_TYPES = [
        ('journey', 'Journey Based'),
        ('drip', 'Drip Campaign'),
        ('reminder', 'Reminder Campaign'),
        ('blast', 'One-time Blast'),
    ]

    CHANNEL_TYPES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('voice', 'Voice'),
        ('chat', 'Chat'),
    ]

    CAMPAIGN_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    # Account relationship
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='nurturing_campaigns')
    
    # Existing fields
    journey = models.ForeignKey('Journey', on_delete=models.CASCADE, related_name='nurturing_campaigns', null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    is_ongoing = models.BooleanField(
        default=False,
        help_text="If True, campaign runs indefinitely until manually ended"
    )
    status = models.CharField(
        max_length=20,
        choices=CAMPAIGN_STATUS_CHOICES,
        default='draft',
        help_text="Current status of the campaign"
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='status_changed_campaigns'
    )
    
    # Auto-enrollment configuration
    auto_enroll_new_leads = models.BooleanField(
        default=False,
        help_text="If True, automatically enroll new leads that match the criteria"
    )
    auto_enroll_filters = models.JSONField(
        blank=True, 
        null=True,
        help_text="""
        Filters to determine which new leads should be auto-enrolled.
        Format: [
            {
                "model": "lead|d2c_lead|b2b_lead|lead_field_value|lead_intake_value",
                "field": "field_name",
                "operator": "equals|contains|greater_than|less_than|is_empty|is_not_empty",
                "value": "value_to_compare"
            }
        ]
        """
    )
    
    config = models.JSONField(
        blank=True, 
        null=True,
        help_text="""
        Additional configuration for the campaign:
        - For all campaigns: {
            "track_opens": true,
            "track_clicks": true,
            "track_replies": true,
            "track_delivery": true,
            "allow_opt_out": true,
            "opt_out_message": "Reply STOP to unsubscribe"
          }
        - For email campaigns: {
            "from_email": "sender@example.com",
            "from_name": "Sender Name",
            "reply_to": "reply@example.com",
            "priority": "high|normal|low",
            "attachments": [
                {
                    "name": "file.pdf",
                    "url": "https://..."
                }
            ]
          }
        - For SMS campaigns: {
            "from_number": "+1234567890",
            "priority": "high|normal|low",
            "media_urls": ["https://..."]
          }
        - For voice campaigns: {
            "from_number": "+1234567890",
            "voice": "male|female",
            "language": "en-US",
            "retry_attempts": 3,
            "retry_delay": 300,
            "record_call": true,
            "call_timeout": 60,
            "machine_detection": "true|false|prefer_human"
          }
        - For chat campaigns: {
            "platform": "whatsapp|messenger|telegram",
            "priority": "high|normal|low",
            "media_urls": ["https://..."],
            "quick_replies": [
                {
                    "text": "Yes",
                    "value": "yes"
                },
                {
                    "text": "No",
                    "value": "no"
                }
            ]
          }
        """
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # New fields for campaign type
    campaign_type = models.CharField(max_length=20, choices=CAMPAIGN_TYPES, default='journey')
    channel = models.CharField(
        max_length=10,
        choices=CHANNEL_TYPES,
        null=True,
        blank=True
    )
    template = models.ForeignKey(
        'MessageTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bulk_campaigns'
    )
    content = models.TextField(blank=True, null=True)
    crm_campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name='nurturing_campaigns')

    class Meta:
        managed = False
        db_table = 'acs_leadnurturingcampaign'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['is_ongoing']),
            models.Index(fields=['status_changed_at']),
        ]

    def clean(self):
        """Validate campaign configuration"""
        super().clean()
        
        # Validate end date only if not an ongoing campaign
        if not self.is_ongoing and self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError("End date must be after start date")

        if self.campaign_type == 'journey':
            if not self.journey:
                raise ValidationError("Journey is required for journey-based campaigns")
        else:  # bulk campaign
            if not self.channel:
                raise ValidationError("Channel is required for bulk campaigns")
            if not self.template and not self.content:
                raise ValidationError("Either template or content is required for bulk campaigns")

    def update_status(self, new_status, user):
        """
        Update the campaign status with proper tracking

        Args:
            new_status (str): New status from CAMPAIGN_STATUS_CHOICES
            user: User making the status change
        """
        if new_status not in dict(self.CAMPAIGN_STATUS_CHOICES):
            raise ValueError(f"Invalid status: {new_status}")

        # If completing or cancelling an ongoing campaign, update is_ongoing
        if new_status in ['completed', 'cancelled']:
            self.is_ongoing = False
            if not self.end_date:
                self.end_date = timezone.now()

        self.status = new_status
        self.status_changed_at = timezone.now()
        self.status_changed_by = user
        self.save()

    def is_active_or_scheduled(self):
        """Check if campaign is currently active or scheduled to start"""
        if not self.active:
            return False

        if self.status not in ['active', 'scheduled']:
            return False

        now = timezone.now()
        
        # Check start date
        if self.start_date and self.start_date > now:
            return False

        # Check end date only if not ongoing
        if not self.is_ongoing and self.end_date and self.end_date < now:
            return False

        return True

    def can_send_message(self, participant):
        """Check if a message can be sent to a participant"""
        if not self.is_active_or_scheduled():
            return False

        # Check participant status
        if participant.status not in ['active']:
            return False

        # For ongoing campaigns, we only need to check the start date
        if self.is_ongoing:
            return not self.start_date or self.start_date <= timezone.now()

        # For campaigns with end dates, check both start and end
        now = timezone.now()
        if self.start_date and self.start_date > now:
            return False
        if self.end_date and self.end_date < now:
            return False

        return True

    def get_next_send_time(self, last_send_time=None):
        """Calculate the next send time based on campaign type and settings"""
        # First check if campaign is active/scheduled
        if not self.is_active_or_scheduled():
            return None

        if self.campaign_type == 'drip':
            return self._get_drip_next_send_time(last_send_time)
        elif self.campaign_type == 'reminder':
            return self._get_reminder_next_send_time(last_send_time)
        elif self.campaign_type == 'blast':
            return self._get_blast_next_send_time()
        return None

    def _get_drip_next_send_time(self, last_send_time=None):
        """Calculate next send time for drip campaigns"""
        if not hasattr(self, 'drip_schedule'):
            return None

        now = timezone.now()
        tz = pytz.timezone(self.crm_campaign.timezone) if self.crm_campaign else pytz.UTC
        now = now.astimezone(tz)

        # Get the current step for the participant
        participant = self.participants.first()  # This should be called with a specific participant
        if not participant:
            return None

        progress = participant.drip_campaign_progress.first()
        if not progress:
            # Start with the first step
            first_step = self.drip_schedule.message_steps.order_by('order').first()
            if not first_step:
                return None
            progress = DripCampaignProgress.objects.create(
                participant=participant,
                current_step=first_step,
                next_scheduled_interval=now
            )
            return now

        # Get the next step
        current_step = progress.current_step
        if not current_step:
            return None

        next_step = self.drip_schedule.message_steps.filter(order__gt=current_step.order).order_by('order').first()
        if not next_step:
            return None

        # Calculate next send time based on the current step's delay
        if not last_send_time:
            next_time = now
        else:
            next_time = last_send_time + current_step.get_delay_timedelta()

        # Apply business hours and weekend restrictions
        if self.drip_schedule.business_hours_only:
            start_time = self.drip_schedule.start_time
            end_time = self.drip_schedule.end_time

            if next_time.time() < start_time:
                next_time = datetime.combine(next_time.date(), start_time)
            elif next_time.time() > end_time:
                next_time = datetime.combine(next_time.date() + timedelta(days=1), start_time)

        if self.drip_schedule.exclude_weekends:
            while next_time.weekday() >= 5:
                next_time += timedelta(days=1)

        # Update progress
        progress.current_step = next_step
        progress.next_scheduled_interval = next_time
        progress.save()

        return next_time

    def _get_reminder_next_send_time(self, last_send_time=None):
        """Calculate next send time for reminder campaigns"""
        if not hasattr(self, 'reminder_schedule'):
            return None

        # Implementation for reminder campaigns
        pass

    def _get_blast_next_send_time(self):
        """Get send time for blast campaigns"""
        if not hasattr(self, 'blast_schedule'):
            return None
        return self.blast_schedule.send_time

    def move_to_next_step(self, next_step, event_type='enter_step', metadata=None):
        """Move participant to next step and create event"""
        if not self.journey:
            raise ValidationError("Cannot move to next step for bulk campaigns")

        self.current_journey_step = next_step
        self.last_event_at = timezone.now()
        self.save()

        JourneyEvent.objects.create(
            participant=self,
            journey_step=next_step,
            event_type=event_type,
            metadata=metadata,
            created_by=self.last_updated_by
        )

    def replace_variables(self, context):
        """
        Replaces variables in the campaign content with values from the context.
        
        Args:
            context (dict): Dictionary containing values for variables.
                           Should be structured as: {'lead': {...}, 'campaign': {...}, etc.}
        
        Returns:
            str: Content with variables replaced with their values
        """
        # If using a template, use its replace_variables method
        if self.template:
            return self.template.replace_variables(context)
            
        # If using direct content, process it here
        if not self.content:
            return ""
            
        content = self.content
        
        # Get all active variables
        from external_models.models.messages import TemplateVariable
        variables = TemplateVariable.objects.filter(
            category__is_active=True,
            is_active=True
        ).select_related('category')
        
        # Replace each variable
        for var in variables:
            placeholder = var.get_placeholder()
            if placeholder in content:
                category = var.category.name
                if category == 'system':
                    # Handle system variables
                    if var.name == 'current_date':
                        value = timezone.now().strftime('%Y-%m-%d')
                    elif var.name == 'current_time':
                        value = timezone.now().strftime('%I:%M %p')
                else:
                    # Get value from context using the model and field information
                    model_data = context.get(category, {})
                    if isinstance(model_data, dict):
                        value = model_data.get(var.name, '')
                    else:
                        # If model_data is an actual model instance
                        value = getattr(model_data, var.field_name, '')
                
                content = content.replace(placeholder, str(value))
        
        return content

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

class BulkCampaignMessage(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('scheduled', 'Scheduled'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('opened', 'Opened'),
        ('clicked', 'Clicked'),
        ('replied', 'Replied'),
        ('opted_out', 'Opted Out')
    ]

    campaign = models.ForeignKey('LeadNurturingCampaign', on_delete=models.CASCADE, related_name='messages')
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE, related_name='bulk_messages')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # New fields for drip campaign message steps
    drip_message_step = models.ForeignKey(
        'DripCampaignMessageStep',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
        help_text="The message step that generated this message (for drip campaigns)"
    )
    step_order = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="The order of the message step in the drip sequence"
    )

    class Meta:
        managed = False
        db_table = 'bulk_campaign_message'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['participant', 'status']),
            models.Index(fields=['scheduled_for']),
            models.Index(fields=['drip_message_step']),
            models.Index(fields=['step_order']),
        ]

    def __str__(self):
        return f"{self.campaign.name} - {self.participant.lead.email} - {self.status}"

    def update_status(self, new_status, metadata=None):
        """Update message status and related timestamps"""
        self.status = new_status
        now = timezone.now()

        if new_status == 'sent':
            self.sent_at = now
        elif new_status == 'delivered':
            self.delivered_at = now
        elif new_status == 'opened':
            self.opened_at = now
        elif new_status == 'clicked':
            self.clicked_at = now
        elif new_status == 'replied':
            self.replied_at = now

        if metadata:
            if not self.metadata:
                self.metadata = {}
            self.metadata.update(metadata)

        self.save()

    def can_be_sent(self):
        """Check if the message can be sent"""
        if self.status not in ['pending', 'scheduled']:
            return False

        if self.scheduled_for and self.scheduled_for > timezone.now():
            return False

        return self.campaign.can_send_message(self.participant)

    def get_message_content(self):
        """Get the message content based on campaign type and message step"""
        # Prepare context for variable replacement
        lead = self.participant.lead
        campaign = self.campaign
        context = {
            'lead': {
                'first_name': lead.first_name,
                'last_name': lead.last_name,
                'email': lead.email,
                'phone_number': lead.phone_number,
                'company': lead.company_name if hasattr(lead, 'company_name') else None,
                'title': lead.title if hasattr(lead, 'title') else None,
            },
            'campaign': {
                'name': campaign.name,
                'type': campaign.campaign_type,
                'channel': campaign.channel,
            }
        }

        if self.campaign.campaign_type == 'drip' and self.drip_message_step:
            # For drip campaigns, use the content from the message step
            if self.drip_message_step.template:
                return self.drip_message_step.template.replace_variables(context)
            # For direct content in message step, use the utility function
            return replace_variables(self.drip_message_step.content, context)
        elif self.campaign.template:
            # For other campaign types, use the campaign template
            return self.campaign.template.replace_variables(context)
        # For direct content in campaign, use the utility function
        return replace_variables(self.campaign.content, context)

class LeadNurturingParticipant(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='lead_nurturing_participations')
    nurturing_campaign = models.ForeignKey('LeadNurturingCampaign', on_delete=models.CASCADE, related_name='participants')
    current_journey_step = models.ForeignKey('JourneyStep', on_delete=models.SET_NULL, null=True, blank=True, related_name='current_participants')
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('completed', 'Completed'),
            ('exited', 'Exited'),
            ('paused', 'Paused'),
            ('opted_out', 'Opted Out')
        ],
        default='active'
    )
    last_event_at = models.DateTimeField(null=True, blank=True)
    entered_campaign_at = models.DateTimeField(auto_now_add=True)
    exited_campaign_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_lead_nurturing_participants')
    last_updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='updated_lead_nurturing_participants')
    
    # Campaign tracking fields
    last_message_sent_at = models.DateTimeField(null=True, blank=True)
    messages_sent_count = models.PositiveIntegerField(default=0)
    next_scheduled_message = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'lead_nurturing_participant'
        unique_together = [
            ['lead', 'nurturing_campaign', 'status']
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['last_event_at']),
            models.Index(fields=['last_message_sent_at']),
            models.Index(fields=['next_scheduled_message']),
            models.Index(fields=['entered_campaign_at']),
            models.Index(fields=['exited_campaign_at']),
        ]

    def __str__(self):
        return f"{self.lead} in {self.nurturing_campaign}"

    def clean(self):
        """Validate participant configuration"""
        super().clean()
        
        # For journey-based campaigns, journey is required
        if self.nurturing_campaign and self.nurturing_campaign.campaign_type == 'journey' and not self.nurturing_campaign.journey:
            raise ValidationError("Journey is required for journey-based campaigns")

    def move_to_next_step(self, next_step, event_type='enter_step', metadata=None):
        """Move participant to next step and create event"""
        if not self.nurturing_campaign.journey:
            raise ValidationError("Cannot move to next step for bulk campaigns")
            
        self.current_journey_step = next_step
        self.last_event_at = timezone.now()
        self.save()
        
        JourneyEvent.objects.create(
            participant=self,
            journey_step=next_step,
            event_type=event_type,
            metadata=metadata,
            created_by=self.last_updated_by
        )

    def update_campaign_progress(self, message_sent=False, scheduled_time=None):
        """Update campaign progress for bulk campaigns"""
        if not self.nurturing_campaign or self.nurturing_campaign.campaign_type == 'journey':
            return

        now = timezone.now()
        campaign = self.nurturing_campaign

        if message_sent:
            self.messages_sent_count += 1
            self.last_message_sent_at = now

        if scheduled_time:
            self.next_scheduled_message = scheduled_time

        self.save()

        # Update campaign-specific progress
        if campaign.campaign_type == 'drip':
            self._update_drip_progress(now, scheduled_time)
        elif campaign.campaign_type == 'reminder':
            self._update_reminder_progress(now, scheduled_time)
        elif campaign.campaign_type == 'blast':
            self._update_blast_progress(now)

    def _update_drip_progress(self, now, scheduled_time):
        """Update progress for drip campaigns"""
        progress = self.drip_campaign_progress.first()
        if not progress:
            progress = DripCampaignProgress.objects.create(
                participant=self
            )
        
        if self.messages_sent_count > 0:
            progress.last_interval = now
        
        if scheduled_time:
            progress.next_scheduled_interval = scheduled_time
            
        progress.save()

    def _update_reminder_progress(self, now, scheduled_time):
        """Update progress for reminder campaigns"""
        days_before = self._get_days_before(now)
        if days_before > 0:
            ReminderCampaignProgress.objects.create(
                participant=self,
                days_before=days_before,
                sent_at=now,
                next_scheduled_reminder=scheduled_time
            )

    def _update_blast_progress(self, now):
        """Update progress for blast campaigns"""
        progress, created = BlastCampaignProgress.objects.get_or_create(
            participant=self
        )
        progress.message_sent = True
        progress.sent_at = now
        progress.save()

    def _get_days_before(self, current_time):
        """Helper method to calculate days before for reminder campaigns"""
        if not self.nurturing_campaign or self.nurturing_campaign.campaign_type != 'reminder':
            return 0

        campaign = self.nurturing_campaign
        if not campaign.reminder_schedule:
            return 0

        # Find the next reminder time that hasn't been sent yet
        sent_days = set(
            self.reminder_campaign_progress.values_list('days_before', flat=True)
        )
        
        for reminder in campaign.reminder_schedule.reminder_times.all():
            if reminder.days_before not in sent_days:
                return reminder.days_before

        return 0

    def get_campaign_progress(self):
        """Get the current campaign progress"""
        campaign = self.nurturing_campaign
        if not campaign:
            return None

        if campaign.campaign_type == 'drip':
            progress = self.drip_campaign_progress.first()
            if progress:
                return {
                    'last_interval': progress.last_interval,
                    'intervals_completed': progress.intervals_completed,
                    'total_intervals': progress.total_intervals,
                    'next_scheduled_interval': progress.next_scheduled_interval
                }
        elif campaign.campaign_type == 'reminder':
            reminders = self.reminder_campaign_progress.all().order_by('-sent_at')
            next_reminder = reminders.filter(next_scheduled_reminder__isnull=False).first()
            return {
                'reminders_sent': [
                    {
                        'days_before': r.days_before,
                        'sent_at': r.sent_at
                    } for r in reminders
                ],
                'next_reminder': {
                    'days_before': next_reminder.days_before if next_reminder else None,
                    'scheduled_for': next_reminder.next_scheduled_reminder if next_reminder else None
                } if next_reminder else None
            }
        elif campaign.campaign_type == 'blast':
            progress = self.blast_campaign_progress.first()
            if progress:
                return {
                    'message_sent': progress.message_sent,
                    'sent_at': progress.sent_at
                }

        return None
