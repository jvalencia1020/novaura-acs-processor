import logging
from django.utils import timezone
from external_models.models.nurturing_campaigns import BulkCampaignMessage

logger = logging.getLogger(__name__)

class MessageValidationService:
    """
    Service for validating messages before they are sent.
    Ensures all message components are complete and legal for sending.
    """

    def __init__(self, message_delivery_service):
        self.message_delivery_service = message_delivery_service

    def validate_message_pair(self, regular_message: BulkCampaignMessage, opt_out_message: BulkCampaignMessage = None) -> bool:
        """
        Validates a pair of messages (regular and opt-out) before sending.
        
        Args:
            regular_message: The regular campaign message to validate
            opt_out_message: Optional opt-out message to validate
            
        Returns:
            bool: True if both messages are valid and ready to send
        """
        try:
            campaign = regular_message.campaign
            participant = regular_message.participant
            lead = participant.lead

            # Basic campaign and participant validation
            if not campaign.can_send_message(participant):
                logger.warning(f"Participant {participant.id} not eligible for sending")
                return False

            # Validate regular message content
            if campaign.campaign_type == 'reminder':
                if not regular_message.reminder_message:
                    logger.warning(f"Regular message {regular_message.id} has no reminder_message attached")
                    return False
                channel_config = None
                if campaign.channel == 'sms':
                    channel_config = regular_message.reminder_message.sms_config
                elif campaign.channel == 'email':
                    channel_config = regular_message.reminder_message.email_config
                elif campaign.channel == 'voice':
                    channel_config = regular_message.reminder_message.voice_config
                elif campaign.channel == 'chat':
                    channel_config = regular_message.reminder_message.chat_config
                
                # Voice messages use platform_config instead of content
                if campaign.channel == 'voice':
                    if not channel_config or not channel_config.platform_config:
                        logger.warning(f"Regular message {regular_message.id} has no platform_config in reminder_message voice config")
                        return False
                else:
                    if not channel_config or not channel_config.content:
                        logger.warning(f"Regular message {regular_message.id} has no content in reminder_message channel config")
                        return False
            else:
                # For non-reminder campaigns, validate based on channel
                if campaign.channel == 'voice':
                    # Voice messages need platform configuration
                    if not self._validate_voice_platform_config(regular_message):
                        logger.warning(f"Regular message {regular_message.id} has no valid voice platform configuration")
                        return False
                else:
                    # Other channels need content
                    if not regular_message.get_message_content():
                        logger.warning(f"Regular message {regular_message.id} has no content")
                        return False

            # Validate lead contact information
            if campaign.channel in ['sms', 'voice']:
                formatted_number = self.message_delivery_service._format_phone_number(lead.phone_number)
                if not formatted_number:
                    logger.warning(f"Lead {lead.id} has invalid phone number")
                    return False

            # Validate opt-out message if present
            if opt_out_message:
                if campaign.channel == 'voice':
                    # Voice opt-out messages need platform configuration
                    if not self._validate_voice_platform_config(opt_out_message):
                        logger.warning(f"Opt-out message {opt_out_message.id} has no valid voice platform configuration")
                        return False
                else:
                    # Other channels need content
                    if not opt_out_message.get_message_content():
                        logger.warning(f"Opt-out message {opt_out_message.id} has no content")
                        return False

            # Validate message timing
            if regular_message.scheduled_for > timezone.now():
                logger.warning(f"Regular message {regular_message.id} is not yet due to be sent")
                return False

            if opt_out_message and opt_out_message.scheduled_for > timezone.now():
                logger.warning(f"Opt-out message {opt_out_message.id} is not yet due to be sent")
                return False

            # Validate channel-specific requirements
            if not self._validate_channel_requirements(campaign, regular_message, opt_out_message):
                return False

            return True

        except Exception as e:
            logger.exception(f"Message validation failed: {e}")
            return False

    def _validate_channel_requirements(self, campaign, regular_message, opt_out_message=None) -> bool:
        """
        Validates channel-specific requirements for messages.
        
        Args:
            campaign: The campaign the messages belong to
            regular_message: The regular message to validate
            opt_out_message: Optional opt-out message to validate
            
        Returns:
            bool: True if all channel-specific requirements are met
        """
        try:
            if campaign.channel == 'sms':
                # Validate SMS-specific requirements
                if not self._validate_sms_requirements(campaign, regular_message, opt_out_message):
                    return False

            elif campaign.channel == 'voice':
                # Validate voice-specific requirements
                if not self._validate_voice_requirements(campaign, regular_message, opt_out_message):
                    return False

            elif campaign.channel == 'email':
                # Validate email-specific requirements
                if not self._validate_email_requirements(campaign, regular_message, opt_out_message):
                    return False

            return True

        except Exception as e:
            logger.exception(f"Channel validation failed: {e}")
            return False

    def _validate_sms_requirements(self, campaign, regular_message, opt_out_message=None) -> bool:
        """Validates SMS-specific requirements"""
        try:
            # Check for valid service phone number
            service_phone = None
            if regular_message.message_type == 'opt_out_notice':
                if campaign.sms_config:
                    service_phone = campaign.sms_config.get_from_number()
            elif regular_message.message_type == 'opt_out_confirmation':
                if campaign.sms_config:
                    service_phone = campaign.sms_config.get_from_number()
            elif campaign.campaign_type == 'drip' and regular_message.drip_message_step:
                service_phone = regular_message.drip_message_step.sms_config.get_from_number()
            elif campaign.campaign_type == 'reminder' and regular_message.reminder_message:
                service_phone = regular_message.reminder_message.sms_config.get_from_number()
            else:
                service_phone = campaign.sms_config.get_from_number()

            if not service_phone:
                logger.warning(f"No valid service phone number found for message {regular_message.id}")
                return False

            return True

        except Exception as e:
            logger.exception(f"SMS validation failed: {e}")
            return False

    def _validate_voice_requirements(self, campaign, regular_message, opt_out_message=None) -> bool:
        """Validates voice-specific requirements"""
        try:
            # Check for valid service phone number
            service_phone = None
            if regular_message.message_type == 'opt_out_notice':
                if campaign.voice_config:
                    service_phone = campaign.voice_config.get_from_number()
            elif regular_message.message_type == 'opt_out_confirmation':
                if campaign.voice_config:
                    service_phone = campaign.voice_config.get_from_number()
            elif campaign.campaign_type == 'drip' and regular_message.drip_message_step:
                service_phone = regular_message.drip_message_step.voice_config.get_from_number()
            elif campaign.campaign_type == 'reminder' and regular_message.reminder_message:
                service_phone = regular_message.reminder_message.voice_config.get_from_number()
            else:
                service_phone = campaign.voice_config.get_from_number()

            if not service_phone:
                logger.warning(f"No valid service phone number found for message {regular_message.id}")
                return False

            # Validate voice platform configuration
            if not self._validate_voice_platform_config(regular_message):
                logger.warning(f"No valid voice platform configuration found for message {regular_message.id}")
                return False

            return True

        except Exception as e:
            logger.exception(f"Voice validation failed: {e}")
            return False

    def _validate_email_requirements(self, campaign, regular_message, opt_out_message=None) -> bool:
        """Validates email-specific requirements"""
        try:
            # Check for valid from address
            from_address = None
            if regular_message.message_type == 'opt_out_notice':
                if campaign.email_config:
                    from_address = campaign.email_config.get_from_address()
            elif regular_message.message_type == 'opt_out_confirmation':
                if campaign.email_config:
                    from_address = campaign.email_config.get_from_address()
            elif campaign.campaign_type == 'drip' and regular_message.drip_message_step:
                from_address = regular_message.drip_message_step.email_config.get_from_address()
            elif campaign.campaign_type == 'reminder' and regular_message.reminder_message:
                from_address = regular_message.reminder_message.email_config.get_from_address()
            else:
                from_address = campaign.email_config.get_from_address()

            if not from_address:
                logger.warning(f"No valid from address found for message {regular_message.id}")
                return False

            # Check for valid subject
            if not campaign.subject:
                logger.warning(f"No subject found for message {regular_message.id}")
                return False

            return True

        except Exception as e:
            logger.exception(f"Email validation failed: {e}")
            return False

    def _validate_voice_platform_config(self, message) -> bool:
        """
        Validates that a voice message has proper platform configuration.
        
        Args:
            message: The message to validate
            
        Returns:
            bool: True if the voice platform configuration is valid
        """
        try:
            campaign = message.campaign
            
            # Get the appropriate voice config based on campaign type and message type
            voice_config = None
            
            if message.message_type in ['opt_out_notice', 'opt_out_confirmation']:
                voice_config = campaign.voice_config
            elif campaign.campaign_type == 'drip' and message.drip_message_step:
                voice_config = message.drip_message_step.voice_config
            elif campaign.campaign_type == 'reminder' and message.reminder_message:
                voice_config = message.reminder_message.voice_config
            else:
                voice_config = campaign.voice_config
            
            if not voice_config:
                logger.warning(f"No voice config found for message {message.id}")
                return False
            
            # Check that platform is specified
            if not voice_config.platform:
                logger.warning(f"No platform specified in voice config for message {message.id}")
                return False
            
            # Check that platform_config exists and is not empty
            if not voice_config.platform_config:
                logger.warning(f"No platform_config found in voice config for message {message.id}")
                return False
            
            # Validate platform-specific configuration based on the platform
            if voice_config.platform == 'bland_ai':
                return self._validate_bland_ai_config(voice_config)
            elif voice_config.platform == 'vapi':
                return self._validate_vapi_config(voice_config)
            elif voice_config.platform == 'elevenlabs':
                return self._validate_elevenlabs_config(voice_config)
            elif voice_config.platform == 'twilio':
                return self._validate_twilio_voice_config(voice_config)
            else:
                logger.warning(f"Unsupported voice platform: {voice_config.platform}")
                return False
                
        except Exception as e:
            logger.exception(f"Voice platform config validation failed: {e}")
            return False

    def _validate_bland_ai_config(self, voice_config) -> bool:
        """Validates Bland AI specific configuration"""
        try:
            config = voice_config.platform_config
            
            # Check for required Bland AI fields
            required_fields = ['pathway_id']  # Bland AI uses 'pathway_id' instead of 'content'
            
            for field in required_fields:
                if not config.get(field):
                    logger.warning(f"Missing required Bland AI field: {field}")
                    return False
            
            # Validate voice ID if specified
            if voice_config.voice_id and not isinstance(voice_config.voice_id, str):
                logger.warning("Voice ID must be a string")
                return False
            
            # Validate max_duration if specified
            if voice_config.max_duration and not isinstance(voice_config.max_duration, int):
                logger.warning("Max duration must be an integer")
                return False
            
            return True
            
        except Exception as e:
            logger.exception(f"Bland AI config validation failed: {e}")
            return False

    def _validate_vapi_config(self, voice_config) -> bool:
        """Validates VAPI specific configuration"""
        try:
            config = voice_config.platform_config
            
            # Check for required VAPI fields
            if 'assistant' not in config:
                logger.warning("VAPI config missing 'assistant' configuration")
                return False
            
            assistant = config['assistant']
            if 'model' not in assistant:
                logger.warning("VAPI assistant config missing 'model'")
                return False
            
            # Validate model
            valid_models = ['gpt-4', 'gpt-3.5-turbo']
            if assistant['model'] not in valid_models:
                logger.warning(f"Invalid VAPI model: {assistant['model']}")
                return False
            
            return True
            
        except Exception as e:
            logger.exception(f"VAPI config validation failed: {e}")
            return False

    def _validate_elevenlabs_config(self, voice_config) -> bool:
        """Validates ElevenLabs specific configuration"""
        try:
            config = voice_config.platform_config
            
            # Check for required ElevenLabs fields
            if 'voice_id' not in config:
                logger.warning("ElevenLabs config missing 'voice_id'")
                return False
            
            # Validate voice_settings if present
            if 'voice_settings' in config:
                voice_settings = config['voice_settings']
                if 'stability' in voice_settings:
                    stability = voice_settings['stability']
                    if not isinstance(stability, (int, float)) or not 0 <= stability <= 1:
                        logger.warning("ElevenLabs stability must be a number between 0 and 1")
                        return False
            
            return True
            
        except Exception as e:
            logger.exception(f"ElevenLabs config validation failed: {e}")
            return False

    def _validate_twilio_voice_config(self, voice_config) -> bool:
        """Validates Twilio Voice specific configuration"""
        try:
            config = voice_config.platform_config
            
            # Check for required Twilio Voice fields
            if 'twiml' not in config and 'url' not in config:
                logger.warning("Twilio Voice config missing 'twiml' or 'url'")
                return False
            
            return True
            
        except Exception as e:
            logger.exception(f"Twilio Voice config validation failed: {e}")
            return False 