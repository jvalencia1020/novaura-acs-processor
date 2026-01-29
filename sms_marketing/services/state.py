"""
Subscriber state machine for managing opt-in/opt-out state transitions.
"""
import logging
from typing import Optional, Dict
from django.utils import timezone
from django.db import transaction
from sms_marketing.models import SmsSubscriber, SmsKeywordCampaign, SmsMessage

logger = logging.getLogger(__name__)


class SMSMarketingStateManager:
    """Manages subscriber state transitions"""
    
    @transaction.atomic
    def get_or_create_subscriber(self, endpoint, phone_number: str):
        """Get or create subscriber for endpoint + phone"""
        subscriber, created = SmsSubscriber.objects.get_or_create(
            endpoint=endpoint,
            phone_number=phone_number,
            defaults={'status': 'unknown'}
        )
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
            subscriber.save()
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
            subscriber.save()
            return {'status': 'pending_opt_in', 'confirmed': False}
        
        return {'status': subscriber.status, 'confirmed': False}
    
    @transaction.atomic
    def handle_double_opt_in_confirmation(self, subscriber: SmsSubscriber, campaign: SmsKeywordCampaign) -> bool:
        """Complete double opt-in confirmation"""
        if subscriber.status != 'pending_opt_in':
            logger.warning(f"Subscriber {subscriber.id} not in pending_opt_in state")
            return False
        
        subscriber.status = 'opted_in'
        subscriber.opt_in_at = timezone.now()
        subscriber.last_inbound_at = timezone.now()
        subscriber.save()
        return True
    
    @transaction.atomic
    def handle_opt_out(self, subscriber: SmsSubscriber, keyword: str, message: Optional[SmsMessage] = None) -> Dict:
        """Handle opt-out state transition"""
        was_opted_in = subscriber.status == 'opted_in'

        # If user opts out while pending, clear pending opt-in fields (doc behavior).
        if subscriber.status == 'pending_opt_in':
            subscriber.opt_in_source = None
            subscriber.opt_in_keyword = None
            subscriber.opt_in_at = None
            subscriber.opt_in_message = None
        
        subscriber.status = 'opted_out'
        subscriber.opt_out_at = timezone.now()
        subscriber.opt_out_source = 'keyword'
        if message:
            subscriber.opt_out_message = message
        subscriber.last_inbound_at = timezone.now()
        subscriber.save()
        
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

