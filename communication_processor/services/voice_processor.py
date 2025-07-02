import logging
from typing import Dict, Any
from django.utils import timezone

from communication_processor.services.base_processor import BaseChannelProcessor
from communication_processor.models import CommunicationEvent
from shared_services.voice_delivery.voice_delivery_service import VoiceDeliveryService

logger = logging.getLogger(__name__)

class VoiceProcessor(BaseChannelProcessor):
    """Voice processor for handling voice communication events"""
    
    def __init__(self, queue_url: str, config: Dict[str, Any] = None):
        super().__init__('voice', queue_url, config)
        self.voice_delivery = VoiceDeliveryService()
    
    def validate_event(self, event_data: Dict[str, Any]) -> bool:
        """Validate voice event data"""
        required_fields = ['phone_number', 'content']
        return all(field in event_data for field in required_fields)
    
    def process_event(self, event_data: Dict[str, Any]) -> CommunicationEvent:
        """Process a voice communication event"""
        try:
            # Extract event data
            phone_number = event_data.get('phone_number')
            content = event_data.get('content')
            lead_id = event_data.get('lead_id')
            user_id = event_data.get('user_id')
            voice_config_id = event_data.get('voice_config_id')
            
            # Get lead and user
            from external_models.models.external_references import Lead
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            lead = Lead.objects.get(id=lead_id) if lead_id else None
            user = User.objects.get(id=user_id) if user_id else None
            
            # Get voice configuration if specified
            voice_config = None
            if voice_config_id:
                from external_models.models.channel_configs import VoiceConfig
                voice_config = VoiceConfig.objects.get(id=voice_config_id)
            
            # Send voice message
            success, thread_message = self.voice_delivery.send_voice_message(
                content=content,
                lead=lead,
                user=user,
                voice_config=voice_config,
                message_type=event_data.get('message_type', 'regular'),
                metadata=event_data.get('metadata', {})
            )
            
            # Create communication event
            event = CommunicationEvent.objects.create(
                event_type='voice_call_initiated',
                channel='voice',
                lead=lead,
                campaign=event_data.get('campaign'),
                external_id=event_data.get('call_id'),
                event_data={
                    'phone_number': phone_number,
                    'content': content,
                    'success': success,
                    'thread_message_id': thread_message.id if thread_message else None,
                    'voice_config_id': voice_config.id if voice_config else None,
                    **event_data
                },
                timestamp=timezone.now()
            )
            
            return event
            
        except Exception as e:
            logger.error(f"Error processing voice event: {str(e)}")
            raise 