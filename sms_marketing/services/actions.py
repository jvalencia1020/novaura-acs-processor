"""
Action execution service for SMS marketing keyword rules.

This module provides handlers for executing different action types when keywords are matched.
Each action handler updates subscriber state, creates events, and enqueues downstream tasks.
"""
import logging
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from external_models.models.external_references import Lead
from django.utils import timezone
from django.db import transaction

from ..models import (
    SmsKeywordCampaign,
    SmsKeywordRule,
    SmsSubscriber,
    SmsSubscriberCampaignSubscription,
    SmsMessage,
    SmsCampaignEvent,
)

logger = logging.getLogger(__name__)


class ActionExecutionResult:
    """Result of executing an action"""
    def __init__(self, success: bool, message: str = "", data: Optional[Dict[str, Any]] = None):
        self.success = success
        self.message = message
        self.data = data or {}


def execute_action(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    action_config: Optional[Dict[str, Any]] = None
) -> ActionExecutionResult:
    """
    Execute an action based on the rule's action_type.
    
    Args:
        campaign: The SMS keyword campaign
        rule: The matched keyword rule
        subscriber: The SMS subscriber
        message: The inbound SMS message
        action_config: Action configuration (from rule.action_config or campaign defaults)
        
    Returns:
        ActionExecutionResult with success status and details
    """
    action_type = rule.action_type
    config = action_config or rule.action_config or {}
    
    logger.info(f"Executing action {action_type} for subscriber {subscriber.phone_number}")
    
    try:
        if action_type == 'OPT_IN':
            return handle_opt_in(campaign, rule, subscriber, message, config)
        elif action_type == 'OPT_OUT':
            return handle_opt_out(campaign, rule, subscriber, message, config)
        elif action_type == 'HELP':
            return handle_help(campaign, rule, subscriber, message, config)
        elif action_type == 'SEND_TEMPLATE':
            return handle_send_template(campaign, rule, subscriber, message, config)
        elif action_type == 'START_JOURNEY':
            return handle_start_journey(campaign, rule, subscriber, message, config)
        elif action_type == 'CREATE_LEAD':
            return handle_create_lead(campaign, rule, subscriber, message, config)
        elif action_type == 'ROUTE_TO_AGENT':
            return handle_route_to_agent(campaign, rule, subscriber, message, config)
        elif action_type == 'COMPOSITE':
            return handle_composite(campaign, rule, subscriber, message, config)
        else:
            logger.warning(f"Unknown action type: {action_type}")
            return ActionExecutionResult(
                success=False,
                message=f"Unknown action type: {action_type}"
            )
    except Exception as e:
        logger.exception(f"Error executing action {action_type}: {str(e)}")
        return ActionExecutionResult(
            success=False,
            message=f"Error executing action: {str(e)}"
        )


def handle_opt_in(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle OPT_IN action.
    
    Respects campaign.opt_in_mode:
    - 'single': Set subscriber to opted_in immediately
    - 'double': Set subscriber to pending_opt_in, send confirmation request
    - 'none': Skip opt-in state change (log only)
    
    Priority for welcome message:
    1. config.template_id (if set)
    2. config.welcome_message (if set)
    3. rule.initial_reply (keyword-level default)
    4. campaign.welcome_message (campaign-level default)
    5. No message sent
    
    Priority for confirmation message (double opt-in):
    1. config.confirmation_message
    2. rule.confirmation_message (keyword-level default)
    3. campaign.confirmation_message (campaign-level default)
    4. Default: "Reply YES to confirm your opt-in."
    """
    opt_in_mode = campaign.opt_in_mode
    
    with transaction.atomic():
        now = timezone.now()
        # Update subscriber state based on opt_in_mode
        if opt_in_mode == 'single':
            subscriber.status = 'opted_in'
            subscriber.opt_in_at = now
            subscriber.opt_in_source = 'keyword'
            subscriber.opt_in_keyword = rule.keyword.keyword if rule.keyword else None
            subscriber.opt_in_message = message
            subscriber.last_inbound_at = now
            subscriber.sms_campaign = campaign
            subscriber.save()
            
            # Send welcome message for single opt-in
            welcome_message = _get_welcome_message(campaign, rule, config)
            if welcome_message:
                # TODO: Enqueue task to send SMS message
                logger.info(f"Would send welcome message: {welcome_message}")
            
        elif opt_in_mode == 'double':
            subscriber.status = 'pending_opt_in'
            subscriber.opt_in_source = 'keyword'
            subscriber.opt_in_keyword = rule.keyword.keyword if rule.keyword else None
            subscriber.opt_in_message = message
            subscriber.last_inbound_at = now
            subscriber.sms_campaign = campaign
            subscriber.save()
            
            # Send confirmation message
            # Priority: config.confirmation_message > rule.confirmation_message > campaign.confirmation_message > default
            confirmation_message = (
                config.get('confirmation_message') or
                rule.confirmation_message or
                campaign.confirmation_message
            )
            if not confirmation_message:
                confirmation_message = "Reply YES to confirm your opt-in."
            # TODO: Enqueue task to send SMS message
            logger.info(f"Would send confirmation message: {confirmation_message}")
            
        elif opt_in_mode == 'none':
            # Skip opt-in state change, just log
            subscriber.last_inbound_at = now
            subscriber.sms_campaign = campaign
            subscriber.save()

        # Per-campaign subscription: get_or_create and set status/opted_in_at/opt_in_message/opt_in_rule (re-opt-in clears opted_out)
        subscription, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
            subscriber=subscriber,
            campaign=campaign,
            defaults={
                'status': 'pending_opt_in' if opt_in_mode == 'double' else 'opted_in',
                'opted_in_at': now,
                'opt_in_message': message,
                'opt_in_rule': rule,
            },
        )
        subscription.status = 'pending_opt_in' if opt_in_mode == 'double' else 'opted_in'
        subscription.opted_in_at = now
        subscription.opt_in_message = message
        subscription.opt_in_rule = rule
        subscription.opted_out_at = None
        subscription.opt_out_message = None
        if subscriber.lead_id and subscription.lead_id is None:
            subscription.lead = subscriber.lead
        subscription.save()

        # Double opt-in: When the subscriber replies YES to confirm, the processor that handles
        # that confirmation must set this subscription to status='opted_in' and optionally
        # update opted_in_at to the confirmation time. Do not change opt_in_message or opt_in_rule
        # (they stay the initial START message/rule). See SmsSubscriberCampaignSubscription.
        
        # Handle lead creation if requested
        if config.get('create_lead_if_missing') and not subscriber.lead:
            # TODO: Enqueue task to create lead
            logger.info("Would create lead if missing")
        
        # Create event log
        SmsCampaignEvent.objects.create(
            endpoint=subscriber.endpoint,
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            event_type='opt_in',
            payload={
                'opt_in_mode': opt_in_mode,
                'keyword': rule.keyword.keyword if rule.keyword else None,
            }
        )
    
    return ActionExecutionResult(
        success=True,
        message=f"Opt-in processed (mode: {opt_in_mode})"
    )


def handle_opt_out(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle OPT_OUT action.
    
    Priority for opt-out message:
    1. campaign.opt_out_message (campaign-level default)
    2. Default: "You have been unsubscribed. You will no longer receive messages."
    
    Note: Opt-out is universal behavior, so opt-out messages are campaign-level only.
    """
    now = timezone.now()
    with transaction.atomic():
        subscriber.status = 'opted_out'
        subscriber.opt_out_at = now
        subscriber.opt_out_source = 'keyword'
        subscriber.opt_out_message = message
        subscriber.last_inbound_at = now
        subscriber.save()

        # Per-campaign subscription: get_or_create then set opted_out for this campaign
        subscription, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
            subscriber=subscriber,
            campaign=campaign,
            defaults={'status': 'opted_out', 'opted_out_at': now, 'opt_out_message': message},
        )
        subscription.status = 'opted_out'
        subscription.opted_out_at = now
        subscription.opt_out_message = message
        subscription.save()

        # Global STOP: mark all other campaign subscriptions for this subscriber as opted_out
        SmsSubscriberCampaignSubscription.objects.filter(
            subscriber=subscriber
        ).exclude(campaign=campaign).update(status='opted_out', opted_out_at=now)
        
        # Send opt-out confirmation
        # Priority: campaign.opt_out_message > endpoint.sms_settings.stop_message > default
        opt_out_message = campaign.opt_out_message
        if not opt_out_message and getattr(subscriber, 'endpoint_id', None):
            endpoint_sms = getattr(getattr(subscriber, 'endpoint', None), 'sms_settings', None)
            if endpoint_sms and getattr(endpoint_sms, 'stop_message', None):
                opt_out_message = endpoint_sms.stop_message
        if not opt_out_message:
            opt_out_message = "You have been unsubscribed. You will no longer receive messages."
        # TODO: Enqueue task to send SMS message
        logger.info(f"Would send opt-out confirmation: {opt_out_message}")
        
        # Create event log
        SmsCampaignEvent.objects.create(
            endpoint=subscriber.endpoint,
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            event_type='opt_out',
            payload={
                'keyword': rule.keyword.keyword if rule.keyword else None,
            }
        )
    
    return ActionExecutionResult(
        success=True,
        message="Opt-out processed"
    )


def handle_help(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle HELP action.
    
    Priority for help message:
    1. config.help_text (rule-specific override in action_config)
    2. campaign.help_text (campaign-level default)
    3. campaign.program.help_text (if program exists)
    4. endpoint.sms_settings.help_message (endpoint-level default)
    5. Default: "Reply STOP to opt out. Reply HELP for more information."
    """
    help_text = (
        config.get('help_text') or
        campaign.help_text or
        (campaign.program.help_text if campaign.program else None)
    )
    if not help_text and getattr(subscriber, 'endpoint_id', None):
        endpoint_sms = getattr(getattr(subscriber, 'endpoint', None), 'sms_settings', None)
        if endpoint_sms and getattr(endpoint_sms, 'help_message', None):
            help_text = endpoint_sms.help_message
    if not help_text:
        help_text = "Reply STOP to opt out. Reply HELP for more information."
    
    # TODO: Enqueue task to send SMS message
    logger.info(f"Would send help message: {help_text}")
    
    # Create event log
    SmsCampaignEvent.objects.create(
        endpoint=subscriber.endpoint,
        campaign=campaign,
        rule=rule,
        subscriber=subscriber,
        message=message,
        event_type='message_sent',
        payload={
            'message_type': 'help',
            'help_text': help_text,
        }
    )
    
    return ActionExecutionResult(
        success=True,
        message="Help message sent"
    )


def handle_send_template(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle SEND_TEMPLATE action.
    
    Requires config.template_id (ID of MessageTemplate with channel='sms').
    Template context variables available:
    - lead: Subscriber's linked Lead
    - campaign: SmsKeywordCampaign
    - subscriber: SmsSubscriber
    """
    template_id = config.get('template_id')
    if not template_id:
        return ActionExecutionResult(
            success=False,
            message="SEND_TEMPLATE action requires template_id in config"
        )
    
    try:
        from external_models.models.messages import MessageTemplate
        
        template = MessageTemplate.objects.get(id=template_id, channel='sms')
        
        # Build template context
        context = {
            'lead': subscriber.lead,
            'campaign': campaign,
            'subscriber': subscriber,
        }
        
        # TODO: Render template with context and enqueue task to send SMS message
        logger.info(f"Would send template message (template_id={template_id})")
        
        # Create event log
        SmsCampaignEvent.objects.create(
            endpoint=subscriber.endpoint,
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            event_type='message_sent',
            payload={
                'message_type': 'template',
                'template_id': template_id,
            }
        )
        
        return ActionExecutionResult(
            success=True,
            message=f"Template message queued (template_id={template_id})"
        )
    except MessageTemplate.DoesNotExist:
        return ActionExecutionResult(
            success=False,
            message=f"MessageTemplate with id={template_id} and channel='sms' not found"
        )


def handle_start_journey(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle START_JOURNEY action.
    
    Requires subscriber to have a linked lead (will fail if no lead).
    Uses config.nurturing_campaign_id or falls back to campaign.follow_up_nurturing_campaign.
    """
    nurturing_campaign_id = config.get('nurturing_campaign_id')
    if not nurturing_campaign_id:
        if campaign.follow_up_nurturing_campaign:
            nurturing_campaign = campaign.follow_up_nurturing_campaign
        else:
            return ActionExecutionResult(
                success=False,
                message="START_JOURNEY action requires nurturing_campaign_id in config or campaign.follow_up_nurturing_campaign"
            )
    else:
        try:
            from external_models.models.nurturing_campaigns import LeadNurturingCampaign
            nurturing_campaign = LeadNurturingCampaign.objects.get(id=nurturing_campaign_id)
        except LeadNurturingCampaign.DoesNotExist:
            return ActionExecutionResult(
                success=False,
                message=f"LeadNurturingCampaign with id={nurturing_campaign_id} not found"
            )
    
    # Create LeadNurturingParticipant
    try:
        from external_models.models.nurturing_campaigns import LeadNurturingParticipant

        # Get or create campaign-level subscription (single source of truth for subscriber, campaign, rule, opt-in message)
        subscription, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
            subscriber=subscriber,
            campaign=campaign,
            defaults={
                'status': 'opted_in',
                'opted_in_at': timezone.now(),
                'opt_in_message': message,
                'opt_in_rule': rule,
                'lead': subscriber.lead,  # campaign-scoped lead; backfill from subscriber
            }
        )
        # Update subscription with rule/message/lead if it already existed but was missing them
        update_fields = []
        if subscription.opt_in_rule_id is None and rule:
            subscription.opt_in_rule = rule
            subscription.opt_in_message = message or subscription.opt_in_message
            update_fields.extend(['opt_in_rule', 'opt_in_message'])
        elif subscription.opt_in_message_id is None and message:
            subscription.opt_in_message = message
            update_fields.append('opt_in_message')
        if subscription.lead_id is None and subscriber.lead_id:
            subscription.lead = subscriber.lead
            update_fields.append('lead')
        if update_fields:
            subscription.save(update_fields=update_fields)

        # Prefer subscription.lead (campaign-scoped); fall back to subscriber.lead for backfill
        lead_for_participant = subscription.lead or subscriber.lead
        if not lead_for_participant:
            return ActionExecutionResult(
                success=False,
                message="START_JOURNEY action requires a linked lead (subscription.lead or subscriber.lead)"
            )

        participant, created = LeadNurturingParticipant.objects.get_or_create(
            nurturing_campaign=nurturing_campaign,
            lead=lead_for_participant,
            defaults={
                'status': 'active',
                'originating_subscription': subscription,
            }
        )
        # Backfill attribution if participant already existed but was missing it
        if not created and participant.originating_subscription_id is None:
            participant.originating_subscription = subscription
            participant.save(update_fields=['originating_subscription_id'])
        
        # TODO: Enqueue first step in journey system
        
        # Create event log
        SmsCampaignEvent.objects.create(
            endpoint=subscriber.endpoint,
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            event_type='nurturing_campaign_enrolled',
            nurturing_campaign=nurturing_campaign,
            nurturing_participant=participant,
            payload={
                'nurturing_campaign_id': nurturing_campaign.id,
                'participant_id': participant.id,
            }
        )
        
        return ActionExecutionResult(
            success=True,
            message=f"Enrolled in nurturing campaign (id={nurturing_campaign.id})"
        )
    except Exception as e:
        logger.exception(f"Error creating LeadNurturingParticipant: {str(e)}")
        return ActionExecutionResult(
            success=False,
            message=f"Error enrolling in journey: {str(e)}"
        )


def handle_create_lead(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle CREATE_LEAD action.

    Uses shared crm.services.lead_dedup: find by campaign/account + phone/email,
    update or create, then link subscriber and subscriptions. Requires a linked
    CRM campaign for creation.
    """
    try:
        from crm.services.lead_dedup import create_or_update_lead

        lead_data = config.get('lead_data', {})
        phone_number = subscriber.phone_number
        email = lead_data.get('email')

        # Resolve CRM campaign: primary or first active linked
        crm_campaign = campaign.get_primary_crm_campaign()
        if not crm_campaign:
            rel = campaign.crm_campaign_relations.filter(is_active=True).first()
            crm_campaign = rel.crm_campaign if rel else None

        if not crm_campaign:
            return ActionExecutionResult(
                success=False,
                message="Cannot create lead: link a CRM campaign to this SMS campaign (primary or active).",
            )

        lead, created_new = create_or_update_lead(
            campaign=crm_campaign,
            account=campaign.account,
            phone_number=phone_number,
            email=email,
            lead_data=lead_data,
            lead_type=None,  # SMS uses base Lead
        )

        if not created_new:
            logger.info(
                f"CREATE_LEAD: found existing lead id={lead.id} (campaign + contact), updated and linked subscriber"
            )

        # Link to subscriber (kept for backfill / existing integrations)
        subscriber.lead = lead
        subscriber.save()

        # Campaign-scoped: set subscription.lead when subscription exists for this campaign
        SmsSubscriberCampaignSubscription.objects.filter(
            subscriber=subscriber, campaign=campaign
        ).update(lead=lead)

        # Create event log
        SmsCampaignEvent.objects.create(
            endpoint=subscriber.endpoint,
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            event_type='message_received',
            payload={
                'action': 'create_lead',
                'lead_id': lead.id,
            }
        )

        return ActionExecutionResult(
            success=True,
            message=f"Lead {'updated' if not created_new else 'created'} (id={lead.id})",
            data={'lead_id': lead.id}
        )
    except ValueError as e:
        return ActionExecutionResult(success=False, message=str(e))
    except Exception as e:
        logger.exception(f"Error creating lead: {str(e)}")
        return ActionExecutionResult(
            success=False,
            message=f"Error creating lead: {str(e)}"
        )


def link_lead_for_subscriber(
    subscriber: SmsSubscriber,
    campaign: SmsKeywordCampaign,
    config: Dict[str, Any],
) -> Optional["Lead"]:
    """
    Link or create lead for subscriber and set subscription.lead for this campaign.
    Used after double opt-in confirmation. Returns the lead or None.
    """
    from external_models.models.external_references import Lead
    from crm.services.lead_dedup import create_or_update_lead

    if subscriber.lead_id:
        lead = subscriber.lead
        SmsSubscriberCampaignSubscription.objects.filter(
            subscriber=subscriber, campaign=campaign
        ).update(lead=lead)
        return lead

    if not config.get('create_lead_if_missing'):
        return None

    crm_campaign = campaign.get_primary_crm_campaign()
    if not crm_campaign:
        rel = campaign.crm_campaign_relations.filter(is_active=True).first()
        crm_campaign = rel.crm_campaign if rel else None
    if not crm_campaign:
        logger.warning(
            "Cannot create lead for subscriber %s: SmsKeywordCampaign %s has no CRM campaign",
            subscriber.phone_number, campaign.id,
        )
        return None

    lead_data = config.get('lead_data', {})
    try:
        lead, _ = create_or_update_lead(
            campaign=crm_campaign,
            account=campaign.account,
            phone_number=subscriber.phone_number,
            email=lead_data.get('email'),
            lead_data=lead_data,
            lead_type=None,
        )
    except ValueError as e:
        logger.warning(f"link_lead_for_subscriber: {e}")
        return None

    subscriber.lead = lead
    subscriber.save()
    SmsSubscriberCampaignSubscription.objects.filter(
        subscriber=subscriber, campaign=campaign
    ).update(lead=lead)
    return lead


def enroll_subscriber_in_follow_up_nurturing(
    campaign: SmsKeywordCampaign,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    rule: Optional[SmsKeywordRule],
) -> Optional[Any]:
    """
    If campaign has follow_up_nurturing_campaign, get_or_create subscription and
    LeadNurturingParticipant with originating_subscription. Returns participant or None.
    """
    nurturing_campaign = getattr(campaign, 'follow_up_nurturing_campaign', None)
    if not nurturing_campaign:
        return None

    from external_models.models.nurturing_campaigns import LeadNurturingParticipant

    now = timezone.now()
    subscription, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
        subscriber=subscriber,
        campaign=campaign,
        defaults={
            'status': 'opted_in',
            'opted_in_at': now,
            'opt_in_message': message,
            'opt_in_rule': rule,
            'lead': subscriber.lead,
        },
    )
    update_fields = []
    if subscription.opt_in_rule_id is None and rule:
        subscription.opt_in_rule = rule
        subscription.opt_in_message = message or subscription.opt_in_message
        update_fields.extend(['opt_in_rule', 'opt_in_message'])
    elif subscription.opt_in_message_id is None and message:
        subscription.opt_in_message = message
        update_fields.append('opt_in_message')
    if subscription.lead_id is None and subscriber.lead_id:
        subscription.lead = subscriber.lead
        update_fields.append('lead')
    if update_fields:
        subscription.save(update_fields=update_fields)

    lead_for_participant = subscription.lead or subscriber.lead
    if not lead_for_participant:
        return None

    participant, created = LeadNurturingParticipant.objects.get_or_create(
        nurturing_campaign=nurturing_campaign,
        lead=lead_for_participant,
        defaults={
            'status': 'active',
            'originating_subscription': subscription,
        },
    )
    if not created and participant.originating_subscription_id is None:
        participant.originating_subscription = subscription
        participant.save(update_fields=['originating_subscription_id'])
    return participant


def get_welcome_message_for_opt_in(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    config: Dict[str, Any],
) -> Optional[str]:
    """Return welcome message body for opt-in (same priority as _get_welcome_message)."""
    return _get_welcome_message(campaign, rule, config)


def handle_route_to_agent(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle ROUTE_TO_AGENT action.
    
    Creates/retrieves Conversation for subscriber.
    Creates ConversationMessage for threading.
    Links SmsMessage to conversation.
    Routes to ACS conversation engine.
    """
    try:
        from external_models.models.communications import Conversation, ConversationMessage, Participant
        
        # Get or create conversation
        conversation_sid = f"SM_MKT_{subscriber.endpoint.id}_{subscriber.phone_number}"
        
        conversation, created = Conversation.objects.get_or_create(
            twilio_sid=conversation_sid,
            defaults={
                'channel': 'sms',
                'state': 'active',
                'lead': subscriber.lead,
                'messaging_service_sid': subscriber.endpoint.value,
                'account_sid': message.account_sid,  # Twilio Account SID from message
            }
        )
        
        # Update conversation if it already existed
        if not created:
            conversation.lead = subscriber.lead or conversation.lead
            conversation.state = 'active'
            conversation.save()
        
        # Get or create participant
        # Generate a unique participant SID if needed
        participant_sid = f"PN_{conversation.id}_{subscriber.phone_number[-4:]}"
        participant, _ = Participant.objects.get_or_create(
            conversation=conversation,
            phone_number=subscriber.phone_number,
            defaults={
                'participant_sid': participant_sid,
            }
        )
        
        # Create conversation message
        conversation_message = ConversationMessage.objects.create(
            conversation=conversation,
            participant=participant,
            body=message.body_raw,
            direction='inbound',
            channel='sms',
            message_sid=message.provider_message_id or f"SM_{message.id}",
            account_sid=message.account_sid,
            messaging_service_sid=message.messaging_service_sid,
            status='received',
        )
        
        # Link SmsMessage to conversation
        message.conversation = conversation
        message.conversation_message = conversation_message
        message.save()
        
        # TODO: Route to ACS conversation engine
        logger.info(f"Would route to ACS conversation engine (conversation_id={conversation.id})")
        
        # Create event log
        SmsCampaignEvent.objects.create(
            endpoint=subscriber.endpoint,
            campaign=campaign,
            rule=rule,
            subscriber=subscriber,
            message=message,
            event_type='message_received',
            payload={
                'action': 'route_to_agent',
                'conversation_id': conversation.id,
                'conversation_message_id': conversation_message.id,
            }
        )
        
        return ActionExecutionResult(
            success=True,
            message=f"Routed to agent (conversation_id={conversation.id})",
            data={
                'conversation_id': conversation.id,
                'conversation_message_id': conversation_message.id,
            }
        )
    except Exception as e:
        logger.exception(f"Error routing to agent: {str(e)}")
        return ActionExecutionResult(
            success=False,
            message=f"Error routing to agent: {str(e)}"
        )


def handle_composite(
    campaign: SmsKeywordCampaign,
    rule: SmsKeywordRule,
    subscriber: SmsSubscriber,
    message: SmsMessage,
    config: Dict[str, Any]
) -> ActionExecutionResult:
    """
    Handle COMPOSITE action.
    
    Executes multiple actions in sequence or parallel.
    config.actions: Array of {type, config} objects
    config.execution_mode: 'sequential' | 'parallel' (default: 'sequential')
    config.stop_on_error: bool (default: False)
    """
    actions = config.get('actions', [])
    if not actions:
        return ActionExecutionResult(
            success=False,
            message="COMPOSITE action requires 'actions' array with at least one action"
        )
    
    execution_mode = config.get('execution_mode', 'sequential')
    stop_on_error = config.get('stop_on_error', False)
    
    results = []
    errors = []
    
    if execution_mode == 'sequential':
        # Execute actions one by one
        for i, action_item in enumerate(actions):
            action_type = action_item.get('type')
            action_config = action_item.get('config', {})
            
            if not action_type:
                error_msg = f"Action {i+1} is missing 'type' field"
                errors.append(error_msg)
                if stop_on_error:
                    break
                continue
            
            # Create a temporary rule for this sub-action
            temp_rule = SmsKeywordRule(
                campaign=campaign,
                action_type=action_type,
                action_config=action_config
            )
            
            result = execute_action(
                campaign=campaign,
                rule=temp_rule,
                subscriber=subscriber,
                message=message,
                action_config=action_config
            )
            
            results.append({
                'index': i,
                'type': action_type,
                'success': result.success,
                'message': result.message,
            })
            
            if not result.success and stop_on_error:
                errors.append(f"Action {i+1} ({action_type}) failed: {result.message}")
                break
    else:
        # Parallel execution (simplified - in production would use async tasks)
        # For now, execute sequentially but log as parallel
        logger.warning("Parallel execution mode requested but executing sequentially (not yet implemented)")
        return handle_composite(campaign, rule, subscriber, message, {
            **config,
            'execution_mode': 'sequential'
        })
    
    # Create event log
    SmsCampaignEvent.objects.create(
        endpoint=subscriber.endpoint,
        campaign=campaign,
        rule=rule,
        subscriber=subscriber,
        message=message,
        event_type='message_received',
        payload={
            'action': 'composite',
            'execution_mode': execution_mode,
            'results': results,
            'errors': errors,
        }
    )
    
    success = len(errors) == 0
    return ActionExecutionResult(
        success=success,
        message=f"Composite action executed ({len(results)} actions, {len(errors)} errors)",
        data={
            'results': results,
            'errors': errors,
        }
    )


def _get_welcome_message(campaign: SmsKeywordCampaign, rule: SmsKeywordRule, config: Dict[str, Any]) -> Optional[str]:
    """
    Get welcome message based on priority:
    1. config.template_id (if set) - TODO: render template
    2. config.welcome_message (if set)
    3. rule.initial_reply (keyword-level default)
    4. campaign.welcome_message (campaign-level default)
    5. None (no message sent)
    """
    # Priority 1: template_id
    if config.get('template_id'):
        # TODO: Load and render template
        logger.info(f"Would render template (template_id={config['template_id']})")
        return None  # Placeholder
    
    # Priority 2: welcome_message in config
    if config.get('welcome_message'):
        return config['welcome_message']
    
    # Priority 3: keyword-level default
    if rule.initial_reply:
        return rule.initial_reply
    
    # Priority 4: campaign-level default
    if campaign.welcome_message:
        return campaign.welcome_message
    
    # No message
    return None
