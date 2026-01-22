"""
Scheduled task to process pending SMS messages from database.
Run this periodically (e.g., every 5 minutes) as a safety net for messages
that weren't queued to SQS or got stuck.

This is part of the hybrid approach:
- Worker checks database when SQS is empty (immediate recovery)
- This scheduled task catches older stuck messages (safety net)
"""
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from sms_marketing.models import SmsMessage
from sms_marketing.services.processor import SMSMarketingProcessor

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process pending SMS messages from database (scheduled fallback mechanism)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of messages to process (default: 50)'
        )
        parser.add_argument(
            '--age-minutes',
            type=int,
            default=5,
            help='Only process messages older than this many minutes (default: 5)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without actually processing'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        age_minutes = options['age_minutes']
        dry_run = options['dry_run']
        
        processor = SMSMarketingProcessor()
        
        # Find messages that are pending and older than specified age
        cutoff_time = timezone.now() - timezone.timedelta(minutes=age_minutes)
        
        pending_messages = SmsMessage.objects.filter(
            processing_status='pending',
            direction='inbound',
            created_at__lt=cutoff_time
        ).order_by('created_at')[:limit]
        
        count = pending_messages.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No pending messages found'))
            return
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN: Would process {count} pending message(s)'))
            self.stdout.write(f'Messages older than {age_minutes} minutes:')
            for msg in pending_messages:
                age = timezone.now() - msg.created_at
                self.stdout.write(
                    f'  - ID {msg.id}: {msg.from_number} → {msg.to_number} '
                    f'(age: {age.total_seconds() / 60:.1f} minutes)'
                )
            return
        
        self.stdout.write(f'Processing {count} pending message(s)...')
        self.stdout.write(f'Messages older than {age_minutes} minutes will be processed\n')
        
        success_count = 0
        fail_count = 0
        
        for msg in pending_messages:
            try:
                # Prepare message data as if it came from SQS
                message_data = {
                    'sms_message_id': msg.id,
                    'message_sid': msg.provider_message_id,
                    'from_number': msg.from_number,
                    'to_number': msg.to_number,
                    'body': msg.body_raw,
                    'body_normalized': msg.body_normalized,
                    'endpoint_id': msg.endpoint.id if msg.endpoint else None,
                }
                
                with transaction.atomic():
                    success = processor.process_inbound_message(message_data)
                
                if success:
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✓ Processed message {msg.id}'))
                else:
                    fail_count += 1
                    self.stdout.write(self.style.WARNING(f'  ✗ Failed to process message {msg.id}'))
                    
            except Exception as e:
                fail_count += 1
                logger.exception(f"Error processing message {msg.id}: {e}")
                self.stdout.write(self.style.ERROR(f'  ✗ Error processing message {msg.id}: {e}'))
        
        self.stdout.write(self.style.SUCCESS(
            f'\nCompleted: {success_count} succeeded, {fail_count} failed'
        ))
        
        if fail_count > 0:
            self.stdout.write(self.style.WARNING(
                f'\n{fail_count} message(s) failed to process. Check logs for details.'
            ))
