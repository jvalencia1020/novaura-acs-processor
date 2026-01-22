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
                except SmsMessage.DoesNotExist:
                    logger.error(f"SmsMessage {sms_message_id} not found")
                    return False
            else:
                # Create message from payload (fallback)
                message = self._create_message_from_payload(message_data)
            
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
            
            # Get or create subscriber
            subscriber, _ = self.state_manager.get_or_create_subscriber(
                endpoint, message.from_number
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
                campaigns = SmsKeywordCampaign.objects.filter(
                    endpoint=endpoint,
                    status='active'
                ).order_by('-priority', 'id')

                for campaign in campaigns:
                    if self.state_manager.is_confirmation_keyword(keyword_candidate, campaign):
                        # Complete double opt-in
                        self.state_manager.handle_double_opt_in_confirmation(subscriber, campaign)
                        # Send welcome message
                        # Find the rule that triggered the opt-in
                        rule = campaign.rules.filter(
                            keyword__keyword__iexact=subscriber.opt_in_keyword
                        ).first()
                        if rule:
                            action_config = rule.action_config or {}
                            self.action_executor._send_welcome_message(campaign, subscriber, action_config)
                        
                        # Update message with campaign/rule/subscriber links
                        message.sms_campaign = campaign  # Field name is sms_campaign
                        message.rule = rule
                        message.subscriber = subscriber
                        message.processing_status = 'processed'  # Use 'processed' not 'completed'
                        message.processed_at = timezone.now()
                        message.save(update_fields=['sms_campaign', 'rule', 'subscriber', 'processing_status', 'processed_at'])
                        
                        # Log event
                        self._log_event(
                            endpoint, campaign, rule, subscriber, message,
                            'opt_in', {'confirmed': True, 'opt_in_keyword': subscriber.opt_in_keyword}
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
            route_result = self.router.route_inbound(
                endpoint, message.from_number, message.body_normalized or message.body_raw, subscriber
            )
            
            if not route_result:
                # No match - handle fallback
                return self._handle_fallback(endpoint, subscriber, message)
            
            # Handle global commands
            if route_result.match_type == 'global_stop':
                return self._handle_global_opt_out(subscriber, message, endpoint)
            
            if route_result.match_type == 'global_help':
                return self._handle_global_help(subscriber, message, endpoint)
            
            # Update message with campaign/rule/subscriber links
            message.sms_campaign = route_result.campaign  # Field name is sms_campaign
            message.rule = route_result.rule
            message.subscriber = subscriber
            message.save()
            
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
                        'error', {'reason': 'subscriber_opted_out'}
                    )
                    return True  # Processed, but blocked
            
            # Execute action
            action_config = route_result.rule.action_config or {}
            execution_result = self.action_executor.execute_action(
                route_result.campaign,
                route_result.rule,
                subscriber,
                message,
                action_config
            )
            
            # Log event
            self._log_event(
                endpoint, route_result.campaign, route_result.rule, subscriber, message,
                execution_result.event_type, execution_result.payload
            )
            
            # Mark as processed if successful
            if execution_result.success:
                message.processing_status = 'processed'  # Use 'processed' not 'completed'
                message.processed_at = timezone.now()
                message.save(update_fields=['processing_status', 'processed_at'])
            else:
                message.processing_status = 'failed'
                message.processed_at = timezone.now()
                message.error = execution_result.error or 'Action execution failed'
                message.save(update_fields=['processing_status', 'processed_at', 'error'])
            
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
        return body.upper().strip()
    
    def _handle_global_opt_out(self, subscriber: SmsSubscriber, message: SmsMessage, endpoint: ContactEndpoint) -> bool:
        """Handle global STOP command"""
        from sms_marketing.services.state import SMSMarketingStateManager
        state_manager = SMSMarketingStateManager()
        
        keyword = self._extract_keyword_candidate(message.body_normalized or message.body_raw)
        result = state_manager.handle_opt_out(subscriber, keyword)
        
        # Update message with subscriber link
        message.subscriber = subscriber
        message.processing_status = 'processed'  # Use 'processed' not 'completed'
        message.processed_at = timezone.now()
        message.save(update_fields=['subscriber', 'processing_status', 'processed_at'])
        
        # Send opt-out confirmation
        opt_out_text = "You have been unsubscribed. You will no longer receive messages."
        self.action_executor._send_message(subscriber.phone_number, opt_out_text, endpoint.value)
        
        # Log event
        self._log_event(
            endpoint, None, None, subscriber, message,
            'opt_out', {
                'opt_out_source': 'keyword',
                'opt_out_keyword': keyword,
                'was_opted_in': result['was_opted_in']
            }
        )
        
        return True
    
    def _handle_global_help(self, subscriber: SmsSubscriber, message: SmsMessage, endpoint: ContactEndpoint) -> bool:
        """Handle global HELP command"""
        help_text = "Reply STOP to opt out. Reply HELP for more information."
        self.action_executor._send_message(subscriber.phone_number, help_text, endpoint.value)
        
        # Update message with subscriber link and mark as completed
        message.subscriber = subscriber
        message.processing_status = 'completed'
        message.processed_at = timezone.now()
        message.save(update_fields=['subscriber', 'processing_status', 'processed_at'])
        
        # Log event
        self._log_event(
            endpoint, None, None, subscriber, message,
            'message_sent', {'message_type': 'help', 'help_text': help_text}
        )
        
        return True
    
    def _handle_fallback(self, endpoint: ContactEndpoint, subscriber: SmsSubscriber, message: SmsMessage) -> bool:
        """Handle fallback when no rule matches"""
        # Get campaigns for this endpoint
        # Use direct model manager query (same pattern as router.py) for consistency
        campaigns = SmsKeywordCampaign.objects.filter(
            endpoint=endpoint,
            status='active'
        ).order_by('-priority', 'id')
        
        logger.debug(
            f"Fallback: Found {campaigns.count()} active campaigns for endpoint {endpoint.id} "
            f"(endpoint value: {endpoint.value})"
        )
        
        if campaigns.count() == 0:
            logger.warning(
                f"No active campaigns found for endpoint {endpoint.id}. "
                f"Total campaigns for endpoint: {SmsKeywordCampaign.objects.filter(endpoint=endpoint).count()}, "
                f"Active campaigns: {SmsKeywordCampaign.objects.filter(endpoint=endpoint, status='active').count()}"
            )
        
        for campaign in campaigns:
            if campaign.fallback_action_type:
                # Execute fallback action
                # Create a temporary rule for fallback
                class FallbackRule:
                    def __init__(self, action_type, action_config):
                        self.action_type = action_type
                        self.action_config = action_config or {}
                        self.keyword = type('Keyword', (), {'keyword': ''})()
                
                fallback_rule = FallbackRule(campaign.fallback_action_type, campaign.fallback_action_config)
                
                execution_result = self.action_executor.execute_action(
                    campaign, fallback_rule, subscriber, message, campaign.fallback_action_config or {}
                )
                
                # Update message with campaign/subscriber links
                message.sms_campaign = campaign  # Field name is sms_campaign, not campaign
                message.subscriber = subscriber
                
                # Mark as completed or failed based on execution result
                if execution_result.success:
                    message.processing_status = 'processed'  # Use 'processed' not 'completed'
                    message.processed_at = timezone.now()
                    message.save(update_fields=['sms_campaign', 'subscriber', 'processing_status', 'processed_at'])
                else:
                    message.processing_status = 'failed'
                    message.processed_at = timezone.now()
                    message.error = execution_result.error or 'Fallback action failed'
                    message.save(update_fields=['campaign', 'subscriber', 'processing_status', 'processed_at', 'error'])
                
                # Log event
                self._log_event(
                    endpoint, campaign, None, subscriber, message,
                    execution_result.event_type, {
                        **execution_result.payload,
                        'fallback': True,
                        'reason': 'no_keyword_match'
                    }
                )
                
                return execution_result.success
        
        # No fallback configured - mark as processed (no action needed)
        message.subscriber = subscriber
        message.processing_status = 'processed'  # Use 'processed' not 'completed'
        message.processed_at = timezone.now()
        message.save(update_fields=['subscriber', 'processing_status', 'processed_at'])
        
        # Log event
        self._log_event(
            endpoint, None, None, subscriber, message,
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
                    'normalized_body': message.body_normalized if message else None,
                    'subscriber_status_before': getattr(subscriber, '_status_before', None),
                    'subscriber_status_after': subscriber.status if subscriber else None,
                }
            )
        except Exception as e:
            logger.error(f"Failed to log event: {e}")

