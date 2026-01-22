"""
Action execution handlers for SMS marketing campaigns.
"""
import logging
from typing import Dict, Any, Optional
from django.utils import timezone
from django.db import transaction
from external_models.models.messages import MessageTemplate
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant
from external_models.models.communications import Conversation, ConversationMessage
from shared_services.lead_matching_service import LeadMatchingService
from sms_marketing.models import SmsMessage, SmsSubscriber, SmsKeywordCampaign, SmsKeywordRule
from sms_marketing.services.message_sender import SMSMarketingMessageSender

logger = logging.getLogger(__name__)


class ExecutionResult:
    """Result of action execution"""
    def __init__(self, success: bool, event_type: str, payload: Dict[str, Any], error: Optional[str] = None):
        self.success = success
        self.event_type = event_type
        self.payload = payload
        self.error = error


class SMSMarketingActionExecutor:
    """Executes actions for SMS marketing campaigns"""
    
    def __init__(self):
        self.message_sender = SMSMarketingMessageSender()
        self.lead_matching = LeadMatchingService()
    
    def execute_action(
        self,
        campaign: SmsKeywordCampaign,
        rule: SmsKeywordRule,
        subscriber: SmsSubscriber,
        message: SmsMessage,
        action_config: Dict[str, Any]
    ) -> ExecutionResult:
        """Execute action based on rule.action_type"""
        action_type = rule.action_type
        
        try:
            if action_type == 'OPT_IN':
                return self._handle_opt_in(campaign, rule, subscriber, message, action_config)
            elif action_type == 'OPT_OUT':
                return self._handle_opt_out(campaign, rule, subscriber, message, action_config)
            elif action_type == 'HELP':
                return self._handle_help(campaign, rule, subscriber, message, action_config)
            elif action_type == 'SEND_TEMPLATE':
                return self._handle_send_template(campaign, rule, subscriber, message, action_config)
            elif action_type == 'START_JOURNEY':
                return self._handle_start_journey(campaign, rule, subscriber, message, action_config)
            elif action_type == 'CREATE_LEAD':
                return self._handle_create_lead(campaign, rule, subscriber, message, action_config)
            elif action_type == 'ROUTE_TO_AGENT':
                return self._handle_route_to_agent(campaign, rule, subscriber, message, action_config)
            elif action_type == 'COMPOSITE':
                return self._handle_composite(campaign, rule, subscriber, message, action_config)
            else:
                return ExecutionResult(
                    False,
                    'error',
                    {'error': f'Unknown action type: {action_type}'},
                    f'Unknown action type: {action_type}'
                )
        except Exception as e:
            logger.exception(f"Error executing action {action_type}: {e}")
            return ExecutionResult(
                False,
                'error',
                {'error': str(e)},
                str(e)
            )
    
    def _handle_opt_in(self, campaign, rule, subscriber, message, action_config):
        """Handle OPT_IN action"""
        from sms_marketing.services.state import SMSMarketingStateManager
        state_manager = SMSMarketingStateManager()
        
        keyword = rule.keyword.keyword
        result = state_manager.handle_opt_in(
            subscriber, campaign, rule, campaign.opt_in_mode, keyword
        )
        
        # Link lead if available
        lead = self._link_or_create_lead(subscriber, campaign, action_config)
        
        # Send confirmation/welcome message
        if result['confirmed']:
            # Single opt-in: send welcome message
            self._send_welcome_message(campaign, subscriber, action_config)
        else:
            # Double opt-in: send confirmation request
            self._send_confirmation_request(campaign, subscriber, action_config)
        
        return ExecutionResult(
            True,
            'opt_in',
            {
                'campaign_id': campaign.id,
                'rule_id': rule.id,
                'opt_in_mode': campaign.opt_in_mode,
                'opt_in_keyword': keyword,
                'confirmed': result['confirmed'],
                'lead_linked': lead is not None,
                'lead_id': lead.id if lead else None
            }
        )
    
    def _handle_opt_out(self, campaign, rule, subscriber, message, action_config):
        """Handle OPT_OUT action"""
        from sms_marketing.services.state import SMSMarketingStateManager
        state_manager = SMSMarketingStateManager()
        
        keyword = rule.keyword.keyword if rule else 'STOP'
        result = state_manager.handle_opt_out(subscriber, keyword)
        
        # Send opt-out confirmation
        self._send_opt_out_confirmation(subscriber, campaign)
        
        return ExecutionResult(
            True,
            'opt_out',
            {
                'opt_out_source': 'keyword',
                'opt_out_keyword': keyword,
                'was_opted_in': result['was_opted_in']
            }
        )
    
    def _handle_help(self, campaign, rule, subscriber, message, action_config):
        """Handle HELP action"""
        help_text = (
            action_config.get('help_text') or
            getattr(campaign, 'help_text', None) or
            "Reply STOP to opt out. Reply HELP for more information."
        )
        
        # Send help message
        success, sms_message = self.message_sender.send_message(
            subscriber=subscriber,
            campaign=campaign,
            body=help_text,
            rule=rule,
            message_type='help'
        )
        
        return ExecutionResult(
            success,
            'message_sent' if success else 'error',
            {
                'message_type': 'help',
                'help_text': help_text,
                'sms_message_id': sms_message.id if sms_message else None
            },
            error=None if success else 'Failed to send help message'
        )
    
    def _handle_send_template(self, campaign, rule, subscriber, message, action_config):
        """Handle SEND_TEMPLATE action"""
        template_id = action_config.get('template_id')
        if not template_id:
            return ExecutionResult(False, 'error', {'error': 'template_id required'}, 'template_id required')
        
        try:
            template = MessageTemplate.objects.get(id=template_id, channel='sms')
        except MessageTemplate.DoesNotExist:
            return ExecutionResult(False, 'error', {'error': 'Template not found'}, 'Template not found')
        
        # Render template with context
        context = {
            'lead': subscriber.lead,
            'campaign': campaign,
            'subscriber': subscriber
        }
        rendered_content = template.replace_variables(context)
        
        # Send message
        success, sms_message = self.message_sender.send_message(
            subscriber=subscriber,
            campaign=campaign,
            body=rendered_content,
            rule=rule,
            message_type='template'
        )
        
        return ExecutionResult(
            success,
            'message_sent' if success else 'error',
            {
                'template_id': template_id,
                'message_type': 'template',
                'sms_message_id': sms_message.id if sms_message else None
            },
            error=None if success else 'Failed to send template message'
        )
    
    def _handle_start_journey(self, campaign, rule, subscriber, message, action_config):
        """Handle START_JOURNEY action"""
        nurturing_campaign_id = (
            action_config.get('nurturing_campaign_id') or
            (campaign.follow_up_nurturing_campaign.id if campaign.follow_up_nurturing_campaign else None)
        )
        
        if not nurturing_campaign_id:
            return ExecutionResult(False, 'error', {'error': 'nurturing_campaign_id required'}, 'nurturing_campaign_id required')
        
        try:
            nurturing_campaign = LeadNurturingCampaign.objects.get(id=nurturing_campaign_id)
        except LeadNurturingCampaign.DoesNotExist:
            return ExecutionResult(False, 'error', {'error': 'Nurturing campaign not found'}, 'Nurturing campaign not found')
        
        # Create participant
        lead = subscriber.lead
        if not lead:
            return ExecutionResult(False, 'error', {'error': 'Subscriber has no linked lead'}, 'Subscriber has no linked lead')
        
        participant, created = LeadNurturingParticipant.objects.get_or_create(
            lead=lead,
            nurturing_campaign=nurturing_campaign,
            defaults={'status': 'active'}
        )
        
        # Enqueue first step (this would trigger journey processor)
        # You may need to enqueue a task here to start the journey
        # For now, we'll just create the participant
        
        return ExecutionResult(
            True,
            'nurturing_campaign_enrolled',
            {
                'nurturing_campaign_id': nurturing_campaign_id,
                'nurturing_participant_id': participant.id,
                'lead_id': lead.id
            }
        )
    
    def _handle_create_lead(self, campaign, rule, subscriber, message, action_config):
        """Handle CREATE_LEAD action"""
        lead_data = action_config.get('lead_data', {})
        
        # Create lead
        from external_models.models.external_references import Lead
        
        lead = Lead.objects.create(
            phone_number=subscriber.phone_number,
            account=campaign.account,
            **lead_data
        )
        
        # Link to subscriber
        subscriber.lead = lead
        subscriber.save()
        
        return ExecutionResult(
            True,
            'message_received',
            {'lead_id': lead.id, 'lead_created': True}
        )
    
    def _handle_route_to_agent(self, campaign, rule, subscriber, message, action_config):
        """Handle ROUTE_TO_AGENT action"""
        # Get or create conversation
        conversation = self._get_or_create_conversation(subscriber, campaign.endpoint, subscriber.lead)
        
        # Create conversation message
        conversation_message = ConversationMessage.objects.create(
            conversation=conversation,
            message_sid=f"SM_MKT_{message.id}",
            direction='inbound',
            channel='sms',
            body=message.body_raw,
            from_number=subscriber.phone_number,
            to_number=campaign.endpoint.value,
            raw_data={'sms_message_id': message.id}
        )
        
        # Link SmsMessage to conversation
        message.conversation = conversation
        message.conversation_message = conversation_message
        message.save()
        
        # Route to ACS (existing integration)
        # This would call your ACS conversation engine
        
        return ExecutionResult(
            True,
            'message_received',
            {
                'conversation_id': conversation.id,
                'conversation_message_id': conversation_message.id
            }
        )
    
    def _handle_composite(self, campaign, rule, subscriber, message, action_config):
        """Handle COMPOSITE action"""
        actions = action_config.get('actions', [])
        execution_mode = action_config.get('execution_mode', 'sequential')
        stop_on_error = action_config.get('stop_on_error', False)
        
        results = []
        for action_item in actions:
            action_type = action_item.get('type')
            action_config_item = action_item.get('config', {})
            
            # Create a temporary rule-like object for sub-actions
            class TempRule:
                def __init__(self, action_type, action_config):
                    self.action_type = action_type
                    self.action_config = action_config
                    self.keyword = type('Keyword', (), {'keyword': ''})()
            
            temp_rule = TempRule(action_type, action_config_item)
            
            result = self.execute_action(campaign, temp_rule, subscriber, message, action_config_item)
            results.append({
                'type': action_type,
                'success': result.success,
                'event_type': result.event_type
            })
            
            if stop_on_error and not result.success:
                break
        
        return ExecutionResult(
            all(r['success'] for r in results),
            'composite',
            {'actions': results, 'execution_mode': execution_mode}
        )
    
    # Helper methods
    def _link_or_create_lead(self, subscriber: SmsSubscriber, campaign: SmsKeywordCampaign, action_config: Dict):
        """Link subscriber to existing lead or create new one"""
        if subscriber.lead:
            return subscriber.lead
        
        # Try to find existing lead
        lead = self.lead_matching.get_lead_by_phone(subscriber.phone_number)
        
        if not lead and action_config.get('create_lead_if_missing'):
            # Create new lead
            from external_models.models.external_references import Lead
            lead = Lead.objects.create(
                phone_number=subscriber.phone_number,
                account=campaign.account
            )
        
        if lead:
            subscriber.lead = lead
            subscriber.save()
        
        return lead
    
    def _get_or_create_conversation(self, subscriber: SmsSubscriber, endpoint, lead=None):
        """Get or create conversation for SMS marketing"""
        conversation_sid = f"SM_MKT_{endpoint.id}_{subscriber.phone_number}"
        
        conversation, created = Conversation.objects.get_or_create(
            twilio_sid=conversation_sid,
            defaults={
                'channel': 'sms',
                'state': 'active',
                'lead': lead,
                'messaging_service_sid': endpoint.value
            }
        )
        
        return conversation
    
    def _send_message(
        self,
        subscriber: SmsSubscriber,
        campaign: SmsKeywordCampaign,
        body: str,
        rule: Optional[SmsKeywordRule] = None,
        message_type: str = 'regular'
    ):
        """
        Send SMS message using SMSMarketingMessageSender.
        
        Args:
            subscriber: SmsSubscriber to send to
            campaign: SmsKeywordCampaign this message is for
            body: Message content
            rule: Optional SmsKeywordRule that triggered this message
            message_type: Type of message ('welcome', 'confirmation', 'help', 'opt_out', 'regular')
            
        Returns:
            tuple: (success: bool, sms_message: SmsMessage or None)
        """
        return self.message_sender.send_message(
            subscriber=subscriber,
            campaign=campaign,
            body=body,
            rule=rule,
            message_type=message_type
        )
    
    def _send_welcome_message(self, campaign: SmsKeywordCampaign, subscriber: SmsSubscriber, action_config: Dict):
        """Send welcome message after opt-in"""
        template_id = action_config.get('template_id')
        welcome_text = action_config.get('welcome_message')
        
        if template_id:
            # Use template
            self._handle_send_template(campaign, None, subscriber, None, {'template_id': template_id})
        elif welcome_text:
            # Use direct text
            self._send_message(subscriber, campaign, welcome_text, message_type='welcome')
        elif hasattr(campaign, 'welcome_message') and campaign.welcome_message:
            # Use campaign default
            self._send_message(subscriber, campaign, campaign.welcome_message, message_type='welcome')
    
    def _send_confirmation_request(self, campaign: SmsKeywordCampaign, subscriber: SmsSubscriber, action_config: Dict):
        """Send double opt-in confirmation request"""
        confirmation_text = (
            action_config.get('confirmation_message') or
            "Reply YES to confirm your opt-in."
        )
        self._send_message(subscriber, campaign, confirmation_text, message_type='confirmation')
    
    def _send_opt_out_confirmation(self, subscriber: SmsSubscriber, campaign: SmsKeywordCampaign):
        """Send opt-out confirmation"""
        opt_out_text = (
            getattr(campaign, 'opt_out_message', None) or
            "You have been unsubscribed. You will no longer receive messages."
        )
        self._send_message(subscriber, campaign, opt_out_text, message_type='opt_out')

