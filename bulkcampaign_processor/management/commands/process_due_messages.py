from django.core.management.base import BaseCommand
from bulkcampaign_processor.tasks.bulk_campaign_tasks import process_due_messages, process_retry_messages
import logging

logger = logging.getLogger('bulkcampaign_processor')

class Command(BaseCommand):
    help = 'Manually process all due messages for bulk campaigns'

    def add_arguments(self, parser):
        parser.add_argument(
            '--retry-only',
            action='store_true',
            help='Only process retry messages',
        )

    def handle(self, *args, **options):
        try:
            if options['retry_only']:
                processed_count = process_retry_messages()
                self.stdout.write(self.style.SUCCESS(f'Successfully processed {processed_count} retry messages'))
            else:
                processed_count = process_due_messages()
                self.stdout.write(self.style.SUCCESS(f'Successfully processed {processed_count} due messages'))
        except Exception as e:
            logger.error(f"Error processing messages: {str(e)}")
            self.stdout.write(self.style.ERROR(f'Error processing messages: {str(e)}')) 