from django.core.management.base import BaseCommand
from django.conf import settings
import time
import signal
import sys
import logging
from typing import Dict, Any

from communication_processor.services.processor_factory import ProcessorFactory
from communication_processor.models import ChannelProcessor

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Runs the SQS worker for communication processing'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, sig, frame):
        logger.info('Shutting down communication processor worker...')
        self.stdout.write(self.style.WARNING('Shutting down communication processor worker...'))
        self.running = False

    def handle(self, *args, **options):
        logger.info('Starting Communication Processor Worker')
        self.stdout.write(self.style.SUCCESS('Starting Communication Processor Worker'))
        
        worker_type = options.get('worker_type', 'all')
        
        if worker_type == 'sms':
            self._run_sms_worker()
        elif worker_type == 'email':
            self._run_email_worker()
        else:
            self._run_all_workers()

    def _run_all_workers(self):
        """Run the main worker that processes all channels."""
        while self.running:
            try:
                # Get all active processors from the database
                processors = ProcessorFactory.get_all_processors()
                
                if not processors:
                    logger.warning("No active processors found. Waiting 30 seconds before retry...")
                    self.stdout.write(self.style.WARNING("No active processors found. Waiting 30 seconds before retry..."))
                    time.sleep(30)
                    continue
                
                # Process messages for each active processor
                total_processed = 0
                total_failed = 0
                
                for channel_type, processor in processors.items():
                    try:
                        logger.info(f"Processing messages for {channel_type} channel")
                        stats = processor.process_messages(max_messages=10)
                        
                        total_processed += stats['processed']
                        total_failed += stats['failed']
                        
                        if stats['processed'] > 0 or stats['failed'] > 0:
                            logger.info(f"{channel_type}: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                            self.stdout.write(f"{channel_type}: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                        
                    except Exception as e:
                        logger.error(f"Error processing {channel_type} messages: {e}")
                        self.stderr.write(self.style.ERROR(f"Error processing {channel_type} messages: {e}"))
                        total_failed += 1
                
                # Log summary
                if total_processed > 0 or total_failed > 0:
                    logger.info(f"Worker cycle complete: Total processed {total_processed}, Total failed {total_failed}")
                    self.stdout.write(f"Worker cycle complete: Total processed {total_processed}, Total failed {total_failed}")
                
                # Sleep to avoid tight loop
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}")
                self.stderr.write(self.style.ERROR(f"Unexpected error in worker loop: {e}"))
                time.sleep(30)  # Wait longer on unexpected errors

    def _run_sms_worker(self):
        """Run SMS-specific worker."""
        logger.info("Starting SMS Worker")
        self.stdout.write(self.style.SUCCESS("Starting SMS Worker"))
        
        # Get SMS queue URL from environment or use default
        queue_url = getattr(settings, 'SMS_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/054037109114/novaura-acs-sms-events')
        
        try:
            processor = ProcessorFactory.get_processor('sms', queue_url)
            
            if not processor:
                logger.error("Failed to create SMS processor")
                self.stderr.write(self.style.ERROR("Failed to create SMS processor"))
                return
            
            while self.running:
                try:
                    stats = processor.process_messages(max_messages=10)
                    logger.info(f"SMS: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                    self.stdout.write(f"SMS: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                    time.sleep(5)
                    
                except KeyboardInterrupt:
                    logger.info("SMS Worker stopped by user")
                    break
                except Exception as e:
                    logger.error(f"Error in SMS worker: {e}")
                    self.stderr.write(self.style.ERROR(f"Error in SMS worker: {e}"))
                    time.sleep(30)
                    
        except Exception as e:
            logger.error(f"Failed to initialize SMS worker: {e}")
            self.stderr.write(self.style.ERROR(f"Failed to initialize SMS worker: {e}"))

    def _run_email_worker(self):
        """Run Email-specific worker."""
        logger.info("Starting Email Worker")
        self.stdout.write(self.style.SUCCESS("Starting Email Worker"))
        
        # Get Email queue URL from environment or use default
        queue_url = getattr(settings, 'EMAIL_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/054037109114/novaura-acs-email-events')
        
        try:
            processor = ProcessorFactory.get_processor('email', queue_url)
            
            if not processor:
                logger.error("Failed to create Email processor")
                self.stderr.write(self.style.ERROR("Failed to create Email processor"))
                return
            
            while self.running:
                try:
                    stats = processor.process_messages(max_messages=10)
                    logger.info(f"Email: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                    self.stdout.write(f"Email: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                    time.sleep(5)
                    
                except KeyboardInterrupt:
                    logger.info("Email Worker stopped by user")
                    break
                except Exception as e:
                    logger.error(f"Error in Email worker: {e}")
                    self.stderr.write(self.style.ERROR(f"Error in Email worker: {e}"))
                    time.sleep(30)
                    
        except Exception as e:
            logger.error(f"Failed to initialize Email worker: {e}")
            self.stderr.write(self.style.ERROR(f"Failed to initialize Email worker: {e}"))

    def add_arguments(self, parser):
        parser.add_argument(
            '--worker-type',
            type=str,
            default='all',
            choices=['all', 'sms', 'email'],
            help='Type of worker to run (default: all)'
        ) 