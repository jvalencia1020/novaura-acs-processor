from django.db import models
from django.conf import settings
from external_models.models.external_references import Lead, Account, Campaign, Funnel
from external_models.models.reporting import BlandAICall


class Conversation(models.Model):
    """
    Represents a Twilio Conversation session.
    """
    STATE_CHOICES = (
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('archived', 'Archived'),
    )

    CHANNEL_CHOICES = (
        ('sms', 'SMS'),
        ('chat', 'Chat'),
        ('email', 'Email'),
        ('voice', 'Voice'),
    )

    # The unique Twilio ID for this conversation (e.g. 'CHXXXXXXXXXXXXXXXXX')
    twilio_sid = models.CharField(max_length=34, unique=True)
    
    # Twilio Account SID
    account_sid = models.CharField(max_length=34, blank=True, null=True)
    
    # Twilio Messaging Service SID (if used)
    messaging_service_sid = models.CharField(max_length=34, blank=True, null=True)

    # Friendly name, if you set one via Twilio or want to store a local name
    friendly_name = models.CharField(max_length=255, blank=True, null=True)

    # Conversation state as defined by Twilio; using choices enforces valid values.
    state = models.CharField(max_length=50, choices=STATE_CHOICES, default="active")

    # Default channel for this conversation
    channel = models.CharField(
        max_length=10,
        choices=CHANNEL_CHOICES,
        blank=True,
        null=True,
        help_text="Default channel for this conversation"
    )

    # Link to your internal CRM Lead (if applicable)
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Track which user from your team created the conversation (if applicable)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_conversations"
    )

    class Meta:
        managed = False
        db_table = 'communications_conversation'
        indexes = [
            models.Index(fields=['state']),
            models.Index(fields=['friendly_name']),
            models.Index(fields=['account_sid']),
            models.Index(fields=['messaging_service_sid']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Conversation {self.twilio_sid}"


class Participant(models.Model):
    """
    A participant in a Twilio Conversation (could be an end user, a phone number, etc.).
    """
    # Twilio participant SID (e.g. 'MBXXXXXXXXXXXXXXXXX')
    participant_sid = models.CharField(max_length=34, unique=True)

    # The conversation they belong to
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants"
    )

    # For SMS-based participants, store their phone number.
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    
    # Location data for phone numbers
    country = models.CharField(max_length=2, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    zip_code = models.CharField(max_length=20, blank=True, null=True)

    # If a user on your team is also a participant.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversation_participants"
    )

    # Optional JSON field to store channel-specific metadata (e.g., chat identity, messaging binding)
    metadata = models.JSONField(blank=True, null=True, help_text="Optional channel-specific metadata.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'communications_participant'
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['country']),
            models.Index(fields=['state']),
        ]

    def __str__(self):
        return f"Participant {self.participant_sid} in {self.conversation}"


class ConversationMessage(models.Model):
    """
    A message in a Twilio Conversation.
    """
    # Twilio message identifiers
    message_sid = models.CharField(max_length=34, unique=True)
    sms_message_sid = models.CharField(max_length=34, blank=True, null=True)
    sms_sid = models.CharField(max_length=34, blank=True, null=True)
    
    # Twilio Account SID
    account_sid = models.CharField(max_length=34, blank=True, null=True)
    
    # Twilio Messaging Service SID (if used)
    messaging_service_sid = models.CharField(max_length=34, blank=True, null=True)

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages"
    )

    participant = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages"
    )

    # The message text body.
    body = models.TextField()

    # Optional field to capture message direction (inbound/outbound) if needed.
    DIRECTION_CHOICES = (
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    )
    direction = models.CharField(
        max_length=8,
        choices=DIRECTION_CHOICES,
        blank=True,
        null=True,
        help_text="Message direction if applicable."
    )

    # Message status
    status = models.CharField(max_length=50, blank=True, null=True)
    
    # Number of segments for long messages
    num_segments = models.IntegerField(default=1)
    
    # Number of media attachments
    num_media = models.IntegerField(default=0)

    # Optional field to store a media URL if the message includes an attachment.
    media_url = models.URLField(blank=True, null=True, help_text="Optional URL for attached media.")

    CHANNEL_CHOICES = (
        ('sms', 'SMS'),
        ('chat', 'Chat'),
        ('email', 'Email'),
        ('voice', 'Voice'),
    )
    channel = models.CharField(
        max_length=10,
        choices=CHANNEL_CHOICES,
        blank=True,
        null=True,
        help_text="Channel of communication used for this message."
    )

    # Store the complete raw message data
    raw_data = models.JSONField(blank=True, null=True, help_text="Complete raw message data from Twilio")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'communications_conversationmessage'
        indexes = [
            models.Index(fields=['message_sid']),
            models.Index(fields=['sms_message_sid']),
            models.Index(fields=['sms_sid']),
            models.Index(fields=['status']),
        ]
        ordering = ['created_at']

    def __str__(self):
        return f"Message {self.message_sid}: {self.body[:50]}..."


class ConversationThread(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='threads')
    subject = models.CharField(max_length=255, blank=True, null=True)
    channel = models.CharField(
        max_length=10,
        choices=[('sms', 'SMS'), ('email', 'Email'), ('voice', 'Voice'), ('chat', 'Chat')],
        help_text="Platform where the conversation happened."
    )
    status = models.CharField(
        max_length=20,
        choices=[('open', 'Open'), ('assigned', 'Assigned'), ('closed', 'Closed')],
        default='open'
    )
    last_message_timestamp = models.DateTimeField(blank=True, null=True)

    # Link to Twilio Conversation object (optional)
    twilio_conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='threads'
    )

    # Link to Bland AI Call (optional)
    bland_ai_call = models.ForeignKey(
        BlandAICall,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='threads'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'communications_conversationthread'
        ordering = ['-last_message_timestamp']

    def __str__(self):
        return f"Thread {self.id} - {self.lead} ({self.channel})"


class ThreadMessage(models.Model):
    thread = models.ForeignKey(ConversationThread, on_delete=models.CASCADE, related_name='messages')
    sender_type = models.CharField(max_length=10, choices=[('user', 'User'), ('contact', 'Contact')])
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    channel = models.CharField(
        max_length=10,
        choices=[('sms', 'SMS'), ('email', 'Email'), ('voice', 'Voice'), ('chat', 'Chat')]
    )
    media_url = models.URLField(blank=True, null=True)
    read_status = models.BooleanField(default=False, help_text="Whether the message has been read")
    replied_status = models.BooleanField(default=False, help_text="Whether the message has been replied to")
    bland_ai_message_id = models.BigIntegerField(null=True, blank=True, unique=True, help_text="ID of the message in Bland AI transcripts")

    # Optional link to raw Twilio message
    twilio_message = models.ForeignKey(
        ConversationMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='thread_messages'
    )

    # Optional link to the lead who sent the message
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='thread_messages'
    )

    # Optional link to the user who sent the message
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='thread_messages'
    )

    class Meta:
        managed = False
        db_table = 'communications_threadmessage'
        ordering = ['timestamp']

    def __str__(self):
        return f"Message {self.id} in Thread {self.thread.id}"


class ContactEndpointChannel(models.Model):
    CHANNEL_CHOICES = (
        ('sms', 'SMS'),
        ('voice', 'Voice'),
        ('email', 'Email'),
        ('social', 'Social Media'),
    )

    endpoint = models.ForeignKey('ContactEndpoint', on_delete=models.CASCADE, related_name='channels')
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)

    class Meta:
        managed = False
        unique_together = ('endpoint', 'channel')
        db_table = 'contact_endpoint_channel'

    def __str__(self):
        return f"{self.endpoint.value} - {self.channel}"


class ContactEndpoint(models.Model):
    PLATFORM_CHOICES = (
        # Phone platforms
        ('twilio', 'Twilio'),
        ('vonage', 'Vonage'),
        ('bandwidth', 'Bandwidth'),
        ('plivo', 'Plivo'),
        # Email platforms
        ('gmail', 'Gmail'),
        ('outlook', 'Outlook'),
        ('sendgrid', 'SendGrid'),
        ('mailchimp', 'Mailchimp'),
        # Social platforms
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('twitter', 'Twitter'),
        ('linkedin', 'LinkedIn'),
        ('whatsapp', 'WhatsApp'),
        # Other
        ('other', 'Other'),
    )

    PRIORITY_CHOICES = (
        ('primary', 'Primary'),
        ('secondary', 'Secondary'),
        ('backup', 'Backup'),
    )

    # Contact info
    value = models.CharField(
        max_length=255,
        help_text="Phone number, email address, or social handle"
    )
    platform = models.CharField(
        max_length=50,
        choices=PLATFORM_CHOICES,
        null=True,
        blank=True,
        help_text="Platform or service provider for this contact endpoint"
    )

    # Enhancements
    label = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="User-friendly label (e.g. 'Work Phone', 'Personal Email')"
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='primary',
        help_text="Preferred usage priority for this endpoint"
    )
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)

    # CRM Relationships
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contact_endpoints'
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contact_endpoints'
    )
    funnel = models.ForeignKey(
        Funnel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contact_endpoints'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'contact_endpoint'
        indexes = [
            models.Index(fields=['value']),
        ]

    def __str__(self):
        label = f"{self.value}"
        if self.label:
            label += f" ({self.label})"
        elif self.platform:
            label += f" ({self.platform})"
        return label

    def get_channel_list(self):
        return [c.channel for c in self.channels.all()]

