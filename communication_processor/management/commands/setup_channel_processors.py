import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import Count

from communication_processor.models import ChannelProcessor, SQSMessage
from communication_processor.services.processor_factory import ProcessorFactory


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Set up channel processor configurations'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--channel',
            type=str,
            help='Set up a specific channel (e.g., sms, email)'
        )
        parser.add_argument(
            '--queue-url',
            type=str,
            help='SQS Queue URL for the channel'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Batch size for processing'
        )
        parser.add_argument(
            '--visibility-timeout',
            type=int,
            default=300,
            help='SQS visibility timeout in seconds'
        )
        parser.add_argument(
            '--max-retries',
            type=int,
            default=3,
            help='Maximum retry attempts'
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all channel configurations'
        )
        parser.add_argument(
            '--delete',
            type=str,
            help='Delete a channel configuration'
        )
        parser.add_argument(
            '--enable',
            type=str,
            help='Enable a channel processor'
        )
        parser.add_argument(
            '--disable',
            type=str,
            help='Disable a channel processor'
        )
        parser.add_argument(
            '--cleanup-messages',
            action='store_true',
            help='Clean up old failed messages'
        )
        parser.add_argument(
            '--cleanup-days',
            type=int,
            default=7,
            help='Number of days for cleanup (default: 7)'
        )
    
    def handle(self, *args, **options):
        if options['list']:
            self._list_configurations()
            return
        
        if options['delete']:
            self._delete_configuration(options['delete'])
            return
        
        if options['enable']:
            self._enable_channel(options['enable'])
            return
        
        if options['disable']:
            self._disable_channel(options['disable'])
            return
        
        if options['cleanup_messages']:
            self._cleanup_messages(options['cleanup_days'])
            return
        
        if options['channel']:
            self._setup_channel(
                options['channel'],
                options['queue_url'],
                options['batch_size'],
                options['visibility_timeout'],
                options['max_retries']
            )
        else:
            self._setup_default_channels()
    
    def _list_configurations(self):
        """List all channel configurations."""
        self.stdout.write('Channel Processor Configurations:')
        self.stdout.write('=' * 50)
        
        configs = ChannelProcessor.objects.all().order_by('channel_type')
        
        if not configs:
            self.stdout.write(self.style.WARNING('No configurations found'))
            return
        
        for config in configs:
            status = 'ACTIVE' if config.is_active else 'INACTIVE'
            self.stdout.write(
                f'{config.channel_type.upper()}: {status}'
            )
            self.stdout.write(f'  Queue URL: {config.queue_url}')
            self.stdout.write(f'  Batch Size: {config.batch_size}')
            self.stdout.write(f'  Visibility Timeout: {config.visibility_timeout}s')
            self.stdout.write(f'  Max Retries: {config.max_retries}')
            self.stdout.write('')
    
    def _delete_configuration(self, channel_type: str):
        """Delete a channel configuration."""
        try:
            config = ChannelProcessor.objects.get(channel_type=channel_type)
            config.delete()
            self.stdout.write(
                self.style.SUCCESS(f'Deleted configuration for {channel_type}')
            )
        except ChannelProcessor.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Configuration not found for {channel_type}')
            )
    
    def _enable_channel(self, channel_type: str):
        """Enable a channel processor."""
        try:
            config = ChannelProcessor.objects.get(channel_type=channel_type)
            config.is_active = True
            config.save()
            self.stdout.write(
                self.style.SUCCESS(f'Enabled {channel_type} processor')
            )
        except ChannelProcessor.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Configuration not found for {channel_type}')
            )
    
    def _disable_channel(self, channel_type: str):
        """Disable a channel processor."""
        try:
            config = ChannelProcessor.objects.get(channel_type=channel_type)
            config.is_active = False
            config.save()
            self.stdout.write(
                self.style.SUCCESS(f'Disabled {channel_type} processor')
            )
        except ChannelProcessor.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Configuration not found for {channel_type}')
            )
    
    def _setup_channel(self, channel_type: str, queue_url: str, batch_size: int, 
                      visibility_timeout: int, max_retries: int):
        """Set up a specific channel configuration."""
        if not queue_url:
            self.stdout.write(
                self.style.ERROR('Queue URL is required')
            )
            return
        
        # Validate channel type
        supported_channels = ProcessorFactory.get_supported_channels()
        if channel_type not in supported_channels:
            self.stdout.write(
                self.style.ERROR(f'Unsupported channel type: {channel_type}')
            )
            self.stdout.write(f'Supported channels: {", ".join(supported_channels)}')
            return
        
        # Create or update configuration
        config, created = ChannelProcessor.objects.update_or_create(
            channel_type=channel_type,
            defaults={
                'queue_url': queue_url,
                'batch_size': batch_size,
                'visibility_timeout': visibility_timeout,
                'max_retries': max_retries,
                'is_active': True,
                'processor_class': f'communication_processor.services.{channel_type}_processor.{channel_type.title()}Processor'
            }
        )
        
        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(f'{action} configuration for {channel_type}')
        )
    
    def _setup_default_channels(self):
        """Set up default channel configurations."""
        self.stdout.write('Setting up default channel configurations...')
        
        # Get queue URLs from environment or settings
        default_configs = {
            'sms': {
                'queue_url': getattr(settings, 'SMS_QUEUE_URL', ''),
                'batch_size': 10,
                'visibility_timeout': 300,
                'max_retries': 3
            },
            'email': {
                'queue_url': getattr(settings, 'EMAIL_QUEUE_URL', ''),
                'batch_size': 10,
                'visibility_timeout': 300,
                'max_retries': 3
            }
        }
        
        for channel_type, config in default_configs.items():
            if config['queue_url']:
                self._setup_channel(
                    channel_type,
                    config['queue_url'],
                    config['batch_size'],
                    config['visibility_timeout'],
                    config['max_retries']
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'No queue URL configured for {channel_type}')
                )
        
        self.stdout.write(
            self.style.SUCCESS('Default channel setup completed')
        )
    
    def _cleanup_messages(self, days_old: int):
        """Clean up old failed messages."""
        from datetime import timedelta
        from django.utils import timezone
        
        cutoff_date = timezone.now() - timedelta(days=days_old)
        
        # Clean up old failed messages
        old_failed_messages = SQSMessage.objects.filter(
            status='failed',
            received_at__lt=cutoff_date
        )
        
        count = old_failed_messages.count()
        if count > 0:
            old_failed_messages.delete()
            self.stdout.write(
                self.style.SUCCESS(f'Cleaned up {count} old failed messages older than {days_old} days')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'No old failed messages found older than {days_old} days')
            )
        
        # Also clean up duplicate messages (keep the most recent one)
        from django.db.models import Max
        
        duplicates = SQSMessage.objects.values('message_id').annotate(
            max_id=Max('id')
        ).filter(
            message_id__in=SQSMessage.objects.values('message_id').annotate(
                count=Count('id')
            ).filter(count__gt=1).values_list('message_id', flat=True)
        )
        
        duplicate_count = 0
        for duplicate in duplicates:
            # Delete all but the most recent record for each message_id
            old_records = SQSMessage.objects.filter(
                message_id=duplicate['message_id']
            ).exclude(
                id=duplicate['max_id']
            )
            duplicate_count += old_records.count()
            old_records.delete()
        
        if duplicate_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f'Cleaned up {duplicate_count} duplicate message records')
            )
        else:
            self.stdout.write(
                self.style.WARNING('No duplicate message records found')
            ) 