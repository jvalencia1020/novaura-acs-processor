import logging
from django.utils import timezone
from django.db.models import Q

from external_models.models.nurturing_campaigns import LeadNurturingCampaign
from bulkcampaign_processor.services.bulk_campaign_processor import BulkCampaignProcessor

logger = logging.getLogger(__name__)

def process_bulk_campaigns():
    """
    Process all active bulk campaigns
    This should be run periodically by a scheduled task
    """
    logger.info("Starting bulk campaign processing")
    processor = BulkCampaignProcessor()
    processed_count = 0

    # Find all active bulk campaigns
    campaigns = LeadNurturingCampaign.objects.filter(
        Q(status='active') | Q(status='scheduled'),
        campaign_type__in=['drip', 'reminder', 'blast']
    ).select_related(
        'drip_schedule',
        'reminder_schedule',
        'blast_schedule'
    )

    logger.info(f"Found {campaigns.count()} active/scheduled campaigns to process")
    
    for campaign in campaigns:
        try:
            logger.info(f"Processing campaign {campaign.id} (type: {campaign.campaign_type}, status: {campaign.status})")
            
            # Log campaign details
            if campaign.campaign_type == 'drip':
                logger.info(f"Drip campaign {campaign.id} schedule: {campaign.drip_schedule}")
            elif campaign.campaign_type == 'reminder':
                logger.info(f"Reminder campaign {campaign.id} schedule: {campaign.reminder_schedule}")
            elif campaign.campaign_type == 'blast':
                logger.info(f"Blast campaign {campaign.id} schedule: {campaign.blast_schedule}")
            
            count = processor.process_campaign(campaign)
            processed_count += count
            logger.info(f"Successfully processed campaign {campaign.id}: {count} messages scheduled")
        except Exception as e:
            logger.exception(f"Error processing campaign {campaign.id}: {str(e)}")
            logger.error(f"Campaign details - Type: {campaign.campaign_type}, Status: {campaign.status}, Name: {campaign.name}")

    logger.info(f"Completed bulk campaign processing - Processed {processed_count} total messages across {campaigns.count()} campaigns")
    return processed_count

def process_due_messages():
    """
    Process all messages that are due to be sent
    This should be run frequently (e.g., every minute) by a scheduled task
    """
    processor = BulkCampaignProcessor()
    processed_count = processor.process_due_messages()
    return processed_count 