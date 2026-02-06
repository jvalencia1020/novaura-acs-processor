from django.conf import settings
from django.db import models
import uuid


class LinkVersion(models.Model):
    """
    Audit trail for link changes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    link = models.ForeignKey(
        'Link',
        on_delete=models.CASCADE,
        related_name='versions',
    )
    version = models.IntegerField()

    destination_url = models.TextField()
    utm_overrides = models.JSONField(default=dict)
    routing_rules = models.JSONField(default=dict)
    active = models.BooleanField()

    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    change_reason = models.TextField(blank=True)

    class Meta:
        managed = False
        db_table = 'link_tracking_link_versions'
        ordering = ['-version']
        unique_together = [['link', 'version']]
        indexes = [
            models.Index(fields=['link', '-version']),
        ]

    def __str__(self):
        return f"{self.link} v{self.version}"


class PublishOutbox(models.Model):
    """
    Outbox pattern for reliable publishing to DynamoDB.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETE = 'complete', 'Complete'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    link = models.ForeignKey(
        'Link',
        on_delete=models.CASCADE,
        related_name='publish_outbox',
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        help_text='Format: {link_id}:{updated_at_timestamp}',
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    retry_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'link_tracking_publish_outbox'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['link', '-created_at']),
        ]

    def __str__(self):
        return f"Publish {self.link} ({self.status})"
