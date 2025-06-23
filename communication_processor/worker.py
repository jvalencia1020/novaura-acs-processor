#!/usr/bin/env python
"""
SQS Worker for Communication Processor

This worker continuously polls SQS queues and processes communication events
using the appropriate channel processors.
"""

import os
import sys
import time
import logging
import django
from typing import Dict, Any

# Add the current working directory to Python path so Django can find the acs_personalization module
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'acs_personalization.settings.prod')
django.setup()

from communication_processor.services.processor_factory import ProcessorFactory
from communication_processor.models import ChannelProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_worker():
    """
    Main worker function that continuously processes messages from all active queues.
    """
    logger.info("Starting Communication Processor Worker")
    
    while True:
        try:
            # Get all active processors from the database
            processors = ProcessorFactory.get_all_processors()
            
            if not processors:
                logger.warning("No active processors found. Waiting 30 seconds before retry...")
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
                    
                except Exception as e:
                    logger.error(f"Error processing {channel_type} messages: {e}")
                    total_failed += 1
            
            # Log summary
            if total_processed > 0 or total_failed > 0:
                logger.info(f"Worker cycle complete: Total processed {total_processed}, Total failed {total_failed}")
            
            # Sleep to avoid tight loop
            time.sleep(5)
            
        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in worker loop: {e}")
            time.sleep(30)  # Wait longer on unexpected errors


def run_sms_worker():
    """
    SMS-specific worker function for testing.
    """
    logger.info("Starting SMS Worker")
    
    # Get SMS queue URL from environment or use default
    queue_url = os.environ.get('SMS_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/054037109114/novaura-acs-sms-events')
    
    try:
        processor = ProcessorFactory.get_processor('sms', queue_url)
        
        if not processor:
            logger.error("Failed to create SMS processor")
            return
        
        while True:
            try:
                stats = processor.process_messages(max_messages=10)
                logger.info(f"SMS: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("SMS Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in SMS worker: {e}")
                time.sleep(30)
                
    except Exception as e:
        logger.error(f"Failed to initialize SMS worker: {e}")


def run_email_worker():
    """
    Email-specific worker function for testing.
    """
    logger.info("Starting Email Worker")
    
    # Get Email queue URL from environment or use default
    queue_url = os.environ.get('EMAIL_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/054037109114/novaura-acs-email-events')
    
    try:
        processor = ProcessorFactory.get_processor('email', queue_url)
        
        if not processor:
            logger.error("Failed to create Email processor")
            return
        
        while True:
            try:
                stats = processor.process_messages(max_messages=10)
                logger.info(f"Email: Processed {stats['processed']}, Failed {stats['failed']}, Deleted {stats['deleted']}")
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("Email Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in Email worker: {e}")
                time.sleep(30)
                
    except Exception as e:
        logger.error(f"Failed to initialize Email worker: {e}")


def main():
    """
    Main entry point that determines which worker to run based on environment variables.
    """
    worker_type = os.environ.get('WORKER_TYPE', 'all')
    
    if worker_type == 'sms':
        run_sms_worker()
    elif worker_type == 'email':
        run_email_worker()
    else:
        run_worker()


if __name__ == "__main__":
    main() 