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
from sms_marketing.models import (
    SmsMessage,
    SmsSubscriber,
    SmsKeywordCampaign,
    SmsKeywordRule,
    SmsSubscriberCampaignSubscription,
)
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
            subscriber, campaign, rule, campaign.opt_in_mode, keyword, message=message
        )
        
        # Link lead if available
        lead = self._link_or_create_lead(subscriber, campaign, action_config)
        
        # When opt-in is confirmed, enroll in follow-up nurturing campaign if linked (drip/reminder/blast)
        nurturing_participant = None
        if result['confirmed']:
            nurturing_participant = self._enroll_in_follow_up_nurturing_campaign_if_applicable(
                campaign, subscriber, message, rule=rule
            )
        
        # Send confirmation/welcome message
        if result['confirmed']:
            # Single opt-in: send welcome message
            self._send_welcome_message(campaign, rule, subscriber, action_config)
        else:
            # Double opt-in: send confirmation request
            self._send_confirmation_request(campaign, rule, subscriber, action_config)
        
        payload = {
            'campaign_id': campaign.id,
            'rule_id': rule.id,
            'opt_in_mode': campaign.opt_in_mode,
            'opt_in_keyword': keyword,
            'confirmed': result['confirmed'],
            'lead_linked': lead is not None,
            'lead_id': lead.id if lead else None
        }
        if nurturing_participant:
            payload['nurturing_participant_id'] = nurturing_participant.id
            payload['nurturing_campaign_id'] = nurturing_participant.nurturing_campaign_id
        return ExecutionResult(True, 'opt_in', payload)

    def _handle_opt_out(self, campaign, rule, subscriber, message, action_config):
        """Handle OPT_OUT action"""
        from sms_marketing.services.state import SMSMarketingStateManager
        state_manager = SMSMarketingStateManager()
        
        keyword = rule.keyword.keyword if rule else 'STOP'
        result = state_manager.handle_opt_out(subscriber, keyword, message=message, campaign=campaign)
        
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
        """Handle HELP action. Endpoint first, then action_config, campaign, program, default."""
        endpoint = getattr(subscriber, 'endpoint', None)
        sms_settings = getattr(endpoint, 'sms_settings', None) if endpoint else None
        help_text = (
            (getattr(sms_settings, 'help_message', None) if sms_settings else None)
            or action_config.get('help_text')
            or getattr(campaign, 'help_text', None)
            or (getattr(campaign.program, 'help_text', None) if getattr(campaign, 'program', None) else None)
            or "Reply STOP to opt out. Reply HELP for more information."
        )

        # Send help message (apply variable replacement for plain text too)
        success, sms_message = self._send_message(
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

        # Ensure lead exists (create for CRM campaign if missing) so we can create participant
        lead = subscriber.lead
        if not lead:
            lead = self._link_or_create_lead(subscriber, campaign, action_config or {'create_lead_if_missing': True})
        if not lead:
            return ExecutionResult(False, 'error', {'error': 'Subscriber has no linked lead'}, 'Subscriber has no linked lead')
        created_by_id = getattr(nurturing_campaign, 'created_by_id', None)
        if not created_by_id:
            return ExecutionResult(False, 'error', {'error': 'Nurturing campaign has no created_by'}, 'Nurturing campaign has no created_by')

        # Get or create campaign-level subscription so participant can link via originating_subscription (doc item 2)
        now = timezone.now()
        subscription, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
            subscriber=subscriber,
            campaign=campaign,
            defaults={
                'status': 'opted_in',
                'opted_in_at': now,
                'opt_in_message': message,
                'opt_in_rule': rule,
                'lead': lead,
            },
        )
        update_sub = []
        if subscription.opt_in_rule_id is None and rule is not None:
            subscription.opt_in_rule = rule
            update_sub.append('opt_in_rule')
        if subscription.opt_in_message_id is None and message is not None:
            subscription.opt_in_message = message
            update_sub.append('opt_in_message')
        if subscription.lead_id is None and lead is not None:
            subscription.lead = lead
            update_sub.append('lead')
        if update_sub:
            subscription.save(update_fields=update_sub)

        lead_for_participant = subscription.lead or lead
        defaults = {
            'status': 'active',
            'originating_subscription': subscription,
            'created_by_id': created_by_id,
            'metadata': {},  # DB column is NOT NULL
        }
        participant, created = LeadNurturingParticipant.objects.get_or_create(
            lead=lead_for_participant,
            nurturing_campaign=nurturing_campaign,
            defaults=defaults,
        )
        # Always set originating_subscription so it's set on create and when participant existed without it
        if participant.originating_subscription_id != subscription.id:
            participant.originating_subscription = subscription
            participant.save(update_fields=['originating_subscription_id'])

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
        """
        Handle CREATE_LEAD action.

        Uses crm.services.lead_dedup: find by campaign/account + phone/email,
        update or create, then set subscriber.lead and subscription.lead (doc item 1).
        """
        try:
            from crm.services.lead_dedup import create_or_update_lead
        except ImportError:
            from external_models.models.external_references import Lead
            # Fallback if lead_dedup not available
            lead_data = dict(action_config.get('lead_data', {}))
            crm_campaign = campaign.get_primary_crm_campaign()
            if not crm_campaign:
                rel = getattr(campaign, 'crm_campaign_relations', None)
                if rel:
                    first_rel = rel.filter(is_active=True).first()
                    crm_campaign = first_rel.crm_campaign if first_rel else None
            if not crm_campaign:
                return ExecutionResult(
                    False, 'error',
                    {'error': 'Campaign has no linked CRM campaign; cannot create lead'},
                    'Campaign has no linked CRM campaign'
                )
            lead_data.setdefault('campaign', crm_campaign)
            lead_data.setdefault('phone_number', subscriber.phone_number)
            lead_data.pop('account', None)
            lead = Lead.objects.create(**lead_data)
            subscriber.lead = lead
            subscriber.save()
            SmsSubscriberCampaignSubscription.objects.filter(
                subscriber=subscriber, campaign=campaign
            ).update(lead=lead)
            return ExecutionResult(True, 'message_received', {'lead_id': lead.id, 'lead_created': True})

        lead_data = dict(action_config.get('lead_data', {}))
        phone_number = subscriber.phone_number
        email = lead_data.get('email')
        crm_campaign = campaign.get_primary_crm_campaign()
        if not crm_campaign:
            rel = getattr(campaign, 'crm_campaign_relations', None)
            if rel:
                first_rel = rel.filter(is_active=True).first()
                crm_campaign = first_rel.crm_campaign if first_rel else None
        if not crm_campaign:
            return ExecutionResult(
                False, 'error',
                {'error': 'Campaign has no linked CRM campaign; cannot create lead'},
                'Campaign has no linked CRM campaign'
            )

        lead, created_new = create_or_update_lead(
            campaign=crm_campaign,
            account=getattr(campaign, 'account', None),
            phone_number=phone_number,
            email=email,
            lead_data=lead_data,
            lead_type=None,
        )
        if not created_new:
            logger.info(
                "CREATE_LEAD: found existing lead id=%s (campaign + contact), updated and linked subscriber",
                lead.id,
            )

        subscriber.lead = lead
        subscriber.save()
        SmsSubscriberCampaignSubscription.objects.filter(
            subscriber=subscriber, campaign=campaign
        ).update(lead=lead)

        return ExecutionResult(
            True,
            'message_received',
            {'lead_id': lead.id, 'lead_created': created_new}
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
        """
        Link subscriber to existing lead or create new one.
        When a lead is set, also updates subscription.lead for (subscriber, campaign) (doc item 1).
        """
        if subscriber.lead_id:
            lead = subscriber.lead
            SmsSubscriberCampaignSubscription.objects.filter(
                subscriber=subscriber, campaign=campaign
            ).update(lead=lead)
            return lead

        crm_campaign = campaign.get_primary_crm_campaign()
        if not crm_campaign:
            rel = getattr(campaign, 'crm_campaign_relations', None)
            if rel:
                first_rel = rel.filter(is_active=True).first()
                crm_campaign = first_rel.crm_campaign if first_rel else None
        if not crm_campaign:
            logger.warning(
                "Cannot create lead for subscriber %s: SmsKeywordCampaign %s has no CRM campaign",
                subscriber.phone_number, campaign.id
            )
            return None

        if not action_config.get('create_lead_if_missing'):
            lead = self.lead_matching.get_lead_by_phone(subscriber.phone_number)
            if lead:
                subscriber.lead = lead
                subscriber.save()
                SmsSubscriberCampaignSubscription.objects.filter(
                    subscriber=subscriber, campaign=campaign
                ).update(lead=lead)
            return lead

        try:
            from crm.services.lead_dedup import create_or_update_lead
            lead_data = action_config.get('lead_data') or {}
            lead, _ = create_or_update_lead(
                campaign=crm_campaign,
                account=getattr(campaign, 'account', None),
                phone_number=subscriber.phone_number,
                email=lead_data.get('email'),
                lead_data=lead_data,
                lead_type=None,
            )
        except (ImportError, ValueError):
            from external_models.models.external_references import Lead
            lead = Lead.objects.create(
                phone_number=subscriber.phone_number,
                campaign=crm_campaign,
            )

        subscriber.lead = lead
        subscriber.save()
        SmsSubscriberCampaignSubscription.objects.filter(
            subscriber=subscriber, campaign=campaign
        ).update(lead=lead)
        return lead

    def _enroll_in_follow_up_nurturing_campaign_if_applicable(
        self,
        campaign,
        subscriber,
        message,
        rule=None,
    ):
        """
        When campaign has follow_up_nurturing_campaign, always enroll the subscriber into that
        lead nurturing campaign: create the lead for the CRM campaign if not already created,
        then create or get the participant with originating_subscription set to the campaign-level
        opt-in subscription. Returns the participant or None.
        """
        nurturing_campaign = getattr(campaign, 'follow_up_nurturing_campaign', None)
        if not nurturing_campaign:
            return None

        # Ensure lead exists so we can enroll (create for CRM campaign if missing)
        lead = subscriber.lead
        if not lead:
            lead = self._link_or_create_lead(subscriber, campaign, {'create_lead_if_missing': True})
        if not lead:
            return None

        # created_by_id is required by the DB; use the nurturing campaign's creator
        created_by_id = getattr(nurturing_campaign, 'created_by_id', None)
        if not created_by_id:
            return None

        # Get or create the campaign-level subscription; backfill subscription.lead (doc item 1/2)
        now = timezone.now()
        subscription, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
            subscriber=subscriber,
            campaign=campaign,
            defaults={
                'status': 'opted_in',
                'opted_in_at': now,
                'opt_in_message': message,
                'opt_in_rule': rule,
                'lead': lead,
            },
        )
        update_sub = []
        if rule is not None and subscription.opt_in_rule_id is None:
            subscription.opt_in_rule = rule
            update_sub.append('opt_in_rule')
        if message is not None and subscription.opt_in_message_id is None:
            subscription.opt_in_message = message
            update_sub.append('opt_in_message')
        if subscription.lead_id is None and lead is not None:
            subscription.lead = lead
            update_sub.append('lead')
        if update_sub:
            subscription.save(update_fields=update_sub)

        lead_for_participant = subscription.lead or lead
        defaults = {
            'status': 'active',
            'originating_subscription': subscription,
            'created_by_id': created_by_id,
            'metadata': {},  # DB column is NOT NULL
        }
        participant, created = LeadNurturingParticipant.objects.get_or_create(
            lead=lead_for_participant,
            nurturing_campaign=nurturing_campaign,
            defaults=defaults,
        )
        # Always set originating_subscription so it's set on create and when participant existed without it
        if participant.originating_subscription_id != subscription.id:
            participant.originating_subscription = subscription
            participant.save(update_fields=['originating_subscription_id'])
        return participant

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
        campaign: Optional[SmsKeywordCampaign],
        body: str,
        rule: Optional[SmsKeywordRule] = None,
        message_type: str = 'regular'
    ):
        """
        Send SMS message using SMSMarketingMessageSender.

        When rule has short_link set, passes raw body and context to the sender so it can
        create SmsMessage first, inject {{link.short_link}}, and run replace_variables there.
        Otherwise renders body with _render_plain_text and sends (no context).

        Returns:
            tuple: (success: bool, sms_message: SmsMessage or None)
        """
        if rule and rule.short_link:
            context = self._build_message_context(subscriber=subscriber, campaign=campaign, rule=rule)
            return self.message_sender.send_message(
                subscriber=subscriber,
                campaign=campaign,
                body=body,
                rule=rule,
                message_type=message_type,
                context=context,
            )
        rendered_body = self._render_plain_text(body, subscriber=subscriber, campaign=campaign, rule=rule)
        return self.message_sender.send_message(
            subscriber=subscriber,
            campaign=campaign,
            body=rendered_body,
            rule=rule,
            message_type=message_type,
        )

    def _build_message_context(
        self,
        subscriber: SmsSubscriber,
        campaign: Optional[SmsKeywordCampaign] = None,
        rule: Optional[SmsKeywordRule] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build context dict for variable replacement (lead, campaign, keyword, etc.)."""
        endpoint = None
        try:
            endpoint = campaign.endpoint if campaign else getattr(subscriber, 'endpoint', None)
        except Exception:
            endpoint = getattr(subscriber, 'endpoint', None)

        keyword_text = None
        try:
            keyword_text = rule.keyword.keyword if rule and getattr(rule, 'keyword', None) else None
        except Exception:
            keyword_text = None

        context: Dict[str, Any] = {
            'lead': getattr(subscriber, 'lead', None),
            'subscriber': subscriber,
            'campaign': campaign,
            'endpoint': endpoint,
            'account': getattr(campaign, 'account', None) if campaign else getattr(endpoint, 'account', None),
            'keyword': {
                'keyword': keyword_text,
                'endpoint_value': getattr(endpoint, 'value', None) if endpoint else None,
            },
        }
        # Include link for {{link.short_link}} when rule has a short link (base URL from domain + slug_canonical).
        # rule.short_link is the FK (Link instance); Link.short_link property returns get_full_url().
        if rule and rule.short_link:
            context['link'] = rule.short_link
        if extra_context:
            context.update(extra_context)
        # Normalize: use lowercase 'link' so variable replacement is consistent with other categories
        if 'Link' in context:
            if 'link' not in context:
                context['link'] = context['Link']
            del context['Link']
        return context

    def _render_plain_text(
        self,
        body: Optional[str],
        subscriber: SmsSubscriber,
        campaign: Optional[SmsKeywordCampaign] = None,
        rule: Optional[SmsKeywordRule] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Apply TemplateVariable/TemplateVariableCategory replacement to plain text bodies.
        Uses MessageTemplate.replace_variables() so templates and plain text share the same variable system.
        """
        if not body:
            return body or ""

        context = self._build_message_context(
            subscriber=subscriber, campaign=campaign, rule=rule, extra_context=extra_context
        )
        try:
            return MessageTemplate(content=body).replace_variables(context)
        except Exception as e:
            logger.warning(f"Variable replacement failed; sending raw body. error={e}")
            return body
    
    def _send_welcome_message(self, campaign: SmsKeywordCampaign, rule: Optional[SmsKeywordRule], subscriber: SmsSubscriber, action_config: Dict):
        """Send welcome message after opt-in"""
        template_id = action_config.get('template_id')
        welcome_text = action_config.get('welcome_message')
        rule_initial_reply = getattr(rule, 'initial_reply', None) if rule else None
        
        # Priority (per design doc):
        # 1) rule.initial_reply -> 2) action_config.template_id -> 3) action_config.welcome_message -> 4) campaign.welcome_message
        if rule_initial_reply:
            self._send_message(subscriber, campaign, rule_initial_reply, rule=rule, message_type='welcome')
        elif template_id:
            # Use template
            self._handle_send_template(campaign, None, subscriber, None, {'template_id': template_id})
        elif welcome_text:
            # Use direct text
            self._send_message(subscriber, campaign, welcome_text, rule=rule, message_type='welcome')
        elif hasattr(campaign, 'welcome_message') and campaign.welcome_message:
            # Use campaign default
            self._send_message(subscriber, campaign, campaign.welcome_message, rule=rule, message_type='welcome')
    
    def _send_confirmation_request(self, campaign: SmsKeywordCampaign, rule: Optional[SmsKeywordRule], subscriber: SmsSubscriber, action_config: Dict):
        """Send double opt-in confirmation request"""
        confirmation_text = (
            (getattr(rule, 'confirmation_message', None) if rule else None) or
            action_config.get('confirmation_message') or
            getattr(campaign, 'confirmation_message', None) or
            "Reply YES to confirm your opt-in."
        )
        self._send_message(subscriber, campaign, confirmation_text, rule=rule, message_type='confirmation')
    
    def _send_opt_out_confirmation(self, subscriber: SmsSubscriber, campaign: SmsKeywordCampaign):
        """Send opt-out confirmation. Endpoint first, then campaign, then default."""
        endpoint = getattr(subscriber, 'endpoint', None)
        sms_settings = getattr(endpoint, 'sms_settings', None) if endpoint else None
        opt_out_text = (
            (getattr(sms_settings, 'stop_message', None) if sms_settings else None)
            or getattr(campaign, 'opt_out_message', None)
            or "You have been unsubscribed. You will no longer receive messages."
        )
        self._send_message(subscriber, campaign, opt_out_text, message_type='opt_out')


# ---------------------------------------------------------------------------
# Adapter layer for processor: function-based API that delegates to the class.
# Processor imports execute_action, ActionExecutionResult, link_lead_for_subscriber,
# enroll_subscriber_in_follow_up_nurturing, get_welcome_message_for_opt_in.
# ---------------------------------------------------------------------------

class ActionExecutionResult:
    """Result type expected by processor (success, message, data)."""
    def __init__(self, success: bool, message: str = "", data: Optional[Dict[str, Any]] = None):
        self.success = success
        self.message = message
        self.data = data or {}


def execute_action(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    action_config: Optional[Dict[str, Any]] = None,
) -> ActionExecutionResult:
    """Execute action via SMSMarketingActionExecutor. Returns ActionExecutionResult for processor."""
    executor = SMSMarketingActionExecutor()
    result = executor.execute_action(
        campaign, rule, subscriber, message, action_config or {}
    )
    return ActionExecutionResult(
        success=result.success,
        message=result.error or "",
        data=result.payload or {},
    )


def link_lead_for_subscriber(
    subscriber: SmsSubscriber,
    campaign: SmsKeywordCampaign,
    config: Optional[Dict[str, Any]] = None,
):
    """Link or create lead for subscriber and set subscription.lead (doc item 1). Used after double opt-in."""
    executor = SMSMarketingActionExecutor()
    return executor._link_or_create_lead(subscriber, campaign, config or {})


def enroll_subscriber_in_follow_up_nurturing(
    campaign: SmsKeywordCampaign,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    rule: Optional[SmsKeywordRule] = None,
):
    """Enroll subscriber in follow_up_nurturing_campaign with originating_subscription (doc item 2)."""
    executor = SMSMarketingActionExecutor()
    return executor._enroll_in_follow_up_nurturing_campaign_if_applicable(
        campaign, subscriber, message, rule=rule
    )


def get_welcome_message_for_opt_in(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return welcome message body (same priority as _send_welcome_message). Used by processor for double opt-in."""
    config = config or {}
    if getattr(rule, 'initial_reply', None):
        return rule.initial_reply
    if config.get('welcome_message'):
        return config['welcome_message']
    if getattr(campaign, 'welcome_message', None):
        return campaign.welcome_message
    return None
