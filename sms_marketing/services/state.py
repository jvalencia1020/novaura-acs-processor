"""
Subscriber state machine for managing opt-in/opt-out state transitions.
"""
import logging
from typing import Optional, Dict
from django.utils import timezone
from django.db import transaction
from sms_marketing.models import (
    SmsSubscriber,
    SmsKeywordCampaign,
    SmsMessage,
    SmsSubscriberCampaignSubscription,
)

logger = logging.getLogger(__name__)


class SMSMarketingStateManager:
    """Manages subscriber state transitions"""
    
    @transaction.atomic
    def get_or_create_subscriber(self, endpoint, phone_number: str, sms_campaign_id: Optional[int] = None):
        """Get or create subscriber for endpoint + phone. Optionally set sms_campaign when known at creation/resolution time."""
        defaults = {'status': 'unknown'}
        if sms_campaign_id is not None:
            defaults['sms_campaign_id'] = sms_campaign_id
        subscriber, created = SmsSubscriber.objects.get_or_create(
            endpoint=endpoint,
            phone_number=phone_number,
            defaults=defaults
        )
        if not created and sms_campaign_id is not None and subscriber.sms_campaign_id is None:
            subscriber.sms_campaign_id = sms_campaign_id
            subscriber.save(update_fields=['sms_campaign_id'])
        return subscriber, created
    
    @transaction.atomic
    def update_last_inbound(self, subscriber: SmsSubscriber):
        """Update last inbound timestamp"""
        subscriber.last_inbound_at = timezone.now()
        subscriber.save(update_fields=['last_inbound_at'])
    
    @transaction.atomic
    def handle_opt_in(
        self,
        subscriber: SmsSubscriber,
        campaign: SmsKeywordCampaign,
        rule,
        opt_in_mode: str,  # 'single', 'double', 'none'
        keyword: str,
        message: Optional[SmsMessage] = None
    ) -> Dict:
        """
        Handle opt-in state transition.
        
        Returns:
            dict with status info: {'status': 'opted_in'|'pending_opt_in', 'confirmed': bool}
        """
        now = timezone.now()
        
        if opt_in_mode == 'none':
            # No state change, just log
            return {'status': subscriber.status, 'confirmed': False}
        
        elif opt_in_mode == 'single':
            # Immediate opt-in
            subscriber.status = 'opted_in'
            subscriber.opt_in_at = now
            subscriber.opt_in_source = 'keyword'
            subscriber.opt_in_keyword = keyword
            if message:
                subscriber.opt_in_message = message
            subscriber.last_inbound_at = now
            subscriber.sms_campaign = campaign
            subscriber.save()
            # Per-campaign subscription: one row per (subscriber, campaign)
            sub, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
                subscriber=subscriber,
                campaign=campaign,
                defaults={
                    'status': 'opted_in',
                    'opted_in_at': now,
                    'opt_in_message': message,
                },
            )
            if sub.status == 'opted_out':
                sub.opted_out_at = None
                sub.opt_out_message = None
            sub.status = 'opted_in'
            sub.opted_in_at = now
            sub.opt_in_message = message
            sub.save(update_fields=['status', 'opted_in_at', 'opt_in_message', 'opted_out_at', 'opt_out_message'])
            return {'status': 'opted_in', 'confirmed': True}

        elif opt_in_mode == 'double':
            # Set to pending, require confirmation
            subscriber.status = 'pending_opt_in'
            subscriber.opt_in_source = 'keyword'
            subscriber.opt_in_keyword = keyword
            subscriber.opt_in_at = None  # Not confirmed yet
            if message:
                subscriber.opt_in_message = message
            subscriber.last_inbound_at = now
            subscriber.sms_campaign = campaign
            subscriber.save()
            # Per-campaign subscription: pending until they reply YES (see handle_double_opt_in_confirmation)
            sub, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
                subscriber=subscriber,
                campaign=campaign,
                defaults={
                    'status': 'pending_opt_in',
                    'opted_in_at': now,
                    'opt_in_message': message,
                },
            )
            if sub.status == 'opted_out':
                sub.opted_out_at = None
                sub.opt_out_message = None
            sub.status = 'pending_opt_in'
            sub.opted_in_at = now
            sub.opt_in_message = message  # Always the initial START message that triggered the flow
            sub.save(update_fields=['status', 'opted_in_at', 'opt_in_message', 'opted_out_at', 'opt_out_message'])
            return {'status': 'pending_opt_in', 'confirmed': False}

        return {'status': subscriber.status, 'confirmed': False}
    
    @transaction.atomic
    def handle_double_opt_in_confirmation(self, subscriber: SmsSubscriber, campaign: SmsKeywordCampaign) -> bool:
        """
        Complete double opt-in confirmation (subscriber replied YES).
        Updates both the subscriber and the per-campaign subscription.
        opt_in_message stays the initial START message; opted_in_at can reflect confirmation time.
        """
        if subscriber.status != 'pending_opt_in':
            logger.warning(f"Subscriber {subscriber.id} not in pending_opt_in state")
            return False

        now = timezone.now()
        subscriber.status = 'opted_in'
        subscriber.opt_in_at = now
        subscriber.last_inbound_at = now
        subscriber.save()

        # Subscription row already exists with status='pending_opt_in' from initial opt-in
        try:
            sub = SmsSubscriberCampaignSubscription.objects.get(subscriber=subscriber, campaign=campaign)
            sub.status = 'opted_in'
            sub.opted_in_at = now  # When they confirmed (opt_in_message remains the START message)
            sub.save(update_fields=['status', 'opted_in_at'])
        except SmsSubscriberCampaignSubscription.DoesNotExist:
            logger.warning(
                f"No SmsSubscriberCampaignSubscription for subscriber={subscriber.id} campaign={campaign.id}; creating"
            )
            SmsSubscriberCampaignSubscription.objects.create(
                subscriber=subscriber,
                campaign=campaign,
                status='opted_in',
                opted_in_at=now,
            )
        return True
    
    @transaction.atomic
    def handle_opt_out(
        self,
        subscriber: SmsSubscriber,
        keyword: str,
        message: Optional[SmsMessage] = None,
        campaign: Optional[SmsKeywordCampaign] = None,
    ) -> Dict:
        """
        Handle opt-out state transition.
        Optionally update per-campaign subscriptions: current campaign's row gets opt_out_message;
        all subscriptions for this subscriber get status=opted_out and opted_out_at.
        subscriber.sms_campaign is left unchanged so we know which campaign they stopped from.
        """
        was_opted_in = subscriber.status == 'opted_in'
        now = timezone.now()

        # If user opts out while pending, clear pending opt-in fields (doc behavior).
        if subscriber.status == 'pending_opt_in':
            subscriber.opt_in_source = None
            subscriber.opt_in_keyword = None
            subscriber.opt_in_at = None
            subscriber.opt_in_message = None

        subscriber.status = 'opted_out'
        subscriber.opt_out_at = now
        subscriber.opt_out_source = 'keyword'
        if message:
            subscriber.opt_out_message = message
        subscriber.last_inbound_at = now
        # Do not clear subscriber.sms_campaign — keep for reference (which campaign they stopped from)
        subscriber.save()

        # Per-campaign subscriptions: mark all as opted_out; only current campaign row gets opt_out_message
        if campaign:
            sub, _ = SmsSubscriberCampaignSubscription.objects.get_or_create(
                subscriber=subscriber,
                campaign=campaign,
                defaults={
                    'status': 'opted_out',
                    'opted_in_at': now,
                    'opted_out_at': now,
                    'opt_out_message': message,
                },
            )
            sub.status = 'opted_out'
            sub.opted_out_at = now
            sub.opt_out_message = message
            sub.save(update_fields=['status', 'opted_out_at', 'opt_out_message'])

            # Global STOP: all other subscriptions for this subscriber get same opted_out_at, no opt_out_message
            other_subs = SmsSubscriberCampaignSubscription.objects.filter(
                subscriber=subscriber
            ).exclude(campaign=campaign)
            other_subs.update(status='opted_out', opted_out_at=now)
        else:
            # No campaign context (e.g. global STOP): mark all existing subscriptions as opted_out
            SmsSubscriberCampaignSubscription.objects.filter(subscriber=subscriber).update(
                status='opted_out', opted_out_at=now
            )

        return {'was_opted_in': was_opted_in}
    
    def is_confirmation_keyword(self, keyword: str, campaign: SmsKeywordCampaign) -> bool:
        """Check if keyword is a confirmation keyword for double opt-in"""
        # Default confirmation keywords
        default_confirmations = ['YES', 'Y', 'CONFIRM', 'OK']
        
        # Check campaign-specific confirmation keywords if configured
        # This would be in campaign metadata or config if needed
        # For now, use defaults
        confirmations = default_confirmations
        
        return keyword.upper() in [c.upper() for c in confirmations]

