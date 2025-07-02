from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from django.conf import settings

class BaseVoicePlatform(ABC):
    """Abstract base class for voice platforms"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_key = self._get_api_key()
    
    @abstractmethod
    def _get_api_key(self) -> str:
        """Get API key for the platform"""
        pass
    
    @abstractmethod
    def send_call(self, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Send a voice call through the platform"""
        pass
    
    @abstractmethod
    def validate_payload(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate payload for the platform"""
        pass
    
    @abstractmethod
    def format_payload(self, voice_config, content: str, phone_number: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Format payload for the platform"""
        pass
    
    def _clean_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove empty strings, empty objects, and empty lists from payload.
        This helps prevent 400 errors from voice platform APIs.
        
        Args:
            payload: The payload to clean
            
        Returns:
            Cleaned payload with empty values removed
        """
        def clean_value(value):
            if isinstance(value, dict):
                # Clean nested dictionaries
                cleaned = {}
                for k, v in value.items():
                    cleaned_v = clean_value(v)
                    if cleaned_v is not None:
                        cleaned[k] = cleaned_v
                return cleaned if cleaned else None
            elif isinstance(value, list):
                # Clean lists
                cleaned = [clean_value(v) for v in value if clean_value(v) is not None]
                return cleaned if cleaned else None
            elif isinstance(value, str):
                # Remove empty strings
                return value if value.strip() else None
            else:
                # Keep other values (numbers, booleans, etc.)
                return value
        
        cleaned_payload = {}
        for key, value in payload.items():
            cleaned_value = clean_value(value)
            if cleaned_value is not None:
                cleaned_payload[key] = cleaned_value
        
        return cleaned_payload 