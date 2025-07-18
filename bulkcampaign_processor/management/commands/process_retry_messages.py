from django.core.management.base import BaseCommand
from bulkcampaign_processor.tasks.bulk_campaign_tasks import process_retry_messages
import logging

logger = logging.getLogger('bulkcampaign_processor')

class Command(BaseCommand):
    help = 'Manually process all retry messages for bulk campaigns'

    def handle(self, *args, **options):
        try:
            processed_count = process_retry_messages()
            self.stdout.write(self.style.SUCCESS(f'Successfully processed {processed_count} retry messages'))
        except Exception as e:
            logger.error(f"Error processing retry messages: {str(e)}")
            self.stdout.write(self.style.ERROR(f'Error processing retry messages: {str(e)}')) 