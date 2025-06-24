import logging
from typing import Optional, Dict, Any
from django.conf import settings

logger = logging.getLogger(__name__)


class MessageSender:
    """
    Utility class for sending response messages to users.
    This can be extended to support different messaging platforms.
    """
    
    def __init__(self, platform: str = 'twilio'):
        self.platform = platform
        self.client = self._get_client()
    
    def _get_client(self):
        """Get the appropriate client for the messaging platform."""
        if self.platform == 'twilio':
            try:
                from twilio.rest import Client
                return Client(
                    settings.TWILIO_ACCOUNT_SID,
                    settings.TWILIO_AUTH_TOKEN
                )
            except ImportError:
                logger.error("Twilio client not available")
                return None
        return None
    
    def send_sms(self, to_number: str, message: str, from_number: Optional[str] = None) -> bool:
        """
        Send an SMS message.
        
        Args:
            to_number: The recipient's phone number
            message: The message content
            from_number: The sender's phone number (optional)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.client:
            logger.error("No messaging client available")
            return False
        
        try:
            if self.platform == 'twilio':
                from_number = from_number or getattr(settings, 'TWILIO_PHONE_NUMBER', None)
                if not from_number:
                    logger.error("No from_number provided and TWILIO_PHONE_NUMBER not configured")
                    return False
                
                message = self.client.messages.create(
                    body=message,
                    from_=from_number,
                    to=to_number
                )
                
                logger.info(f"SMS sent successfully: {message.sid}")
                return True
                
        except Exception as e:
            logger.error(f"Error sending SMS to {to_number}: {e}")
            return False
    
    def send_opt_out_confirmation(self, to_number: str, campaign_name: Optional[str] = None, from_number: Optional[str] = None) -> bool:
        """
        Send opt-out confirmation message.
        
        Args:
            to_number: The recipient's phone number
            campaign_name: Optional campaign name
            from_number: The sender's phone number (optional)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        message = "You have been unsubscribed from this campaign. You will no longer receive messages."
        if campaign_name:
            message = f"You have been unsubscribed from '{campaign_name}'. You will no longer receive messages."
        
        return self.send_sms(to_number, message, from_number)
    
    def send_help_message(self, to_number: str, from_number: Optional[str] = None) -> bool:
        """
        Send help message.
        
        Args:
            to_number: The recipient's phone number
            from_number: The sender's phone number (optional)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        message = (
            "Reply STOP to opt out of messages. "
            "Reply HELP for this message. "
            "Reply INFO for more information."
        )
        
        return self.send_sms(to_number, message, from_number)
    
    def send_info_message(self, to_number: str, campaign_name: Optional[str] = None, from_number: Optional[str] = None) -> bool:
        """
        Send info message.
        
        Args:
            to_number: The recipient's phone number
            campaign_name: Optional campaign name
            from_number: The sender's phone number (optional)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        message = "You're receiving messages from our automated system. Reply STOP to opt out."
        if campaign_name:
            message += f" Current campaign: {campaign_name}"
        
        return self.send_sms(to_number, message, from_number)
    
    def send_opt_in_confirmation(self, to_number: str, campaign_name: Optional[str] = None, from_number: Optional[str] = None) -> bool:
        """
        Send opt-in confirmation message.
        
        Args:
            to_number: The recipient's phone number
            campaign_name: Optional campaign name
            from_number: The sender's phone number (optional)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        message = "You have been successfully subscribed to our messages."
        if campaign_name:
            message = f"You have been successfully subscribed to '{campaign_name}'."
        
        return self.send_sms(to_number, message, from_number) 