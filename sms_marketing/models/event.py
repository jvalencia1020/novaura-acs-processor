from django.db import models
from external_models.models.communications import ContactEndpoint
from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant


class SmsCampaignEvent(models.Model):
    """
    Event log for routing and compliance events (read-only from API perspective).
    """
    EVENT_TYPE_CHOICES = [
        ('keyword_matched', 'Keyword Matched'),
        ('rule_triggered', 'Rule Triggered'),
        ('opt_in', 'Opt In'),
        ('opt_out', 'Opt Out'),
        ('nurturing_campaign_enrolled', 'Nurturing Campaign Enrolled'),
        ('message_sent', 'Message Sent'),
        ('message_received', 'Message Received'),
        ('error', 'Error'),
    ]

    endpoint = models.ForeignKey(
        ContactEndpoint,
        on_delete=models.CASCADE,
        related_name='sms_campaign_events',
        help_text='SMS endpoint for this event'
    )

    # Optional relationships (nullable for events not yet fully processed)
    campaign = models.ForeignKey(
        'SmsKeywordCampaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text='Campaign this event is associated with'
    )
    rule = models.ForeignKey(
        'SmsKeywordRule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text='Rule this event is associated with'
    )
    subscriber = models.ForeignKey(
        'SmsSubscriber',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text='Subscriber this event is associated with'
    )
    message = models.ForeignKey(
        'SmsMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text='Message this event is associated with'
    )

    # Nurturing campaign relationships (for enrollment events)
    nurturing_campaign = models.ForeignKey(
        LeadNurturingCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_campaign_events',
        help_text='Nurturing campaign when enrollment events occur'
    )
    nurturing_participant = models.ForeignKey(
        LeadNurturingParticipant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_campaign_events',
        help_text='Participant created when enrolling in nurturing campaign'
    )

    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES,
        help_text='Type of event'
    )
    payload = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional event data'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'sms_campaign_event'
        indexes = [
            models.Index(fields=['endpoint', 'created_at']),
            models.Index(fields=['campaign', 'created_at']),
            models.Index(fields=['event_type', 'created_at']),
            models.Index(fields=['nurturing_campaign']),
            models.Index(fields=['subscriber', 'created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type} - {self.endpoint.value} ({self.created_at})"

