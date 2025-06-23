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
        logger.info(f"Validating SMS event: {event_data.get('MessageSid', 'No MessageSid')}")
        
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
        
        logger.info(f"SMS event validation passed for MessageSid: {event_data['MessageSid']}")
        return True
    
    def process_event(self, event_data: Dict[str, Any]) -> CommunicationEvent:
        """
        Process an SMS event from Twilio using shared services.
        
        Args:
            event_data: The SMS event data
            
        Returns:
            CommunicationEvent: The processed event
        """
        logger.info(f"Processing SMS event: {event_data.get('MessageSid', 'No MessageSid')}")
        
        # Determine event type based on Twilio event
        event_type = self._determine_event_type(event_data)
        logger.info(f"Determined event type: {event_type}")
        
        # Extract phone numbers
        from_number = event_data.get('from_number') or event_data.get('From', '')
        to_number = event_data.get('to_number') or event_data.get('To', '')
        logger.info(f"Phone numbers - From: {from_number}, To: {to_number}")
        
        # Use shared service to find lead
        lead = self.lead_matching_service.get_lead_from_event(event_data, from_number or to_number)
        if lead:
            logger.info(f"Found lead: {lead.id}")
        else:
            logger.info("No lead found for this event")
        
        # Use shared service to get or create conversation
        conversation = self.conversation_service.get_or_create_conversation(event_data, 'sms')
        if conversation:
            logger.info(f"Got/created conversation: {conversation.id}")
        else:
            logger.info("No conversation created")
        
        # Use shared service to get or create participant
        participant = self.conversation_service.get_or_create_participant(conversation, from_number or to_number, 'phone_number')
        if participant:
            logger.info(f"Got/created participant: {participant.id}")
        else:
            logger.info("No participant created")
        
        # Create conversation message if this is a message event
        conversation_message = None
        if event_type in ['message_received', 'message_sent']:
            conversation_message = self.conversation_service.create_conversation_message(
                conversation, participant, event_data, 'sms'
            )
            if conversation_message:
                logger.info(f"Created conversation message: {conversation_message.id}")
            else:
                logger.info("No conversation message created")
        
        # Use shared service to find associated nurturing campaign
        nurturing_campaign = self.campaign_matching_service.find_nurturing_campaign_from_event(event_data, lead)
        if nurturing_campaign:
            logger.info(f"Found nurturing campaign: {nurturing_campaign.id}")
        else:
            logger.info("No nurturing campaign found")
        
        # Process business logic based on event type
        if event_type == 'message_received':
            logger.info("Processing incoming message business logic")
            self._process_incoming_message(event_data, lead, nurturing_campaign, conversation_message)
        
        # Create communication event
        try:
            communication_event = CommunicationEvent.objects.create(
                event_type=event_type,
                channel_type=self.channel_type,
                external_id=event_data.get('message_sid') or event_data.get('MessageSid'),
                lead=lead,
                conversation=conversation,
                conversation_message=conversation_message,
                nurturing_campaign=nurturing_campaign,
                event_data=self._extract_event_data(event_data),
                raw_data=event_data
            )
            logger.info(f"Created communication event: {communication_event.id}")
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
        
        # Use shared service to check for reserved keywords
        keyword_action = self.keyword_processing_service.check_reserved_keywords(message_body)
        
        if keyword_action:
            # Use shared service to handle reserved keyword
            self.keyword_processing_service.handle_reserved_keyword(
                keyword_action, lead, nurturing_campaign, from_number, message_body, 'sms'
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
        
        # Log message context if available
        message_context = event_data.get('message_context', {})
        if message_context:
            logger.info(f"Processed message from {from_number} in campaign '{message_context.get('campaign_name')}' step {message_context.get('step_number')}")
        else:
            logger.info(f"Processed regular message from {from_number}: {message_body[:50]}...")
    
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
            
            logger.info(f"Created journey event for response from {participant.lead}")
            
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
        
        # Log the response
        logger.info(f"Processed bulk campaign response from {participant.lead}")
    
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