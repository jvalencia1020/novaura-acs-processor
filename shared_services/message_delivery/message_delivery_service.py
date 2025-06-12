import logging
from django.utils import timezone
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from django.conf import settings

from external_models.models.communications import (
    Conversation,
    Participant,
    ConversationMessage,
    ConversationThread,
    ThreadMessage
)

logger = logging.getLogger(__name__)

class MessageDeliveryService:
    """
    Service class for handling message delivery operations across different channels.
    This service can be used by both JourneyProcessor and BulkCampaignProcessor.
    """

    def __init__(self):
        self.twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    def send_message(self, channel, content, lead, user, subject=None, service_phone=None, message_type='regular'):
        """
        Send a message through the specified channel.
        
        Args:
            channel (str): The channel to send through ('sms', 'email', 'voice', 'chat')
            content (str): The message content
            lead: The lead to send to
            user: The user sending the message
            subject (str, optional): Subject for email messages
            service_phone (str, optional): Service phone number for SMS/Voice
            message_type (str, optional): Type of message ('regular', 'opt_out_notice', 'opt_out_confirmation')
            
        Returns:
            tuple: (success, thread_message)
        """
        try:
            # Log message type for tracking
            logger.info(f"Sending {message_type} message through {channel} channel")

            if channel == 'sms':
                return self._send_sms(content, lead, user, service_phone, message_type)
            elif channel == 'email':
                return self._send_email(content, lead, user, subject, message_type)
            elif channel == 'voice':
                return self._send_voice(content, lead, user, message_type)
            elif channel == 'chat':
                return self._send_chat(content, lead, user, message_type)
            else:
                logger.error(f"Unsupported channel: {channel}")
                return False, None
        except Exception as e:
            logger.exception(f"Error sending {channel} message: {str(e)}")
            return False, None

    def _send_sms(self, content, lead, user, service_phone, message_type='regular'):
        """Send an SMS message using Twilio"""
        try:
            if not service_phone:
                raise ValueError("No service phone number provided for SMS")

            # Format phone numbers
            formatted_to = self._format_phone_number(lead.phone_number)
            formatted_from = self._format_phone_number(service_phone)

            if not formatted_to or not formatted_from:
                raise ValueError("Invalid phone number format")

            # Send message directly
            twilio_message = self.twilio_client.messages.create(
                body=content,
                from_=formatted_from,
                to=formatted_to,
            )

            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='sms',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create conversation for the message
            conversation = Conversation.objects.create(
                twilio_sid=twilio_message.sid,
                lead=lead,
                channel='sms',
                state='active',
                created_by=user
            )

            # Create thread message with message type
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=content,
                channel='sms',
                lead=lead,
                user=user,
                message_type=message_type,
                twilio_message=ConversationMessage.objects.create(
                    message_sid=twilio_message.sid,
                    conversation=conversation,
                    body=content,
                    direction='outbound',
                    channel='sms'
                )
            )

            # Log successful opt-out message delivery
            if message_type in ['opt_out_notice', 'opt_out_confirmation']:
                logger.info(f"Successfully sent {message_type} message to {lead.email} via SMS")

            return True, thread_message

        except Exception as e:
            logger.error(f"Error sending SMS message: {str(e)}")
            return False, None

    def _send_email(self, content, lead, user, subject=None, message_type='regular'):
        """Send an email message"""
        try:
            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='email',
                status='open',
                subject=subject,
                last_message_timestamp=timezone.now()
            )

            # Create thread message with message type
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=content,
                channel='email',
                lead=lead,
                user=user,
                message_type=message_type
            )

            # TODO: Implement actual email sending using your email service
            # This could be SendGrid, Mailgun, etc.
            # For now, we'll just mark it as sent
            thread_message.read_status = True
            thread_message.save()

            # Log successful opt-out message delivery
            if message_type in ['opt_out_notice', 'opt_out_confirmation']:
                logger.info(f"Successfully sent {message_type} message to {lead.email} via email")

            return True, thread_message

        except Exception as e:
            logger.error(f"Error sending email message: {str(e)}")
            return False, None

    def _send_voice(self, content, lead, user, message_type='regular'):
        """Send a voice message"""
        try:
            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='voice',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message with message type
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=content,
                channel='voice',
                lead=lead,
                user=user,
                message_type=message_type
            )

            # TODO: Implement actual voice call using Bland AI
            # This would involve:
            # 1. Creating a Bland AI call
            # 2. Linking it to the thread
            # 3. Initiating the call
            # For now, we'll just mark it as sent
            thread_message.read_status = True
            thread_message.save()

            # Log successful opt-out message delivery
            if message_type in ['opt_out_notice', 'opt_out_confirmation']:
                logger.info(f"Successfully sent {message_type} message to {lead.email} via voice")

            return True, thread_message

        except Exception as e:
            logger.error(f"Error sending voice message: {str(e)}")
            return False, None

    def _send_chat(self, content, lead, user, message_type='regular'):
        """Send a chat message"""
        try:
            # Create thread for tracking
            thread = ConversationThread.objects.create(
                lead=lead,
                channel='chat',
                status='open',
                last_message_timestamp=timezone.now()
            )

            # Create thread message with message type
            thread_message = ThreadMessage.objects.create(
                thread=thread,
                sender_type='user',
                content=content,
                channel='chat',
                lead=lead,
                user=user,
                message_type=message_type
            )

            # TODO: Implement actual chat message sending using your chat service
            # This could be Intercom, Drift, etc.
            # For now, we'll just mark it as sent
            thread_message.read_status = True
            thread_message.save()

            # Log successful opt-out message delivery
            if message_type in ['opt_out_notice', 'opt_out_confirmation']:
                logger.info(f"Successfully sent {message_type} message to {lead.email} via chat")

            return True, thread_message

        except Exception as e:
            logger.error(f"Error sending chat message: {str(e)}")
            return False, None

    def _format_phone_number(self, phone_number):
        """
        Format phone number to E.164 format required by Twilio
        Args:
            phone_number (str): Raw phone number in any format
        Returns:
            str: Phone number in E.164 format
        """
        if not phone_number:
            logger.debug("No phone number provided to format")
            return None
            
        # Remove any non-digit characters
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

    def add_identity_participant(self, conversation_obj, identity, projected_address=None):
        """
        Add an identity-based participant to the conversation.
        
        Args:
            conversation_obj: The conversation object
            identity: The identity to use for the participant
            projected_address: The phone number to project for this identity
            
        Returns:
            tuple: (participant_obj, created)
        """
        # First check if the participant exists in our database
        existing = Participant.objects.filter(
            conversation=conversation_obj,
            user=None,
            phone_number=None,
        ).first()

        if existing:
            logger.debug(f"Found existing participant in database with SID: {existing.participant_sid}")
            return existing, False

        # Check if the participant exists in Twilio
        logger.debug(f"Checking for existing participant with identity='{identity}' in Twilio")
        existing_participants = self.twilio_client.conversations \
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

        participant = self.twilio_client.conversations \
            .conversations(conversation_obj.twilio_sid) \
            .participants \
            .create(**participant_params)

        participant_obj = Participant.objects.create(
            participant_sid=participant.sid,
            conversation=conversation_obj,
            phone_number=None,
            user=None
        )
        return participant_obj, True 