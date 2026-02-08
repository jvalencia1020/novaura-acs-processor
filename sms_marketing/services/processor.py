"""
Main processor for SMS marketing messages.
"""
import logging
import json
import boto3
from typing import Dict, Any, Optional
from django.utils import timezone
from django.db import transaction
from external_models.models.communications import ContactEndpoint
from sms_marketing.models import SmsMessage, SmsSubscriber, SmsCampaignEvent, SmsKeywordCampaign
from sms_marketing.services.router import SMSMarketingRouter
from sms_marketing.services.state import SMSMarketingStateManager
from sms_marketing.services.actions import SMSMarketingActionExecutor

logger = logging.getLogger(__name__)


class SMSMarketingProcessor:
    """Processes inbound SMS marketing messages from SQS"""
    
    def __init__(self):
        self.router = SMSMarketingRouter()
        self.state_manager = SMSMarketingStateManager()
        self.action_executor = SMSMarketingActionExecutor()
    
    def process_inbound_message(self, message_data: Dict[str, Any]) -> bool:
        """
        Process an inbound SMS marketing message.
        
        Args:
            message_data: Message data from SQS (or S3 reference)
            
        Returns:
            bool: True if processing succeeded
        """
        message = None
        try:
            # Load SmsMessage from database if ID provided
            sms_message_id = message_data.get('sms_message_id')
            if sms_message_id:
                try:
                    message = SmsMessage.objects.get(id=sms_message_id)
                    logger.info(
                        f"Processing SmsMessage {sms_message_id} from database: "
                        f"from={message.from_number}, to={message.to_number}, "
                        f"body='{message.body_raw}', normalized='{message.body_normalized}'"
                    )
                except SmsMessage.DoesNotExist:
                    logger.error(f"SmsMessage {sms_message_id} not found")
                    return False
            else:
                # Create message from payload (fallback)
                message = self._create_message_from_payload(message_data)
                logger.info(
                    f"Created SmsMessage {message.id} from payload: "
                    f"from={message.from_number}, to={message.to_number}, body='{message.body_raw}'"
                )
            
            # Set processing status to 'processing' when we start
            message.processing_status = 'processing'
            message.save(update_fields=['processing_status'])
            
            # Get endpoint
            endpoint = message.endpoint
            if not endpoint:
                logger.error(f"Message {message.id} has no endpoint")
                message.processing_status = 'failed'
                message.error = 'No endpoint found'
                message.save(update_fields=['processing_status', 'error'])
                return False
            
            # Get or create subscriber (pass campaign when webhook provides it)
            subscriber, _ = self.state_manager.get_or_create_subscriber(
                endpoint, message.from_number, sms_campaign_id=message.sms_campaign_id
            )
            
            # Update last inbound timestamp
            self.state_manager.update_last_inbound(subscriber)
            
            # Extract keyword candidate
            keyword_candidate = self._extract_keyword_candidate(message.body_normalized or message.body_raw)
            
            # Check for double opt-in confirmation first
            if subscriber.status == 'pending_opt_in':
                # Check if this is a confirmation keyword
                # We need to find the campaign that triggered the pending state
                # For now, check all active campaigns for this endpoint
                # Use direct model manager query (same pattern as router.py) for consistency
                campaigns_qs = SmsKeywordCampaign.objects.filter(
                    endpoint=endpoint,
                    status='active'
                ).order_by('-priority', 'id')

                campaigns = list(campaigns_qs)
                # If webhook provided a campaign hint (sms_campaign_id), try it first.
                if message.sms_campaign_id and message.sms_campaign:
                    try:
                        hinted = message.sms_campaign
                        if hinted.status == 'active' and hinted.endpoint_id == endpoint.id:
                            campaigns = [hinted] + [c for c in campaigns if c.id != hinted.id]
                    except Exception:
                        pass

                for campaign in campaigns:
                    if self.state_manager.is_confirmation_keyword(keyword_candidate, campaign):
                        # Complete double opt-in
                        self.state_manager.handle_double_opt_in_confirmation(subscriber, campaign)
                        # Find the rule that triggered the opt-in (for action_config and welcome message)
                        rule = campaign.rules.filter(
                            keyword__keyword__iexact=subscriber.opt_in_keyword
                        ).first()
                        action_config = (rule.action_config or {}) if rule else {}
                        # Link/create lead so we can enroll in follow-up nurturing campaign
                        self.action_executor._link_or_create_lead(subscriber, campaign, action_config)
                        # Enroll in follow-up nurturing campaign (drip/reminder/blast) if linked
                        self.action_executor._enroll_in_follow_up_nurturing_campaign_if_applicable(
                            campaign, subscriber, message
                        )
                        if rule:
                            self.action_executor._send_welcome_message(campaign, rule, subscriber, action_config)
                        
                        # Update message with campaign/rule/subscriber links
                        message.sms_campaign = campaign  # Field name is sms_campaign
                        message.rule = rule
                        message.subscriber = subscriber
                        message.processing_status = 'processed'  # Use 'processed' not 'completed'
                        message.processed_at = timezone.now()
                        message.save(update_fields=['sms_campaign', 'rule', 'subscriber', 'processing_status', 'processed_at'])
                        if subscriber.sms_campaign_id != campaign.id:
                            subscriber.sms_campaign = campaign
                            subscriber.save(update_fields=['sms_campaign_id'])
                        
                        # Log event
                        self._log_event(
                            endpoint, campaign, rule, subscriber, message,
                            'opt_in',
                            {
                                'confirmed': True,
                                'opt_in_keyword': subscriber.opt_in_keyword,
                                'rule_id': rule.id if rule else None,
                            }
                        )
                        return True
                else:
                    # Not a confirmation keyword, ignore
                    logger.info(f"Subscriber {subscriber.id} in pending_opt_in, ignoring non-confirmation keyword")
                    message.processing_status = 'skipped'
                    message.processed_at = timezone.now()
                    message.subscriber = subscriber
                    message.save(update_fields=['processing_status', 'processed_at', 'subscriber'])
                    return True
            
            # Route message
            keyword_candidate = self._extract_keyword_candidate(message.body_normalized or message.body_raw)
            logger.info(f"Routing message {message.id} with keyword candidate: '{keyword_candidate}'")

            campaign_hint = message.sms_campaign if message.sms_campaign_id else None
            route_result = self.router.route_inbound(
                endpoint,
                message.from_number,
                message.body_normalized or message.body_raw,
                subscriber,
                campaign_hint=campaign_hint,
            )
            
            if not route_result:
                # No match - handle fallback
                logger.info(f"No route found for message {message.id}, handling fallback")
                return self._handle_fallback(endpoint, subscriber, message)
            
            # Handle global commands
            if route_result.match_type == 'global_stop':
                return self._handle_global_opt_out(subscriber, message, endpoint)
            
            if route_result.match_type == 'global_help':
                return self._handle_global_help(subscriber, message, endpoint)
            
            # Update message with campaign/rule/subscriber links
            campaign = route_result.campaign
            message.sms_campaign = campaign  # Field name is sms_campaign
            message.rule = route_result.rule
            message.subscriber = subscriber
            message.save()
            if subscriber.sms_campaign_id != campaign.id:
                subscriber.sms_campaign = campaign
                subscriber.save(update_fields=['sms_campaign_id'])

            # Audit: keyword matched a rule (doc event type)
            self._log_event(
                endpoint,
                route_result.campaign,
                route_result.rule,
                subscriber,
                message,
                'keyword_matched',
                {
                    'keyword_candidate': keyword_candidate,
                    'keyword_matched': route_result.keyword_matched,
                    'match_type': route_result.match_type,
                    'selected_rule_id': route_result.rule.id if route_result.rule else None,
                }
            )
            
            # Check subscriber status restrictions
            if subscriber.status == 'opted_out' and route_result.rule.requires_not_opted_out:
                if route_result.rule.action_type != 'OPT_IN':
                    # Blocked - subscriber opted out
                    message.processing_status = 'skipped'
                    message.processed_at = timezone.now()
                    message.error = 'Subscriber opted out'
                    message.save(update_fields=['processing_status', 'processed_at', 'error'])
                    
                    self._log_event(
                        endpoint, route_result.campaign, route_result.rule, subscriber, message,
                        'error',
                        {
                            'reason': 'subscriber_opted_out',
                            'keyword_candidate': keyword_candidate,
                            'selected_rule_id': route_result.rule.id if route_result.rule else None,
                        }
                    )
                    return True  # Processed, but blocked
            
            # Execute action
            logger.info(
                f"Executing action '{route_result.rule.action_type}' for message {message.id} "
                f"(campaign: {route_result.campaign.id}, rule: {route_result.rule.id})"
            )
            action_config = route_result.rule.action_config or {}
            execution_result = self.action_executor.execute_action(
                route_result.campaign,
                route_result.rule,
                subscriber,
                message,
                action_config
            )
            
            logger.info(
                f"Action execution result for message {message.id}: "
                f"success={execution_result.success}, event_type={execution_result.event_type}"
            )
            if not execution_result.success:
                logger.warning(
                    f"Action execution failed for message {message.id}: {execution_result.error}"
                )
            
            # Audit: rule was triggered (doc event type)
            self._log_event(
                endpoint,
                route_result.campaign,
                route_result.rule,
                subscriber,
                message,
                'rule_triggered',
                {
                    'keyword_candidate': keyword_candidate,
                    'selected_rule_id': route_result.rule.id if route_result.rule else None,
                    'rule_id': route_result.rule.id if route_result.rule else None,
                    'action_type': route_result.rule.action_type if route_result.rule else None,
                    'success': execution_result.success,
                    'execution_event_type': execution_result.event_type,
                    'execution_payload': execution_result.payload,
                    'error': execution_result.error,
                }
            )

            # Log event
            self._log_event(
                endpoint, route_result.campaign, route_result.rule, subscriber, message,
                execution_result.event_type,
                {
                    **(execution_result.payload or {}),
                    'keyword_candidate': keyword_candidate,
                    'selected_rule_id': route_result.rule.id if route_result.rule else None,
                }
            )
            
            # Mark as processed if successful
            if execution_result.success:
                message.processing_status = 'processed'  # Use 'processed' not 'completed'
                message.processed_at = timezone.now()
                message.save(update_fields=['processing_status', 'processed_at'])
                logger.info(f"Message {message.id} marked as processed successfully")
            else:
                message.processing_status = 'failed'
                message.processed_at = timezone.now()
                message.error = execution_result.error or 'Action execution failed'
                message.save(update_fields=['processing_status', 'processed_at', 'error'])
                logger.error(f"Message {message.id} marked as failed: {message.error}")
            
            return execution_result.success
            
        except Exception as e:
            logger.exception(f"Error processing inbound message: {e}")
            # Update message status on error
            if message:
                try:
                    message.processing_status = 'failed'
                    message.error = str(e)
                    message.processed_at = timezone.now()
                    message.save(update_fields=['processing_status', 'error', 'processed_at'])
                except Exception as save_error:
                    logger.error(f"Failed to update message status on error: {save_error}")
            
            # Try to log error event
            try:
                if message:
                    self._log_event(
                        message.endpoint if hasattr(message, 'endpoint') else None,
                        None, None, None, message,
                        'error', {'error': str(e)}
                    )
            except:
                pass
            return False
    
    def _create_message_from_payload(self, message_data: Dict[str, Any]) -> SmsMessage:
        """Create SmsMessage from SQS payload (fallback)"""
        # This should rarely be needed if webhook creates message first
        endpoint_id = message_data.get('endpoint_id')
        endpoint = ContactEndpoint.objects.get(id=endpoint_id) if endpoint_id else None
        
        message = SmsMessage.objects.create(
            endpoint=endpoint,
            provider='twilio',
            provider_message_id=message_data.get('message_sid'),
            direction='inbound',
            status='received',
            processing_status='pending',  # Start as pending
            from_number=message_data.get('from_number'),
            to_number=message_data.get('to_number'),
            body_raw=message_data.get('body'),
            body_normalized=message_data.get('body_normalized'),
            received_at=timezone.now()
        )
        return message
    
    def _extract_keyword_candidate(self, body: str) -> str:
        """Extract keyword candidate from message body"""
        if not body:
            return ""
        # Normalize casing and collapse whitespace per design doc.
        return " ".join(body.upper().split())
    
    def _handle_global_opt_out(self, subscriber: SmsSubscriber, message: SmsMessage, endpoint: ContactEndpoint) -> bool:
        """Handle global STOP command"""
        from sms_marketing.services.state import SMSMarketingStateManager
        state_manager = SMSMarketingStateManager()

        campaign_context = self._get_campaign_context_for_global_command(endpoint, message)

        keyword = self._extract_keyword_candidate(message.body_normalized or message.body_raw)
        result = state_manager.handle_opt_out(
            subscriber, keyword, message=message, campaign=campaign_context
        )
        
        # Update message with subscriber link
        message.subscriber = subscriber
        if campaign_context and not message.sms_campaign_id:
            message.sms_campaign = campaign_context
            if subscriber.sms_campaign_id != campaign_context.id:
                subscriber.sms_campaign = campaign_context
                subscriber.save(update_fields=['sms_campaign_id'])
        message.processing_status = 'processed'  # Use 'processed' not 'completed'
        message.processed_at = timezone.now()
        message.save(update_fields=['subscriber', 'sms_campaign', 'processing_status', 'processed_at'])
        
        # Send opt-out confirmation
        opt_out_text = (
            getattr(campaign_context, 'opt_out_message', None)
            if campaign_context else None
        ) or "You have been unsubscribed. You will no longer receive messages."
        self.action_executor._send_message(
            subscriber=subscriber,
            campaign=campaign_context,
            body=opt_out_text,
            rule=None,
            message_type='opt_out',
        )
        
        # Log event
        self._log_event(
            endpoint, campaign_context, None, subscriber, message,
            'opt_out', {
                'opt_out_source': 'keyword',
                'opt_out_keyword': keyword,
                'was_opted_in': result['was_opted_in'],
                'keyword_candidate': keyword,
            }
        )
        
        return True
    
    def _handle_global_help(self, subscriber: SmsSubscriber, message: SmsMessage, endpoint: ContactEndpoint) -> bool:
        """Handle global HELP command"""
        campaign_context = self._get_campaign_context_for_global_command(endpoint, message)
        help_text = (
            getattr(campaign_context, 'help_text', None)
            if campaign_context else None
        ) or (
            (campaign_context.program.help_text if campaign_context and campaign_context.program else None)
        ) or "Reply STOP to opt out. Reply HELP for more information."

        self.action_executor._send_message(
            subscriber=subscriber,
            campaign=campaign_context,
            body=help_text,
            rule=None,
            message_type='help',
        )
        
        # Update message with subscriber link
        message.subscriber = subscriber
        if campaign_context and not message.sms_campaign_id:
            message.sms_campaign = campaign_context
            if subscriber.sms_campaign_id != campaign_context.id:
                subscriber.sms_campaign = campaign_context
                subscriber.save(update_fields=['sms_campaign_id'])
        message.processing_status = 'processed'
        message.processed_at = timezone.now()
        message.save(update_fields=['subscriber', 'sms_campaign', 'processing_status', 'processed_at'])
        
        # Log event
        self._log_event(
            endpoint, campaign_context, None, subscriber, message,
            'message_sent',
            {
                'message_type': 'help',
                'help_text': help_text,
                'keyword_candidate': self._extract_keyword_candidate(message.body_normalized or message.body_raw),
            }
        )
        
        return True

    def _get_campaign_context_for_global_command(
        self,
        endpoint: ContactEndpoint,
        message: SmsMessage
    ) -> Optional[SmsKeywordCampaign]:
        """
        Best-effort campaign context for global commands (HELP/STOP).
        If webhook provided sms_campaign_id, use it; otherwise use highest-priority active campaign for endpoint.
        """
        try:
            if message.sms_campaign_id and message.sms_campaign:
                hinted = message.sms_campaign
                if hinted.status == 'active' and hinted.endpoint_id == endpoint.id:
                    return hinted
        except Exception:
            pass

        return SmsKeywordCampaign.objects.filter(
            endpoint=endpoint,
            status='active'
        ).order_by('-priority', 'id').first()
    
    def _handle_fallback(self, endpoint: ContactEndpoint, subscriber: SmsSubscriber, message: SmsMessage) -> bool:
        """Handle fallback when no rule matches"""
        # Always link subscriber for auditability.
        message.subscriber = subscriber

        # Non-opted-in handling (endpoint-level SMS settings).
        # If sender is not opted in and no valid opt-in/keyword path applies (we're in fallback),
        # reply using endpoint.sms_settings (template -> message -> else no-op).
        if subscriber.status != 'opted_in':
            sms_settings = getattr(endpoint, 'sms_settings', None)
            reply_body = None
            used_template = False
            template_id = None

            if sms_settings:
                template = getattr(sms_settings, 'not_opted_in_default_reply_template', None)
                if template and getattr(template, 'channel', None) == 'sms':
                    try:
                        context = {
                            'lead': getattr(subscriber, 'lead', None),
                            'subscriber': subscriber,
                            'endpoint': endpoint,
                            'account': getattr(endpoint, 'account', None),
                            'campaign': None,
                            'keyword': {
                                'keyword': None,
                                'endpoint_value': getattr(endpoint, 'value', None),
                            },
                        }
                        reply_body = template.replace_variables(context)
                        used_template = True
                        template_id = getattr(template, 'id', None)
                    except Exception as e:
                        logger.warning(f"Failed to render endpoint not-opted-in reply template for endpoint {endpoint.id}: {e}")
                        reply_body = None
                        used_template = False
                        template_id = None

                if not reply_body:
                    reply_body = getattr(sms_settings, 'not_opted_in_default_reply_message', None)

            if reply_body:
                # Apply variable replacement for plain text replies too.
                success, outbound_sms = self.action_executor._send_message(
                    subscriber=subscriber,
                    campaign=None,
                    body=reply_body,
                    rule=None,
                    message_type='not_opted_in_default_reply',
                )

                if success:
                    message.processing_status = 'processed'
                    message.processed_at = timezone.now()
                    message.save(update_fields=['subscriber', 'processing_status', 'processed_at'])
                else:
                    message.processing_status = 'failed'
                    message.processed_at = timezone.now()
                    message.error = 'Not-opted-in default reply failed'
                    message.save(update_fields=['subscriber', 'processing_status', 'processed_at', 'error'])

                self._log_event(
                    endpoint,
                    None,
                    None,
                    subscriber,
                    message,
                    'message_sent' if success else 'error',
                    {
                        'fallback': True,
                        'fallback_type': 'endpoint_not_opted_in_reply',
                        'reason': 'no_keyword_match',
                        'message_type': 'not_opted_in_default_reply',
                        'used_template': used_template,
                        'template_id': template_id,
                        'sms_message_id': getattr(outbound_sms, 'id', None) if outbound_sms else None,
                    }
                )
                return success

            # No endpoint-level reply configured: no-op (or generic help later if desired).
            message.processing_status = 'processed'
            message.processed_at = timezone.now()
            message.save(update_fields=['subscriber', 'processing_status', 'processed_at'])
            self._log_event(
                endpoint, None, None, subscriber, message,
                'message_received', {'fallback': False, 'reason': 'no_keyword_match', 'not_opted_in': True}
            )
            return True

        # Opted-in handling (campaign-level opted-in fallback -> campaign fallback action).
        # Deterministic campaign selection:
        # - if webhook hinted a campaign (message.sms_campaign_id), prefer it (if active for endpoint)
        # - else choose highest priority active campaign for endpoint
        campaign = None
        try:
            if message.sms_campaign_id and message.sms_campaign:
                hinted = message.sms_campaign
                if hinted.status == 'active' and hinted.endpoint_id == endpoint.id:
                    campaign = hinted
        except Exception:
            pass

        if not campaign:
            campaign = SmsKeywordCampaign.objects.filter(
                endpoint=endpoint,
                status='active'
            ).order_by('-priority', 'id').first()

        if not campaign:
            logger.info(
                f"No active campaigns found for endpoint {endpoint.id}; "
                f"marking message {message.id} as processed (no action)"
            )
            message.processing_status = 'processed'
            message.processed_at = timezone.now()
            message.save(update_fields=['subscriber', 'processing_status', 'processed_at'])
            self._log_event(
                endpoint, None, None, subscriber, message,
                'message_received', {'fallback': False, 'reason': 'no_keyword_match'}
            )
            return True

        # Link message to chosen campaign for auditability.
        message.sms_campaign = campaign
        if subscriber.sms_campaign_id != campaign.id:
            subscriber.sms_campaign = campaign
            subscriber.save(update_fields=['sms_campaign_id'])

        rendered_body = None
        used_template = False
        template_id = None

        try:
            template = getattr(campaign, 'opted_in_fallback_template', None)
            if template:
                context = {
                    'lead': getattr(subscriber, 'lead', None),
                    'campaign': campaign,
                    'subscriber': subscriber,
                    # Optional keyword context for templates (doc suggestion)
                    'keyword': {
                        'keyword': None,
                        'endpoint_value': getattr(endpoint, 'value', None),
                    },
                    'account': getattr(campaign, 'account', None),
                }
                rendered_body = template.replace_variables(context)
                used_template = True
                template_id = getattr(template, 'id', None)
        except Exception as e:
            logger.warning(f"Failed to render opted-in fallback template for campaign {campaign.id}: {e}")
            rendered_body = None
            used_template = False
            template_id = None

        if not rendered_body:
            rendered_body = getattr(campaign, 'opted_in_fallback_message', None)

        if rendered_body:
            # Apply variable replacement for plain text replies too (templates are already rendered).
            success, outbound_sms = self.action_executor._send_message(
                subscriber=subscriber,
                campaign=campaign,
                body=rendered_body,
                rule=None,
                message_type='opted_in_fallback',
            )

            if success:
                message.processing_status = 'processed'
                message.processed_at = timezone.now()
                message.save(update_fields=['sms_campaign', 'subscriber', 'processing_status', 'processed_at'])
            else:
                message.processing_status = 'failed'
                message.processed_at = timezone.now()
                message.error = 'Opted-in fallback reply failed'
                message.save(update_fields=['sms_campaign', 'subscriber', 'processing_status', 'processed_at', 'error'])

            self._log_event(
                endpoint,
                campaign,
                None,
                subscriber,
                message,
                'message_sent' if success else 'error',
                {
                    'fallback': True,
                    'fallback_type': 'opted_in_reply',
                    'reason': 'no_keyword_match',
                    'message_type': 'opted_in_fallback',
                    'used_template': used_template,
                    'template_id': template_id,
                    'sms_message_id': getattr(outbound_sms, 'id', None) if outbound_sms else None,
                }
            )
            return success

        # If no opted-in fallback reply was used, fall back to campaign fallback action (if any)
        if campaign.fallback_action_type:
            logger.info(
                f"Executing fallback action '{campaign.fallback_action_type}' for message {message.id} "
                f"(campaign: {campaign.id})"
            )

            # Create a temporary rule-like object for fallback execution
            class FallbackRule:
                def __init__(self, action_type, action_config):
                    self.action_type = action_type
                    self.action_config = action_config or {}
                    self.keyword = type('Keyword', (), {'keyword': ''})()

            fallback_rule = FallbackRule(campaign.fallback_action_type, campaign.fallback_action_config)
            execution_result = self.action_executor.execute_action(
                campaign, fallback_rule, subscriber, message, campaign.fallback_action_config or {}
            )

            logger.info(
                f"Fallback action result for message {message.id}: "
                f"success={execution_result.success}, event_type={execution_result.event_type}"
            )

            if execution_result.success:
                message.processing_status = 'processed'
                message.processed_at = timezone.now()
                message.save(update_fields=['sms_campaign', 'subscriber', 'processing_status', 'processed_at'])
            else:
                message.processing_status = 'failed'
                message.processed_at = timezone.now()
                message.error = execution_result.error or 'Fallback action failed'
                message.save(update_fields=['sms_campaign', 'subscriber', 'processing_status', 'processed_at', 'error'])
                logger.error(
                    f"Fallback action failed for message {message.id}, campaign {campaign.id}: "
                    f"{execution_result.error}"
                )

            self._log_event(
                endpoint,
                campaign,
                None,
                subscriber,
                message,
                execution_result.event_type,
                {
                    **(execution_result.payload or {}),
                    'fallback': True,
                    'reason': 'no_keyword_match',
                }
            )
            return execution_result.success

        # No fallback configured - mark as processed (no action needed)
        logger.info(
            f"No fallback configured for endpoint {endpoint.id}, campaign {campaign.id}; "
            f"marking message {message.id} as processed (no action)"
        )
        message.processing_status = 'processed'
        message.processed_at = timezone.now()
        message.save(update_fields=['sms_campaign', 'subscriber', 'processing_status', 'processed_at'])
        self._log_event(
            endpoint, campaign, None, subscriber, message,
            'message_received', {'fallback': False, 'reason': 'no_keyword_match'}
        )
        return True
    
    def _log_event(
        self,
        endpoint: ContactEndpoint,
        campaign,
        rule,
        subscriber: SmsSubscriber,
        message: SmsMessage,
        event_type: str,
        payload: Dict[str, Any]
    ):
        """Create SmsCampaignEvent log"""
        try:
            SmsCampaignEvent.objects.create(
                endpoint=endpoint,
                campaign=campaign,
                rule=rule,
                subscriber=subscriber,
                message=message,
                event_type=event_type,
                payload={
                    **payload,
                    'provider': message.provider if message else None,
                    'provider_message_id': message.provider_message_id if message else None,
                    'raw_body': message.body_raw if message else None,
                    'normalized_body': message.body_normalized if message else None,
                    'webhook_query_params': message.webhook_query_params if message else None,
                    'subscriber_status_before': getattr(subscriber, '_status_before', None),
                    'subscriber_status_after': subscriber.status if subscriber else None,
                }
            )
        except Exception as e:
            logger.error(f"Failed to log event: {e}")

