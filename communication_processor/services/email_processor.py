import logging
from typing import Dict, Any, Optional
from django.utils import timezone

from communication_processor.services.base_processor import BaseChannelProcessor
from communication_processor.models import CommunicationEvent
from external_models.models.communications import Conversation, ConversationMessage, Participant
from external_models.models.external_references import Lead


logger = logging.getLogger(__name__)


class EmailProcessor(BaseChannelProcessor):
    """
    Processor for email communication events.
    """
    
    def __init__(self, queue_url: str, config: Dict[str, Any] = None):
        super().__init__('email', queue_url, config)
    
    def validate_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Validate email event data.
        
        Args:
            event_data: The event data to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        required_fields = ['message_id', 'from', 'to']
        
        # Check for required fields
        for field in required_fields:
            if field not in event_data:
                logger.warning(f"Email event missing required field: {field}")
                return False
        
        # Validate email format
        if not self._is_valid_email(event_data.get('from', '')):
            logger.warning(f"Invalid from email: {event_data.get('from')}")
            return False
        
        return True
    
    def process_event(self, event_data: Dict[str, Any]) -> CommunicationEvent:
        """
        Process an email event.
        
        Args:
            event_data: The email event data
            
        Returns:
            CommunicationEvent: The processed event
        """
        # Determine event type
        event_type = self._determine_event_type(event_data)
        
        # Extract email addresses
        from_email = event_data.get('from', '')
        to_email = event_data.get('to', '')
        
        # Try to find lead based on email
        lead = self._get_lead_by_email(from_email or to_email)
        
        # Get or create conversation
        conversation = self._get_or_create_conversation(event_data)
        
        # Get or create participant
        participant = self._get_or_create_participant(conversation, from_email or to_email)
        
        # Create conversation message if this is a message event
        conversation_message = None
        if event_type in ['message_received', 'message_sent']:
            conversation_message = self._create_conversation_message(
                conversation, participant, event_data
            )
        
        # Find associated nurturing campaign
        nurturing_campaign = self._find_nurturing_campaign(event_data, lead)
        
        # Create communication event
        communication_event = CommunicationEvent.objects.create(
            event_type=event_type,
            channel_type=self.channel_type,
            external_id=event_data['message_id'],
            lead=lead,
            conversation=conversation,
            conversation_message=conversation_message,
            nurturing_campaign=nurturing_campaign,
            event_data=self._extract_event_data(event_data),
            raw_data=event_data
        )
        
        return communication_event
    
    def _determine_event_type(self, event_data: Dict[str, Any]) -> str:
        """
        Determine the event type based on email event data.
        
        Args:
            event_data: The event data
            
        Returns:
            str: The event type
        """
        # Check for delivery status events
        if 'event' in event_data:
            event = event_data['event']
            if event == 'delivered':
                return 'delivery_status'
            elif event == 'bounced':
                return 'error'
            elif event == 'opened':
                return 'read_receipt'
            elif event == 'clicked':
                return 'read_receipt'
        
        # Check for message direction
        if event_data.get('direction') == 'inbound':
            return 'message_received'
        elif event_data.get('direction') == 'outbound':
            return 'message_sent'
        
        # Default to message received for inbound messages
        return 'message_received'
    
    def _get_lead_by_email(self, email: str) -> Optional[Lead]:
        """
        Find a lead by email address.
        
        Args:
            email: The email address to search for
            
        Returns:
            Lead or None
        """
        if not email:
            return None
        
        try:
            # This would need to be implemented based on your lead model structure
            # For now, we'll return None and let the caller handle it
            return None
        except Lead.DoesNotExist:
            return None
    
    def _get_or_create_conversation(self, event_data: Dict[str, Any]) -> Conversation:
        """
        Get or create a conversation for this email event.
        
        Args:
            event_data: The event data
            
        Returns:
            Conversation object
        """
        conversation_id = event_data.get('conversation_id') or event_data.get('thread_id')
        
        if conversation_id:
            try:
                return Conversation.objects.get(twilio_sid=conversation_id)
            except Conversation.DoesNotExist:
                pass
        
        # Create new conversation
        conversation_data = {
            'twilio_sid': conversation_id or f"EMAIL_{event_data['message_id']}",
            'channel': 'email',
            'state': 'active',
            'friendly_name': event_data.get('subject', 'Email Conversation')
        }
        
        return Conversation.objects.create(**conversation_data)
    
    def _get_or_create_participant(self, conversation: Conversation, email: str) -> Participant:
        """
        Get or create a participant for this conversation.
        
        Args:
            conversation: The conversation
            email: The email address
            
        Returns:
            Participant object
        """
        if not email:
            # Create a generic participant
            participant_data = {
                'participant_sid': f"EMAIL_PART_{conversation.twilio_sid}_{timezone.now().timestamp()}",
                'conversation': conversation
            }
            return Participant.objects.create(**participant_data)
        
        # Try to find existing participant
        try:
            return Participant.objects.get(
                conversation=conversation,
                metadata__email=email
            )
        except Participant.DoesNotExist:
            # Create new participant
            participant_data = {
                'participant_sid': f"EMAIL_PART_{conversation.twilio_sid}_{email}",
                'conversation': conversation,
                'metadata': {'email': email}
            }
            return Participant.objects.create(**participant_data)
    
    def _create_conversation_message(self, conversation: Conversation, participant: Participant, event_data: Dict[str, Any]) -> ConversationMessage:
        """
        Create a conversation message from the event data.
        
        Args:
            conversation: The conversation
            participant: The participant
            event_data: The event data
            
        Returns:
            ConversationMessage object
        """
        message_data = {
            'message_sid': event_data['message_id'],
            'conversation': conversation,
            'participant': participant,
            'body': event_data.get('body', '') or event_data.get('text', ''),
            'direction': event_data.get('direction', 'inbound'),
            'status': event_data.get('status', 'received'),
            'channel': 'email',
            'raw_data': event_data
        }
        
        return ConversationMessage.objects.create(**message_data)
    
    def _extract_event_data(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract structured event data from the raw event.
        
        Args:
            event_data: The raw event data
            
        Returns:
            Dict with structured event data
        """
        return {
            'message_id': event_data.get('message_id'),
            'from_email': event_data.get('from'),
            'to_email': event_data.get('to'),
            'subject': event_data.get('subject'),
            'body': event_data.get('body') or event_data.get('text'),
            'direction': event_data.get('direction'),
            'status': event_data.get('status'),
            'event': event_data.get('event'),
            'timestamp': event_data.get('timestamp'),
            'headers': event_data.get('headers', {}),
        }
    
    def _is_valid_email(self, email: str) -> bool:
        """
        Basic email validation.
        
        Args:
            email: The email to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email)) 