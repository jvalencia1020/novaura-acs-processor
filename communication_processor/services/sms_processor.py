import logging
from typing import Dict, Any, Optional
from django.utils import timezone

from communication_processor.services.base_processor import BaseChannelProcessor
from communication_processor.models import CommunicationEvent
from external_models.models.communications import ConversationMessage
from external_models.models.nurturing_campaigns import LeadNurturingParticipant
from communication_processor.utils.message_sender import MessageSender

from shared_services import (
    LeadMatchingService,
    CampaignMatchingService,
    ConversationService,
    KeywordProcessingService,
    AIAgentService
)

logger = logging.getLogger(__name__)


class SMSProcessor(BaseChannelProcessor):
    """
    SMS processor that uses shared services for better code reuse.
    """
    
    def __init__(self, queue_url: str, config: Dict[str, Any] = None):
        super().__init__('sms', queue_url, config)
        self.message_sender = MessageSender()
        
        # Initialize shared services
        self.lead_matching_service = LeadMatchingService()
        self.campaign_matching_service = CampaignMatchingService()
        self.conversation_service = ConversationService()
        self.keyword_processing_service = KeywordProcessingService(self.message_sender)
        self.ai_agent_service = AIAgentService(self.message_sender)
    
    def validate_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Validate SMS event data from Twilio.
        
        Args:
            event_data: The event data to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        # Check for required fields (support both camelCase and snake_case)
        message_sid = event_data.get('MessageSid') or event_data.get('message_sid')
        account_sid = event_data.get('AccountSid') or event_data.get('account_sid')
        
        if not message_sid:
            logger.warning("SMS event missing required field: MessageSid/message_sid")
            return False
            
        if not account_sid:
            logger.warning("SMS event missing required field: AccountSid/account_sid")
            return False
        
        # Validate MessageSid format (should start with SM)
        if not message_sid.startswith('SM'):
            logger.warning(f"Invalid MessageSid format: {message_sid}")
            return False
        
        return True
    
    def process_event(self, event_data: Dict[str, Any], sqs_message=None) -> CommunicationEvent:
        """
        Process an SMS event from Twilio using shared services.
        
        Args:
            event_data: The SMS event data
            sqs_message: The SQS message record (optional)
            
        Returns:
            CommunicationEvent: The processed event
        """
        # Normalize field names to handle both camelCase and snake_case
        message_sid = event_data.get('MessageSid') or event_data.get('message_sid')
        
        # Determine event type based on Twilio event
        event_type = self._determine_event_type(event_data)
        
        # Extract phone numbers (support both formats)
        from_number = event_data.get('from_number') or event_data.get('From', '')
        to_number = event_data.get('to_number') or event_data.get('To', '')
        
        # Use shared service to find lead
        lead = self.lead_matching_service.get_lead_from_event(event_data, from_number or to_number)
        
        # Check if conversation and message already exist (from webhook)
        conversation = None
        conversation_message = None
        participant = None
        
        # Try to get existing conversation and message from the event data
        conversation_id = event_data.get('conversation_id')
        conversation_message_id = event_data.get('conversation_message_id')
        participant_id = event_data.get('participant_id')
        
        if conversation_id and conversation_message_id:
            try:
                from external_models.models.communications import Conversation, ConversationMessage, Participant
                
                # Get existing conversation
                conversation = Conversation.objects.get(id=conversation_id)
                
                # Get existing conversation message
                conversation_message = ConversationMessage.objects.get(id=conversation_message_id)
                
                # Get existing participant
                if participant_id:
                    participant = Participant.objects.get(id=participant_id)
                
            except (Conversation.DoesNotExist, ConversationMessage.DoesNotExist, Participant.DoesNotExist) as e:
                logger.warning(f"Could not find existing records: {e}")
                # Fall back to creating new ones
                conversation = None
                conversation_message = None
                participant = None
        
        # If we don't have existing records, create them
        if not conversation:
            conversation = self.conversation_service.get_or_create_conversation(event_data, 'sms')
        
        if not participant:
            participant = self.conversation_service.get_or_create_participant(conversation, from_number or to_number, 'phone_number')
        
        # Only create conversation message if it doesn't exist and this is a message event
        if not conversation_message and event_type in ['message_received', 'message_sent']:
            conversation_message = self.conversation_service.create_conversation_message(
                conversation, participant, event_data, 'sms'
            )
        
        # Use shared service to find associated nurturing campaign
        nurturing_campaign = self.campaign_matching_service.find_nurturing_campaign_from_event(event_data, lead)
        
        # Process business logic based on event type
        if event_type == 'message_received':
            self._process_incoming_message(event_data, lead, nurturing_campaign, conversation_message)
        
        # Create communication event
        try:
            communication_event_data = {
                'event_type': event_type,
                'channel_type': self.channel_type,
                'external_id': message_sid,
                'lead': lead,
                'conversation': conversation,
                'conversation_message': conversation_message,
                'nurturing_campaign': nurturing_campaign,
                'event_data': self._extract_event_data(event_data),
                'raw_data': event_data
            }
            
            # Add sqs_message if provided
            if sqs_message:
                communication_event_data['sqs_message'] = sqs_message
            
            communication_event = CommunicationEvent.objects.create(**communication_event_data)
            return communication_event
        except Exception as e:
            logger.error(f"Failed to create communication event: {e}", exc_info=True)
            raise
    
    def _process_incoming_message(self, event_data: Dict[str, Any], lead, 
                                nurturing_campaign, conversation_message):
        """
        Process incoming SMS message with business logic using shared services.
        
        Args:
            event_data: The event data
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            conversation_message: The conversation message
        """
        message_body = event_data.get('body', '') or event_data.get('Body', '')
        from_number = event_data.get('from_number') or event_data.get('From', '')
        to_number = event_data.get('to_number') or event_data.get('To', '')  # This is the Twilio number
        
        # Use shared service to check for reserved keywords
        keyword_action = self.keyword_processing_service.check_reserved_keywords(message_body)
        
        if keyword_action:
            # Use shared service to handle reserved keyword, passing the Twilio number
            self.keyword_processing_service.handle_reserved_keyword(
                keyword_action, lead, nurturing_campaign, from_number, message_body, 'sms', to_number
            )
        else:
            # Process regular message
            self._process_regular_message(event_data, lead, nurturing_campaign, conversation_message)
    
    def _process_regular_message(self, event_data: Dict[str, Any], lead, 
                               nurturing_campaign, conversation_message):
        """
        Process regular (non-keyword) message.
        
        Args:
            event_data: The event data
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            conversation_message: The conversation message
        """
        message_body = event_data.get('body', '') or event_data.get('Body', '')
        from_number = event_data.get('from_number') or event_data.get('From', '')
        
        # Update lead engagement metrics
        if lead:
            lead.last_contact_date = timezone.now()
            lead.save(update_fields=['last_contact_date'])
        
        # Process campaign-specific logic
        if nurturing_campaign:
            self._process_campaign_response(event_data, lead, nurturing_campaign, conversation_message)
        
        # Check if agent mode is enabled and handle AI agent response using shared service
        agent_mode = event_data.get('agent_mode', False)
        if agent_mode:
            self.ai_agent_service.handle_agent_response(
                event_data, lead, nurturing_campaign, conversation_message, 'sms'
            )
    
    def _process_campaign_response(self, event_data: Dict[str, Any], lead, 
                                 nurturing_campaign, conversation_message):
        """
        Process campaign-specific response logic.
        
        Args:
            event_data: The event data
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign
            conversation_message: The conversation message
        """
        if not lead:
            return
        
        # Use shared service to get campaign participant
        participant = self.campaign_matching_service.get_campaign_participant(lead, nurturing_campaign)
        
        if not participant:
            return
        
        # Update participant engagement
        participant.last_event_at = timezone.now()
        participant.save(update_fields=['last_event_at'])
        
        # Handle journey-based campaigns
        if nurturing_campaign.campaign_type == 'journey':
            self._process_journey_response(event_data, participant, conversation_message)
        
        # Handle other campaign types (drip, reminder, blast)
        elif nurturing_campaign.campaign_type in ['drip', 'reminder', 'blast']:
            self._process_bulk_campaign_response(event_data, participant, conversation_message)
    
    def _process_journey_response(self, event_data: Dict[str, Any], participant: LeadNurturingParticipant, 
                                conversation_message):
        """
        Process response for journey-based campaigns.
        
        Args:
            event_data: The event data
            participant: The campaign participant
            conversation_message: The conversation message
        """
        # Create journey event for the response
        from external_models.models.journeys import JourneyEvent, EventType
        
        try:
            response_event_type = EventType.objects.get(name='response_received')
            
            JourneyEvent.objects.create(
                participant=participant,
                journey_step=participant.current_journey_step,
                event_type=response_event_type,
                metadata={
                    'message_body': event_data.get('Body', ''),
                    'conversation_message_id': conversation_message.id if conversation_message else None,
                    'from_number': event_data.get('From', ''),
                    'to_number': event_data.get('To', '')
                },
                created_by=participant.last_updated_by
            )
            
        except EventType.DoesNotExist:
            logger.warning("EventType 'response_received' not found")
    
    def _process_bulk_campaign_response(self, event_data: Dict[str, Any], participant: LeadNurturingParticipant, 
                                      conversation_message):
        """
        Process response for bulk campaigns (drip, reminder, blast).
        
        Args:
            event_data: The event data
            participant: The campaign participant
            conversation_message: The conversation message
        """
        # Update campaign progress
        participant.update_campaign_progress()
    
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
    
    def _extract_event_data(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract structured event data from the raw event.
        
        Args:
            event_data: The raw event data
            
        Returns:
            Dict with structured event data
        """
        extracted_data = {
            'message_sid': event_data.get('message_sid') or event_data.get('MessageSid'),
            'from_number': event_data.get('from_number') or event_data.get('From'),
            'to_number': event_data.get('to_number') or event_data.get('To'),
            'body': event_data.get('body') or event_data.get('Body'),
            'direction': event_data.get('direction') or event_data.get('Direction'),
            'status': event_data.get('status') or event_data.get('MessageStatus'),
            'num_segments': event_data.get('num_segments') or event_data.get('NumSegments'),
            'num_media': event_data.get('num_media') or event_data.get('NumMedia'),
            'price': event_data.get('price') or event_data.get('Price'),
            'price_unit': event_data.get('price_unit') or event_data.get('PriceUnit'),
            'error_code': event_data.get('error_code') or event_data.get('ErrorCode'),
            'error_message': event_data.get('error_message') or event_data.get('ErrorMessage'),
        }
        
        # Add enhanced context data
        if 'message_context' in event_data:
            extracted_data['message_context'] = event_data['message_context']
        
        if 'metadata' in event_data:
            extracted_data['metadata'] = event_data['metadata']
        
        if 'processing_hints' in event_data:
            extracted_data['processing_hints'] = event_data['processing_hints']
        
        if 'timestamps' in event_data:
            extracted_data['timestamps'] = event_data['timestamps']
        
        # Add agent mode data
        if 'agent_mode' in event_data:
            extracted_data['agent_mode'] = event_data['agent_mode']
        
        if 'agent_config' in event_data:
            extracted_data['agent_config'] = event_data['agent_config']
        
        return extracted_data 