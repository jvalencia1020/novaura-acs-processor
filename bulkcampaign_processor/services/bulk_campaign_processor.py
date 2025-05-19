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
        now = timezone.now()

        # Check if it's time to send the blast
        if schedule.send_time > now:
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
        """Send an SMS message using Twilio Conversations API and track it in our system"""
        try:
            # Get or create Twilio conversation
            conversation_obj, _ = self._create_or_get_twilio_conversation(
                lead=message.participant.lead,
                friendly_name=f"Campaign-{message.campaign.id}-Lead-{message.participant.lead.id}"
            )

            # Get the service phone number
            service_phone = None
            if message.campaign.config and message.campaign.config.get('from_number'):
                service_phone = message.campaign.config['from_number']
                print(f"Using service phone from campaign config: {service_phone}")
            elif message.campaign.crm_campaign and message.campaign.crm_campaign.campaign_from_number:
                service_phone = message.campaign.crm_campaign.campaign_from_number
                print(f"Using service phone from CRM campaign: {service_phone}")

            if not service_phone:
                raise ValueError("No service phone number found in campaign configuration")

            print(f"Lead phone number: {message.participant.lead.phone_number}")
            print(f"Service phone number: {service_phone}")
            formatted_proxy = self._format_phone_number(service_phone)
            print(f"Formatted service phone: {formatted_proxy}")

            # Add lead participant
            lead_participant, _ = self._add_participant_to_twilio_conversation(
                conversation_obj=conversation_obj,
                phone_number=message.participant.lead.phone_number,
                proxy_address=formatted_proxy
            )

            # Add system identity with projected address
            system_identity = 'acs-system'
            system_participant, _ = self._add_identity_participant(
                conversation_obj=conversation_obj,
                identity=system_identity,
                projected_address=formatted_proxy
            )

            # Send message using system identity as the author
            message_obj = self._send_twilio_conversation_message(
                conversation_obj=conversation_obj,
                author=system_identity,
                body=message.campaign.content,
                channel='sms'
            )

            # Create thread and thread message for tracking
            thread = ConversationThread.objects.create(
                lead=message.participant.lead,
                channel='sms',
                status='open',
                twilio_conversation=conversation_obj,
                last_message_timestamp=timezone.now()
            )

            ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=message.campaign.content,
                channel='sms',
                twilio_message=message_obj,
                lead=message.participant.lead,
                user=message.campaign.created_by
            )

            return True

        except Exception as e:
            print(f"Error sending SMS message: {str(e)}")
            return False

    def _create_or_get_twilio_conversation(self, lead=None, friendly_name=None):
        """
        Return a tuple of (conversation_obj, created).
        If an active conversation linked to a lead exists, reuse it.
        Otherwise, create a new conversation in Twilio and store it locally.
        """
        if lead:
            existing = Conversation.objects.filter(lead=lead, state='active').first()
            if existing:
                return existing, False

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        convo = client.conversations.conversations.create(friendly_name=friendly_name)
        conversation_obj = Conversation.objects.create(
            twilio_sid=convo.sid,
            friendly_name=convo.friendly_name,
            state=convo.state,  # Expecting "active"
            lead=lead,
            created_by=None  # Will be updated in the view if needed
        )
        return conversation_obj, True

    def _format_phone_number(self, phone_number):
        """
        Format phone number to E.164 format required by Twilio
        Args:
            phone_number (str): Raw phone number in any format (e.g., XXX-XXX-XXXX, (XXX) XXX-XXXX, etc.)
        Returns:
            str: Phone number in E.164 format
        """
        if not phone_number:
            print("No phone number provided to format")
            return None
            
        # Remove any non-digit characters (including hyphens, parentheses, spaces)
        digits = ''.join(filter(str.isdigit, phone_number))
        print(f"Extracted digits from phone number: {digits}")
        
        # Handle XXX-XXX-XXXX format (10 digits)
        if len(digits) == 10:
            formatted = f"+1{digits}"
            print(f"Formatted 10-digit number: {formatted}")
            return formatted
            
        # If number starts with 1 and is 11 digits, it's already a US number
        if len(digits) == 11 and digits.startswith('1'):
            formatted = f"+{digits}"
            print(f"Formatted 11-digit number: {formatted}")
            return formatted
            
        # If number already has country code (starts with +), just ensure it's clean
        if phone_number.startswith('+'):
            formatted = f"+{digits}"
            print(f"Formatted number with existing country code: {formatted}")
            return formatted
            
        # If we can't determine the format, return None
        print(f"Could not determine format for phone number: {phone_number}")
        return None

    def _add_participant_to_twilio_conversation(self, conversation_obj, phone_number=None, user=None, proxy_address=None):
        """
        Create or retrieve a Participant for this conversation in Twilio and locally.
        If no user is specified, defaults to system user (ID=7).
        
        Args:
            conversation_obj: The conversation object
            phone_number: The phone number to add as a participant
            user: The user to associate with the participant
            proxy_address: The Twilio phone number to use as proxy for SMS
        """
        if phone_number:
            # Format phone number to E.164
            formatted_number = self._format_phone_number(phone_number)
            print(f"Attempting to add participant with formatted number: {formatted_number}")
            if not formatted_number:
                raise ValueError(f"Invalid phone number format: {phone_number}")
                
            existing = Participant.objects.filter(
                conversation=conversation_obj,
                phone_number=phone_number
            ).first()
            if existing:
                return existing, False

        # If no user specified, use default system user (ID=7)
        if not user:
            from external_models.models.accounts import User
            user = User.objects.get(id=7)

        existing = Participant.objects.filter(
            conversation=conversation_obj,
            user=user
        ).first()
        if existing:
            return existing, False

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        if phone_number:
            print(f"Creating Twilio participant with phone number: {formatted_number}")
            print(f"Conversation SID: {conversation_obj.twilio_sid}")
            try:
                # Create participant with both binding address and proxy address
                participant = client.conversations \
                    .conversations(conversation_obj.twilio_sid) \
                    .participants \
                    .create(
                        messaging_binding_address=formatted_number,
                        messaging_binding_proxy_address=proxy_address
                    )
                print(f"Successfully created participant with SID: {participant.sid}")
            except Exception as e:
                print(f"Twilio API Error: {str(e)}")
                print(f"Request details:")
                print(f"- Conversation SID: {conversation_obj.twilio_sid}")
                print(f"- Phone number: {formatted_number}")
                print(f"- Proxy address: {proxy_address}")
                raise
        else:
            participant = client.conversations \
                .conversations(conversation_obj.twilio_sid) \
                .participants \
                .create(identity=f"user-{user.id}")

        participant_obj = Participant.objects.create(
            participant_sid=participant.sid,
            conversation=conversation_obj,
            phone_number=phone_number,
            user=user
        )
        return participant_obj, True

    def _send_twilio_conversation_message(self, conversation_obj, author, body, channel=None):
        """
        Send a message via Twilio's Conversations API and store it locally.
        
        Args:
            conversation_obj: The conversation object
            author: The author of the message (can be 'system' or a participant SID)
            body: The message content
            channel: The channel type (e.g., 'sms')
        """
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.conversations \
            .conversations(conversation_obj.twilio_sid) \
            .messages \
            .create(
                author=author,
                body=body
            )
        
        # Create message object without participant if author is 'system'
        message_obj = ConversationMessage.objects.create(
            message_sid=message.sid,
            conversation=conversation_obj,
            participant=None if author == 'system' else Participant.objects.get(participant_sid=author),
            body=body,
            direction='outbound',
            channel=channel
        )
        return message_obj

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
            print(f"Found existing participant in database with SID: {existing.participant_sid}")
            return existing, False

        # Check if the participant exists in Twilio
        print(f"Checking for existing participant with identity='{identity}' in Twilio")
        existing_participants = client.conversations \
            .conversations(conversation_obj.twilio_sid) \
            .participants \
            .list()

        # Look for a participant with matching identity
        for participant in existing_participants:
            if participant.identity == identity:
                print(f"Found existing participant in Twilio with SID: {participant.sid}")
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
        print(f"Adding new identity participant with identity='{identity}'")
        participant_params = {'identity': identity}
        
        # Add projected address if provided
        if projected_address:
            print(f"Using projected address: {projected_address}")
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