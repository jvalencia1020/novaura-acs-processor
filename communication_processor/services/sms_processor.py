import logging
from typing import Dict, Any, Optional
from django.utils import timezone

from communication_processor.services.base_processor import BaseChannelProcessor
from communication_processor.models import CommunicationEvent
from external_models.models.communications import Conversation, ConversationMessage, Participant
from external_models.models.external_references import Lead


logger = logging.getLogger(__name__)


class SMSProcessor(BaseChannelProcessor):
    """
    Processor for SMS communication events from Twilio.
    """
    
    def __init__(self, queue_url: str, config: Dict[str, Any] = None):
        super().__init__('sms', queue_url, config)
    
    def validate_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Validate SMS event data from Twilio.
        
        Args:
            event_data: The event data to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        required_fields = ['MessageSid', 'AccountSid']
        
        # Check for required fields
        for field in required_fields:
            if field not in event_data:
                logger.warning(f"SMS event missing required field: {field}")
                return False
        
        # Validate MessageSid format (should start with SM)
        if not event_data['MessageSid'].startswith('SM'):
            logger.warning(f"Invalid MessageSid format: {event_data['MessageSid']}")
            return False
        
        return True
    
    def process_event(self, event_data: Dict[str, Any]) -> CommunicationEvent:
        """
        Process an SMS event from Twilio.
        
        Args:
            event_data: The SMS event data
            
        Returns:
            CommunicationEvent: The processed event
        """
        # Determine event type based on Twilio event
        event_type = self._determine_event_type(event_data)
        
        # Extract phone numbers
        from_number = event_data.get('From', '')
        to_number = event_data.get('To', '')
        
        # Try to find or create lead based on phone number
        lead = self._get_lead_by_phone(from_number or to_number)
        
        # Get or create conversation
        conversation = self._get_or_create_conversation(event_data)
        
        # Get or create participant
        participant = self._get_or_create_participant(conversation, from_number or to_number)
        
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
            external_id=event_data['MessageSid'],
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
        Determine the event type based on Twilio event data.
        
        Args:
            event_data: The event data
            
        Returns:
            str: The event type
        """
        # Check for delivery status events
        if 'MessageStatus' in event_data:
            status = event_data['MessageStatus']
            if status == 'delivered':
                return 'delivery_status'
            elif status == 'failed':
                return 'error'
            elif status == 'read':
                return 'read_receipt'
        
        # Check for message direction
        if event_data.get('Direction') == 'inbound':
            return 'message_received'
        elif event_data.get('Direction') == 'outbound-api':
            return 'message_sent'
        
        # Default to message received for inbound messages
        return 'message_received'
    
    def _get_lead_by_phone(self, phone_number: str) -> Optional[Lead]:
        """
        Find a lead by phone number.
        
        Args:
            phone_number: The phone number to search for
            
        Returns:
            Lead or None
        """
        if not phone_number:
            return None
        
        # Clean phone number
        clean_phone = self._clean_phone_number(phone_number)
        
        try:
            # This would need to be implemented based on your lead model structure
            # For now, we'll return None and let the caller handle it
            return None
        except Lead.DoesNotExist:
            return None
    
    def _get_or_create_conversation(self, event_data: Dict[str, Any]) -> Conversation:
        """
        Get or create a conversation for this SMS event.
        
        Args:
            event_data: The event data
            
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
            'twilio_sid': conversation_sid or f"CONV_{event_data['MessageSid']}",
            'account_sid': event_data.get('AccountSid'),
            'messaging_service_sid': event_data.get('MessagingServiceSid'),
            'channel': 'sms',
            'state': 'active'
        }
        
        return Conversation.objects.create(**conversation_data)
    
    def _get_or_create_participant(self, conversation: Conversation, phone_number: str) -> Participant:
        """
        Get or create a participant for this conversation.
        
        Args:
            conversation: The conversation
            phone_number: The phone number
            
        Returns:
            Participant object
        """
        if not phone_number:
            # Create a generic participant
            participant_data = {
                'participant_sid': f"PART_{conversation.twilio_sid}_{timezone.now().timestamp()}",
                'conversation': conversation
            }
            return Participant.objects.create(**participant_data)
        
        # Try to find existing participant
        try:
            return Participant.objects.get(
                conversation=conversation,
                phone_number=phone_number
            )
        except Participant.DoesNotExist:
            # Create new participant
            participant_data = {
                'participant_sid': f"PART_{conversation.twilio_sid}_{phone_number}",
                'conversation': conversation,
                'phone_number': phone_number
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
            'message_sid': event_data['MessageSid'],
            'sms_message_sid': event_data.get('SmsMessageSid'),
            'sms_sid': event_data.get('SmsSid'),
            'account_sid': event_data.get('AccountSid'),
            'messaging_service_sid': event_data.get('MessagingServiceSid'),
            'conversation': conversation,
            'participant': participant,
            'body': event_data.get('Body', ''),
            'direction': event_data.get('Direction', 'inbound'),
            'status': event_data.get('MessageStatus', 'received'),
            'num_segments': event_data.get('NumSegments', 1),
            'num_media': event_data.get('NumMedia', 0),
            'channel': 'sms',
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
            'message_sid': event_data.get('MessageSid'),
            'from_number': event_data.get('From'),
            'to_number': event_data.get('To'),
            'body': event_data.get('Body'),
            'direction': event_data.get('Direction'),
            'status': event_data.get('MessageStatus'),
            'num_segments': event_data.get('NumSegments'),
            'num_media': event_data.get('NumMedia'),
            'price': event_data.get('Price'),
            'price_unit': event_data.get('PriceUnit'),
            'error_code': event_data.get('ErrorCode'),
            'error_message': event_data.get('ErrorMessage'),
        }
    
    def _clean_phone_number(self, phone_number: str) -> str:
        """
        Clean a phone number for consistent formatting.
        
        Args:
            phone_number: The phone number to clean
            
        Returns:
            Cleaned phone number
        """
        # Remove all non-digit characters except +
        import re
        cleaned = re.sub(r'[^\d+]', '', phone_number)
        
        # Ensure it starts with +
        if not cleaned.startswith('+'):
            cleaned = '+' + cleaned
        
        return cleaned 