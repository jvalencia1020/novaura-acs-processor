import logging
from typing import Optional, Dict, Any
from external_models.models.external_references import Lead
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant

logger = logging.getLogger(__name__)


class CampaignMatchingService:
    """
    Service for matching nurturing campaigns across different communication channels.
    Provides reusable methods for finding campaigns by various identifiers.
    """

    def find_nurturing_campaign_from_event(self, event_data: Dict[str, Any], lead: Optional[Lead]) -> Optional[LeadNurturingCampaign]:
        """
        Find nurturing campaign from event data using enhanced fields.
        
        Args:
            event_data: The event data
            lead: The lead (if found)
            
        Returns:
            LeadNurturingCampaign or None
        """
        # First try to get campaign by ID if provided
        campaign_id = event_data.get('nurturing_campaign_id')
        if campaign_id:
            try:
                return LeadNurturingCampaign.objects.get(id=campaign_id)
            except LeadNurturingCampaign.DoesNotExist:
                logger.warning(f"Nurturing campaign with ID {campaign_id} not found")
        
        # Try to get campaign participant by ID if provided
        participant_id = event_data.get('campaign_participant_id')
        if participant_id:
            try:
                participant = LeadNurturingParticipant.objects.get(id=participant_id)
                return participant.nurturing_campaign
            except LeadNurturingParticipant.DoesNotExist:
                logger.warning(f"Campaign participant with ID {participant_id} not found")
        
        # Try to get campaign by name if provided
        campaign_name = event_data.get('campaign_name')
        if campaign_name:
            campaign = self.get_campaign_by_name(campaign_name)
            if campaign:
                return campaign
        
        # Fallback to lead-based matching
        if lead:
            return self.find_campaign_by_lead(event_data, lead)
        
        return None
    
    def get_campaign_by_name(self, campaign_name: str) -> Optional[LeadNurturingCampaign]:
        """
        Find a nurturing campaign by name.
        
        Args:
            campaign_name: The campaign name to search for
            
        Returns:
            LeadNurturingCampaign or None
        """
        if not campaign_name:
            return None
        
        try:
            campaign = LeadNurturingCampaign.objects.filter(
                name__iexact=campaign_name,
                status='active'
            ).first()
            
            if campaign:
                return campaign
            
            logger.info(f"No active campaign found with name: {campaign_name}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding campaign by name {campaign_name}: {e}")
            return None
    
    def find_campaign_by_lead(self, event_data: Dict[str, Any], lead: Lead) -> Optional[LeadNurturingCampaign]:
        """
        Find nurturing campaign by lead and event context.
        
        Args:
            event_data: The event data
            lead: The lead
            
        Returns:
            LeadNurturingCampaign or None
        """
        if not lead:
            return None
        
        try:
            # Look for active campaign participants for this lead
            active_participants = LeadNurturingParticipant.objects.filter(
                lead=lead,
                status='active'
            ).select_related('nurturing_campaign')
            
            if not active_participants.exists():
                logger.info(f"No active campaign participants found for lead {lead.id}")
                return None
            
            # If multiple campaigns, try to determine the most relevant one
            if active_participants.count() > 1:
                return self._determine_most_relevant_campaign(active_participants, event_data)
            
            # Return the single active campaign
            return active_participants.first().nurturing_campaign
            
        except Exception as e:
            logger.error(f"Error finding campaign by lead {lead.id}: {e}")
            return None
    
    def _determine_most_relevant_campaign(self, participants, event_data: Dict[str, Any]) -> Optional[LeadNurturingCampaign]:
        """
        Determine the most relevant campaign when multiple are active.
        
        Args:
            participants: QuerySet of active participants
            event_data: The event data
            
        Returns:
            LeadNurturingCampaign or None
        """
        # Check for campaign type hints in event data
        campaign_type = event_data.get('campaign_type')
        if campaign_type:
            for participant in participants:
                if participant.nurturing_campaign.campaign_type == campaign_type:
                    return participant.nurturing_campaign
        
        # Check for channel hints
        channel = event_data.get('channel')
        if channel:
            for participant in participants:
                campaign = participant.nurturing_campaign
                if hasattr(campaign, f'{channel}_config') and getattr(campaign, f'{channel}_config'):
                    return campaign
        
        # Check for recent activity
        most_recent = participants.order_by('-last_event_at').first()
        if most_recent and most_recent.last_event_at:
            return most_recent.nurturing_campaign
        
        # Default to the first active campaign
        return participants.first().nurturing_campaign
    
    def get_campaign_participant(self, lead: Lead, campaign: LeadNurturingCampaign) -> Optional[LeadNurturingParticipant]:
        """
        Get the campaign participant for a lead and campaign.
        
        Args:
            lead: The lead
            campaign: The nurturing campaign
            
        Returns:
            LeadNurturingParticipant or None
        """
        if not lead or not campaign:
            return None
        
        try:
            return LeadNurturingParticipant.objects.filter(
                lead=lead,
                nurturing_campaign=campaign
            ).first()
            
        except Exception as e:
            logger.error(f"Error getting campaign participant for lead {lead.id} and campaign {campaign.id}: {e}")
            return None
    
    def get_active_campaigns_for_lead(self, lead: Lead) -> list:
        """
        Get all active campaigns for a lead.
        
        Args:
            lead: The lead
            
        Returns:
            List of active nurturing campaigns
        """
        if not lead:
            return []
        
        try:
            active_participants = LeadNurturingParticipant.objects.filter(
                lead=lead,
                status='active'
            ).select_related('nurturing_campaign')
            
            return [participant.nurturing_campaign for participant in active_participants]
            
        except Exception as e:
            logger.error(f"Error getting active campaigns for lead {lead.id}: {e}")
            return [] 