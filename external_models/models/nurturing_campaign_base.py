from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

class CampaignScheduleBase(models.Model):
    """Base model for campaign scheduling"""
    business_hours_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        managed = False


class CampaignProgressBase(models.Model):
    """Base model for campaign progress tracking"""
    participant = models.ForeignKey('LeadNurturingParticipant', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        managed = False


class RetryStrategy(models.Model):
    """Model for configuring retry behavior across campaign types"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    # Retry attempt settings
    max_attempts = models.PositiveIntegerField(
        default=3,
        help_text="Maximum number of retry attempts"
    )
    base_delay_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Base delay in minutes between retries"
    )
    backoff_factor = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=2.0,
        help_text="Multiplier for exponential backoff (e.g., 2.0 means double the delay each time)"
    )
    max_delay_minutes = models.PositiveIntegerField(
        default=1440,
        help_text="Maximum delay in minutes (caps the exponential backoff)"
    )
    
    # Retry conditions
    retry_on_failure = models.BooleanField(
        default=True,
        help_text="Whether to retry on failure"
    )
    retry_on_timeout = models.BooleanField(
        default=True,
        help_text="Whether to retry on timeout"
    )
    retry_on_error = models.BooleanField(
        default=True,
        help_text="Whether to retry on error"
    )
    
    # Notification settings
    notify_on_max_retries = models.BooleanField(
        default=True,
        help_text="Whether to send notification when max retries are reached"
    )
    notify_recipients = models.JSONField(
        default=list,
        blank=True,
        help_text="List of email addresses to notify"
    )
    
    # Status tracking
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_retry_strategies'
    )

    class Meta:
        managed = False
        db_table = 'retry_strategy'
        verbose_name_plural = 'Retry Strategies'
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        """Validate retry strategy configuration"""
        super().clean()
        
        if self.max_attempts < 1:
            raise ValidationError("max_attempts must be at least 1")
        
        if self.base_delay_minutes < 1:
            raise ValidationError("base_delay_minutes must be at least 1")
        
        if self.backoff_factor <= 0:
            raise ValidationError("backoff_factor must be greater than 0")
        
        if self.max_delay_minutes < self.base_delay_minutes:
            raise ValidationError("max_delay_minutes must be greater than or equal to base_delay_minutes")

    def get_delay_for_attempt(self, attempt):
        """
        Calculate the delay for a specific retry attempt
        
        Args:
            attempt: The current retry attempt number (1-based)
            
        Returns:
            int: Delay in minutes
        """
        if attempt < 1 or attempt > self.max_attempts:
            return 0
            
        delay = self.base_delay_minutes * (self.backoff_factor ** (attempt - 1))
        return int(min(delay, self.max_delay_minutes))

    @classmethod
    def get_default_strategy(cls):
        """Get or create the default retry strategy"""
        strategy, _ = cls.objects.get_or_create(
            name='Default Strategy',
            defaults={
                'description': 'Default retry strategy with exponential backoff',
                'max_attempts': 3,
                'base_delay_minutes': 60,
                'backoff_factor': 2.0,
                'max_delay_minutes': 1440,
                'retry_on_failure': True,
                'retry_on_timeout': True,
                'retry_on_error': True,
                'notify_on_max_retries': True
            }
        )
        return strategy 