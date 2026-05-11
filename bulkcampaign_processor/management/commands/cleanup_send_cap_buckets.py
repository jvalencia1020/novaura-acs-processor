import logging

from django.core.management.base import BaseCommand

from bulkcampaign_processor.tasks.cleanup_send_cap_buckets import cleanup_send_cap_buckets

logger = logging.getLogger('bulkcampaign_processor')


class Command(BaseCommand):
    help = 'Delete aged nurturing send-cap bucket rows (see RETENTION_BY_PERIOD in cleanup task).'

    def handle(self, *args, **options):
        try:
            n = cleanup_send_cap_buckets()
            self.stdout.write(self.style.SUCCESS(f'Deleted {n} send-cap bucket row(s)'))
        except Exception as e:
            logger.exception('cleanup_send_cap_buckets command failed')
            self.stdout.write(self.style.ERROR(str(e)))
