import time
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from communication_processor.services.processor_factory import ProcessorFactory
from communication_processor.models import ChannelProcessor


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the communication processor for all active channels'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--channel',
            type=str,
            help='Process only a specific channel (e.g., sms, email)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Number of messages to process in each batch'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Interval between processing cycles in seconds'
        )
        parser.add_argument(
            '--max-cycles',
            type=int,
            default=None,
            help='Maximum number of processing cycles to run'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without actually processing messages (for testing)'
        )
    
    def handle(self, *args, **options):
        channel = options['channel']
        batch_size = options['batch_size']
        interval = options['interval']
        max_cycles = options['max_cycles']
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No messages will be processed')
            )
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting communication processor...')
        )
        
        if channel:
            self.stdout.write(f'Processing channel: {channel}')
        else:
            self.stdout.write('Processing all active channels')
        
        cycle_count = 0
        
        try:
            while True:
                if max_cycles and cycle_count >= max_cycles:
                    self.stdout.write(f'Reached maximum cycles ({max_cycles})')
                    break
                
                cycle_count += 1
                self.stdout.write(f'Processing cycle {cycle_count}...')
                
                if channel:
                    # Process single channel
                    self._process_channel(channel, batch_size, dry_run)
                else:
                    # Process all active channels
                    self._process_all_channels(batch_size, dry_run)
                
                if not dry_run:
                    self.stdout.write(f'Sleeping for {interval} seconds...')
                    time.sleep(interval)
                else:
                    self.stdout.write('Dry run completed')
                    break
                    
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING('\nStopping communication processor...')
            )
        except Exception as e:
            logger.error(f'Error in communication processor: {e}')
            self.stdout.write(
                self.style.ERROR(f'Error: {e}')
            )
    
    def _process_channel(self, channel_type: str, batch_size: int, dry_run: bool):
        """
        Process messages for a specific channel.
        
        Args:
            channel_type: The channel type to process
            batch_size: Number of messages to process
            dry_run: Whether to run in dry run mode
        """
        try:
            processor = ProcessorFactory.get_processor(channel_type)
            if not processor:
                self.stdout.write(
                    self.style.ERROR(f'No processor found for channel: {channel_type}')
                )
                return
            
            if dry_run:
                # Simulate processing
                self.stdout.write(f'[DRY RUN] Would process {batch_size} messages for {channel_type}')
                return
            
            stats = processor.process_messages(batch_size)
            
            self.stdout.write(
                f'{channel_type}: Processed {stats["processed"]}, '
                f'Failed {stats["failed"]}, Deleted {stats["deleted"]}'
            )
            
        except Exception as e:
            logger.error(f'Error processing channel {channel_type}: {e}')
            self.stdout.write(
                self.style.ERROR(f'Error processing {channel_type}: {e}')
            )
    
    def _process_all_channels(self, batch_size: int, dry_run: bool):
        """
        Process messages for all active channels.
        
        Args:
            batch_size: Number of messages to process per channel
            dry_run: Whether to run in dry run mode
        """
        try:
            processors = ProcessorFactory.get_all_processors()
            
            if not processors:
                self.stdout.write(
                    self.style.WARNING('No active processors found')
                )
                return
            
            total_stats = {
                'processed': 0,
                'failed': 0,
                'deleted': 0
            }
            
            for channel_type, processor in processors.items():
                try:
                    if dry_run:
                        self.stdout.write(f'[DRY RUN] Would process {batch_size} messages for {channel_type}')
                        continue
                    
                    stats = processor.process_messages(batch_size)
                    
                    # Accumulate stats
                    for key in total_stats:
                        total_stats[key] += stats[key]
                    
                    self.stdout.write(
                        f'{channel_type}: Processed {stats["processed"]}, '
                        f'Failed {stats["failed"]}, Deleted {stats["deleted"]}'
                    )
                    
                except Exception as e:
                    logger.error(f'Error processing channel {channel_type}: {e}')
                    self.stdout.write(
                        self.style.ERROR(f'Error processing {channel_type}: {e}')
                    )
            
            if not dry_run:
                self.stdout.write(
                    f'Total: Processed {total_stats["processed"]}, '
                    f'Failed {total_stats["failed"]}, Deleted {total_stats["deleted"]}'
                )
            
        except Exception as e:
            logger.error(f'Error processing all channels: {e}')
            self.stdout.write(
                self.style.ERROR(f'Error processing all channels: {e}')
            ) 