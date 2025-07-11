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
from .channel_configs import EmailConfig, SMSConfig, VoiceConfig, ChatConfig
from bulkcampaign_processor.utils.variable_replacement import replace_variables
import logging

logger = logging.getLogger(__name__)

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

    # OneToOne fields for the shared channel config models
    email_config = models.OneToOneField(EmailConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    sms_config = models.OneToOneField(SMSConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    voice_config = models.OneToOneField(VoiceConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    chat_config = models.OneToOneField(ChatConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    # Opt-out configuration
    enable_opt_out = models.BooleanField(
        default=True,
        help_text="If True, allows participants to opt out by replying with 'STOP'"
    )
    initial_opt_out_notice = models.TextField(
        default="Reply STOP to opt out of further messages.",
        help_text="Message sent with the first message to inform participants about opt-out option"
    )
    opt_out_message = models.TextField(
        default="You have been unsubscribed from this campaign. You will no longer receive messages.",
        help_text="Message to send when a participant opts out"
    )

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
        # Get the appropriate channel config based on campaign channel
        channel_config = None
        if self.channel == 'email' and self.email_config:
            channel_config = self.email_config
        elif self.channel == 'sms' and self.sms_config:
            channel_config = self.sms_config
        elif self.channel == 'voice' and self.voice_config:
            channel_config = self.voice_config
        elif self.channel == 'chat' and self.chat_config:
            channel_config = self.chat_config
            
        if not channel_config:
            logger.error(f"No channel config found for campaign {self.id}")
            return ""
            
        # Use template if available, otherwise use content
        if channel_config.template:
            return channel_config.template.replace_variables(context)
        elif channel_config.content:
            return replace_variables(channel_config.content, context)
            
        return ""

class BulkCampaignMessageGroup(models.Model):
    """
    Model to group related bulk campaign messages together for a participant.
    This allows handling message sending logic for groups of messages,
    such as regular messages and opt-out messages, at the participant level.
    """
    campaign = models.ForeignKey('LeadNurturingCampaign', on_delete=models.CASCADE, related_name='message_groups')
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE, related_name='message_groups')
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled')
        ],
        default='pending'
    )
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'bulk_campaign_message_group'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['participant', 'status']),
        ]

    def __str__(self):
        return f"{self.campaign.name} - {self.participant.lead.email} - Group {self.id}"

    def update_status(self, new_status, metadata=None):
        """Update group status and metadata"""
        self.status = new_status
        if metadata:
            if not self.metadata:
                self.metadata = {}
            self.metadata.update(metadata)
        self.save()

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
        ('opted_out', 'Opted Out'),
        ('cancelled', 'Cancelled')
    ]

    MESSAGE_TYPES = [
        ('regular', 'Regular Message'),
        ('opt_out_notice', 'Opt-out Notice'),
        ('opt_out_confirmation', 'Opt-out Confirmation')
    ]

    campaign = models.ForeignKey('LeadNurturingCampaign', on_delete=models.CASCADE, related_name='messages')
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE, related_name='bulk_messages')
    message_group = models.ForeignKey(
        'BulkCampaignMessageGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
        help_text="The message group this message belongs to"
    )
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

    # Fields for drip campaign message steps
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

    # New field for reminder campaign messages
    reminder_message = models.ForeignKey(
        'ReminderMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bulk_messages',
        help_text="The reminder message configuration for this message (for reminder campaigns)"
    )

    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default='regular')

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
            models.Index(fields=['reminder_message']),
            models.Index(fields=['message_group']),
        ]
        # Unique constraints to prevent duplicate message scheduling
        constraints = [
            # For blast campaigns: unique per participant, campaign, and message type
            # (when drip_message_step and reminder_message are NULL)
            models.UniqueConstraint(
                fields=['participant', 'campaign', 'message_type'],
                condition=models.Q(
                    drip_message_step__isnull=True,
                    reminder_message__isnull=True
                ),
                name='unique_blast_message_per_participant'
            ),
            # For drip campaigns: unique per participant, drip message step, and message type
            # (when drip_message_step is not NULL)
            models.UniqueConstraint(
                fields=['participant', 'drip_message_step', 'message_type'],
                condition=models.Q(
                    drip_message_step__isnull=False
                ),
                name='unique_drip_message_per_step'
            ),
            # For reminder campaigns: unique per participant, reminder message, and message type
            # (when reminder_message is not NULL)
            models.UniqueConstraint(
                fields=['participant', 'reminder_message', 'message_type'],
                condition=models.Q(
                    reminder_message__isnull=False
                ),
                name='unique_reminder_message_per_reminder'
            ),
        ]

    def __str__(self):
        return f"{self.campaign.name} - {self.participant.lead.email} - {self.status}"

    def clean(self):
        """Validate that the appropriate fields are set based on campaign type"""
        super().clean()
        
        campaign = self.campaign
        if not campaign:
            return
            
        if campaign.campaign_type == 'drip' and not self.drip_message_step:
            raise ValidationError("Drip message step is required for drip campaigns")
        elif campaign.campaign_type == 'reminder' and not self.reminder_message:
            raise ValidationError("Reminder message is required for reminder campaigns")
        elif campaign.campaign_type == 'blast' and (self.drip_message_step or self.reminder_message):
            raise ValidationError("Blast campaigns should not have drip_message_step or reminder_message set")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def update_status(self, new_status, metadata=None):
        """Update message status and related timestamps"""
        self.status = new_status
        now = timezone.now()

        if new_status == 'sent':
            self.sent_at = now
            # If this is an opt-out confirmation message, mark it as sent on the participant
            if self.message_type == 'opt_out_confirmation':
                self.participant.opt_out_message_sent = True
                self.participant.save()
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
        """Get the message content based on campaign type and message step with enhanced variable replacement"""
        # Prepare context for variable replacement
        lead = self.participant.lead
        campaign = self.campaign
        context = {
            'lead': {
                'first_name': lead.first_name or '',
                'last_name': lead.last_name or '',
                'email': lead.email or '',
                'phone_number': lead.phone_number or '',
                'company': getattr(lead, 'company_name', '') or '',
                'title': getattr(lead, 'title', '') or '',
                'channel': getattr(lead, 'channel', '') or '',
                'source': getattr(lead, 'source', '') or '',
                'lead_type': getattr(lead, 'lead_type', '') or '',
                'score': getattr(lead, 'score', 0) or 0,
                'conversion_probability': getattr(lead, 'conversion_probability', 0) or 0,
                'is_qualified': getattr(lead, 'is_qualified', False) or False,
                'is_disqualified': getattr(lead, 'is_disqualified', False) or False,
            },
            'campaign': {
                'name': campaign.name or '',
                'type': campaign.campaign_type or '',
                'channel': campaign.channel or '',
                'description': getattr(campaign, 'description', '') or '',
            }
        }

        # Handle opt-out messages
        if self.message_type == 'opt_out_notice':
            content = campaign.initial_opt_out_notice or ''
            return replace_variables(content, context)
        elif self.message_type == 'opt_out_confirmation':
            content = campaign.opt_out_message or ''
            return replace_variables(content, context)

        # Get content based on campaign type
        content = ""
        
        if self.campaign.campaign_type == 'drip' and self.drip_message_step:
            # Get the channel config for the message step
            channel_config = self.drip_message_step.get_channel_config()
            if not channel_config:
                logger.error(f"No channel config found for drip message step {self.drip_message_step.id}")
                return ""
                
            # Use template if available, otherwise use content
            if channel_config.template:
                content = channel_config.template.content or ""
                logger.debug(f"Using template content for drip step: {content[:100]}...")
            elif channel_config.content:
                content = channel_config.content or ""
                logger.debug(f"Using direct content for drip step: {content[:100]}...")
            else:
                logger.error(f"No content found in drip message step {self.drip_message_step.id}")
                return ""
                
        elif self.campaign.campaign_type == 'reminder' and self.reminder_message:
            # Get the channel config for the reminder message
            channel_config = None
            if campaign.channel == 'email' and self.reminder_message.email_config:
                channel_config = self.reminder_message.email_config
            elif campaign.channel == 'sms' and self.reminder_message.sms_config:
                channel_config = self.reminder_message.sms_config
            elif campaign.channel == 'voice' and self.reminder_message.voice_config:
                channel_config = self.reminder_message.voice_config
            elif campaign.channel == 'chat' and self.reminder_message.chat_config:
                channel_config = self.reminder_message.chat_config
                
            if not channel_config:
                logger.error(f"No channel config found for reminder message {self.reminder_message.id}")
                return ""
                
            # Use template if available, otherwise use content
            if channel_config.template:
                content = channel_config.template.content or ""
                logger.debug(f"Using template content for reminder: {content[:100]}...")
            elif channel_config.content:
                content = channel_config.content or ""
                logger.debug(f"Using direct content for reminder: {content[:100]}...")
            else:
                logger.error(f"No content found in reminder message {self.reminder_message.id}")
                return ""
                
        else:
            # For other campaign types, get the appropriate channel config
            channel_config = None
            if campaign.channel == 'email' and campaign.email_config:
                channel_config = campaign.email_config
            elif campaign.channel == 'sms' and campaign.sms_config:
                channel_config = campaign.sms_config
            elif campaign.channel == 'voice' and campaign.voice_config:
                channel_config = campaign.voice_config
            elif campaign.channel == 'chat' and campaign.chat_config:
                channel_config = campaign.chat_config
                
            if not channel_config:
                logger.error(f"No channel config found for campaign {campaign.id}")
                return ""
                
            # Use template if available, otherwise use content
            if channel_config.template:
                content = channel_config.template.content or ""
                logger.debug(f"Using template content for campaign: {content[:100]}...")
            elif channel_config.content:
                content = channel_config.content or ""
                logger.debug(f"Using direct content for campaign: {content[:100]}...")
            else:
                logger.error(f"No content found in campaign {campaign.id}")
                return ""
        
        # Apply variable replacement
        if content:
            processed_content = replace_variables(content, context)
            
            # Check if variables were replaced
            if "{{" in processed_content and "}}" in processed_content:
                # Try one more time with a more aggressive approach
                processed_content = replace_variables(processed_content, context)
            
            return processed_content
        
        return ""

    @classmethod
    def check_existing_message(cls, participant, campaign, message_type, drip_message_step=None, reminder_message=None):
        """
        Check if a message already exists for the given parameters.
        Returns the existing message if found, None otherwise.
        
        This method respects the unique constraints for different campaign types:
        - Blast campaigns: unique per participant + campaign + message_type
        - Drip campaigns: unique per participant + drip_message_step + message_type  
        - Reminder campaigns: unique per participant + reminder_message + message_type
        """
        # Base filters
        filters = {
            'participant': participant,
            'campaign': campaign,
            'message_type': message_type,
        }
        
        # Add campaign-specific filters based on campaign type
        if campaign.campaign_type == 'blast':
            # For blast campaigns, ensure drip_message_step and reminder_message are NULL
            filters.update({
                'drip_message_step__isnull': True,
                'reminder_message__isnull': True,
            })
        elif campaign.campaign_type == 'drip':
            # For drip campaigns, require drip_message_step to be set
            if not drip_message_step:
                raise ValueError("drip_message_step is required for drip campaigns")
            filters['drip_message_step'] = drip_message_step
        elif campaign.campaign_type == 'reminder':
            # For reminder campaigns, require reminder_message to be set
            if not reminder_message:
                raise ValueError("reminder_message is required for reminder campaigns")
            filters['reminder_message'] = reminder_message
        
        # Exclude cancelled and failed messages from the check
        existing_message = cls.objects.filter(
            **filters
        ).exclude(
            status__in=['cancelled', 'failed']
        ).first()
        
        return existing_message

    @classmethod
    def create_message_safely(cls, participant, campaign, message_type, **kwargs):
        """
        Safely create a bulk campaign message, checking for existing messages first.
        Returns the created message or the existing message if one already exists.
        
        This method prevents duplicate message creation by checking existing messages
        before creating new ones, respecting the unique constraints for each campaign type.
        """
        # Determine campaign-specific parameters
        drip_message_step = kwargs.get('drip_message_step')
        reminder_message = kwargs.get('reminder_message')
        
        # Check for existing message
        existing_message = cls.check_existing_message(
            participant=participant,
            campaign=campaign,
            message_type=message_type,
            drip_message_step=drip_message_step,
            reminder_message=reminder_message
        )
        
        if existing_message:
            return existing_message
        
        # Create new message
        message_data = {
            'participant': participant,
            'campaign': campaign,
            'message_type': message_type,
            **kwargs
        }
        
        # Ensure campaign-specific fields are properly set
        if campaign.campaign_type == 'blast':
            message_data.update({
                'drip_message_step': None,
                'reminder_message': None,
            })
        elif campaign.campaign_type == 'drip':
            if not drip_message_step:
                raise ValueError("drip_message_step is required for drip campaigns")
            message_data['drip_message_step'] = drip_message_step
        elif campaign.campaign_type == 'reminder':
            if not reminder_message:
                raise ValueError("reminder_message is required for reminder campaigns")
            message_data['reminder_message'] = reminder_message
        
        return cls.objects.create(**message_data)

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
    opt_out_message_sent = models.BooleanField(
        default=False,
        help_text="Indicates whether the opt-out confirmation message has been sent"
    )
    metadata = models.JSONField(blank=True, null=True)

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
        if days_before is not None and days_before > 0:
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
            # Skip reminders with None days_before values
            if reminder.days_before is None:
                continue
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

    def can_opt_out(self):
        """
        Check if a participant can opt out of the campaign.
        Returns a tuple of (can_opt_out: bool, reason: str)
        """
        # Check if campaign allows opt-outs
        if not self.nurturing_campaign.enable_opt_out:
            return False, "Opt-out is not enabled for this campaign"

        # Check if participant is already opted out
        if self.status == 'opted_out':
            return False, "Participant has already opted out"

        # Check if campaign is active
        if not self.nurturing_campaign.is_active_or_scheduled():
            return False, "Campaign is not active"

        # Check if participant is in a valid state to opt out
        if self.status not in ['active', 'paused']:
            return False, f"Cannot opt out while in '{self.status}' status"

        return True, "Participant can opt out"

    def opt_out(self, user=None):
        """
        Handle participant opt-out:
        1. Update participant status to opted_out
        2. Set exited_campaign_at timestamp
        3. Cancel all pending/scheduled messages
        4. Update last_updated_by if user provided
        """
        # Check if participant can opt out
        can_opt_out, reason = self.can_opt_out()
        if not can_opt_out:
            raise ValidationError(reason)

        now = timezone.now()
        
        # Update participant status
        self.status = 'opted_out'
        self.exited_campaign_at = now
        if user:
            self.last_updated_by = user
        self.save()

        # Cancel all pending/scheduled messages
        self.bulk_messages.filter(
            status__in=['pending', 'scheduled']
        ).update(
            status='cancelled',
            error_message='Message cancelled due to participant opt-out',
            updated_at=now
        )

        # Create an opt-out event if this is a journey campaign
        if self.nurturing_campaign.campaign_type == 'journey':
            JourneyEvent.objects.create(
                participant=self,
                journey_step=self.current_journey_step,
                event_type='opt_out',
                created_by=user or self.last_updated_by
            )

        # Only create opt-out confirmation message if one hasn't been sent
        if not self.opt_out_message_sent and self.nurturing_campaign.enable_opt_out:
            BulkCampaignMessage.objects.create(
                campaign=self.nurturing_campaign,
                participant=self,
                status='scheduled',
                scheduled_for=now,
                message_type='opt_out_confirmation'
            )

        return True

    def reset_opt_out_message(self, user=None):
        """
        Reset the opt-out message flag to allow resending the opt-out message.
        This is useful when:
        1. The previous opt-out message failed to send
        2. We need to resend the opt-out message
        3. There was an issue with the previous opt-out process
        
        Args:
            user: User performing the reset (optional)
        """
        self.opt_out_message_sent = False
        if user:
            self.last_updated_by = user
        self.save()

        # Log the reset in metadata
        if not self.metadata:
            self.metadata = {}
        self.metadata.update({
            'opt_out_message_reset': {
                'timestamp': timezone.now().isoformat(),
                'user_id': user.id if user else None,
                'reason': 'Manual reset'
            }
        })
        self.save()

        return True
