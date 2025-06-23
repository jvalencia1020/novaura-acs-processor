import logging
from typing import Optional, Dict, Any
from django.utils import timezone
from external_models.models.external_references import Lead
from external_models.models.nurturing_campaigns import LeadNurturingCampaign
from communication_processor.models import CommunicationEvent

logger = logging.getLogger(__name__)


class AIAgentService:
    """
    Service for AI agent functionality across different communication channels.
    Provides reusable methods for generating AI responses and managing agent interactions.
    """

    def __init__(self, message_sender=None):
        self.message_sender = message_sender
    
    def handle_agent_response(self, event_data: Dict[str, Any], lead: Optional[Lead], 
                            nurturing_campaign: Optional[LeadNurturingCampaign], 
                            conversation_message=None, channel: str = 'sms') -> bool:
        """
        Handle AI agent response generation and sending.
        
        Args:
            event_data: The event data
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            conversation_message: The conversation message
            channel: The communication channel
            
        Returns:
            bool: True if agent response was handled successfully
        """
        contact_info = self._get_contact_info(event_data, channel)
        user_message = event_data.get('body', '') or event_data.get('Body', '')
        
        logger.info(f"Agent mode enabled for message from {contact_info}")
        
        # Get agent configuration from event data
        agent_config = event_data.get('agent_config', {})
        agent_prompt = agent_config.get('prompt', '')
        agent_context = agent_config.get('context', {})
        
        # Generate AI agent response
        agent_response = self.generate_agent_response(
            user_message, lead, nurturing_campaign, agent_prompt, agent_context, channel
        )
        
        if agent_response:
            # Send the agent response
            if self.message_sender:
                success = self.message_sender.send_message(contact_info, agent_response, channel)
                if success:
                    logger.info(f"Sent AI agent response to {contact_info}: {agent_response[:50]}...")
                    
                    # Create communication event for the agent response
                    self._create_agent_response_event(event_data, lead, nurturing_campaign, agent_response, channel)
                    return True
                else:
                    logger.error(f"Failed to send AI agent response to {contact_info}")
                    return False
        else:
            logger.warning(f"No AI agent response generated for message from {contact_info}")
            return False
    
    def generate_agent_response(self, user_message: str, lead: Optional[Lead], 
                              nurturing_campaign: Optional[LeadNurturingCampaign],
                              agent_prompt: str, agent_context: Dict[str, Any], 
                              channel: str = 'sms') -> Optional[str]:
        """
        Generate AI agent response based on user message and context.
        
        Args:
            user_message: The user's message
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            agent_prompt: Custom prompt for the agent
            agent_context: Additional context for the agent
            channel: The communication channel
            
        Returns:
            Generated response or None if generation failed
        """
        try:
            # Build context for the AI agent
            context = self._build_agent_context(
                user_message, lead, nurturing_campaign, agent_prompt, agent_context, channel
            )
            
            # Call your AI agent service
            # response = your_ai_agent_service.generate_response(context)
            
            # For now, return a placeholder response
            response = self._generate_placeholder_agent_response(context)
            
            return response
            
        except Exception as e:
            logger.error(f"Error generating AI agent response: {e}")
            return None
    
    def _build_agent_context(self, user_message: str, lead: Optional[Lead], 
                           nurturing_campaign: Optional[LeadNurturingCampaign],
                           agent_prompt: str, agent_context: Dict[str, Any], 
                           channel: str) -> Dict[str, Any]:
        """
        Build context for the AI agent.
        
        Args:
            user_message: The user's message
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            agent_prompt: Custom prompt for the agent
            agent_context: Additional context for the agent
            channel: The communication channel
            
        Returns:
            Dict with agent context
        """
        context = {
            'user_message': user_message,
            'lead_name': f"{lead.first_name} {lead.last_name}" if lead else "Unknown",
            'lead_email': lead.email if lead else None,
            'lead_phone': lead.phone_number if lead else None,
            'campaign_name': nurturing_campaign.name if nurturing_campaign else None,
            'campaign_type': nurturing_campaign.campaign_type if nurturing_campaign else None,
            'step_number': agent_context.get('step_number', 1),
            'conversation_history': agent_context.get('conversation_history', []),
            'campaign_goals': agent_context.get('campaign_goals', []),
            'custom_prompt': agent_prompt,
            'channel': channel,
            'timestamp': timezone.now().isoformat()
        }
        
        # Add channel-specific context
        if channel == 'sms':
            context['message_length_limit'] = 160
            context['supports_media'] = True
        elif channel == 'email':
            context['message_length_limit'] = 1000
            context['supports_media'] = True
        elif channel == 'chat':
            context['message_length_limit'] = 500
            context['supports_media'] = True
        
        return context
    
    def _generate_placeholder_agent_response(self, context: Dict[str, Any]) -> str:
        """
        Generate a placeholder agent response for testing.
        
        Args:
            context: The context for response generation
            
        Returns:
            Placeholder response
        """
        user_message = context.get('user_message', '').lower()
        lead_name = context.get('lead_name', 'there')
        campaign_name = context.get('campaign_name', 'our campaign')
        channel = context.get('channel', 'sms')
        
        # Simple keyword-based responses for testing
        if 'hello' in user_message or 'hi' in user_message:
            return f"Hello {lead_name}! Thanks for reaching out about {campaign_name}. How can I help you today?"
        
        elif 'help' in user_message:
            return f"Hi {lead_name}! I'm here to help with {campaign_name}. What specific questions do you have?"
        
        elif 'info' in user_message or 'information' in user_message:
            return f"Hi {lead_name}! I'd be happy to provide more information about {campaign_name}. What would you like to know?"
        
        elif 'yes' in user_message:
            return f"Great {lead_name}! I'm glad you're interested in {campaign_name}. Let me get you the next steps."
        
        elif 'no' in user_message:
            return f"I understand {lead_name}. No worries about {campaign_name}. Is there anything else I can help you with?"
        
        else:
            return f"Thanks for your message {lead_name}! I'm processing your inquiry about {campaign_name} and will get back to you with more details soon."
    
    def _get_contact_info(self, event_data: Dict[str, Any], channel: str) -> str:
        """
        Get contact information from event data.
        
        Args:
            event_data: The event data
            channel: The communication channel
            
        Returns:
            Contact information (phone, email, etc.)
        """
        if channel == 'sms':
            return event_data.get('from_number') or event_data.get('From', '')
        elif channel == 'email':
            return event_data.get('from_email') or event_data.get('From', '')
        else:
            return event_data.get('from_number') or event_data.get('From', '')
    
    def _create_agent_response_event(self, event_data: Dict[str, Any], lead: Optional[Lead], 
                                   nurturing_campaign: Optional[LeadNurturingCampaign], 
                                   agent_response: str, channel: str):
        """
        Create a communication event for the AI agent response.
        
        Args:
            event_data: The original event data
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            agent_response: The AI agent's response
            channel: The communication channel
        """
        try:
            # Create agent response event data
            agent_event_data = {
                'message_sid': f"AGENT_{event_data.get('message_sid', '')}_{timezone.now().timestamp()}",
                'from_number': event_data.get('to_number') or event_data.get('To', ''),  # From your number
                'to_number': event_data.get('from_number') or event_data.get('From', ''),  # To user
                'body': agent_response,
                'direction': 'outbound-api',
                'event_type': 'agent_response',
                'agent_mode': True,
                'agent_response_to': event_data.get('message_sid'),
                'lead_id': lead.id if lead else None,
                'nurturing_campaign_id': nurturing_campaign.id if nurturing_campaign else None,
                'channel': channel
            }
            
            # Create the communication event
            CommunicationEvent.objects.create(
                event_type='agent_response',
                channel_type=channel,
                external_id=agent_event_data['message_sid'],
                lead=lead,
                nurturing_campaign=nurturing_campaign,
                event_data=agent_event_data,
                raw_data=agent_event_data
            )
            
            logger.info(f"Created agent response event for message {event_data.get('message_sid')}")
            
        except Exception as e:
            logger.error(f"Error creating agent response event: {e}")
    
    def validate_agent_config(self, agent_config: Dict[str, Any]) -> bool:
        """
        Validate AI agent configuration.
        
        Args:
            agent_config: The agent configuration to validate
            
        Returns:
            bool: True if configuration is valid
        """
        try:
            required_fields = ['prompt', 'context']
            
            for field in required_fields:
                if field not in agent_config:
                    logger.warning(f"Agent config missing required field: {field}")
                    return False
            
            # Validate prompt
            if not agent_config['prompt'] or len(agent_config['prompt'].strip()) == 0:
                logger.warning("Agent config has empty prompt")
                return False
            
            # Validate context
            if not isinstance(agent_config['context'], dict):
                logger.warning("Agent config context must be a dictionary")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating agent config: {e}")
            return False 