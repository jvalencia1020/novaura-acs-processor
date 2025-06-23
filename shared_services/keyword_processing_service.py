import logging
from typing import Optional, Dict, Any
from django.db import transaction
from external_models.models.external_references import Lead
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant

logger = logging.getLogger(__name__)


class KeywordProcessingService:
    """
    Service for processing reserved keywords across different communication channels.
    Provides reusable methods for handling opt-outs, opt-ins, help requests, etc.
    """

    # Reserved keywords for communication processing
    RESERVED_KEYWORDS = {
        'STOP': 'opt_out',
        'STOPALL': 'opt_out_all',
        'START': 'opt_in',
        'HELP': 'help',
        'INFO': 'info',
        'YES': 'confirm',
        'NO': 'decline',
        'UNSUBSCRIBE': 'opt_out',
        'CANCEL': 'opt_out',
    }
    
    def __init__(self, message_sender=None):
        self.message_sender = message_sender
    
    def check_reserved_keywords(self, message_body: str) -> Optional[str]:
        """
        Check if message contains reserved keywords.
        
        Args:
            message_body: The message body to check
            
        Returns:
            Action to take or None if no reserved keyword found
        """
        if not message_body:
            return None
        
        # Normalize message for comparison
        normalized_message = message_body.strip().upper()
        
        for keyword, action in self.RESERVED_KEYWORDS.items():
            if normalized_message == keyword:
                return action
        
        return None
    
    def handle_reserved_keyword(self, action: str, lead: Optional[Lead], 
                              nurturing_campaign: Optional[LeadNurturingCampaign],
                              contact_info: str, message_body: str, channel: str = 'sms') -> bool:
        """
        Handle reserved keyword actions.
        
        Args:
            action: The action to take
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            contact_info: The contact information (phone, email, etc.)
            message_body: The original message body
            channel: The communication channel
            
        Returns:
            bool: True if action was handled successfully
        """
        logger.info(f"Processing reserved keyword: {message_body} -> {action}")
        
        try:
            if action == 'opt_out':
                return self._handle_opt_out(lead, nurturing_campaign, contact_info, channel)
            elif action == 'opt_out_all':
                return self._handle_opt_out_all(lead, contact_info, channel)
            elif action == 'opt_in':
                return self._handle_opt_in(lead, nurturing_campaign, contact_info, channel)
            elif action == 'help':
                return self._handle_help_request(lead, nurturing_campaign, contact_info, channel)
            elif action == 'info':
                return self._handle_info_request(lead, nurturing_campaign, contact_info, channel)
            elif action in ['confirm', 'decline']:
                return self._handle_confirmation(action, lead, nurturing_campaign, contact_info, channel)
            else:
                logger.warning(f"Unknown keyword action: {action}")
                return False
                
        except Exception as e:
            logger.error(f"Error handling reserved keyword {action}: {e}")
            return False
    
    def _handle_opt_out(self, lead: Optional[Lead], nurturing_campaign: Optional[LeadNurturingCampaign], 
                       contact_info: str, channel: str) -> bool:
        """
        Handle opt-out request.
        
        Args:
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            contact_info: The contact information
            channel: The communication channel
            
        Returns:
            bool: True if opt-out was successful
        """
        with transaction.atomic():
            if nurturing_campaign:
                # Opt out from specific campaign
                participant = LeadNurturingParticipant.objects.filter(
                    lead=lead,
                    nurturing_campaign=nurturing_campaign,
                    status__in=['active', 'paused']
                ).first()
                
                if participant:
                    try:
                        participant.opt_out()
                        logger.info(f"Successfully opted out {contact_info} from campaign {nurturing_campaign.name}")
                        
                        # Send opt-out confirmation message
                        if self.message_sender:
                            success = self.message_sender.send_opt_out_confirmation(contact_info, nurturing_campaign.name, channel)
                            if success:
                                logger.info(f"Sent opt-out confirmation to {contact_info}")
                            else:
                                logger.error(f"Failed to send opt-out confirmation to {contact_info}")
                        
                        return True
                        
                    except Exception as e:
                        logger.error(f"Error opting out from campaign: {e}")
                        return False
            else:
                # Opt out from all campaigns for this lead
                return self._handle_opt_out_all(lead, contact_info, channel)
        
        return False
    
    def _handle_opt_out_all(self, lead: Optional[Lead], contact_info: str, channel: str) -> bool:
        """
        Handle opt-out from all campaigns.
        
        Args:
            lead: The lead (if found)
            contact_info: The contact information
            channel: The communication channel
            
        Returns:
            bool: True if opt-out was successful
        """
        if not lead:
            logger.warning(f"Cannot opt out {contact_info} from all campaigns - no lead found")
            return False
        
        with transaction.atomic():
            active_participants = LeadNurturingParticipant.objects.filter(
                lead=lead,
                status__in=['active', 'paused']
            )
            
            success_count = 0
            for participant in active_participants:
                try:
                    participant.opt_out()
                    logger.info(f"Opted out {contact_info} from campaign {participant.nurturing_campaign.name}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"Error opting out from campaign {participant.nurturing_campaign.name}: {e}")
            
            # Send opt-out confirmation message for all campaigns
            if self.message_sender:
                success = self.message_sender.send_opt_out_confirmation(contact_info, channel=channel)
                if success:
                    logger.info(f"Sent opt-out confirmation to {contact_info}")
                else:
                    logger.error(f"Failed to send opt-out confirmation to {contact_info}")
            
            return success_count > 0
    
    def _handle_opt_in(self, lead: Optional[Lead], nurturing_campaign: Optional[LeadNurturingCampaign], 
                      contact_info: str, channel: str) -> bool:
        """
        Handle opt-in request.
        
        Args:
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            contact_info: The contact information
            channel: The communication channel
            
        Returns:
            bool: True if opt-in was successful
        """
        if not lead:
            logger.warning(f"Cannot opt in {contact_info} - no lead found")
            return False
        
        if nurturing_campaign:
            # Opt in to specific campaign
            participant, created = LeadNurturingParticipant.objects.get_or_create(
                lead=lead,
                nurturing_campaign=nurturing_campaign,
                defaults={'status': 'active'}
            )
            
            if not created and participant.status == 'opted_out':
                participant.status = 'active'
                participant.exited_campaign_at = None
                participant.save()
                logger.info(f"Successfully opted in {contact_info} to campaign {nurturing_campaign.name}")
                
                # Send opt-in confirmation message
                if self.message_sender:
                    success = self.message_sender.send_opt_in_confirmation(contact_info, nurturing_campaign.name, channel)
                    if success:
                        logger.info(f"Sent opt-in confirmation to {contact_info}")
                    else:
                        logger.error(f"Failed to send opt-in confirmation to {contact_info}")
                
                return True
        
        return False
    
    def _handle_help_request(self, lead: Optional[Lead], nurturing_campaign: Optional[LeadNurturingCampaign], 
                           contact_info: str, channel: str) -> bool:
        """
        Handle help request.
        
        Args:
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            contact_info: The contact information
            channel: The communication channel
            
        Returns:
            bool: True if help message was sent successfully
        """
        if self.message_sender:
            success = self.message_sender.send_help_message(contact_info, channel)
            if success:
                logger.info(f"Sent help message to {contact_info}")
                return True
            else:
                logger.error(f"Failed to send help message to {contact_info}")
                return False
        
        return False
    
    def _handle_info_request(self, lead: Optional[Lead], nurturing_campaign: Optional[LeadNurturingCampaign], 
                           contact_info: str, channel: str) -> bool:
        """
        Handle info request.
        
        Args:
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            contact_info: The contact information
            channel: The communication channel
            
        Returns:
            bool: True if info message was sent successfully
        """
        campaign_name = nurturing_campaign.name if nurturing_campaign else None
        
        if self.message_sender:
            success = self.message_sender.send_info_message(contact_info, campaign_name, channel)
            if success:
                logger.info(f"Sent info message to {contact_info}")
                return True
            else:
                logger.error(f"Failed to send info message to {contact_info}")
                return False
        
        return False
    
    def _handle_confirmation(self, action: str, lead: Optional[Lead], 
                           nurturing_campaign: Optional[LeadNurturingCampaign], 
                           contact_info: str, channel: str) -> bool:
        """
        Handle confirmation responses (YES/NO).
        
        Args:
            action: The action (confirm/decline)
            lead: The lead (if found)
            nurturing_campaign: The nurturing campaign (if found)
            contact_info: The contact information
            channel: The communication channel
            
        Returns:
            bool: True if confirmation was handled successfully
        """
        logger.info(f"Processing confirmation {action} from {contact_info}")
        
        # Here you would implement confirmation logic
        # This could trigger next steps in a journey or update lead status
        if action == 'confirm':
            # Handle positive confirmation
            logger.info(f"Positive confirmation received from {contact_info}")
            return True
        elif action == 'decline':
            # Handle negative confirmation
            logger.info(f"Negative confirmation received from {contact_info}")
            return True
        
        return False
    
    def get_keyword_help_text(self, channel: str = 'sms') -> str:
        """
        Get help text for reserved keywords.
        
        Args:
            channel: The communication channel
            
        Returns:
            str: Help text for keywords
        """
        if channel == 'sms':
            return (
                "Available commands:\n"
                "STOP - Opt out of this campaign\n"
                "STOPALL - Opt out of all campaigns\n"
                "START - Opt back in\n"
                "HELP - Show this help message\n"
                "INFO - Get campaign information\n"
                "YES/NO - Confirm or decline offers"
            )
        else:
            return (
                "Available commands:\n"
                "UNSUBSCRIBE - Opt out of this campaign\n"
                "HELP - Show this help message\n"
                "INFO - Get campaign information"
            ) 