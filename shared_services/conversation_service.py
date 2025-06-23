import logging
from typing import Optional, Dict, Any
from django.utils import timezone
from external_models.models.communications import Conversation, ConversationMessage, Participant

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Service for managing conversations across different communication channels.
    Provides reusable methods for creating and managing conversations, participants, and messages.
    """

    def get_or_create_conversation(self, event_data: Dict[str, Any], channel: str = 'sms') -> Conversation:
        """
        Get or create a conversation for this event.
        
        Args:
            event_data: The event data
            channel: The communication channel
            
        Returns:
            Conversation object
        """
        conversation_sid = event_data.get('ConversationSid')
        
        if conversation_sid:
            try:
                return Conversation.objects.get(twilio_sid=conversation_sid)
            except Conversation.DoesNotExist:
                pass
        
        # Create new conversation
        conversation_data = {
            'twilio_sid': conversation_sid or f"CONV_{event_data.get('MessageSid', '')}_{timezone.now().timestamp()}",
            'account_sid': event_data.get('AccountSid'),
            'messaging_service_sid': event_data.get('MessagingServiceSid'),
            'channel': channel,
            'state': 'active'
        }
        
        return Conversation.objects.create(**conversation_data)
    
    def get_or_create_participant(self, conversation: Conversation, identifier: str, 
                                identifier_type: str = 'phone_number') -> Participant:
        """
        Get or create a participant for this conversation.
        
        Args:
            conversation: The conversation
            identifier: The participant identifier (phone, email, etc.)
            identifier_type: The type of identifier ('phone_number', 'email', etc.)
            
        Returns:
            Participant object
        """
        if not identifier:
            # Create a generic participant
            participant_data = {
                'participant_sid': f"PART_{conversation.twilio_sid}_{timezone.now().timestamp()}",
                'conversation': conversation
            }
            return Participant.objects.create(**participant_data)
        
        # Try to find existing participant
        try:
            if identifier_type == 'phone_number':
                return Participant.objects.get(
                    conversation=conversation,
                    phone_number=identifier
                )
            # Add other identifier types as needed
            else:
                return Participant.objects.get(
                    conversation=conversation,
                    phone_number=identifier
                )
        except Participant.DoesNotExist:
            # Create new participant
            participant_data = {
                'participant_sid': f"PART_{conversation.twilio_sid}_{identifier}",
                'conversation': conversation,
                identifier_type: identifier
            }
            return Participant.objects.create(**participant_data)
    
    def create_conversation_message(self, conversation: Conversation, participant: Participant, 
                                  event_data: Dict[str, Any], channel: str = 'sms') -> ConversationMessage:
        """
        Create a conversation message from the event data.
        
        Args:
            conversation: The conversation
            participant: The participant
            event_data: The event data
            channel: The communication channel
            
        Returns:
            ConversationMessage object
        """
        message_data = {
            'message_sid': event_data.get('MessageSid') or event_data.get('message_sid'),
            'sms_message_sid': event_data.get('SmsMessageSid'),
            'sms_sid': event_data.get('SmsSid'),
            'account_sid': event_data.get('AccountSid'),
            'messaging_service_sid': event_data.get('MessagingServiceSid'),
            'conversation': conversation,
            'participant': participant,
            'body': event_data.get('Body', '') or event_data.get('body', ''),
            'direction': event_data.get('Direction', 'inbound'),
            'status': event_data.get('MessageStatus', 'received'),
            'num_segments': event_data.get('NumSegments', 1),
            'num_media': event_data.get('NumMedia', 0),
            'channel': channel,
            'raw_data': event_data
        }
        
        return ConversationMessage.objects.create(**message_data)
    
    def update_conversation_status(self, conversation: Conversation, status: str) -> bool:
        """
        Update the status of a conversation.
        
        Args:
            conversation: The conversation to update
            status: The new status
            
        Returns:
            bool: True if update was successful
        """
        try:
            conversation.state = status
            conversation.updated_at = timezone.now()
            conversation.save()
            logger.info(f"Updated conversation {conversation.twilio_sid} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating conversation status: {e}")
            return False
    
    def get_conversation_by_sid(self, conversation_sid: str) -> Optional[Conversation]:
        """
        Get a conversation by its SID.
        
        Args:
            conversation_sid: The conversation SID
            
        Returns:
            Conversation or None
        """
        try:
            return Conversation.objects.get(twilio_sid=conversation_sid)
        except Conversation.DoesNotExist:
            logger.info(f"Conversation with SID {conversation_sid} not found")
            return None
        except Exception as e:
            logger.error(f"Error getting conversation by SID {conversation_sid}: {e}")
            return None
    
    def get_participant_by_identifier(self, conversation: Conversation, identifier: str, 
                                    identifier_type: str = 'phone_number') -> Optional[Participant]:
        """
        Get a participant by identifier.
        
        Args:
            conversation: The conversation
            identifier: The participant identifier
            identifier_type: The type of identifier
            
        Returns:
            Participant or None
        """
        try:
            if identifier_type == 'phone_number':
                return Participant.objects.get(
                    conversation=conversation,
                    phone_number=identifier
                )
            # Add other identifier types as needed
            else:
                return Participant.objects.get(
                    conversation=conversation,
                    phone_number=identifier
                )
        except Participant.DoesNotExist:
            logger.info(f"Participant with {identifier_type} {identifier} not found in conversation {conversation.twilio_sid}")
            return None
        except Exception as e:
            logger.error(f"Error getting participant by {identifier_type} {identifier}: {e}")
            return None
    
    def get_conversation_messages(self, conversation: Conversation, limit: int = 50) -> list:
        """
        Get recent messages for a conversation.
        
        Args:
            conversation: The conversation
            limit: Maximum number of messages to return
            
        Returns:
            List of conversation messages
        """
        try:
            return list(ConversationMessage.objects.filter(
                conversation=conversation
            ).order_by('-created_at')[:limit])
        except Exception as e:
            logger.error(f"Error getting messages for conversation {conversation.twilio_sid}: {e}")
            return [] 