"""
Dedicated SMS message sender for SMS marketing campaigns.
Handles outbound messages with proper tracking in SmsMessage model.
"""
import logging
from typing import Optional
from django.conf import settings
from django.utils import timezone
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from sms_marketing.models import SmsMessage, SmsSubscriber, SmsKeywordCampaign, SmsKeywordRule
from external_models.models.communications import ContactEndpoint

logger = logging.getLogger(__name__)


class SMSMarketingMessageSender:
    """
    Dedicated service for sending SMS marketing messages.
    Creates proper SmsMessage records and updates subscriber tracking.
    """
    
    def __init__(self):
        try:
            self.twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        except Exception as e:
            logger.warning(f"Could not initialize Twilio client: {e}")
            self.twilio_client = None
    
    def send_message(
        self,
        subscriber: SmsSubscriber,
        campaign: SmsKeywordCampaign,
        body: str,
        rule: Optional[SmsKeywordRule] = None,
        message_type: str = 'regular'
    ) -> tuple[bool, Optional[SmsMessage]]:
        """
        Send an SMS marketing message.
        
        Args:
            subscriber: SmsSubscriber to send to
            campaign: SmsKeywordCampaign this message is for
            body: Message content
            rule: Optional SmsKeywordRule that triggered this message
            message_type: Type of message ('welcome', 'confirmation', 'help', 'opt_out', 'regular')
            
        Returns:
            tuple: (success: bool, sms_message: SmsMessage or None)
        """
        if not self.twilio_client:
            logger.error("Twilio client not available")
            return False, None
        
        if not subscriber.endpoint:
            logger.error(f"Subscriber {subscriber.id} has no endpoint")
            return False, None
        
        endpoint = subscriber.endpoint
        from_number = endpoint.value
        to_number = subscriber.phone_number
        
        try:
            # Format phone numbers
            formatted_to = self._format_phone_number(to_number)
            formatted_from = self._format_phone_number(from_number)
            
            if not formatted_to or not formatted_from:
                logger.error(f"Invalid phone number format: to={to_number}, from={from_number}")
                return False, None
            
            # Send message via Twilio
            twilio_message = self.twilio_client.messages.create(
                body=body,
                from_=formatted_from,
                to=formatted_to,
            )
            
            logger.info(f"SMS marketing message sent: {twilio_message.sid} to {to_number}")
            
            # Create SmsMessage record for tracking
            sms_message = SmsMessage.objects.create(
                endpoint=endpoint,
                provider='twilio',
                provider_message_id=twilio_message.sid,
                direction='outbound',
                status='sent',
                processing_status='processed',  # Outbound messages don't need processing
                from_number=formatted_from,
                to_number=formatted_to,
                body_raw=body,
                body_normalized=body.upper().strip(),  # Normalize for consistency
                sms_campaign=campaign,  # Field name is sms_campaign
                rule=rule,
                subscriber=subscriber,
                account=campaign.account if hasattr(campaign, 'account') and campaign.account else None,
                sent_at=timezone.now(),
                # Provider metadata
                account_sid=twilio_message.account_sid,
                api_version=twilio_message.api_version,
                sms_message_sid=twilio_message.sid,
                sms_sid=twilio_message.sid,
                messaging_service_sid=getattr(twilio_message, 'messaging_service_sid', None),
                num_segments=getattr(twilio_message, 'num_segments', 1),
                num_media=getattr(twilio_message, 'num_media', 0),
                raw_data={
                    'message_type': message_type,
                    'twilio_response': {
                        'sid': twilio_message.sid,
                        'status': twilio_message.status,
                        'date_created': str(twilio_message.date_created) if hasattr(twilio_message, 'date_created') else None,
                    }
                }
            )
            
            # Update subscriber's last_outbound_at
            subscriber.last_outbound_at = timezone.now()
            subscriber.save(update_fields=['last_outbound_at'])
            
            logger.info(f"Created SmsMessage {sms_message.id} for outbound message {twilio_message.sid}")
            
            return True, sms_message
            
        except TwilioRestException as e:
            logger.error(f"Twilio error sending SMS to {to_number}: {e}")
            
            # Create failed SmsMessage record for tracking
            try:
                sms_message = SmsMessage.objects.create(
                    endpoint=endpoint,
                    provider='twilio',
                    direction='outbound',
                    status='failed',
                    processing_status='failed',
                    from_number=formatted_from if 'formatted_from' in locals() else from_number,
                    to_number=formatted_to if 'formatted_to' in locals() else to_number,
                    body_raw=body,
                    body_normalized=body.upper().strip(),
                    sms_campaign=campaign,  # Field name is sms_campaign
                    rule=rule,
                    subscriber=subscriber,
                    account=campaign.account if hasattr(campaign, 'account') and campaign.account else None,
                    error=f"Twilio error: {str(e)}",
                    raw_data={
                        'message_type': message_type,
                        'error': str(e),
                        'error_code': getattr(e, 'code', None),
                    }
                )
            except Exception as create_error:
                logger.error(f"Failed to create failed SmsMessage record: {create_error}")
                sms_message = None
            
            return False, sms_message
            
        except Exception as e:
            logger.exception(f"Unexpected error sending SMS to {to_number}: {e}")
            return False, None
    
    def _format_phone_number(self, phone_number: str) -> Optional[str]:
        """
        Format phone number to E.164 format or return as-is for short codes.
        Handles:
        - Already formatted E.164 numbers (e.g., +12035835289)
        - Short codes (e.g., 45555) - return as-is
        - Regular phone numbers - format to E.164
        """
        if not phone_number:
            return None
        
        # Remove all non-digit characters except +
        digits = ''.join(c for c in phone_number if c.isdigit() or c == '+')
        
        # If already in E.164 format (starts with +), return as-is
        if digits.startswith('+'):
            return digits
        
        # Check if it's a short code (typically 4-6 digits, used for SMS)
        # Short codes don't need country codes
        digit_count = len(digits)
        if 4 <= digit_count <= 6:
            # Likely a short code - return as-is
            return digits
        
        # Regular phone number - format to E.164
        # Remove leading 1 if present (US country code)
        if digits.startswith('1') and len(digits) == 11:
            digits = digits[1:]
        
        # Add +1 for US numbers (10 digits)
        if len(digits) == 10:
            return '+1' + digits
        
        # If it's already 11 digits starting with 1, add +
        if len(digits) == 11 and digits.startswith('1'):
            return '+' + digits
        
        # If we can't format it, return None (invalid)
        logger.warning(f"Could not format phone number: {phone_number} (digits: {digits})")
        return None
