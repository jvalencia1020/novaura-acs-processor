import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

import boto3
from django.conf import settings
from django.utils import timezone

from communication_processor.models import SQSMessage, CommunicationEvent, ChannelProcessor
from external_models.models.external_references import Lead


logger = logging.getLogger(__name__)


class BaseChannelProcessor(ABC):
    """
    Base class for all communication channel processors.
    Each channel (SMS, Email, Voice, etc.) should implement this class.
    """
    
    def __init__(self, channel_type: str, queue_url: str, config: Dict[str, Any] = None):
        self.channel_type = channel_type
        self.queue_url = queue_url
        self.config = config or {}
        self.sqs_client = boto3.client('sqs')
        
    @abstractmethod
    def process_event(self, event_data: Dict[str, Any]) -> CommunicationEvent:
        """
        Process a single communication event.
        Must be implemented by each channel processor.
        
        Args:
            event_data: The event data to process
            
        Returns:
            CommunicationEvent: The processed event
        """
        pass
    
    @abstractmethod
    def validate_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Validate that the event data is correct for this channel.
        Must be implemented by each channel processor.
        
        Args:
            event_data: The event data to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        pass
    
    def receive_messages(self, max_messages: int = 10, wait_time: int = 20) -> List[Dict[str, Any]]:
        """
        Receive messages from the SQS queue.
        
        Args:
            max_messages: Maximum number of messages to receive
            wait_time: Long polling wait time in seconds
            
        Returns:
            List of message dictionaries
        """
        try:
            response = self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time,
                AttributeNames=['All'],
                MessageAttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            logger.info(f"Received {len(messages)} messages from {self.channel_type} queue")
            return messages
            
        except Exception as e:
            logger.error(f"Error receiving messages from {self.channel_type} queue: {e}")
            return []
    
    def delete_message(self, receipt_handle: str) -> bool:
        """
        Delete a message from the SQS queue.
        
        Args:
            receipt_handle: The receipt handle of the message to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            return True
        except Exception as e:
            logger.error(f"Error deleting message from {self.channel_type} queue: {e}")
            return False
    
    def process_messages(self, max_messages: int = 10) -> Dict[str, int]:
        """
        Process a batch of messages from the queue.
        
        Args:
            max_messages: Maximum number of messages to process
            
        Returns:
            Dict with processing statistics
        """
        stats = {
            'processed': 0,
            'failed': 0,
            'deleted': 0
        }
        
        messages = self.receive_messages(max_messages)
        
        for message in messages:
            try:
                # Parse message body
                message_body = json.loads(message['Body'])
                
                # Create SQS message record
                sqs_message = SQSMessage.objects.create(
                    message_id=message['MessageId'],
                    receipt_handle=message['ReceiptHandle'],
                    queue_url=self.queue_url,
                    message_body=message_body,
                    status='processing'
                )
                
                # Process the event
                if self.validate_event(message_body):
                    communication_event = self.process_event(message_body)
                    communication_event.sqs_message = sqs_message
                    communication_event.save()
                    
                    # Mark SQS message as completed
                    sqs_message.status = 'completed'
                    sqs_message.processed_at = timezone.now()
                    sqs_message.save()
                    
                    # Delete from SQS queue
                    if self.delete_message(message['ReceiptHandle']):
                        stats['deleted'] += 1
                    
                    stats['processed'] += 1
                    logger.info(f"Successfully processed {self.channel_type} event: {communication_event.external_id}")
                    
                else:
                    # Mark as failed due to validation
                    sqs_message.status = 'failed'
                    sqs_message.error_message = 'Event validation failed'
                    sqs_message.processed_at = timezone.now()
                    sqs_message.save()
                    stats['failed'] += 1
                    
            except Exception as e:
                logger.error(f"Error processing {self.channel_type} message: {e}")
                
                # Update SQS message status
                try:
                    sqs_message = SQSMessage.objects.get(message_id=message['MessageId'])
                    sqs_message.status = 'failed'
                    sqs_message.error_message = str(e)
                    sqs_message.processed_at = timezone.now()
                    sqs_message.save()
                except SQSMessage.DoesNotExist:
                    pass
                
                stats['failed'] += 1
        
        return stats
    
    def get_or_create_conversation(self, external_id: str, **kwargs) -> Optional[Any]:
        """
        Get or create a conversation for this channel.
        This is a helper method that can be overridden by specific processors.
        
        Args:
            external_id: External conversation ID
            **kwargs: Additional conversation data
            
        Returns:
            Conversation object or None
        """
        from external_models.models.communications import Conversation
        
        try:
            return Conversation.objects.get(twilio_sid=external_id)
        except Conversation.DoesNotExist:
            # Create new conversation if needed
            conversation_data = {
                'twilio_sid': external_id,
                'channel': self.channel_type,
                **kwargs
            }
            return Conversation.objects.create(**conversation_data)
    
    def get_or_create_thread(self, lead_id: int, channel: str, **kwargs) -> Optional[Any]:
        """
        Get or create a conversation thread for this channel.
        
        Args:
            lead_id: Lead ID
            channel: Channel type
            **kwargs: Additional thread data
            
        Returns:
            ConversationThread object or None
        """
        from external_models.models.communications import ConversationThread
        from external_models.models.external_references import Lead
        
        try:
            lead = Lead.objects.get(id=lead_id)
            thread, created = ConversationThread.objects.get_or_create(
                lead=lead,
                channel=channel,
                defaults=kwargs
            )
            return thread
        except Lead.DoesNotExist:
            logger.warning(f"Lead {lead_id} not found for thread creation")
            return None

    def _find_nurturing_campaign(self, event_data: Dict[str, Any], lead: Optional[Lead] = None) -> Optional['LeadNurturingCampaign']:
        """
        Find the nurturing campaign associated with this event.
        
        Args:
            event_data: The event data
            lead: Optional Lead instance
            
        Returns:
            LeadNurturingCampaign or None
        """
        from external_models.models.nurturing_campaigns import LeadNurturingCampaign
        
        # First try to find campaign from event data
        campaign_id = event_data.get('campaign_id')
        if campaign_id:
            try:
                return LeadNurturingCampaign.objects.get(id=campaign_id)
            except LeadNurturingCampaign.DoesNotExist:
                pass
        
        # If we have a lead, try to find active campaigns for this lead
        if lead:
            # Look for active campaigns that match this channel
            active_campaigns = LeadNurturingCampaign.objects.filter(
                participants__lead=lead,
                participants__status='active',
                channel=self.channel_type,
                status__in=['active', 'scheduled']
            ).distinct()
            
            if active_campaigns.exists():
                return active_campaigns.first()
        
        return None 