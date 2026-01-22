from django.db import models
from django.core.exceptions import ValidationError
from external_models.models.communications import ContactEndpoint
from external_models.models.external_references import Lead


class SmsSubscriber(models.Model):
    """
    Tracks opt-in state per endpoint + phone number.
    """
    STATUS_CHOICES = [
        ('unknown', 'Unknown'),
        ('pending_opt_in', 'Pending Opt-in'),
        ('opted_in', 'Opted In'),
        ('opted_out', 'Opted Out'),
    ]

    endpoint = models.ForeignKey(
        ContactEndpoint,
        on_delete=models.CASCADE,
        related_name='sms_subscribers',
        help_text='SMS endpoint for this subscriber'
    )
    phone_number = models.CharField(
        max_length=20,
        help_text='Phone number in E.164 format'
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_subscribers',
        help_text='Linked lead for nurturing campaign enrollment'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='unknown',
        help_text='Current opt-in status'
    )

    # Opt-in tracking
    opt_in_source = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Source of opt-in (e.g., keyword, manual, web)'
    )
    opt_in_keyword = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Keyword that triggered opt-in'
    )
    opt_in_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the subscriber opted in'
    )
    opt_in_message = models.ForeignKey(
        'SmsMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opt_in_subscribers',
        help_text='The message that triggered opt-in'
    )

    # Opt-out tracking
    opt_out_source = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Source of opt-out (e.g., STOP, manual, web)'
    )
    opt_out_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the subscriber opted out'
    )
    opt_out_message = models.ForeignKey(
        'SmsMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opt_out_subscribers',
        help_text='The message that triggered opt-out'
    )

    # Activity tracking
    last_inbound_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last time subscriber sent a message'
    )
    last_outbound_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last time we sent a message to subscriber'
    )

    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional metadata for the subscriber'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'sms_subscriber'
        unique_together = ('endpoint', 'phone_number')
        indexes = [
            models.Index(fields=['endpoint', 'phone_number']),
            models.Index(fields=['endpoint', 'status']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['status']),
            models.Index(fields=['lead']),
            models.Index(fields=['opt_in_message']),
            models.Index(fields=['opt_out_message']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.phone_number} ({self.endpoint.value})"

    def clean(self):
        """Validate subscriber data"""
        super().clean()
        if not self.endpoint:
            raise ValidationError("Endpoint is required")
        if not self.phone_number:
            raise ValidationError("Phone number is required")

