from django.db import models
from external_models.models.communications import ContactEndpoint
from external_models.models.communications import Conversation, ConversationMessage
from external_models.models.external_references import Account
from external_models.models.nurturing_campaigns import LeadNurturingCampaign


class SmsMessage(models.Model):
    """
    Message log populated by processor (read-only from API perspective).
    """
    DIRECTION_CHOICES = [
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('received', 'Received'),
    ]

    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending Processing'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('failed', 'Processing Failed'),
        ('skipped', 'Skipped'),
    ]

    endpoint = models.ForeignKey(
        ContactEndpoint,
        on_delete=models.CASCADE,
        related_name='sms_messages',
        help_text='SMS endpoint for this message'
    )
    provider = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='SMS provider (e.g., Twilio, AWS SNS)'
    )
    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='Provider message ID'
    )
    direction = models.CharField(
        max_length=10,
        choices=DIRECTION_CHOICES,
        help_text='Message direction'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text='Message delivery/provider status'
    )
    processing_status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS_CHOICES,
        default='pending',
        help_text='Processing status for subscriber/opt-in workflows'
    )
    from_number = models.CharField(
        max_length=20,
        help_text='Sender phone number'
    )
    to_number = models.CharField(
        max_length=20,
        help_text='Recipient phone number'
    )
    body_raw = models.TextField(
        help_text='Raw message body as received'
    )
    body_normalized = models.TextField(
        blank=True,
        null=True,
        help_text='Normalized message body'
    )

    # Provider metadata
    account_sid = models.CharField(
        max_length=34,
        blank=True,
        null=True,
        help_text='Twilio Account SID'
    )
    api_version = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text='Twilio API version'
    )
    sms_message_sid = models.CharField(
        max_length=34,
        blank=True,
        null=True,
        help_text='Twilio SMS Message SID'
    )
    sms_sid = models.CharField(
        max_length=34,
        blank=True,
        null=True,
        help_text='Twilio SMS SID'
    )
    messaging_service_sid = models.CharField(
        max_length=34,
        blank=True,
        null=True,
        help_text='Twilio Messaging Service SID'
    )

    # Message metadata
    num_segments = models.IntegerField(
        default=1,
        help_text='Number of message segments'
    )
    num_media = models.IntegerField(
        default=0,
        help_text='Number of media attachments'
    )
    media_url = models.URLField(
        blank=True,
        null=True,
        help_text='URL of media attachment (first media if multiple)'
    )

    # Geographic data - From (sender)
    from_country = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        help_text='Sender country code (ISO 3166-1 alpha-2)'
    )
    from_state = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='Sender state/province'
    )
    from_city = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Sender city'
    )
    from_zip = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text='Sender ZIP/postal code'
    )

    # Geographic data - To (recipient)
    to_country = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        help_text='Recipient country code (ISO 3166-1 alpha-2)'
    )
    to_state = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='Recipient state/province'
    )
    to_city = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Recipient city'
    )
    to_zip = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text='Recipient ZIP/postal code'
    )

    # Raw webhook payload (complete original data)
    raw_data = models.JSONField(
        default=dict,
        blank=True,
        help_text='Complete raw webhook payload from provider'
    )

    # Webhook query parameters (from URL query string)
    webhook_query_params = models.JSONField(
        default=dict,
        blank=True,
        help_text='Query parameters from webhook URL (e.g., sms_campaign, utm_source, etc.)'
    )

    # Optional relationships (nullable for messages not yet processed)
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_messages',
        help_text='Account this message is associated with'
    )
    sms_campaign = models.ForeignKey(
        'SmsKeywordCampaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
        help_text='SMS keyword campaign this message is associated with'
    )
    nurturing_campaign = models.ForeignKey(
        LeadNurturingCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_messages',
        help_text='Nurturing campaign this message is associated with'
    )
    rule = models.ForeignKey(
        'SmsKeywordRule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
        help_text='Rule that matched this message'
    )
    subscriber = models.ForeignKey(
        'SmsSubscriber',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
        help_text='Subscriber this message is from/to'
    )

    # Optional conversation links for agent replies and threading
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_marketing_messages',
        help_text='Linked conversation for agent replies (created when ROUTE_TO_AGENT action is triggered)'
    )
    conversation_message = models.ForeignKey(
        ConversationMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_marketing_message',
        help_text='Linked ConversationMessage if message was also stored in conversation thread'
    )

    # Error tracking
    error = models.TextField(
        blank=True,
        null=True,
        help_text='Error message if message failed'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the message was processed for subscriber/opt-in workflows'
    )

    class Meta:
        managed = False
        db_table = 'sms_message'
        indexes = [
            models.Index(fields=['endpoint', 'created_at']),
            models.Index(fields=['account', 'created_at']),
            models.Index(fields=['sms_campaign', 'created_at']),
            models.Index(fields=['nurturing_campaign', 'created_at']),
            models.Index(fields=['subscriber', 'created_at']),
            models.Index(fields=['direction', 'status']),
            models.Index(fields=['processing_status', 'created_at']),
            models.Index(fields=['processing_status', 'processed_at']),
            models.Index(fields=['from_number']),
            models.Index(fields=['to_number']),
            models.Index(fields=['provider_message_id']),
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['conversation_message']),
            models.Index(fields=['account_sid']),
            models.Index(fields=['from_country', 'from_state']),
            models.Index(fields=['to_country', 'to_state']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.direction} {self.from_number} → {self.to_number} ({self.status})"

