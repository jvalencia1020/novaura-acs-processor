import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from communication_processor.models import CommunicationEvent, SQSMessage

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CommunicationEvent)
def communication_event_post_save(sender, instance, created, **kwargs):
    """
    Handle post-save actions for CommunicationEvent.
    
    This signal can be used to:
    - Trigger notifications
    - Update analytics
    - Send webhooks
    - Update conversation threads
    """
    if created:
        logger.info(f"New communication event created: {instance.event_type} - {instance.channel_type}")
        
        # Update conversation thread if this is a message event
        if instance.event_type in ['message_received', 'message_sent']:
            _update_conversation_thread(instance)
        
        # Trigger any additional processing based on event type
        _handle_event_type_specific_actions(instance)


@receiver(post_save, sender=SQSMessage)
def sqs_message_post_save(sender, instance, created, **kwargs):
    """
    Handle post-save actions for SQSMessage.
    
    This signal can be used to:
    - Track processing metrics
    - Alert on failures
    - Update monitoring dashboards
    """
    if created:
        logger.info(f"New SQS message received: {instance.message_id}")
    
    # Log status changes
    if not created and instance.status in ['failed', 'retry']:
        logger.warning(f"SQS message {instance.message_id} status: {instance.status}")
        
        if instance.status == 'failed' and instance.retry_count >= instance.max_retries:
            logger.error(f"SQS message {instance.message_id} exceeded max retries")


def _update_conversation_thread(event):
    """
    Update conversation thread with the latest message.
    
    Args:
        event: CommunicationEvent instance
    """
    try:
        if event.conversation_thread and event.conversation_message:
            # Update last message timestamp
            event.conversation_thread.last_message_timestamp = event.conversation_message.created_at
            event.conversation_thread.save()
            
            logger.debug(f"Updated conversation thread {event.conversation_thread.id}")
    except Exception as e:
        logger.error(f"Error updating conversation thread: {e}")


def _handle_event_type_specific_actions(event):
    """
    Handle specific actions based on event type.
    
    Args:
        event: CommunicationEvent instance
    """
    try:
        if event.event_type == 'message_received':
            _handle_message_received(event)
        elif event.event_type == 'delivery_status':
            _handle_delivery_status(event)
        elif event.event_type == 'read_receipt':
            _handle_read_receipt(event)
        elif event.event_type == 'error':
            _handle_error_event(event)
    except Exception as e:
        logger.error(f"Error handling event type specific actions: {e}")


def _handle_message_received(event):
    """
    Handle message received events.
    
    Args:
        event: CommunicationEvent instance
    """
    # This could trigger:
    # - Auto-response logic
    # - Lead scoring updates
    # - Notification to sales team
    # - Integration with CRM
    logger.info(f"Processing received message for lead: {event.lead}")


def _handle_delivery_status(event):
    """
    Handle delivery status events.
    
    Args:
        event: CommunicationEvent instance
    """
    # This could trigger:
    # - Update message status in CRM
    # - Retry logic for failed deliveries
    # - Analytics tracking
    status = event.event_data.get('status', 'unknown')
    logger.info(f"Message delivery status: {status} for {event.external_id}")


def _handle_read_receipt(event):
    """
    Handle read receipt events.
    
    Args:
        event: CommunicationEvent instance
    """
    # This could trigger:
    # - Update engagement metrics
    # - Follow-up logic
    # - Lead scoring updates
    logger.info(f"Message read receipt for {event.external_id}")


def _handle_error_event(event):
    """
    Handle error events.
    
    Args:
        event: CommunicationEvent instance
    """
    # This could trigger:
    # - Error reporting
    # - Retry logic
    # - Alert notifications
    error_message = event.event_data.get('error_message', 'Unknown error')
    logger.error(f"Communication error: {error_message} for {event.external_id}") 