import logging
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from twilio.rest import Client

from external_models.models.nurturing_campaigns import (
    LeadNurturingCampaign,
    LeadNurturingParticipant,
    BulkCampaignMessage,
    DripCampaignSchedule,
    ReminderCampaignSchedule,
    BlastCampaignSchedule
)
from external_models.models.communications import (
    Conversation,
    Participant,
    ConversationMessage,
    ConversationThread,
    ThreadMessage
)
from django.conf import settings
import time

logger = logging.getLogger(__name__)

class BulkCampaignProcessor:
    """
    Service class for processing bulk nurturing campaigns
    Handles drip campaigns, reminder campaigns, and blast campaigns
    """

    def __init__(self):
        self.campaign_processors = {
            'drip': self._process_drip_campaign,
            'reminder': self._process_reminder_campaign,
            'blast': self._process_blast_campaign
        }

    def process_campaign(self, campaign):
        """
        Process a bulk nurturing campaign based on its type

        Args:
            campaign: LeadNurturingCampaign instance

        Returns:
            int: Number of messages scheduled/sent
        """
        if not campaign.is_active_or_scheduled():
            logger.debug(f"Skipping inactive campaign {campaign}")
            return 0

        processor = self.campaign_processors.get(campaign.campaign_type)
        if not processor:
            logger.error(f"No processor found for campaign type: {campaign.campaign_type}")
            return 0

        return processor(campaign)

    def process_due_messages(self):
        """
        Process all messages that are due to be sent
        This should be run periodically by a scheduled task

        Returns:
            int: Number of messages processed
        """
        logger.info("Processing due messages...")

        # Find all pending messages that are due
        due_messages = BulkCampaignMessage.objects.filter(
            status__in=['pending', 'scheduled'],
            scheduled_for__lte=timezone.now()
        ).select_related(
            'campaign',
            'participant',
            'participant__lead'
        )

        processed_count = 0

        for message in due_messages:
            try:
                if self._send_message(message):
                    processed_count += 1
            except Exception as e:
                logger.exception(f"Error processing message {message.id}: {e}")

        logger.info(f"Processed {processed_count} due messages")
        return processed_count

    def _process_drip_campaign(self, campaign):
        """Process a drip campaign"""
        if not campaign.drip_schedule:
            logger.error(f"Drip campaign {campaign.id} has no schedule")
            return 0

        schedule = campaign.drip_schedule
        now = timezone.now()

        # Find active participants that need messages
        participants = LeadNurturingParticipant.objects.filter(
            nurturing_campaign=campaign,
            status='active'
        ).select_related('lead')

        scheduled_count = 0

        for participant in participants:
            # Check if participant has reached max messages
            if participant.messages_sent_count >= schedule.max_messages:
                continue

            # Check if it's time for next message
            if not self._should_send_drip_message(participant, schedule):
                continue

            # Schedule next message
            if self._schedule_drip_message(participant, schedule):
                scheduled_count += 1

        return scheduled_count

    def _process_reminder_campaign(self, campaign):
        """Process a reminder campaign"""
        if not campaign.reminder_schedule:
            logger.error(f"Reminder campaign {campaign.id} has no schedule")
            return 0

        schedule = campaign.reminder_schedule
        now = timezone.now()

        # Find active participants that need reminders
        participants = LeadNurturingParticipant.objects.filter(
            nurturing_campaign=campaign,
            status='active'
        ).select_related('lead')

        scheduled_count = 0

        for participant in participants:
            # Find next reminder time
            next_reminder = self._get_next_reminder_time(participant, schedule)
            if not next_reminder:
                continue

            # Schedule reminder
            if self._schedule_reminder_message(participant, next_reminder):
                scheduled_count += 1

        return scheduled_count

    def _process_blast_campaign(self, campaign):
        """Process a blast campaign"""
        if not campaign.blast_schedule:
            logger.error(f"Blast campaign {campaign.id} has no schedule")
            return 0

        schedule = campaign.blast_schedule
        now_utc = timezone.now().astimezone(timezone.UTC)

        # Check if it's time to send the blast
        if schedule.send_time > now_utc:
            return 0

        # Find active participants that haven't received the blast
        participants = LeadNurturingParticipant.objects.filter(
            nurturing_campaign=campaign,
            status='active'
        ).exclude(
            bulk_messages__campaign=campaign
        ).select_related('lead')

        scheduled_count = 0

        for participant in participants:
            # Schedule blast message
            if self._schedule_blast_message(participant, schedule):
                scheduled_count += 1

        return scheduled_count

    def _should_send_drip_message(self, participant, schedule):
        """Check if a drip message should be sent to participant"""
        if not participant.last_message_sent_at:
            return True

        # Check if enough time has passed since last message
        interval = schedule.interval * 3600  # Convert hours to seconds
        elapsed = timezone.now() - participant.last_message_sent_at
        return elapsed.total_seconds() >= interval

    def _get_next_reminder_time(self, participant, schedule):
        """Get the next reminder time for a participant"""
        # Get all reminder times
        reminder_times = schedule.reminder_times.all().order_by(
            'days_before', 'days_before_relative', 'hours_before', 'minutes_before'
        )

        # Find the first reminder that hasn't been sent
        sent_days = set(
            participant.reminder_campaign_progress.values_list('days_before', flat=True)
        )

        for reminder in reminder_times:
            if reminder.days_before not in sent_days:
                return reminder

        return None

    def _schedule_drip_message(self, participant, schedule):
        """Schedule a drip campaign message"""
        try:
            with transaction.atomic():
                # Create message
                message = BulkCampaignMessage.objects.create(
                    campaign=participant.nurturing_campaign,
                    participant=participant,
                    status='scheduled',
                    scheduled_for=self._get_next_send_time(schedule)
                )

                # Update participant progress
                participant.update_campaign_progress(
                    scheduled_time=message.scheduled_for
                )

                return True
        except Exception as e:
            logger.exception(f"Error scheduling drip message: {e}")
            return False

    def _schedule_reminder_message(self, participant, reminder):
        """Schedule a reminder campaign message"""
        try:
            with transaction.atomic():
                # Calculate send time based on reminder settings
                send_time = self._calculate_reminder_time(reminder)

                # Create message
                message = BulkCampaignMessage.objects.create(
                    campaign=participant.nurturing_campaign,
                    participant=participant,
                    status='scheduled',
                    scheduled_for=send_time
                )

                # Update participant progress
                participant.update_campaign_progress(
                    scheduled_time=message.scheduled_for
                )

                return True
        except Exception as e:
            logger.exception(f"Error scheduling reminder message: {e}")
            return False

    def _schedule_blast_message(self, participant, schedule):
        """Schedule a blast campaign message"""
        try:
            with transaction.atomic():
                # Create message
                message = BulkCampaignMessage.objects.create(
                    campaign=participant.nurturing_campaign,
                    participant=participant,
                    status='scheduled',
                    scheduled_for=schedule.send_time
                )

                # Update participant progress
                participant.update_campaign_progress(
                    scheduled_time=message.scheduled_for
                )

                return True
        except Exception as e:
            logger.exception(f"Error scheduling blast message: {e}")
            return False

    def _send_message(self, message):
        """Send a scheduled message"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant

            # Check if message can be sent
            if not campaign.can_send_message(participant):
                logger.debug(f"Cannot send message {message.id} - campaign or participant not active")
                return False

            # Send message based on channel
            if campaign.channel == 'email':
                success = self._send_email(message)
            elif campaign.channel == 'sms':
                success = self._send_sms(message)
            elif campaign.channel == 'voice':
                success = self._send_voice(message)
            elif campaign.channel == 'chat':
                success = self._send_chat(message)
            else:
                logger.error(f"Unsupported channel: {campaign.channel}")
                return False

            if success:
                # Update message status
                message.update_status('sent')
                
                # Update participant progress
                participant.update_campaign_progress(message_sent=True)

                return True

            return False

        except Exception as e:
            logger.exception(f"Error sending message {message.id}: {e}")
            message.update_status('failed', {'error': str(e)})
            return False

    def _get_next_send_time(self, schedule):
        """Calculate the next time a message should be sent based on schedule"""
        now = timezone.now()
        
        # If outside business hours, move to next business day
        if schedule.business_hours_only:
            if now.time() >= schedule.end_time:
                # Move to next day
                next_day = now + timezone.timedelta(days=1)
                if schedule.exclude_weekends and next_day.weekday() >= 5:
                    # Skip weekend
                    next_day += timezone.timedelta(days=2)
                return timezone.make_aware(timezone.datetime.combine(next_day.date(), schedule.start_time))
            elif now.time() < schedule.start_time:
                # Move to start time today
                return timezone.make_aware(timezone.datetime.combine(now.date(), schedule.start_time))

        return now

    def _calculate_reminder_time(self, reminder):
        """Calculate the send time for a reminder"""
        now = timezone.now()

        if reminder.days_before is not None:
            # Absolute scheduling
            send_date = now.date() + timezone.timedelta(days=reminder.days_before)
            if reminder.time:
                return timezone.make_aware(timezone.datetime.combine(send_date, reminder.time))
            return timezone.make_aware(timezone.datetime.combine(send_date, time(9, 0)))  # Default to 9 AM
        else:
            # Relative scheduling
            total_seconds = 0
            if reminder.days_before_relative:
                total_seconds += reminder.days_before_relative * 86400
            if reminder.hours_before:
                total_seconds += reminder.hours_before * 3600
            if reminder.minutes_before:
                total_seconds += reminder.minutes_before * 60

            return now + timezone.timedelta(seconds=total_seconds)

    def _send_email(self, message):
        """Send an email message using the configured email service"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='email',
                status='open',
                subject=message.subject if hasattr(message, 'subject') else None,
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=message.content,
                channel='email',
                lead=lead,
                user=campaign.created_by
            )

            # TODO: Implement actual email sending using your email service
            # This could be SendGrid, Mailgun, etc.
            # For now, we'll just mark it as sent
            message.update_status('sent')
            thread_message.read_status = True
            thread_message.save()

            return True

        except Exception as e:
            logger.error(f"Error sending email message: {str(e)}")
            return False

    def _send_sms(self, message):
        """Send an SMS message using Twilio's direct messaging API"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Get the service phone number
            service_phone = None
            if message.campaign.config and message.campaign.config.get('from_number'):
                service_phone = message.campaign.config['from_number']
            elif message.campaign.crm_campaign and message.campaign.crm_campaign.campaign_from_number:
                service_phone = message.campaign.crm_campaign.campaign_from_number

            if not service_phone:
                raise ValueError("No service phone number found in campaign configuration")

            # Format phone numbers
            formatted_to = self._format_phone_number(lead.phone_number)
            formatted_from = self._format_phone_number(service_phone)

            if not formatted_to or not formatted_from:
                raise ValueError("Invalid phone number format")

            # Initialize Twilio client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

            # Send message directly
            twilio_message = client.messages.create(
                body=message.campaign.content,
                from_=formatted_from,
                to=formatted_to
            )

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='sms',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=message.campaign.content,
                channel='sms',
                lead=lead,
                user=campaign.created_by
            )

            return True

        except Exception as e:
            logger.error(f"Error sending SMS message: {str(e)}")
            return False

    def _send_voice(self, message):
        """Send a voice message using Bland AI"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='voice',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=message.content,
                channel='voice',
                lead=lead,
                user=campaign.created_by
            )

            # TODO: Implement actual voice call using Bland AI
            # This would involve:
            # 1. Creating a Bland AI call
            # 2. Linking it to the thread
            # 3. Initiating the call
            # For now, we'll just mark it as sent
            message.update_status('sent')
            thread_message.read_status = True
            thread_message.save()

            return True

        except Exception as e:
            logger.error(f"Error sending voice message: {str(e)}")
            return False

    def _send_chat(self, message):
        """Send a chat message using the configured chat service"""
        try:
            # Get campaign and participant
            campaign = message.campaign
            participant = message.participant
            lead = participant.lead

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='chat',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=message.content,
                channel='chat',
                lead=lead,
                user=campaign.created_by
            )

            # TODO: Implement actual chat message sending using your chat service
            # This could be Intercom, Drift, etc.
            # For now, we'll just mark it as sent
            message.update_status('sent')
            thread_message.read_status = True
            thread_message.save()

            return True

        except Exception as e:
            logger.error(f"Error sending chat message: {str(e)}")
            return False

    def _add_identity_participant(self, conversation_obj, identity, projected_address=None):
        """
        Add an identity-based participant to the conversation.
        
        Args:
            conversation_obj: The conversation object
            identity: The identity to use for the participant (e.g., 'acs-system')
            projected_address: The phone number to project for this identity (e.g., Twilio number)
            
        Returns:
            tuple: (participant_obj, created) where created is a boolean indicating if the participant was newly created
        """
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # First check if the participant exists in our database
        existing = Participant.objects.filter(
            conversation=conversation_obj,
            user=None,  # If you don't link a user in your DB for 'system'
            phone_number=None,
        ).first()

        if existing:
            logger.debug(f"Found existing participant in database with SID: {existing.participant_sid}")
            return existing, False

        # Check if the participant exists in Twilio
        logger.debug(f"Checking for existing participant with identity='{identity}' in Twilio")
        existing_participants = client.conversations \
            .conversations(conversation_obj.twilio_sid) \
            .participants \
            .list()

        # Look for a participant with matching identity
        for participant in existing_participants:
            if participant.identity == identity:
                logger.debug(f"Found existing participant in Twilio with SID: {participant.sid}")
                # Create or update our database record
                participant_obj, _ = Participant.objects.get_or_create(
                    participant_sid=participant.sid,
                    defaults={
                        'conversation': conversation_obj,
                        'phone_number': None,
                        'user': None
                    }
                )
                return participant_obj, False

        # If we get here, we need to create a new participant
        logger.debug(f"Adding new identity participant with identity='{identity}'")
        participant_params = {'identity': identity}
        
        # Add projected address if provided
        if projected_address:
            logger.debug(f"Using projected address: {projected_address}")
            participant_params['messaging_binding_projected_address'] = projected_address

        participant = client.conversations \
            .conversations(conversation_obj.twilio_sid) \
            .participants \
            .create(**participant_params)

        participant_obj = Participant.objects.create(
            participant_sid=participant.sid,
            conversation=conversation_obj,
            phone_number=None,
            user=None  # or link to a special "system" user if desired
        )
        return participant_obj, True

    def _format_phone_number(self, phone_number):
        """
        Format phone number to E.164 format required by Twilio
        Args:
            phone_number (str): Raw phone number in any format (e.g., XXX-XXX-XXXX, (XXX) XXX-XXXX, etc.)
        Returns:
            str: Phone number in E.164 format
        """
        if not phone_number:
            logger.debug("No phone number provided to format")
            return None
            
        # Remove any non-digit characters (including hyphens, parentheses, spaces)
        digits = ''.join(filter(str.isdigit, phone_number))
        
        # Handle XXX-XXX-XXXX format (10 digits)
        if len(digits) == 10:
            formatted = f"+1{digits}"
            return formatted
            
        # If number starts with 1 and is 11 digits, it's already a US number
        if len(digits) == 11 and digits.startswith('1'):
            formatted = f"+{digits}"
            return formatted
            
        # If number already has country code (starts with +), just ensure it's clean
        if phone_number.startswith('+'):
            formatted = f"+{digits}"
            return formatted
            
        # If we can't determine the format, return None
        logger.warning(f"Could not determine format for phone number: {phone_number}")
        return None 