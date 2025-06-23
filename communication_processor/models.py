from django.db import models
from django.conf import settings
from external_models.models.external_references import Lead, Account
from external_models.models.communications import Conversation, ConversationMessage, ConversationThread
from external_models.models.nurturing_campaigns import LeadNurturingCampaign


class SQSMessage(models.Model):
    """
    Tracks SQS messages that have been processed by the communication processor.
    """
    message_id = models.CharField(max_length=255, unique=True, help_text="SQS Message ID")
    receipt_handle = models.CharField(max_length=255, help_text="SQS Receipt Handle")
    queue_url = models.URLField(help_text="SQS Queue URL")
    message_body = models.JSONField(help_text="Raw message body from SQS")
    
    # Processing status
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('retry', 'Retry'),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Error tracking
    error_message = models.TextField(blank=True, null=True)
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    
    # Timestamps
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        managed = False
        db_table = 'communication_processor_sqs_message'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['received_at']),
            models.Index(fields=['message_id']),
        ]
        ordering = ['-received_at']

    def __str__(self):
        return f"SQS Message {self.message_id} - {self.status}"


class CommunicationEvent(models.Model):
    """
    Represents a communication event that was processed from an SQS message.
    """
    EVENT_TYPES = (
        ('message_received', 'Message Received'),
        ('message_sent', 'Message Sent'),
        ('conversation_started', 'Conversation Started'),
        ('conversation_ended', 'Conversation Ended'),
        ('participant_joined', 'Participant Joined'),
        ('participant_left', 'Participant Left'),
        ('delivery_status', 'Delivery Status'),
        ('read_receipt', 'Read Receipt'),
        ('error', 'Error'),
    )
    
    CHANNEL_TYPES = (
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('voice', 'Voice'),
        ('chat', 'Chat'),
        ('whatsapp', 'WhatsApp'),
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('twitter', 'Twitter'),
        ('linkedin', 'LinkedIn'),
    )
    
    # Event identification
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    channel_type = models.CharField(max_length=20, choices=CHANNEL_TYPES)
    external_id = models.CharField(max_length=255, help_text="External ID from the communication platform")
    
    # SQS message reference
    sqs_message = models.ForeignKey(
        SQSMessage,
        on_delete=models.CASCADE,
        related_name='communication_events'
    )
    
    # CRM relationships
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='communication_events'
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='communication_events'
    )
    
    # Nurturing campaign relationship
    nurturing_campaign = models.ForeignKey(
        LeadNurturingCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='communication_events',
        help_text="The nurturing campaign this event is associated with"
    )
    
    # Communication model relationships
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processor_events'
    )
    conversation_message = models.ForeignKey(
        ConversationMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processor_events'
    )
    conversation_thread = models.ForeignKey(
        ConversationThread,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processor_events'
    )
    
    # Event data
    event_data = models.JSONField(help_text="Structured event data")
    raw_data = models.JSONField(help_text="Raw event data from the platform")
    
    # Processing metadata
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_communication_events'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        db_table = 'communication_processor_communication_event'
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['channel_type']),
            models.Index(fields=['external_id']),
            models.Index(fields=['created_at']),
            models.Index(fields=['nurturing_campaign']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type} - {self.channel_type} - {self.external_id}"


class ChannelProcessor(models.Model):
    """
    Configuration for different communication channel processors.
    """
    CHANNEL_TYPES = (
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('voice', 'Voice'),
        ('chat', 'Chat'),
        ('whatsapp', 'WhatsApp'),
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('twitter', 'Twitter'),
        ('linkedin', 'LinkedIn'),
    )
    
    channel_type = models.CharField(max_length=20, choices=CHANNEL_TYPES, unique=True)
    is_active = models.BooleanField(default=True)
    queue_url = models.URLField(help_text="SQS Queue URL for this channel")
    
    # Processor configuration
    processor_class = models.CharField(
        max_length=255,
        help_text="Python class path for the processor"
    )
    config = models.JSONField(
        default=dict,
        help_text="Channel-specific configuration"
    )
    
    # Processing settings
    batch_size = models.IntegerField(default=10, help_text="Number of messages to process in a batch")
    visibility_timeout = models.IntegerField(default=300, help_text="SQS visibility timeout in seconds")
    max_retries = models.IntegerField(default=3, help_text="Maximum retry attempts for failed messages")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        db_table = 'communication_processor_channel_processor'
        ordering = ['channel_type']

    def __str__(self):
        return f"{self.channel_type} Processor"
