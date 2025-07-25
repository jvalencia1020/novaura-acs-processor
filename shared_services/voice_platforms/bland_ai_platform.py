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
    
    def _clean_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and validate payload for Bland AI API"""
        cleaned_payload = payload.copy()
        
        # Remove empty strings, None values, and empty collections
        keys_to_remove = []
        for key, value in cleaned_payload.items():
            if value is None or value == "" or value == "None":
                keys_to_remove.append(key)
            elif isinstance(value, (list, dict)) and not value:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del cleaned_payload[key]
        
        # Handle specific field validations
        
        # 1. Remove tools if pathway_id is present (they're mutually exclusive)
        if 'pathway_id' in cleaned_payload and 'tools' in cleaned_payload:
            logger.warning("Removing 'tools' field as it cannot be used with 'pathway_id'")
            del cleaned_payload['tools']
        
        # 2. Validate background_track
        if 'background_track' in cleaned_payload:
            valid_background_tracks = ['none', 'cafe', 'restaurant', 'office']
            if cleaned_payload['background_track'] not in valid_background_tracks:
                logger.warning(f"Invalid background_track '{cleaned_payload['background_track']}'. Removing field.")
                del cleaned_payload['background_track']
        
        # 3. Validate dispatch_hours structure
        if 'dispatch_hours' in cleaned_payload:
            dispatch_hours = cleaned_payload['dispatch_hours']
            if not isinstance(dispatch_hours, dict) or 'start' not in dispatch_hours or 'end' not in dispatch_hours:
                logger.warning("Invalid dispatch_hours structure. Removing field.")
                del cleaned_payload['dispatch_hours']
        
        # 4. Validate transfer_phone_number
        if 'transfer_phone_number' in cleaned_payload:
            transfer_phone = cleaned_payload['transfer_phone_number']
            if not transfer_phone or not isinstance(transfer_phone, str) or not transfer_phone.strip():
                logger.warning("Invalid transfer_phone_number. Removing field.")
                del cleaned_payload['transfer_phone_number']
        
        # 5. Validate start_time format (should be ISO 8601)
        if 'start_time' in cleaned_payload:
            start_time = cleaned_payload['start_time']
            if not start_time or not isinstance(start_time, str) or not start_time.strip():
                logger.warning("Invalid start_time. Removing field.")
                del cleaned_payload['start_time']
        
        # 6. Validate precall_dtmf_sequence (should only contain digits, *, #, and p for pause)
        if 'precall_dtmf_sequence' in cleaned_payload:
            dtmf_sequence = cleaned_payload['precall_dtmf_sequence']
            if dtmf_sequence:
                import re
                if not re.match(r'^[0-9*#p]+$', dtmf_sequence):
                    logger.warning(f"Invalid DTMF sequence '{dtmf_sequence}'. Removing field.")
                    del cleaned_payload['precall_dtmf_sequence']
        
        # 7. Validate retry field (must be an object, not string)
        if 'retry' in cleaned_payload:
            retry_value = cleaned_payload['retry']
            if not isinstance(retry_value, dict):
                logger.warning("Retry must be an object. Removing field.")
                del cleaned_payload['retry']
        
        # 8. Validate voicemail_sms structure
        if 'voicemail_sms' in cleaned_payload:
            voicemail_sms = cleaned_payload['voicemail_sms']
            if not isinstance(voicemail_sms, dict) or not voicemail_sms:
                logger.warning("Invalid voicemail_sms structure. Removing field.")
                del cleaned_payload['voicemail_sms']
        
        # 9. Validate transfer_list structure
        if 'transfer_list' in cleaned_payload:
            transfer_list = cleaned_payload['transfer_list']
            if not isinstance(transfer_list, dict) or not transfer_list:
                logger.warning("Invalid transfer_list structure. Removing field.")
                del cleaned_payload['transfer_list']
        
        # 10. Validate request_data structure
        if 'request_data' in cleaned_payload:
            request_data = cleaned_payload['request_data']
            if not isinstance(request_data, dict) or not request_data:
                logger.warning("Invalid request_data structure. Removing field.")
                del cleaned_payload['request_data']
        
        logger.debug(f"Cleaned payload: {cleaned_payload}")
        return cleaned_payload


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
        
        # Additional validations
        if 'tools' in payload and 'pathway_id' in payload:
            return False, "Cannot use tools with pathway_id enabled"
        
        if 'background_track' in payload:
            valid_background_tracks = ['none', 'cafe', 'restaurant', 'office']
            if payload['background_track'] not in valid_background_tracks:
                return False, f"Invalid background_track. Must be one of: {valid_background_tracks}"
        
        if 'retry' in payload and not isinstance(payload['retry'], dict):
            return False, "Retry must be an object"
        
        if 'dispatch_hours' in payload:
            dispatch_hours = payload['dispatch_hours']
            if not isinstance(dispatch_hours, dict) or 'start' not in dispatch_hours or 'end' not in dispatch_hours:
                return False, "Dispatch hours must have start and end keys"
        
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
                    value = voice_config.platform_config[field]
                    # Only add non-empty values
                    if value is not None and value != "" and value != "None":
                        # Special handling for collections - only add if they have content
                        if isinstance(value, (list, dict)):
                            if value:  # Only add non-empty collections
                                payload[field] = value
                        else:
                            payload[field] = value
        
        return payload 