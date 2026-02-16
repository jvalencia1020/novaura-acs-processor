"""
Reprocess failed SMS messages from the database.
Use after fixing transient issues (e.g. provider/API outages) to retry messages
that previously failed processing.

Run manually or on a schedule (e.g. after process_pending_sms_messages).
"""
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from sms_marketing.models import SmsMessage
from sms_marketing.services.processor import SMSMarketingProcessor

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reprocess failed inbound SMS messages from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of messages to reprocess (default: 50)'
        )
        parser.add_argument(
            '--age-minutes',
            type=int,
            default=None,
            help='Only reprocess messages that failed at least this many minutes ago (default: no filter)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be reprocessed without actually processing'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        age_minutes = options['age_minutes']
        dry_run = options['dry_run']

        processor = SMSMarketingProcessor()

        qs = SmsMessage.objects.filter(
            processing_status='failed',
            direction='inbound',
        ).order_by('processed_at')

        if age_minutes is not None:
            cutoff = timezone.now() - timezone.timedelta(minutes=age_minutes)
            qs = qs.filter(processed_at__lt=cutoff)

        messages = list(qs[:limit])
        count = len(messages)

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No failed messages found to reprocess'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: Would reprocess {count} failed message(s)'
            ))
            for msg in messages:
                age = f', failed {msg.processed_at}' if msg.processed_at else ''
                self.stdout.write(
                    f'  - ID {msg.id}: {msg.from_number} → {msg.to_number} '
                    f'(error: {msg.error or "—"}){age}'
                )
            return

        self.stdout.write(f'Reprocessing {count} failed message(s)...\n')

        success_count = 0
        fail_count = 0

        for msg in messages:
            try:
                message_data = {
                    'sms_message_id': msg.id,
                    'message_sid': msg.provider_message_id,
                    'from_number': msg.from_number,
                    'to_number': msg.to_number,
                    'body': msg.body_raw,
                    'body_normalized': msg.body_normalized,
                    'endpoint_id': msg.endpoint_id,
                }
                if msg.sms_campaign_id:
                    message_data['sms_campaign_id'] = msg.sms_campaign_id

                with transaction.atomic():
                    success = processor.process_inbound_message(message_data)

                if success:
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✓ Reprocessed message {msg.id}'))
                else:
                    fail_count += 1
                    self.stdout.write(self.style.WARNING(f'  ✗ Failed again message {msg.id}'))

            except Exception as e:
                fail_count += 1
                logger.exception(f"Error reprocessing message {msg.id}: {e}")
                self.stdout.write(self.style.ERROR(f'  ✗ Error reprocessing message {msg.id}: {e}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nCompleted: {success_count} succeeded, {fail_count} failed'
        ))
        if fail_count > 0:
            self.stdout.write(self.style.WARNING(
                f'\n{fail_count} message(s) failed again. Check logs for details.'
            ))
