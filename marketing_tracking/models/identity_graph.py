from django.db import models
from external_models.models.external_references import Lead


class IdentityGraph(models.Model):
    """
    Represents a node in the identity graph that can be linked to multiple leads
    and other identity nodes through various identifiers.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        db_table = 'marketing_tracking_identity_graph'
    
    def __str__(self):
        return f"Identity Graph Node {self.id}"


class IdentityNode(models.Model):
    """
    Represents a specific identifier (email, phone, etc.) that can be linked to
    an identity graph node and potentially multiple leads.
    """
    IDENTIFIER_TYPES = [
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('cookie', 'Cookie'),
        ('device_id', 'Device ID'),
        ('visitor_id', 'Visitor ID'),
        ('ip_address', 'IP Address'),
    ]
    
    identity_graph = models.ForeignKey(IdentityGraph, on_delete=models.CASCADE, related_name='nodes')
    identifier_type = models.CharField(max_length=20, choices=IDENTIFIER_TYPES)
    identifier_value = models.CharField(max_length=255)
    confidence_score = models.FloatField(default=1.0)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        unique_together = ['identifier_type', 'identifier_value']
        indexes = [
            models.Index(fields=['identifier_type', 'identifier_value']),
            models.Index(fields=['identity_graph']),
        ]
    
    def __str__(self):
        return f"{self.get_identifier_type_display()}: {self.identifier_value}"


class LeadIdentityMapping(models.Model):
    """
    Maps leads to identity graph nodes, allowing for multiple leads to be
    associated with the same identity.
    """
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='identity_mappings')
    identity_graph = models.ForeignKey(IdentityGraph, on_delete=models.CASCADE, related_name='lead_mappings')
    confidence_score = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False
        unique_together = ['lead', 'identity_graph']
        indexes = [
            models.Index(fields=['lead', 'identity_graph']),
        ]
    
    def __str__(self):
        return f"Lead {self.lead.id} -> Identity Graph {self.identity_graph.id}"
