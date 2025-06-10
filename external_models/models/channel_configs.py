from django.db import models
from django.core.exceptions import ValidationError
from .communications import ContactEndpoint
from .messages import MessageTemplate

class EmailConfig(models.Model):
    content = models.TextField(blank=True, null=True)
    template = models.ForeignKey(MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='email_configs')
    subject = models.CharField(max_length=255, blank=True, null=True)
    from_endpoint = models.ForeignKey(ContactEndpoint, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    from_name = models.CharField(max_length=255, blank=True, null=True)
    reply_to = models.EmailField(blank=True, null=True)
    priority = models.CharField(max_length=10, choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')], blank=True, null=True)
    track_opens = models.BooleanField(default=False)
    track_clicks = models.BooleanField(default=False)
    attachments = models.JSONField(blank=True, null=True, help_text="List of attachments: [{name, url}]")

    class Meta:
        managed = False
        db_table = 'acs_emailconfig'

    def clean(self):
        super().clean()
        if self.from_endpoint and 'email' not in self.from_endpoint.get_channel_list():
            raise ValidationError("Selected endpoint must be an email endpoint")

    def get_from_email(self):
        return self.from_endpoint.value if self.from_endpoint else self.from_email

class SMSConfig(models.Model):
    content = models.TextField(blank=True, null=True)
    template = models.ForeignKey(MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='sms_configs')
    from_endpoint = models.ForeignKey(ContactEndpoint, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    priority = models.CharField(max_length=10, choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')], blank=True, null=True)
    track_delivery = models.BooleanField(default=False)
    track_replies = models.BooleanField(default=False)
    media_urls = models.JSONField(blank=True, null=True, help_text="List of media URLs")

    class Meta:
        managed = False
        db_table = 'acs_smsconfig'

    def clean(self):
        super().clean()
        if self.from_endpoint and 'sms' not in self.from_endpoint.get_channel_list():
            raise ValidationError("Selected endpoint must be an SMS endpoint")

    def get_from_number(self):
        return self.from_endpoint.value if self.from_endpoint else self.from_number

class VoiceConfig(models.Model):
    content = models.TextField(blank=True, null=True)
    template = models.ForeignKey(MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='voice_configs')
    from_endpoint = models.ForeignKey(ContactEndpoint, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    voice = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female')], blank=True, null=True)
    language = models.CharField(max_length=20, blank=True, null=True)
    priority = models.CharField(max_length=10, choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')], blank=True, null=True)
    retry_attempts = models.PositiveIntegerField(blank=True, null=True)
    retry_delay = models.PositiveIntegerField(blank=True, null=True, help_text="Delay in seconds")
    record_call = models.BooleanField(default=False)
    call_timeout = models.PositiveIntegerField(blank=True, null=True, help_text="Timeout in seconds")
    machine_detection = models.CharField(max_length=20, choices=[('true', 'True'), ('false', 'False'), ('prefer_human', 'Prefer Human')], blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'acs_voiceconfig'

    def clean(self):
        super().clean()
        if self.from_endpoint and 'voice' not in self.from_endpoint.get_channel_list():
            raise ValidationError("Selected endpoint must be a voice endpoint")

    def get_from_number(self):
        return self.from_endpoint.value if self.from_endpoint else self.from_number

class ChatConfig(models.Model):
    content = models.TextField(blank=True, null=True)
    template = models.ForeignKey(MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_configs')
    from_endpoint = models.ForeignKey(ContactEndpoint, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    platform = models.CharField(max_length=20, choices=[('whatsapp', 'WhatsApp'), ('messenger', 'Messenger'), ('telegram', 'Telegram')], blank=True, null=True)
    priority = models.CharField(max_length=10, choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')], blank=True, null=True)
    track_delivery = models.BooleanField(default=False)
    track_read = models.BooleanField(default=False)
    media_urls = models.JSONField(blank=True, null=True, help_text="List of media URLs")
    quick_replies = models.JSONField(blank=True, null=True, help_text="List of quick replies: [{text, value}]")

    class Meta:
        managed = False
        db_table = 'acs_chatconfig'
        
    def clean(self):
        super().clean()
        if self.from_endpoint and 'social' not in self.from_endpoint.get_channel_list():
            raise ValidationError("Selected endpoint must be a social media endpoint")

    def get_from_handle(self):
        return self.from_endpoint.value if self.from_endpoint else None
