import requests
import logging
from typing import Dict, Any, Tuple
from django.conf import settings

from .base_voice_platform import BaseVoicePlatform

logger = logging.getLogger(__name__)

class BlandAIPlatform(BaseVoicePlatform):
    """Bland AI voice platform implementation"""
    
    def _get_api_key(self) -> str:
        return getattr(settings, 'BLAND_AI_API_KEY', None)
    


    def send_call(self, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Send call via Bland AI API"""
        try:
            if not self.api_key:
                return False, {'error': 'BLAND_AI_API_KEY not configured'}
            
            # Clean the payload before sending
            cleaned_payload = self._clean_payload(payload)
            
            url = "https://api.bland.ai/v1/calls"
            headers = {
                'authorization': self.api_key,
                'Content-Type': 'application/json'
            }
            
            logger.debug(f"Making Bland AI API call with cleaned payload: {cleaned_payload}")
            
            response = requests.post(url, json=cleaned_payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"Bland AI API response: {result}")
            
            return result.get('status') == 'success', result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Bland AI API request failed: {str(e)}")
            return False, {'error': f'API request failed: {str(e)}'}
        except Exception as e:
            logger.error(f"Unexpected error in Bland AI API call: {str(e)}")
            return False, {'error': f'Unexpected error: {str(e)}'}
    
    def validate_payload(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate Bland AI payload"""
        required_fields = ['phone_number', 'pathway_id']
        for field in required_fields:
            if not payload.get(field):
                return False, f"Missing required field: {field}"
        return True, ""
    
    def format_payload(self, voice_config, content: str, phone_number: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Format payload for Bland AI"""
        config = voice_config.get_platform_config()
        
        payload = {
            'phone_number': phone_number,
            'task': content,  # Bland AI uses 'task' instead of 'content'
            'metadata': metadata
        }
        
        # Add configuration from VoiceConfig
        for key in ['from', 'voice', 'language', 'max_duration', 'record']:
            if config.get(key):
                payload[key] = config[key]
        
        # Add webhook configuration
        if config.get('webhook'):
            payload['webhook'] = config['webhook']
        if config.get('webhook_events'):
            payload['webhook_events'] = config['webhook_events']
        
        # Add voicemail configuration
        if config.get('voicemail_message'):
            payload['voicemail_message'] = config['voicemail_message']
        if config.get('voicemail_action'):
            payload['voicemail_action'] = config['voicemail_action']
        
        # Add platform-specific configuration from platform_config
        if voice_config.platform_config:
            # Common Bland AI fields that should be in platform_config
            bland_ai_fields = [
                'pathway_id',
                'background_track',
                'first_sentence',
                'wait_for_greeting',
                'block_interruptions',
                'interruption_threshold',
                'model',
                'temperature',
                'dynamic_data',
                'keywords',
                'pronunciation_guide',
                'transfer_phone_number',
                'transfer_list',
                'pathway_version',
                'local_dialing',
                'voicemail_sms',
                'dispatch_hours',
                'ignore_button_press',
                'timezone',
                'request_data',
                'tools',
                'start_time',
                'retry',
                'citation_schema_id',
                'analysis_preset',
                'available_tags',
                'geospatial_dialing',
                'precall_dtmf_sequence'
            ]
            
            for field in bland_ai_fields:
                if field in voice_config.platform_config:
                    payload[field] = voice_config.platform_config[field]
        
        return payload 