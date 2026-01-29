"""
Router service for matching inbound SMS messages to campaigns and rules.
"""
import logging
from typing import Optional
from django.db.models import Q
from external_models.models.communications import ContactEndpoint
from sms_marketing.models import SmsKeywordCampaign, SmsKeywordRule, SmsSubscriber

logger = logging.getLogger(__name__)


class RouteResult:
    """Result of routing operation"""
    def __init__(self, campaign, rule, match_type: str, keyword_matched: str):
        self.campaign = campaign
        self.rule = rule
        self.match_type = match_type
        self.keyword_matched = keyword_matched


class SMSMarketingRouter:
    """Routes inbound SMS messages to appropriate campaigns and rules"""
    
    # Global compliance keywords (highest priority)
    GLOBAL_STOP_KEYWORDS = ['STOP', 'STOPALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT']
    GLOBAL_HELP_KEYWORDS = ['HELP', 'INFO']
    
    def route_inbound(
        self,
        endpoint: ContactEndpoint,
        from_number: str,
        body_normalized: str,
        subscriber: SmsSubscriber,
        campaign_hint: Optional[SmsKeywordCampaign] = None
    ) -> Optional[RouteResult]:
        """
        Route inbound message to campaign and rule.
        
        Args:
            endpoint: ContactEndpoint for the message
            from_number: Sender phone number
            body_normalized: Normalized message body
            subscriber: SmsSubscriber instance
            
        Returns:
            RouteResult or None if no match found
        """
        keyword_candidate = self._extract_keyword_candidate(body_normalized)
        
        # Check global compliance keywords first (highest priority)
        if self._is_global_stop_keyword(keyword_candidate):
            return RouteResult(
                campaign=None,
                rule=None,
                match_type='global_stop',
                keyword_matched=keyword_candidate
            )
        
        if self._is_global_help_keyword(keyword_candidate):
            return RouteResult(
                campaign=None,
                rule=None,
                match_type='global_help',
                keyword_matched=keyword_candidate
            )
        
        # Route to campaign/rule
        return self._route_to_campaign(endpoint, keyword_candidate, subscriber, campaign_hint=campaign_hint)
    
    def _route_to_campaign(
        self,
        endpoint: ContactEndpoint,
        keyword_candidate: str,
        subscriber: SmsSubscriber,
        campaign_hint: Optional[SmsKeywordCampaign] = None
    ) -> Optional[RouteResult]:
        """Route to campaign and rule based on keyword matching"""
        # Get eligible campaigns (active, matching endpoint, ordered by priority)
        campaigns_qs = SmsKeywordCampaign.objects.filter(
            endpoint=endpoint,
            status='active'
        ).order_by('-priority', 'id')

        # If webhook provided a campaign hint (e.g., query param sms_campaign_id), try it first.
        campaigns = list(campaigns_qs)
        if campaign_hint and getattr(campaign_hint, 'id', None):
            try:
                if campaign_hint.status == 'active' and campaign_hint.endpoint_id == endpoint.id:
                    campaigns = [campaign_hint] + [c for c in campaigns if c.id != campaign_hint.id]
            except Exception:
                # Be defensive: hint should never break routing.
                pass
        
        for campaign in campaigns:
            # Get active rules for this campaign
            rules = campaign.rules.filter(is_active=True).order_by('-priority', 'id')
            
            # Filter by subscriber status restrictions
            if subscriber.status == 'opted_out':
                rules = rules.filter(
                    Q(requires_not_opted_out=False) | Q(action_type='OPT_IN')
                )
            
            # Try exact matches first (highest priority)
            for rule in rules.filter(match_type='exact'):
                if self._matches_keyword(rule, keyword_candidate, 'exact'):
                    return RouteResult(campaign, rule, 'exact', rule.keyword.keyword)
            
            # Then starts_with
            for rule in rules.filter(match_type='starts_with'):
                if self._matches_keyword(rule, keyword_candidate, 'starts_with'):
                    return RouteResult(campaign, rule, 'starts_with', rule.keyword.keyword)
            
            # Finally contains
            for rule in rules.filter(match_type='contains'):
                if self._matches_keyword(rule, keyword_candidate, 'contains'):
                    return RouteResult(campaign, rule, 'contains', rule.keyword.keyword)
        
        return None
    
    def _matches_keyword(self, rule: SmsKeywordRule, keyword_candidate: str, match_type: str) -> bool:
        """Check if keyword matches rule"""
        keyword_text = rule.keyword.keyword.upper()
        candidate = keyword_candidate.upper()
        
        if match_type == 'exact':
            return candidate == keyword_text
        elif match_type == 'starts_with':
            return candidate.startswith(keyword_text)
        elif match_type == 'contains':
            return keyword_text in candidate
        
        return False
    
    def _extract_keyword_candidate(self, body_normalized: str) -> str:
        """Extract keyword candidate from normalized body"""
        # Be defensive: ensure whitespace is collapsed and casing normalized.
        return " ".join((body_normalized or "").upper().split())
    
    def _is_global_stop_keyword(self, keyword: str) -> bool:
        """Check if keyword is a global stop command"""
        return keyword in [k.upper() for k in self.GLOBAL_STOP_KEYWORDS]
    
    def _is_global_help_keyword(self, keyword: str) -> bool:
        """Check if keyword is a global help command"""
        return keyword in [k.upper() for k in self.GLOBAL_HELP_KEYWORDS]

