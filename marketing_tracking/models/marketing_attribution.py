from django.db import models
from django.utils import timezone
from external_models.models.external_references import Lead


class MarketingAttribution(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='marketing_attributions')
    
    # UTM Parameters
    utm_source = models.CharField(max_length=255, null=True, blank=True)
    utm_medium = models.CharField(max_length=255, null=True, blank=True)
    utm_campaign = models.CharField(max_length=255, null=True, blank=True)
    utm_content = models.CharField(max_length=255, null=True, blank=True)
    utm_term = models.CharField(max_length=255, null=True, blank=True)
    
    # Additional Marketing Data
    referrer = models.URLField(max_length=2048, null=True, blank=True)
    landing_page = models.URLField(max_length=2048, null=True, blank=True)
    device_type = models.CharField(max_length=50, null=True, blank=True)
    browser = models.CharField(max_length=100, null=True, blank=True)
    operating_system = models.CharField(max_length=100, null=True, blank=True)
    
    # Timestamps
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    
    # Additional Fields for Identity Graph
    visitor_id = models.CharField(max_length=255, null=True, blank=True)
    session_id = models.CharField(max_length=255, null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['lead', 'first_seen_at']),
            models.Index(fields=['utm_source', 'utm_medium', 'utm_campaign']),
            models.Index(fields=['visitor_id']),
        ]
    
    def __str__(self):
        return f"Marketing Attribution for {self.lead} - {self.utm_source}"

    def save(self, *args, **kwargs):
        # Update last_seen_at on every save
        self.last_seen_at = timezone.now()
        super().save(*args, **kwargs)
