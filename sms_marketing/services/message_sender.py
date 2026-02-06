"""
Dedicated SMS message sender for SMS marketing campaigns.
Handles outbound messages with proper tracking in SmsMessage model.
"""
import logging
from typing import Optional, Dict, Any
from django.conf import settings
from django.utils import timezone
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from sms_marketing.models import SmsMessage, SmsSubscriber, SmsKeywordCampaign, SmsKeywordRule
from external_models.models.communications import ContactEndpoint
from external_models.models.messages import MessageTemplate

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
        campaign: Optional[SmsKeywordCampaign],
        body: str,
        rule: Optional[SmsKeywordRule] = None,
        message_type: str = 'regular',
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[SmsMessage]]:
        """
        Send an SMS marketing message.

        When rule has short_link set and context is provided, uses create-before-send:
        creates SmsMessage (pending), builds short URL with sms_msg_id, injects into
        context['link'], runs replace_variables (e.g. {{link.short_link}}), then sends
        and updates the message record.

        Args:
            subscriber: SmsSubscriber to send to
            campaign: Optional SmsKeywordCampaign this message is for
            body: Message content (may contain {{link.short_link}} when rule.short_link is set)
            rule: Optional SmsKeywordRule that triggered this message
            message_type: Type of message ('welcome', 'confirmation', 'help', 'opt_out', 'regular')
            context: Optional context for variable replacement; required for short-link substitution when rule.short_link is set

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

        # Create-before-send path: rule has short_link and context provided
        if rule and rule.short_link and context is not None:
            return self._send_message_with_short_link(
                subscriber=subscriber,
                campaign=campaign,
                body=body,
                rule=rule,
                message_type=message_type,
                endpoint=endpoint,
                from_number=from_number,
                to_number=to_number,
                context=context,
            )

        # Default path: send first, then create SmsMessage
        try:
            formatted_to = self._format_phone_number(to_number)
            formatted_from = self._format_phone_number(from_number)

            if not formatted_to or not formatted_from:
                logger.error(f"Invalid phone number format: to={to_number}, from={from_number}")
                return False, None

            twilio_message = self.twilio_client.messages.create(
                body=body,
                from_=formatted_from,
                to=formatted_to,
            )

            logger.info(f"SMS marketing message sent: {twilio_message.sid} to {to_number}")

            sms_message = SmsMessage.objects.create(
                endpoint=endpoint,
                provider='twilio',
                provider_message_id=twilio_message.sid,
                direction='outbound',
                status='sent',
                processing_status='processed',
                from_number=formatted_from,
                to_number=formatted_to,
                body_raw=body,
                body_normalized=body.upper().strip(),
                sms_campaign=campaign,
                rule=rule,
                subscriber=subscriber,
                account=campaign.account if campaign and hasattr(campaign, 'account') and campaign.account else None,
                sent_at=timezone.now(),
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

            subscriber.last_outbound_at = timezone.now()
            subscriber.save(update_fields=['last_outbound_at'])

            logger.info(f"Created SmsMessage {sms_message.id} for outbound message {twilio_message.sid}")
            return True, sms_message

        except TwilioRestException as e:
            logger.error(f"Twilio error sending SMS to {to_number}: {e}")
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
                    sms_campaign=campaign,
                    rule=rule,
                    subscriber=subscriber,
                    account=campaign.account if campaign and hasattr(campaign, 'account') and campaign.account else None,
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

    def _send_message_with_short_link(
        self,
        subscriber: SmsSubscriber,
        campaign: Optional[SmsKeywordCampaign],
        body: str,
        rule: SmsKeywordRule,
        message_type: str,
        endpoint: ContactEndpoint,
        from_number: str,
        to_number: str,
        context: Dict[str, Any],
    ) -> tuple[bool, Optional[SmsMessage]]:
        """Create SmsMessage first, build short URL with sms_msg_id, replace {{link.short_link}}, then send."""
        formatted_to = self._format_phone_number(to_number)
        formatted_from = self._format_phone_number(from_number)
        if not formatted_to or not formatted_from:
            logger.error(f"Invalid phone number format: to={to_number}, from={from_number}")
            return False, None

        try:
            # 1. Create SmsMessage (pending) so we have an id for the URL
            sms_message = SmsMessage.objects.create(
                endpoint=endpoint,
                provider='twilio',
                provider_message_id=None,
                direction='outbound',
                status='pending',
                processing_status='processed',
                from_number=formatted_from,
                to_number=formatted_to,
                body_raw=body,
                body_normalized=body.upper().strip() if body else '',
                sms_campaign=campaign,
                rule=rule,
                subscriber=subscriber,
                account=campaign.account if campaign and hasattr(campaign, 'account') and campaign.account else None,
                sent_at=timezone.now(),
                raw_data={'message_type': message_type},
            )

            # 2. Build short URL with sms_msg_id
            short_url = f"{rule.short_link.get_full_url()}?sms_msg_id={sms_message.id}"

            # 3. Inject into context and replace variables (including {{link.short_link}})
            # Normalize: use lowercase 'link' for consistency with other variable categories
            if 'Link' in context and 'link' not in context:
                context['link'] = context.pop('Link')
            elif 'Link' in context:
                del context['Link']
            # context['link'] may be a Link instance (from _build_message_context) or a dict
            existing_link = context.get('link')
            if isinstance(existing_link, dict):
                link_dict = {**existing_link, 'short_link': short_url}
            else:
                link_dict = {'short_link': short_url}
            context = {**context, 'link': link_dict}
            body = MessageTemplate(content=body).replace_variables(context)

            # 4. Send via Twilio
            twilio_message = self.twilio_client.messages.create(
                body=body,
                from_=formatted_from,
                to=formatted_to,
            )
            logger.info(f"SMS marketing message sent: {twilio_message.sid} to {to_number} (short link, sms_msg_id={sms_message.id})")

            # 5. Update SmsMessage with provider info and final body
            sms_message.provider_message_id = twilio_message.sid
            sms_message.status = 'sent'
            sms_message.body_raw = body
            sms_message.body_normalized = body.upper().strip()
            sms_message.account_sid = twilio_message.account_sid
            sms_message.api_version = twilio_message.api_version
            sms_message.sms_message_sid = twilio_message.sid
            sms_message.sms_sid = twilio_message.sid
            sms_message.messaging_service_sid = getattr(twilio_message, 'messaging_service_sid', None)
            sms_message.num_segments = getattr(twilio_message, 'num_segments', 1)
            sms_message.num_media = getattr(twilio_message, 'num_media', 0)
            sms_message.raw_data = {
                'message_type': message_type,
                'twilio_response': {
                    'sid': twilio_message.sid,
                    'status': twilio_message.status,
                    'date_created': str(twilio_message.date_created) if hasattr(twilio_message, 'date_created') else None,
                }
            }
            sms_message.save()

            subscriber.last_outbound_at = timezone.now()
            subscriber.save(update_fields=['last_outbound_at'])

            return True, sms_message

        except TwilioRestException as e:
            logger.error(f"Twilio error sending SMS to {to_number}: {e}")
            if 'sms_message' in locals():
                try:
                    sms_message.status = 'failed'
                    sms_message.processing_status = 'failed'
                    sms_message.error = f"Twilio error: {str(e)}"
                    sms_message.raw_data = sms_message.raw_data or {}
                    sms_message.raw_data.update({'error': str(e), 'error_code': getattr(e, 'code', None)})
                    sms_message.save()
                except Exception as update_err:
                    logger.error(f"Failed to update SmsMessage to failed: {update_err}")
            return False, sms_message if 'sms_message' in locals() else None

        except Exception as e:
            logger.exception(f"Unexpected error in short-link send to {to_number}: {e}")
            if 'sms_message' in locals():
                try:
                    sms_message.status = 'failed'
                    sms_message.processing_status = 'failed'
                    sms_message.error = str(e)
                    sms_message.save()
                except Exception as update_err:
                    logger.error(f"Failed to update SmsMessage to failed: {update_err}")
            return False, sms_message if 'sms_message' in locals() else None

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
