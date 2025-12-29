from django.db import models
from django.core.exceptions import ValidationError
from external_models.models.external_references import Account


class SmsProgram(models.Model):
    """
    Program-level identity and compliance container for SMS marketing.
    """
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='sms_programs',
        help_text='Account this program belongs to'
    )
    name = models.CharField(
        max_length=255,
        help_text='Program name (unique per account)'
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text='Program description'
    )
    help_text = models.TextField(
        blank=True,
        null=True,
        help_text='Help text for users'
    )
    opt_in_confirmation_text = models.TextField(
        blank=True,
        null=True,
        help_text='Text sent to confirm opt-in'
    )
    compliance_disclosure_text = models.TextField(
        blank=True,
        null=True,
        help_text='Compliance disclosure text'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this program is active'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'sms_program'
        unique_together = ('account', 'name')
        indexes = [
            models.Index(fields=['account', 'name']),
            models.Index(fields=['account', 'is_active']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.account.name})"

    def clean(self):
        """Validate program data"""
        super().clean()
        if not self.account:
            raise ValidationError("Account is required")

