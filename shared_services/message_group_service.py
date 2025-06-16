import logging
from django.db import transaction
from django.utils import timezone
from external_models.models.nurturing_campaigns import BulkCampaignMessage, BulkCampaignMessageGroup

logger = logging.getLogger(__name__)

class MessageGroupService:
    """
    Service for managing message groups in bulk campaigns.
    Handles creation and management of message groups for related messages.
    """

    def create_message_group(self, campaign, participant, scheduled_for):
        """
        Create a new message group for a campaign participant.
        
        Args:
            campaign: The campaign the messages belong to
            participant: The participant receiving the messages
            scheduled_for: The time the messages should be sent (used for messages, not stored in group)
            
        Returns:
            MessageGroup: The created message group
        """
        try:
            with transaction.atomic():
                group = BulkCampaignMessageGroup.objects.create(
                    campaign=campaign,
                    participant=participant,
                    status='pending'
                )
                logger.info(f"Created message group {group.id} for participant {participant.id}")
                return group
        except Exception as e:
            logger.exception(f"Error creating message group: {e}")
            return None

    def add_message_to_group(self, message, group):
        """
        Add a message to an existing message group.
        
        Args:
            message: The message to add to the group
            group: The message group to add the message to
            
        Returns:
            bool: True if the message was added successfully
        """
        try:
            with transaction.atomic():
                message.message_group = group
                message.save()
                logger.info(f"Added message {message.id} to group {group.id}")
                return True
        except Exception as e:
            logger.exception(f"Error adding message to group: {e}")
            return False

    def create_or_get_message_group(self, campaign, participant, scheduled_for):
        """
        Create a new message group or get an existing one for the given time.
        
        Args:
            campaign: The campaign the messages belong to
            participant: The participant receiving the messages
            scheduled_for: The time the messages should be sent
            
        Returns:
            MessageGroup: The message group
        """
        try:
            # Look for an existing group for this participant
            existing_group = BulkCampaignMessageGroup.objects.filter(
                campaign=campaign,
                participant=participant,
                status='pending'
            ).first()

            if existing_group:
                logger.debug(f"Found existing message group {existing_group.id} for participant {participant.id}")
                return existing_group

            # Create a new group if none exists
            return self.create_message_group(campaign, participant, scheduled_for)

        except Exception as e:
            logger.exception(f"Error creating/getting message group: {e}")
            return None

    def update_group_status(self, group, status, error_message=None):
        """
        Update the status of a message group.
        
        Args:
            group: The message group to update
            status: The new status
            error_message: Optional error message
            
        Returns:
            bool: True if the update was successful
        """
        try:
            with transaction.atomic():
                group.status = status
                if error_message:
                    group.error_message = error_message
                group.updated_at = timezone.now()
                group.save()
                logger.info(f"Updated message group {group.id} status to {status}")
                return True
        except Exception as e:
            logger.exception(f"Error updating message group status: {e}")
            return False

    def cancel_group(self, group, error_message=None):
        """
        Cancel all messages in a group.
        
        Args:
            group: The message group to cancel
            error_message: Optional error message
            
        Returns:
            bool: True if the cancellation was successful
        """
        try:
            with transaction.atomic():
                # Update group status
                self.update_group_status(group, 'cancelled', error_message)
                
                # Cancel all messages in the group
                BulkCampaignMessage.objects.filter(
                    message_group=group
                ).update(
                    status='cancelled',
                    error_message=error_message or 'Message cancelled due to group cancellation',
                    updated_at=timezone.now()
                )
                
                logger.info(f"Cancelled message group {group.id} and all its messages")
                return True
        except Exception as e:
            logger.exception(f"Error cancelling message group: {e}")
            return False 