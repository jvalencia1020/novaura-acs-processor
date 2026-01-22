"""
Management command to run SMS marketing message processor worker.
"""
import json
import logging
import signal
import sys
import time
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from sms_marketing.services.processor import SMSMarketingProcessor
from sms_marketing.models import SmsMessage

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Runs the SQS worker for SMS marketing message processing'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, sig, frame):
        logger.info('Shutting down SMS marketing worker...')
        self.stdout.write(self.style.WARNING('Shutting down SMS marketing worker...'))
        self.running = False

    def handle(self, *args, **options):
        # Instantiate processor here instead of in __init__ to avoid import errors
        processor = SMSMarketingProcessor()
        
        logger.info('Starting SMS Marketing Processor Worker')
        self.stdout.write(self.style.SUCCESS('Starting SMS Marketing Processor Worker'))

        queue_url = getattr(settings, 'SMS_MARKETING_QUEUE_URL', None)

        if not queue_url:
            error_msg = 'SMS_MARKETING_QUEUE_URL not set in settings'
            logger.error(error_msg)
            self.stderr.write(self.style.ERROR(error_msg))
            sys.exit(1)

        logger.info(f'Polling queue: {queue_url}')
        self.stdout.write(self.style.SUCCESS(f'Polling queue: {queue_url}'))

        # Initialize SQS client with retry configuration
        sqs = boto3.client('sqs', config=Config(
            retries=dict(
                max_attempts=3,
                mode='adaptive'
            )
        ))

        # SQS worker loop
        while self.running:
            try:
                # Receive messages
                response = sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=10,  # Long polling - reduced to 10s for more frequent database checks
                    AttributeNames=['All'],
                    MessageAttributeNames=['All']
                )

                messages = response.get('Messages', [])

                if messages:
                    logger.info(f"Processing {len(messages)} messages from SQS")
                    self.stdout.write(f"Processing {len(messages)} messages from SQS")

                    for message in messages:
                        try:
                            start_time = timezone.now()
                            
                            # Check message attributes for filtering
                            message_attributes = message.get('MessageAttributes', {})
                            event_type = message_attributes.get('EventType', {}).get('StringValue')
                            
                            # Only process SMS marketing inbound messages
                            if event_type != 'sms.marketing.inbound':
                                logger.debug(f"Skipping message with EventType: {event_type}")
                                # Delete message to prevent reprocessing
                                sqs.delete_message(
                                    QueueUrl=queue_url,
                                    ReceiptHandle=message['ReceiptHandle']
                                )
                                continue
                            
                            # Parse message body
                            body = json.loads(message['Body'])
                            
                            # Check if message references S3 object
                            if 's3_bucket' in body and 's3_key' in body:
                                # Download from S3
                                body = self._load_from_s3(body['s3_bucket'], body['s3_key'])
                            
                            # Process message within transaction
                            with transaction.atomic():
                                success = processor.process_inbound_message(body)
                            
                            if success:
                                # Delete message after successful processing
                                sqs.delete_message(
                                    QueueUrl=queue_url,
                                    ReceiptHandle=message['ReceiptHandle']
                                )
                                
                                duration = timezone.now() - start_time
                                logger.info(f"Processed SMS marketing message in {duration.total_seconds():.2f}s")
                            else:
                                logger.warning(f"Failed to process message {message.get('MessageId')}")
                                # Handle failed message (could move to DLQ or retry)
                                self._handle_failed_message(sqs, queue_url, message, "Processing failed")

                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON in message: {e}")
                            self._handle_failed_message(sqs, queue_url, message, f"Invalid JSON: {e}")
                        except Exception as e:
                            logger.exception(f"Error processing message: {e}")
                            self._handle_failed_message(sqs, queue_url, message, str(e))
                else:
                    # SQS queue is empty, check database for pending messages as fallback
                    self._process_pending_from_database(processor, limit=5)

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                logger.error(f"AWS SQS error ({error_code}): {error_message}")
                self.stderr.write(self.style.ERROR(f"AWS SQS error ({error_code}): {error_message}"))
                time.sleep(5)  # Back off on AWS errors
            except Exception as e:
                logger.error(f"Error receiving messages: {e}", exc_info=True)
                self.stderr.write(self.style.ERROR(f"Error receiving messages: {e}"))
                time.sleep(5)  # Back off on other errors

    def _load_from_s3(self, bucket: str, key: str) -> dict:
        """Load message data from S3"""
        try:
            s3_client = boto3.client('s3')
            response = s3_client.get_object(Bucket=bucket, Key=key)
            body = json.loads(response['Body'].read().decode('utf-8'))
            logger.info(f"Loaded message from S3: s3://{bucket}/{key}")
            return body
        except Exception as e:
            logger.error(f"Error loading from S3: {e}")
            raise

    def _process_pending_from_database(self, processor, limit=5):
        """
        Process pending messages directly from database as fallback.
        Only processes messages older than 1 minute to avoid race conditions.
        """
        try:
            # Find messages that are pending and older than 1 minute (to avoid race conditions)
            cutoff_time = timezone.now() - timezone.timedelta(minutes=1)
            
            pending_messages = SmsMessage.objects.filter(
                processing_status='pending',
                direction='inbound',
                created_at__lt=cutoff_time  # Only process messages older than 1 minute
            ).order_by('created_at')[:limit]
            
            if pending_messages.exists():
                count = pending_messages.count()
                logger.info(f"Found {count} pending messages in database, processing as fallback...")
                
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
                            logger.info(f"Processed pending message {msg.id} from database (fallback)")
                        else:
                            logger.warning(f"Failed to process pending message {msg.id} from database")
                            
                    except Exception as e:
                        logger.exception(f"Error processing pending message {msg.id} from database: {e}")
                        
        except Exception as e:
            logger.error(f"Error checking for pending messages in database: {e}", exc_info=True)

    def _handle_failed_message(self, sqs, queue_url, message, error_reason):
        """Handle a failed message by moving it to DLQ if configured"""
        try:
            # If DLQ is configured, move message there
            dlq_url = getattr(settings, 'SMS_MARKETING_DLQ_URL', None)
            if dlq_url:
                sqs.send_message(
                    QueueUrl=dlq_url,
                    MessageBody=message['Body'],
                    MessageAttributes={
                        'ErrorReason': {
                            'DataType': 'String',
                            'StringValue': error_reason
                        },
                        'OriginalMessageId': {
                            'DataType': 'String',
                            'StringValue': message['MessageId']
                        }
                    }
                )
                logger.info(f"Moved failed message to DLQ: {message['MessageId']}")

            # Delete from main queue
            sqs.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=message['ReceiptHandle']
            )
        except Exception as e:
            logger.error(f"Error handling failed message: {e}", exc_info=True)

