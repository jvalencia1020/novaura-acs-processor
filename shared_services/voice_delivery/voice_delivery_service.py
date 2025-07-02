import logging
from typing import Dict, Any, Optional, Tuple
from django.utils import timezone

from external_models.models.communications import ConversationThread, ThreadMessage
from external_models.models.channel_configs import VoiceConfig
from external_models.models.reporting import BlandAICall
from ..voice_platforms.voice_platform_factory import VoicePlatformFactory

logger = logging.getLogger(__name__)

class VoiceDeliveryService:
    """Service for delivering voice messages across different platforms"""
    
    def __init__(self):
        self.platform_factory = VoicePlatformFactory()
    
    def send_voice_message(
        self, 
        content: str, 
        lead, 
        user, 
        voice_config: Optional[VoiceConfig] = None,
        message_type: str = 'regular',
        metadata: Dict[str, Any] = None
    ) -> Tuple[bool, Optional[ThreadMessage]]:
        """
        Send a voice message using the appropriate platform
        
        Args:
            content: Message content/task for the AI
            lead: Lead to call
            user: User sending the message
            voice_config: Voice configuration (will use default if not provided)
            message_type: Type of message
            metadata: Additional metadata
            
        Returns:
            Tuple of (success, thread_message)
        """
        try:
            # Validate required data
            if not lead.phone_number:
                raise ValueError("Lead must have a phone number for voice calls")
            
            # Get or create voice configuration
            if not voice_config:
                voice_config = VoiceConfig.objects.filter(platform='bland_ai').first()
                if not voice_config:
                    raise ValueError("No voice configuration found")
            
            # Format phone number
            formatted_phone = self._format_phone_number(lead.phone_number)
            if not formatted_phone:
                raise ValueError(f"Invalid phone number format: {lead.phone_number}")
            
            # Create thread and message records
            thread, thread_message = self._create_thread_records(
                lead, user, content, message_type
            )
            
            # Prepare metadata
            call_metadata = self._prepare_metadata(lead, user, message_type, metadata)
            
            # Get platform and send call
            platform = self.platform_factory.get_platform(voice_config.platform)
            
            # Format payload for the platform
            payload = platform.format_payload(
                voice_config, content, formatted_phone, call_metadata
            )
            
            # Validate payload
            is_valid, error_msg = platform.validate_payload(payload)
            if not is_valid:
                raise ValueError(f"Invalid payload: {error_msg}")
            
            # Send the call
            success, response = platform.send_call(payload)
            
            if success:
                logger.info(f"Successfully initiated {voice_config.platform} call to {formatted_phone}")
                return True, thread_message
            else:
                logger.error(f"Voice call failed: {response.get('error', 'Unknown error')}")
                return False, None
                
        except Exception as e:
            logger.error(f"Error sending voice message: {str(e)}")
            return False, None
    
    def _create_thread_records(self, lead, user, content: str, message_type: str):
        """Create conversation thread and message records"""
        thread = ConversationThread.objects.create(
            lead=lead,
            channel='voice',
            status='open',
            last_message_timestamp=timezone.now()
        )
        
        thread_message = ThreadMessage.objects.create(
            thread=thread,
            sender_type='user',
            content=content,
            channel='voice',
            lead=lead,
            user=user
        )
        
        return thread, thread_message
    
    def _prepare_metadata(self, lead, user, message_type: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Prepare metadata for the call"""
        call_metadata = {
            'lead_id': lead.id,
            'lead_email': lead.email,
            'lead_name': f"{lead.first_name} {lead.last_name}".strip() if lead.first_name or lead.last_name else None,
            'user_id': user.id if user else None,
            'message_type': message_type,
        }
        
        if metadata:
            call_metadata.update(metadata)
        
        return call_metadata
    
    def _create_call_record(self, platform: str, response: Dict[str, Any], lead, phone_number: str, 
                           payload: Dict[str, Any], metadata: Dict[str, Any], thread, thread_message):
        """Create platform-specific call record"""
        if platform == 'bland_ai':
            bland_ai_call = BlandAICall.objects.create(
                call_id=response['call_id'],
                lead=lead,
                phone_number=phone_number,
                request_data=payload,
                metadata=metadata,
                status='queued'
            )
            
            # Link the call to the thread
            thread.bland_ai_call = bland_ai_call
            thread.save()
            
            # Update thread message with call info
            thread_message.bland_ai_message_id = response['call_id']
            thread_message.save()
        
        # Add more platform-specific call records as needed
        # elif platform == 'vapi':
        #     vapi_call = VAPICall.objects.create(...)
    
    def _format_phone_number(self, phone_number: str) -> Optional[str]:
        """Format phone number to E.164 format"""
        if not phone_number:
            return None
            
        # Remove any non-digit characters
        digits = ''.join(filter(str.isdigit, phone_number))
        
        # Handle XXX-XXX-XXXX format (10 digits)
        if len(digits) == 10:
            return f"+1{digits}"
            
        # If number starts with 1 and is 11 digits, it's already a US number
        if len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
            
        # If number already has country code (starts with +), just ensure it's clean
        if phone_number.startswith('+'):
            return f"+{digits}"
            
        return None 