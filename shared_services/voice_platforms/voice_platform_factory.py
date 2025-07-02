from typing import Dict, Type
from .base_voice_platform import BaseVoicePlatform
from .bland_ai_platform import BlandAIPlatform

class VoicePlatformFactory:
    """Factory for creating voice platform instances"""
    
    PLATFORMS: Dict[str, Type[BaseVoicePlatform]] = {
        'bland_ai': BlandAIPlatform,
        # Add more platforms as needed:
        # 'vapi': VAPIPlatform,
        # 'elevenlabs': ElevenLabsPlatform,
        # 'twilio': TwilioVoicePlatform,
    }
    
    @classmethod
    def get_platform(cls, platform_name: str, config: Dict = None) -> BaseVoicePlatform:
        """Get a voice platform instance"""
        if platform_name not in cls.PLATFORMS:
            raise ValueError(f"Unsupported voice platform: {platform_name}")
        
        platform_class = cls.PLATFORMS[platform_name]
        return platform_class(config)
    
    @classmethod
    def register_platform(cls, name: str, platform_class: Type[BaseVoicePlatform]):
        """Register a new voice platform"""
        if not issubclass(platform_class, BaseVoicePlatform):
            raise ValueError("Platform class must inherit from BaseVoicePlatform")
        
        cls.PLATFORMS[name] = platform_class
    
    @classmethod
    def get_supported_platforms(cls) -> list:
        """Get list of supported platforms"""
        return list(cls.PLATFORMS.keys()) 