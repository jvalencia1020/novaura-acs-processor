from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from communication_processor.models import SQSMessage, CommunicationEvent, ChannelProcessor


@admin.register(SQSMessage)
class SQSMessageAdmin(admin.ModelAdmin):
    list_display = [
        'message_id', 'status', 'queue_url', 'retry_count', 
        'received_at', 'processed_at'
    ]
    list_filter = ['status', 'received_at', 'processed_at']
    search_fields = ['message_id', 'receipt_handle']
    readonly_fields = [
        'message_id', 'receipt_handle', 'queue_url', 'message_body',
        'received_at', 'processed_at'
    ]
    ordering = ['-received_at']
    
    fieldsets = (
        ('Message Information', {
            'fields': ('message_id', 'receipt_handle', 'queue_url')
        }),
        ('Processing Status', {
            'fields': ('status', 'retry_count', 'max_retries', 'error_message')
        }),
        ('Timestamps', {
            'fields': ('received_at', 'processed_at')
        }),
        ('Message Data', {
            'fields': ('message_body',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False  # SQS messages are created by the processor


@admin.register(CommunicationEvent)
class CommunicationEventAdmin(admin.ModelAdmin):
    list_display = [
        'event_type', 'channel_type', 'external_id', 'lead_link',
        'conversation_link', 'nurturing_campaign', 'created_at'
    ]
    list_filter = [
        'event_type', 'channel_type', 'created_at', 'updated_at',
        'nurturing_campaign'
    ]
    search_fields = ['external_id', 'event_data']
    readonly_fields = [
        'external_id', 'event_data', 'raw_data', 'created_at', 'updated_at'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Event Information', {
            'fields': ('event_type', 'channel_type', 'external_id')
        }),
        ('Relationships', {
            'fields': ('sqs_message', 'lead', 'account', 'nurturing_campaign',
                      'conversation', 'conversation_message', 'conversation_thread')
        }),
        ('Event Data', {
            'fields': ('event_data', 'raw_data'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('processed_by', 'created_at', 'updated_at')
        }),
    )
    
    def lead_link(self, obj):
        if obj.lead:
            url = reverse('admin:external_models_lead_change', args=[obj.lead.id])
            return format_html('<a href="{}">{}</a>', url, obj.lead)
        return '-'
    lead_link.short_description = 'Lead'
    
    def conversation_link(self, obj):
        if obj.conversation:
            url = reverse('admin:external_models_conversation_change', args=[obj.conversation.id])
            return format_html('<a href="{}">{}</a>', url, obj.conversation.twilio_sid)
        return '-'
    conversation_link.short_description = 'Conversation'
    
    def has_add_permission(self, request):
        return False  # Events are created by the processor


@admin.register(ChannelProcessor)
class ChannelProcessorAdmin(admin.ModelAdmin):
    list_display = [
        'channel_type', 'is_active', 'queue_url', 'batch_size',
        'visibility_timeout', 'max_retries', 'created_at'
    ]
    list_filter = ['channel_type', 'is_active', 'created_at', 'updated_at']
    search_fields = ['channel_type', 'queue_url']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['channel_type']
    
    fieldsets = (
        ('Channel Configuration', {
            'fields': ('channel_type', 'is_active', 'queue_url')
        }),
        ('Processor Settings', {
            'fields': ('processor_class', 'config')
        }),
        ('Processing Settings', {
            'fields': ('batch_size', 'visibility_timeout', 'max_retries')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing an existing object
            return self.readonly_fields + ('channel_type',)
        return self.readonly_fields
