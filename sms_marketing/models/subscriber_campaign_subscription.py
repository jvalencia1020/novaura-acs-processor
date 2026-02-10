from django.db import models


class SmsSubscriberCampaignSubscription(models.Model):
    """
    Tracks opt-in/opt-out state per (subscriber, campaign) so we can record when
    a subscriber opts into different SMS marketing campaigns that use the same endpoint.
    One row per (subscriber, campaign); re-opt-in after opt-out updates the same row.
    """
    STATUS_CHOICES = [
        ('pending_opt_in', 'Pending Opt-in'),
        ('opted_in', 'Opted In'),
        ('opted_out', 'Opted Out'),
    ]

    subscriber = models.ForeignKey(
        'SmsSubscriber',
        on_delete=models.CASCADE,
        related_name='campaign_subscriptions',
    )
    campaign = models.ForeignKey(
        'SmsKeywordCampaign',
        on_delete=models.CASCADE,
        related_name='subscriber_subscriptions',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        help_text='Current subscription status for this campaign',
    )
    opted_in_at = models.DateTimeField(
        help_text='When they opted in (or when pending was set)',
    )
    opt_in_message = models.ForeignKey(
        'SmsMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opt_in_subscription_records',
        help_text='Message that triggered opt-in',
    )
    opt_in_rule = models.ForeignKey(
        'SmsKeywordRule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opt_in_subscription_records',
        help_text='SMS keyword rule that triggered opt-in (use rule.short_link for dynamic link in drip/reminder).',
    )
    opted_out_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When they opted out (if ever)',
    )
    opt_out_message = models.ForeignKey(
        'SmsMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opt_out_subscription_records',
        help_text='Message that triggered opt-out',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'sms_subscriber_campaign_subscription'
        unique_together = [['subscriber', 'campaign']]
        ordering = ['-opted_in_at']
        indexes = [
            models.Index(fields=['subscriber', 'campaign']),
            models.Index(fields=['campaign', 'status']),
        ]

    def __str__(self):
        return f"{self.subscriber.phone_number} / {self.campaign.name} ({self.status})"
