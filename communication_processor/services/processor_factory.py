import logging
from typing import Dict, Any, Type
from django.conf import settings

from communication_processor.models import ChannelProcessor
from communication_processor.services.base_processor import BaseChannelProcessor
from communication_processor.services.sms_processor import SMSProcessor
from communication_processor.services.email_processor import EmailProcessor


logger = logging.getLogger(__name__)


class ProcessorFactory:
    """
    Factory class for creating channel-specific processors.
    """
    
    # Registry of available processors
    PROCESSORS = {
        'sms': SMSProcessor,
        'email': EmailProcessor,
        # Add more processors as needed:
        # 'voice': VoiceProcessor,
        # 'chat': ChatProcessor,
        # 'whatsapp': WhatsAppProcessor,
    }
    
    @classmethod
    def get_processor(cls, channel_type: str, queue_url: str = None, config: Dict[str, Any] = None) -> BaseChannelProcessor:
        """
        Get a processor instance for the specified channel type.
        
        Args:
            channel_type: The type of communication channel
            queue_url: Optional queue URL (will use database config if not provided)
            config: Optional configuration dict
            
        Returns:
            BaseChannelProcessor: The processor instance
            
        Raises:
            ValueError: If channel type is not supported
        """
        if channel_type not in cls.PROCESSORS:
            raise ValueError(f"Unsupported channel type: {channel_type}")
        
        # If queue_url not provided, try to get from database
        if not queue_url:
            try:
                channel_config = ChannelProcessor.objects.get(
                    channel_type=channel_type,
                    is_active=True
                )
                queue_url = channel_config.queue_url
                if not config:
                    config = channel_config.config
            except ChannelProcessor.DoesNotExist:
                logger.warning(f"No configuration found for channel: {channel_type}")
                return None
        
        processor_class = cls.PROCESSORS[channel_type]
        return processor_class(queue_url, config)
    
    @classmethod
    def get_all_processors(cls) -> Dict[str, BaseChannelProcessor]:
        """
        Get all active processors from the database.
        
        Returns:
            Dict mapping channel types to processor instances
        """
        processors = {}
        
        try:
            channel_configs = ChannelProcessor.objects.filter(is_active=True)
            
            for config in channel_configs:
                try:
                    processor = cls.get_processor(
                        config.channel_type,
                        config.queue_url,
                        config.config
                    )
                    if processor:
                        processors[config.channel_type] = processor
                except Exception as e:
                    logger.error(f"Failed to create processor for {config.channel_type}: {e}")
                    
        except Exception as e:
            logger.error(f"Error loading processor configurations: {e}")
        
        return processors
    
    @classmethod
    def register_processor(cls, channel_type: str, processor_class: Type[BaseChannelProcessor]):
        """
        Register a new processor class.
        
        Args:
            channel_type: The channel type to register
            processor_class: The processor class to register
        """
        if not issubclass(processor_class, BaseChannelProcessor):
            raise ValueError("Processor class must inherit from BaseChannelProcessor")
        
        cls.PROCESSORS[channel_type] = processor_class
        logger.info(f"Registered processor for channel: {channel_type}")
    
    @classmethod
    def get_supported_channels(cls) -> list:
        """
        Get list of supported channel types.
        
        Returns:
            List of supported channel types
        """
        return list(cls.PROCESSORS.keys())
    
    @classmethod
    def validate_processor_config(cls, channel_type: str, config: Dict[str, Any]) -> bool:
        """
        Validate processor configuration.
        
        Args:
            channel_type: The channel type
            config: The configuration to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        if channel_type not in cls.PROCESSORS:
            return False
        
        try:
            # Create a temporary processor instance to validate config
            processor_class = cls.PROCESSORS[channel_type]
            # This is a basic validation - you might want to add more specific validation
            return True
        except Exception as e:
            logger.error(f"Configuration validation failed for {channel_type}: {e}")
            return False 