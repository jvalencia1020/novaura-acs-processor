import json
from typing import Dict, Any, Optional
from django.utils import timezone
from external_models.models.external_references import Lead
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant


class SQSMessageBuilder:
    """
    Utility class for building enhanced SQS messages with additional context.
    """
    
    @staticmethod
    def build_sms_message(
        twilio_data: Dict[str, Any],
        lead: Optional[Lead] = None,
        nurturing_campaign: Optional[LeadNurturingCampaign] = None,
        campaign_participant: Optional[LeadNurturingParticipant] = None,
        message_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        processing_hints: Optional[Dict[str, Any]] = None,
        agent_mode: bool = False,
        agent_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build an enhanced SMS message for SQS.
        
        Args:
            twilio_data: Raw Twilio webhook data
            lead: Lead object (optional)
            nurturing_campaign: Nurturing campaign object (optional)
            campaign_participant: Campaign participant object (optional)
            message_context: Additional message context (optional)
            metadata: UTM and tracking metadata (optional)
            processing_hints: Processing instructions (optional)
            agent_mode: Whether AI agent mode is enabled (optional)
            agent_config: AI agent configuration (optional)
            
        Returns:
            Enhanced SQS message dictionary
        """
        # Base message structure
        message = {
            # Twilio fields (normalized to lowercase)
            'message_sid': twilio_data.get('MessageSid'),
            'sms_message_sid': twilio_data.get('SmsMessageSid'),
            'sms_sid': twilio_data.get('SmsSid'),
            'account_sid': twilio_data.get('AccountSid'),
            'messaging_service_sid': twilio_data.get('MessagingServiceSid'),
            'from_number': twilio_data.get('From'),
            'to_number': twilio_data.get('To'),
            'body': twilio_data.get('Body'),
            'event_type': 'sms.status',
            'status': twilio_data.get('MessageStatus', 'received'),
            'num_segments': twilio_data.get('NumSegments', 1),
            'num_media': twilio_data.get('NumMedia', 0),
            'media_url': twilio_data.get('MediaUrl'),
            'direction': twilio_data.get('Direction', 'inbound'),
            'channel': 'sms',
            
            # Timestamps
            'timestamps': {
                'webhook_received': timezone.now().isoformat(),
                'message_sent': twilio_data.get('DateCreated'),
                'message_delivered': twilio_data.get('DateUpdated'),
            }
        }
        
        # Add lead information
        if lead:
            message.update({
                'lead_id': lead.id,
                'lead_phone_number': lead.phone_number,
                'lead_email': lead.email,
                'lead_first_name': lead.first_name,
                'lead_last_name': lead.last_name,
            })
        
        # Add campaign information
        if nurturing_campaign:
            message['nurturing_campaign_id'] = nurturing_campaign.id
            
            # Add campaign participant if provided
            if campaign_participant:
                message['campaign_participant_id'] = campaign_participant.id
        
        # Add message context
        if message_context:
            message['message_context'] = message_context
        elif nurturing_campaign:
            # Generate default message context from campaign
            message['message_context'] = {
                'campaign_name': nurturing_campaign.name,
                'campaign_type': nurturing_campaign.campaign_type,
                'step_number': 1,  # This should be determined by your logic
                'triggered_by': 'webhook',
                'original_message_id': twilio_data.get('MessageSid'),
                'scheduled_send_time': timezone.now().isoformat(),
            }
        
        # Add metadata
        if metadata:
            message['metadata'] = metadata
        else:
            # Generate default metadata
            message['metadata'] = {
                'source_campaign': 'sms_webhook',
                'utm_source': 'sms_campaign',
                'utm_medium': 'sms',
                'utm_campaign': nurturing_campaign.name if nurturing_campaign else 'unknown',
                'utm_content': 'webhook_response',
                'utm_term': 'sms',
                'referrer': 'twilio_webhook',
            }
        
        # Add processing hints
        if processing_hints:
            message['processing_hints'] = processing_hints
        else:
            # Generate default processing hints
            message['processing_hints'] = {
                'expected_keywords': ['YES', 'NO', 'STOP', 'HELP', 'INFO', 'START'],
                'auto_response_enabled': True,
                'require_lead_match': True,
                'campaign_priority': 'normal',
                'retry_on_failure': True,
                'max_retries': 3,
                'timeout_seconds': 30
            }
        
        # Add agent mode configuration
        if agent_mode:
            message['agent_mode'] = True
            
            if agent_config:
                message['agent_config'] = agent_config
            else:
                # Generate default agent configuration
                message['agent_config'] = {
                    'enabled': True,
                    'model': 'gpt-4',  # or your preferred model
                    'temperature': 0.7,
                    'max_tokens': 150,
                    'prompt': f"You are a helpful AI assistant for {nurturing_campaign.name if nurturing_campaign else 'our company'}. Respond naturally and helpfully to customer inquiries.",
                    'context': {
                        'campaign_name': nurturing_campaign.name if nurturing_campaign else 'General',
                        'campaign_type': nurturing_campaign.campaign_type if nurturing_campaign else 'general',
                        'step_number': message_context.get('step_number', 1) if message_context else 1,
                        'conversation_history': [],
                        'campaign_goals': [
                            'Provide helpful information',
                            'Answer customer questions',
                            'Guide customers through the process'
                        ],
                        'response_style': 'friendly and professional',
                        'include_opt_out_info': True
                    },
                    'fallback_response': "Thanks for your message! I'm here to help. Please let me know if you have any questions."
                }
        
        return message
    
    @staticmethod
    def build_delivery_status_message(
        twilio_data: Dict[str, Any],
        lead: Optional[Lead] = None,
        nurturing_campaign: Optional[LeadNurturingCampaign] = None,
        campaign_participant: Optional[LeadNurturingParticipant] = None
    ) -> Dict[str, Any]:
        """
        Build a delivery status message for SQS.
        
        Args:
            twilio_data: Raw Twilio webhook data
            lead: Lead object (optional)
            nurturing_campaign: Nurturing campaign object (optional)
            campaign_participant: Campaign participant object (optional)
            
        Returns:
            Enhanced SQS message dictionary
        """
        message = SQSMessageBuilder.build_sms_message(
            twilio_data, lead, nurturing_campaign, campaign_participant
        )
        
        # Override event type for delivery status
        message['event_type'] = 'sms.delivery_status'
        
        # Add delivery-specific information
        message.update({
            'delivery_status': twilio_data.get('MessageStatus'),
            'error_code': twilio_data.get('ErrorCode'),
            'error_message': twilio_data.get('ErrorMessage'),
            'price': twilio_data.get('Price'),
            'price_unit': twilio_data.get('PriceUnit'),
        })
        
        return message
    
    @staticmethod
    def build_opt_out_message(
        phone_number: str,
        lead: Optional[Lead] = None,
        nurturing_campaign: Optional[LeadNurturingCampaign] = None,
        campaign_participant: Optional[LeadNurturingParticipant] = None,
        keyword: str = 'STOP'
    ) -> Dict[str, Any]:
        """
        Build an opt-out message for SQS.
        
        Args:
            phone_number: The phone number that opted out
            lead: Lead object (optional)
            nurturing_campaign: Nurturing campaign object (optional)
            campaign_participant: Campaign participant object (optional)
            keyword: The keyword that triggered the opt-out
            
        Returns:
            Enhanced SQS message dictionary
        """
        # Create mock Twilio data for opt-out
        twilio_data = {
            'MessageSid': f'SM_optout_{timezone.now().timestamp()}',
            'From': phone_number,
            'To': '+18883034619',  # Your Twilio number
            'Body': keyword,
            'Direction': 'inbound',
            'MessageStatus': 'received',
            'NumSegments': 1,
            'NumMedia': 0,
        }
        
        message = SQSMessageBuilder.build_sms_message(
            twilio_data, lead, nurturing_campaign, campaign_participant
        )
        
        # Override event type for opt-out
        message['event_type'] = 'sms.opt_out'
        
        # Add opt-out specific information
        message.update({
            'opt_out_keyword': keyword,
            'opt_out_type': 'campaign' if nurturing_campaign else 'global',
            'processing_hints': {
                'expected_keywords': [keyword],
                'auto_response_enabled': True,
                'require_lead_match': True,
                'campaign_priority': 'high',
                'retry_on_failure': False,
                'max_retries': 1,
                'timeout_seconds': 10
            }
        })
        
        return message
    
    @staticmethod
    def to_json(message: Dict[str, Any]) -> str:
        """
        Convert message to JSON string.
        
        Args:
            message: The message dictionary
            
        Returns:
            JSON string representation
        """
        return json.dumps(message, default=str)
    
    @staticmethod
    def from_json(json_string: str) -> Dict[str, Any]:
        """
        Parse JSON string to message dictionary.
        
        Args:
            json_string: JSON string representation
            
        Returns:
            Message dictionary
        """
        return json.loads(json_string)


# Convenience functions for common use cases
def build_inbound_sms_message(
    twilio_data: Dict[str, Any],
    lead: Optional[Lead] = None,
    nurturing_campaign: Optional[LeadNurturingCampaign] = None
) -> Dict[str, Any]:
    """
    Build an inbound SMS message with lead and campaign context.
    
    Args:
        twilio_data: Raw Twilio webhook data
        lead: Lead object (optional)
        nurturing_campaign: Nurturing campaign object (optional)
        
    Returns:
        Enhanced SQS message dictionary
    """
    campaign_participant = None
    if lead and nurturing_campaign:
        campaign_participant = LeadNurturingParticipant.objects.filter(
            lead=lead,
            nurturing_campaign=nurturing_campaign,
            status='active'
        ).first()
    
    return SQSMessageBuilder.build_sms_message(
        twilio_data, lead, nurturing_campaign, campaign_participant
    )


def build_campaign_response_message(
    twilio_data: Dict[str, Any],
    lead: Lead,
    nurturing_campaign: LeadNurturingCampaign,
    campaign_participant: LeadNurturingParticipant,
    step_number: int = 1
) -> Dict[str, Any]:
    """
    Build a campaign response message with full context.
    
    Args:
        twilio_data: Raw Twilio webhook data
        lead: Lead object
        nurturing_campaign: Nurturing campaign object
        campaign_participant: Campaign participant object
        step_number: Current step number in the campaign
        
    Returns:
        Enhanced SQS message dictionary
    """
    message_context = {
        'campaign_name': nurturing_campaign.name,
        'campaign_type': nurturing_campaign.campaign_type,
        'step_number': step_number,
        'triggered_by': 'user_response',
        'original_message_id': twilio_data.get('MessageSid'),
        'scheduled_send_time': timezone.now().isoformat(),
        'message_template_id': f'{nurturing_campaign.campaign_type}_step_{step_number}'
    }
    
    metadata = {
        'source_campaign': f'{nurturing_campaign.name.lower().replace(" ", "_")}',
        'utm_source': 'sms_campaign',
        'utm_medium': 'sms',
        'utm_campaign': nurturing_campaign.name.lower().replace(' ', '_'),
        'utm_content': f'step_{step_number}',
        'utm_term': nurturing_campaign.campaign_type,
        'referrer': 'sms_response',
        'landing_page': f'https://example.com/campaign/{nurturing_campaign.id}'
    }
    
    return SQSMessageBuilder.build_sms_message(
        twilio_data, lead, nurturing_campaign, campaign_participant,
        message_context, metadata
    )


@staticmethod
def build_agent_message(
    twilio_data: Dict[str, Any],
    lead: Optional[Lead] = None,
    nurturing_campaign: Optional[LeadNurturingCampaign] = None,
    campaign_participant: Optional[LeadNurturingParticipant] = None,
    agent_prompt: Optional[str] = None,
    agent_context: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[list] = None
) -> Dict[str, Any]:
    """
    Build an SMS message specifically for AI agent processing.
    
    Args:
        twilio_data: Raw Twilio webhook data
        lead: Lead object (optional)
        nurturing_campaign: Nurturing campaign object (optional)
        campaign_participant: Campaign participant object (optional)
        agent_prompt: Custom prompt for the AI agent (optional)
        agent_context: Additional context for the AI agent (optional)
        conversation_history: Previous conversation messages (optional)
        
    Returns:
        Enhanced SQS message dictionary with agent mode enabled
    """
    # Build base message
    message = SQSMessageBuilder.build_sms_message(
        twilio_data, lead, nurturing_campaign, campaign_participant
    )
    
    # Enable agent mode
    message['agent_mode'] = True
    
    # Configure agent settings
    custom_prompt = agent_prompt or f"You are a helpful AI assistant for {nurturing_campaign.name if nurturing_campaign else 'our company'}. Respond naturally and helpfully to customer inquiries."
    
    message['agent_config'] = {
        'enabled': True,
        'model': 'gpt-4',  # or your preferred model
        'temperature': 0.7,
        'max_tokens': 150,
        'prompt': custom_prompt,
        'context': {
            'campaign_name': nurturing_campaign.name if nurturing_campaign else 'General',
            'campaign_type': nurturing_campaign.campaign_type if nurturing_campaign else 'general',
            'step_number': message.get('message_context', {}).get('step_number', 1),
            'conversation_history': conversation_history or [],
            'campaign_goals': [
                'Provide helpful information',
                'Answer customer questions',
                'Guide customers through the process',
                'Maintain engagement'
            ],
            'response_style': 'friendly and professional',
            'include_opt_out_info': True,
            'max_conversation_length': 10,
            'auto_escalate_to_human': True,
            'escalation_triggers': [
                'customer_requests_human',
                'complex_technical_question',
                'complaint_or_negative_feedback',
                'purchase_intent'
            ]
        },
        'fallback_response': "Thanks for your message! I'm here to help. Please let me know if you have any questions.",
        'escalation_message': "I'm connecting you with a human representative who will be with you shortly. Thank you for your patience!"
    }
    
    # Add agent-specific context if provided
    if agent_context:
        message['agent_config']['context'].update(agent_context)
    
    return message 