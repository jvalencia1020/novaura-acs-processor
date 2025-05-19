from django.db import models
from external_models.models.external_references import Account, Campaign, Funnel, Lead


class BlandAICall(models.Model):
    call_id = models.CharField(max_length=255, unique=True)
    account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="bland_ai_calls")
    campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="bland_ai_calls")
    funnel = models.ForeignKey(Funnel, on_delete=models.SET_NULL, null=True, blank=True, related_name="bland_ai_calls")
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="bland_ai_calls")
    call_length = models.FloatField(null=True, blank=True)
    batch_id = models.CharField(max_length=255, null=True, blank=True)
    to_number = models.CharField(max_length=20, null=True, blank=True)
    from_number = models.CharField(max_length=20, null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    request_data = models.JSONField(null=True, blank=True)  # Store the "request_data" object
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(null=True, blank=True)
    inbound = models.BooleanField(null=True, blank=True)
    queue_status = models.CharField(max_length=50, null=True, blank=True)
    endpoint_url = models.URLField(null=True, blank=True)
    max_duration = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    variables = models.JSONField(null=True, blank=True)  # Store the "variables" object
    answered_by = models.CharField(max_length=50, null=True, blank=True)
    record = models.BooleanField(default=False, null=True, blank=True)
    recording_url = models.URLField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)  # Store the "metadata" object
    summary = models.TextField(null=True, blank=True)
    price = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    local_dialing = models.BooleanField(null=True, blank=True)
    call_ended_by = models.CharField(max_length=50, null=True, blank=True)
    pathway_logs = models.JSONField(null=True, blank=True)  # Store pathway logs
    analysis_schema = models.JSONField(null=True, blank=True)
    analysis = models.JSONField(null=True, blank=True)
    concatenated_transcript = models.TextField(null=True, blank=True)
    transcripts = models.JSONField(null=True, blank=True)  # Store the list of transcripts
    status = models.CharField(max_length=50, null=True, blank=True)
    corrected_duration = models.CharField(max_length=50, null=True, blank=True)
    
    # System timestamps
    system_created_at = models.DateTimeField(auto_now_add=True)
    system_updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Call {self.call_id}"

    class Meta:
        managed = False
        db_table = 'bland_ai_call'
        ordering = ['-system_created_at']  # Optional: default ordering by creation date
