from django.core.management.base import BaseCommand
from bulkcampaign_processor.tasks.bulk_campaign_tasks import process_bulk_campaigns
import logging
import os

logger = logging.getLogger('bulkcampaign_processor')

class Command(BaseCommand):
    help = 'Manually process all active bulk campaigns'

    def handle(self, *args, **options):
        # Disable profiling
        os.environ['PYDEVD_DISABLE_FILE_VALIDATION'] = '1'
        
        try:
            process_bulk_campaigns()
            self.stdout.write(self.style.SUCCESS('Successfully processed bulk campaigns'))
        except Exception as e:
            logger.error(f"Error processing bulk campaigns: {str(e)}")
            self.stdout.write(self.style.ERROR(f'Error processing bulk campaigns: {str(e)}')) 