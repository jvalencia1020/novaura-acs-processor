from django.conf import settings
from django.db import models
import uuid


class PrivacyRequest(models.Model):
    """
    GDPR/CCPA privacy requests (deletion, export, suppression).
    """

    class RequestType(models.TextChoices):
        DELETE = 'delete', 'Delete Personal Data'
        EXPORT = 'export', 'Export Personal Data'
        SUPPRESS = 'suppress', 'Suppress from Marketing'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending Review'
        APPROVED = 'approved', 'Approved'
        PROCESSING = 'processing', 'Processing'
        COMPLETE = 'complete', 'Complete'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user_id_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text='SHA256 hash of user identifier (phone, email, etc.)',
    )

    request_type = models.CharField(max_length=20, choices=RequestType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    requested_by = models.CharField(
        max_length=255,
        help_text='Email or support ticket ID',
    )
    source = models.CharField(
        max_length=100,
        default='support',
        help_text='How request was submitted (support, self_service, automated)',
    )

    notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='link_tracking_privacy_requests_reviewed',
    )

    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'link_tracking_privacy_requests'
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['user_id_hash']),
            models.Index(fields=['status', 'requested_at']),
        ]

    def __str__(self):
        return f"{self.get_request_type_display()} - {self.user_id_hash[:8]}... ({self.status})"
