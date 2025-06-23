import logging
import re
from typing import Optional, Dict, Any
from external_models.models.external_references import Lead
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant

logger = logging.getLogger(__name__)


class LeadMatchingService:
    """
    Service for matching leads across different communication channels.
    Provides reusable methods for finding leads by various identifiers.
    """

    def get_lead_from_event(self, event_data: Dict[str, Any], fallback_identifier: str = None) -> Optional[Lead]:
        """
        Get lead from event data using enhanced fields.
        
        Args:
            event_data: The event data containing lead information
            fallback_identifier: Fallback identifier (phone, email, etc.)
            
        Returns:
            Lead or None
        """
        # First try to get lead by ID if provided
        lead_id = event_data.get('lead_id')
        if lead_id:
            try:
                return Lead.objects.get(id=lead_id)
            except Lead.DoesNotExist:
                logger.warning(f"Lead with ID {lead_id} not found")
        
        # Try to get lead by phone number from event
        lead_phone = event_data.get('lead_phone_number')
        if lead_phone:
            lead = self.get_lead_by_phone(lead_phone)
            if lead:
                return lead
        
        # Try to get lead by email from event
        lead_email = event_data.get('lead_email')
        if lead_email:
            lead = self.get_lead_by_email(lead_email)
            if lead:
                return lead
        
        # Fallback to identifier matching
        if fallback_identifier:
            return self.get_lead_by_identifier(fallback_identifier)
        
        return None
    
    def get_lead_by_phone(self, phone_number: str) -> Optional[Lead]:
        """
        Find a lead by phone number.
        
        Args:
            phone_number: The phone number to search for
            
        Returns:
            Lead or None
        """
        if not phone_number:
            return None
        
        # Clean phone number
        clean_phone = self.clean_phone_number(phone_number)
        
        try:
            # Search for lead by phone number
            lead = Lead.objects.filter(phone_number=clean_phone).first()
            if lead:
                return lead
            
            # If not found, you might want to create a new lead
            # This depends on your business logic
            logger.info(f"No lead found for phone number: {clean_phone}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding lead by phone {clean_phone}: {e}")
            return None
    
    def get_lead_by_email(self, email: str) -> Optional[Lead]:
        """
        Find a lead by email address.
        
        Args:
            email: The email address to search for
            
        Returns:
            Lead or None
        """
        if not email:
            return None
        
        try:
            # Search for lead by email
            lead = Lead.objects.filter(email__iexact=email).first()
            if lead:
                return lead
            
            logger.info(f"No lead found for email: {email}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding lead by email {email}: {e}")
            return None
    
    def get_lead_by_identifier(self, identifier: str) -> Optional[Lead]:
        """
        Find a lead by any identifier (phone, email, etc.).
        
        Args:
            identifier: The identifier to search for
            
        Returns:
            Lead or None
        """
        if not identifier:
            return None
        
        # Try phone number first
        if self._looks_like_phone(identifier):
            return self.get_lead_by_phone(identifier)
        
        # Try email
        if self._looks_like_email(identifier):
            return self.get_lead_by_email(identifier)
        
        # Try other fields
        try:
            lead = Lead.objects.filter(
                models.Q(first_name__icontains=identifier) |
                models.Q(last_name__icontains=identifier) |
                models.Q(company__icontains=identifier)
            ).first()
            
            if lead:
                return lead
            
            logger.info(f"No lead found for identifier: {identifier}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding lead by identifier {identifier}: {e}")
            return None
    
    def clean_phone_number(self, phone_number: str) -> str:
        """
        Clean a phone number for consistent formatting.
        
        Args:
            phone_number: The phone number to clean
            
        Returns:
            Cleaned phone number
        """
        if not phone_number:
            return ""
        
        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', phone_number)
        
        # Ensure it starts with +
        if not cleaned.startswith('+'):
            cleaned = '+' + cleaned
        
        return cleaned
    
    def _looks_like_phone(self, identifier: str) -> bool:
        """
        Check if an identifier looks like a phone number.
        
        Args:
            identifier: The identifier to check
            
        Returns:
            bool: True if it looks like a phone number
        """
        # Remove all non-digit characters
        digits = re.sub(r'[^\d]', '', identifier)
        
        # Check if it has 7-15 digits (reasonable phone number length)
        return 7 <= len(digits) <= 15
    
    def _looks_like_email(self, identifier: str) -> bool:
        """
        Check if an identifier looks like an email address.
        
        Args:
            identifier: The identifier to check
            
        Returns:
            bool: True if it looks like an email
        """
        # Simple email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_pattern, identifier)) 