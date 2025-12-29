from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from external_models.models.external_references import Account, Campaign
from external_models.models.communications import ContactEndpoint
from django.conf import settings


class TollFreeNumber(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('reserved', 'Reserved'),
        ('inactive', 'Inactive'),
    ]
    
    # Foreign key relationships
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='toll_free_numbers')
    
    # Core fields
    number = models.CharField(max_length=20, unique=True)  # e.g., "1-800-123-4567"
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    
    # ISCI UID for codifying purposes
    cta_uid = models.CharField(
        max_length=10, 
        unique=True, 
        blank=True, 
        null=True,
        help_text='Unique identifier for ISCI generation (e.g., T0001)'
    )
    
    provider = models.CharField(max_length=100, blank=True)  # Phone service provider
    monthly_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    setup_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    features = models.JSONField(default=list)  # Call forwarding, voicemail, etc.
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        ordering = ['number']
        indexes = [
            models.Index(fields=['account', 'status']),
            models.Index(fields=['cta_uid']),  # Index for ISCI lookups
        ]
        
    def __str__(self):
        return self.number


class Keyword(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('reserved', 'Reserved'),
        ('inactive', 'Inactive'),
    ]
    
    # Foreign key relationships
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='keywords')
    endpoint = models.ForeignKey(
        ContactEndpoint,
        on_delete=models.CASCADE,
        related_name='keywords',
        help_text='SMS endpoint (short code) for this keyword'
    )
    
    # Core fields
    keyword = models.CharField(max_length=50)  # The actual keyword text
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    
    # ISCI UID for codifying purposes
    cta_uid = models.CharField(
        max_length=10, 
        unique=True, 
        blank=True, 
        null=True,
        help_text='Unique identifier for ISCI generation (e.g., K0001)'
    )
    
    carrier = models.CharField(max_length=100, blank=True)  # Mobile carrier
    monthly_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    setup_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    features = models.JSONField(default=list)  # Auto-response, opt-out, etc.
    compliance_info = models.JSONField(default=dict)  # TCPA compliance, opt-in requirements
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        ordering = ['keyword', 'endpoint']
        unique_together = ['keyword', 'endpoint']
        indexes = [
            models.Index(fields=['account', 'status']),
            models.Index(fields=['keyword', 'endpoint']),
            models.Index(fields=['endpoint', 'status']),
            models.Index(fields=['cta_uid']),  # Index for ISCI lookups
        ]
        
    def __str__(self):
        endpoint_value = self.endpoint.value if self.endpoint else 'N/A'
        return f"{self.keyword} ({endpoint_value})"


class URLDomain(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('reserved', 'Reserved'),
        ('inactive', 'Inactive'),
        ('active', 'Active'),  # Added to match your example
    ]
    
    # Foreign key relationships
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='url_domains')
    
    # Core fields
    domain = models.CharField(max_length=255, unique=True)  # e.g., "example.com"
    owner = models.CharField(max_length=100, blank=True, help_text='Owner of the domain')
    owner_of_brand = models.CharField(max_length=100, blank=True, help_text='Owner of the brand')
    use_case = models.CharField(max_length=200, blank=True, help_text='Primary use case for the domain')
    expiration_date = models.DateField(null=True, blank=True, help_text='Domain expiration date')
    annual_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    auto_renew = models.BooleanField(default=True, help_text='Whether domain auto-renews')
    auto_renew_date = models.DateField(null=True, blank=True, help_text='Auto-renewal date')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    character_count = models.PositiveIntegerField(null=True, blank=True, help_text='Character count of the domain')
    
    # ISCI UID for codifying purposes
    cta_uid = models.CharField(
        max_length=10, 
        unique=True, 
        blank=True, 
        null=True,
        help_text='Unique identifier for ISCI generation (e.g., U0001)'
    )
    
    # Additional existing fields
    registrar = models.CharField(max_length=100, blank=True)  # Domain registrar
    setup_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    ssl_certificate = models.BooleanField(default=False)
    hosting_provider = models.CharField(max_length=100, blank=True)
    features = models.JSONField(default=list, null=True, blank=True)  # Analytics, tracking, etc.
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        ordering = ['domain']
        indexes = [
            models.Index(fields=['account', 'status']),
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['expiration_date']),
            models.Index(fields=['auto_renew']),
            models.Index(fields=['auto_renew_date']),
            models.Index(fields=['cta_uid']),  # Index for ISCI lookups
        ]
        
    def __str__(self):
        if self.owner_of_brand:
            return f"{self.domain} ({self.owner_of_brand})"
        return self.domain


class TollFreeNumberCampaignMapping(models.Model):
    """
    Mapping table to connect TollFreeNumber to CRM Campaign
    """
    toll_free_number = models.ForeignKey(TollFreeNumber, on_delete=models.CASCADE, related_name='campaign_mappings')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='toll_free_number_mappings')
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_toll_free_numbers')
    start_date = models.DateTimeField(help_text='When this mapping becomes active')
    end_date = models.DateTimeField(null=True, blank=True, help_text='When this mapping expires (leave blank for indefinite)')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        managed = False
        db_table = 'marketing_tracking_toll_free_number_campaign_mapping'
        unique_together = ['toll_free_number', 'campaign']
        ordering = ['-assigned_at']
        indexes = [
            models.Index(fields=['toll_free_number', 'campaign']),
            models.Index(fields=['campaign', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['is_active', 'start_date', 'end_date']),
        ]
        
    def __str__(self):
        return f"{self.toll_free_number.number} -> {self.campaign.name}"
    
    def is_currently_active(self):
        """Check if this mapping is currently active based on dates and status"""
        from django.utils import timezone
        now = timezone.now()
        
        if not self.is_active:
            return False
            
        if self.start_date > now:
            return False
            
        if self.end_date and self.end_date < now:
            return False
            
        return True


class KeywordCampaignMapping(models.Model):
    """
    Mapping table to connect Keyword to CRM Campaign
    """
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, related_name='campaign_mappings')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='keyword_mappings')
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_keywords')
    start_date = models.DateTimeField(help_text='When this mapping becomes active')
    end_date = models.DateTimeField(null=True, blank=True, help_text='When this mapping expires (leave blank for indefinite)')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        managed = False
        db_table = 'marketing_tracking_keyword_campaign_mapping'
        unique_together = ['keyword', 'campaign']
        ordering = ['-assigned_at']
        indexes = [
            models.Index(fields=['keyword', 'campaign']),
            models.Index(fields=['campaign', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['is_active', 'start_date', 'end_date']),
        ]
        
    def __str__(self):
        endpoint_value = self.keyword.endpoint.value if self.keyword and self.keyword.endpoint else 'N/A'
        return f"{self.keyword.keyword} ({endpoint_value}) -> {self.campaign.name}"
    
    def is_currently_active(self):
        """Check if this mapping is currently active based on dates and status"""
        from django.utils import timezone
        now = timezone.now()
        
        if not self.is_active:
            return False
            
        if self.start_date > now:
            return False
            
        if self.end_date and self.end_date < now:
            return False
            
        return True


class URLDomainCampaignMapping(models.Model):
    """
    Mapping table to connect URLDomain to CRM Campaign
    """
    url_domain = models.ForeignKey(URLDomain, on_delete=models.CASCADE, related_name='campaign_mappings')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='url_domain_mappings')
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_url_domains')
    start_date = models.DateTimeField(help_text='When this mapping becomes active')
    end_date = models.DateTimeField(null=True, blank=True, help_text='When this mapping expires (leave blank for indefinite)')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        managed = False
        db_table = 'marketing_tracking_url_domain_campaign_mapping'
        unique_together = ['url_domain', 'campaign']
        ordering = ['-assigned_at']
        indexes = [
            models.Index(fields=['url_domain', 'campaign']),
            models.Index(fields=['campaign', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['is_active', 'start_date', 'end_date']),
        ]
        
    def __str__(self):
        return f"{self.url_domain.domain} -> {self.campaign.name}"
    
    def is_currently_active(self):
        """Check if this mapping is currently active based on dates and status"""
        from django.utils import timezone
        now = timezone.now()
        
        if not self.is_active:
            return False
            
        if self.start_date > now:
            return False
            
        if self.end_date and self.end_date < now:
            return False
            
        return True


# Signal handlers to auto-generate CTA UIDs
@receiver(pre_save, sender=TollFreeNumber)
def generate_toll_free_uid(sender, instance, **kwargs):
    """Auto-generate CTA UID for TollFreeNumber if not provided"""
    if not instance.cta_uid:
        from ..services import CTAUIDService
        instance.cta_uid = CTAUIDService.generate_uid('toll_free', instance)


@receiver(pre_save, sender=Keyword)
def generate_keyword_uid(sender, instance, **kwargs):
    """Auto-generate CTA UID for Keyword if not provided"""
    if not instance.cta_uid:
        from ..services import CTAUIDService
        instance.cta_uid = CTAUIDService.generate_uid('keyword', instance)


@receiver(pre_save, sender=URLDomain)
def generate_url_domain_uid(sender, instance, **kwargs):
    """Auto-generate CTA UID for URLDomain if not provided"""
    if not instance.cta_uid:
        from ..services import CTAUIDService
        instance.cta_uid = CTAUIDService.generate_uid('url_domain', instance)
