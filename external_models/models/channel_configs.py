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
    # Platform Configuration
    platform = models.CharField(
        max_length=20, 
        choices=[
            ('bland_ai', 'Bland AI'),
            ('vapi', 'VAPI'),
            ('elevenlabs', 'ElevenLabs'),
            ('twilio', 'Twilio'),
        ],
        default='bland_ai'
    )
    
    # Core Configuration
    content = models.TextField(blank=True, null=True)
    template = models.ForeignKey('MessageTemplate', on_delete=models.SET_NULL, null=True, blank=True, related_name='voice_configs')
    from_endpoint = models.ForeignKey(ContactEndpoint, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    
    # Voice Configuration (normalized common fields)
    voice_id = models.CharField(max_length=255, blank=True, null=True, help_text="Platform-specific voice ID")
    voice_name = models.CharField(max_length=100, blank=True, null=True, help_text="Human-readable voice name")
    language = models.CharField(max_length=20, blank=True, null=True)
    temperature = models.FloatField(blank=True, null=True, help_text="Voice temperature/similarity (0.0-1.0)")
    
    # Call Configuration (normalized common fields)
    priority = models.CharField(max_length=10, choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')], blank=True, null=True)
    max_duration = models.PositiveIntegerField(blank=True, null=True, help_text="Maximum call duration in minutes")
    record_call = models.BooleanField(default=False)
    call_timeout = models.PositiveIntegerField(blank=True, null=True, help_text="Timeout in seconds")
    
    # Retry Configuration (normalized common fields)
    retry_attempts = models.PositiveIntegerField(blank=True, null=True)
    retry_delay = models.PositiveIntegerField(blank=True, null=True, help_text="Delay in seconds")
    
    # Voicemail Configuration (normalized common fields)
    voicemail_message = models.TextField(blank=True, null=True)
    voicemail_action = models.CharField(
        max_length=20,
        choices=[
            ('hangup', 'Hang Up'),
            ('leave_message', 'Leave Message'),
            ('ignore', 'Ignore')
        ],
        blank=True,
        null=True
    )
    
    # Platform-specific configuration (JSON)
    platform_config = models.JSONField(
        blank=True, 
        null=True, 
        help_text="Platform-specific configuration options"
    )
    
    # Webhook configuration (JSON for flexibility)
    webhook_config = models.JSONField(
        blank=True, 
        null=True, 
        help_text="Webhook configuration including URL and events"
    )
    
    # Metadata (JSON for extensibility)
    metadata = models.JSONField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'acs_voiceconfig'

    def clean(self):
        super().clean()
        if self.from_endpoint and 'voice' not in self.from_endpoint.get_channel_list():
            raise ValidationError("Selected endpoint must be a voice endpoint")
        
        # Platform-specific validation
        self._validate_platform_config()

    def _validate_platform_config(self):
        """Validate platform-specific configuration"""
        if not self.platform_config:
            return
            
        if self.platform == 'bland_ai':
            self._validate_bland_ai_config()
        elif self.platform == 'vapi':
            self._validate_vapi_config()
        elif self.platform == 'elevenlabs':
            self._validate_elevenlabs_config()

    def _validate_bland_ai_config(self):
        """Validate Bland AI specific configuration"""
        config = self.platform_config or {}
        
        # Validate Bland AI specific fields
        if 'interruption_threshold' in config and not isinstance(config['interruption_threshold'], int):
            raise ValidationError("interruption_threshold must be an integer")
        
        if 'background_track' in config and not config['background_track'].startswith('http'):
            raise ValidationError("background_track must be a valid URL")
        
        if 'pathway_version' in config and not isinstance(config['pathway_version'], int):
            raise ValidationError("pathway_version must be an integer")
        
        if 'max_duration' in config and not isinstance(config['max_duration'], int):
            raise ValidationError("max_duration must be an integer")
        
        if 'temperature' in config and not isinstance(config['temperature'], (int, float)):
            raise ValidationError("temperature must be a number")
        
        if 'dynamic_data' in config and not isinstance(config['dynamic_data'], list):
            raise ValidationError("dynamic_data must be a list")
        
        if 'keywords' in config and not isinstance(config['keywords'], list):
            raise ValidationError("keywords must be a list")
        
        if 'pronunciation_guide' in config and not isinstance(config['pronunciation_guide'], list):
            raise ValidationError("pronunciation_guide must be a list")
        
        if 'webhook_events' in config and not isinstance(config['webhook_events'], list):
            raise ValidationError("webhook_events must be a list")
        
        if 'available_tags' in config and not isinstance(config['available_tags'], list):
            raise ValidationError("available_tags must be a list")

    def _validate_vapi_config(self):
        """Validate VAPI specific configuration"""
        config = self.platform_config or {}
        
        # Validate VAPI specific fields
        if 'assistant' in config:
            assistant = config['assistant']
            if 'model' in assistant and assistant['model'] not in ['gpt-4', 'gpt-3.5-turbo']:
                raise ValidationError("Invalid VAPI assistant model")

    def _validate_elevenlabs_config(self):
        """Validate ElevenLabs specific configuration"""
        config = self.platform_config or {}
        
        # Validate ElevenLabs specific fields
        if 'voice_settings' in config:
            voice_settings = config['voice_settings']
            if 'stability' in voice_settings and not 0 <= voice_settings['stability'] <= 1:
                raise ValidationError("stability must be between 0 and 1")

    def get_from_number(self):
        return self.from_endpoint.value if self.from_endpoint else None

    def get_platform_config(self):
        """Get complete configuration for the selected platform"""
        base_config = {
            'phone_number': None,  # Will be set by caller
            'from': self.get_from_number(),
            'content': self.content,
            'voice': self.voice_id,
            'language': self.language,
            'max_duration': self.max_duration,
            'record': self.record_call,
            'metadata': self.metadata,
        }
        
        # Add webhook config
        if self.webhook_config:
            base_config.update(self.webhook_config)
        
        # Add platform-specific configuration
        if self.platform == 'bland_ai':
            return self._get_bland_ai_config(base_config)
        elif self.platform == 'vapi':
            return self._get_vapi_config(base_config)
        elif self.platform == 'elevenlabs':
            return self._get_elevenlabs_config(base_config)
        
        return base_config

    def _get_bland_ai_config(self, base_config):
        """Get Bland AI specific configuration"""
        config = base_config.copy()
        
        # Map normalized fields to Bland AI API
        config.update({
            'task': self.content,  # Bland AI uses 'task' instead of 'content'
            'voice': self.voice_id,
            'language': self.language,
            'max_duration': self.max_duration,
            'record': self.record_call,
            'metadata': self.metadata,
        })
        
        # Map voicemail fields
        if self.voicemail_message:
            config['voicemail_message'] = self.voicemail_message
        if self.voicemail_action:
            config['voicemail_action'] = self.voicemail_action
        
        # Add webhook configuration
        if self.webhook_config:
            if 'url' in self.webhook_config:
                config['webhook'] = self.webhook_config['url']
            if 'events' in self.webhook_config:
                config['webhook_events'] = self.webhook_config['events']
        
        # Add all Bland AI specific configuration from platform_config
        if self.platform_config:
            # Common Bland AI fields that should be in platform_config
            bland_ai_fields = [
                'pathway_id',
                'background_track',
                'first_sentence',
                'wait_for_greeting',
                'block_interruptions',
                'interruption_threshold',
                'model',
                'temperature',
                'dynamic_data',
                'keywords',
                'pronunciation_guide',
                'transfer_phone_number',
                'transfer_list',
                'pathway_version',
                'local_dialing',
                'voicemail_sms',
                'dispatch_hours',
                'ignore_button_press',
                'timezone',
                'request_data',
                'tools',
                'start_time',
                'retry',
                'citation_schema_id',
                'analysis_preset',
                'available_tags',
                'geospatial_dialing',
                'precall_dtmf_sequence'
            ]
            
            for field in bland_ai_fields:
                if field in self.platform_config:
                    config[field] = self.platform_config[field]
        
        return config

    def _get_vapi_config(self, base_config):
        """Get VAPI specific configuration"""
        config = base_config.copy()
        config.update({
            'assistant': {
                'name': self.voice_name,
                'model': self.platform_config.get('assistant', {}).get('model', 'gpt-4'),
                'voice': self.voice_id,
                'interruptions': not self.platform_config.get('block_interruptions', False),
            },
            'voice': {
                'provider': self.platform_config.get('voice', {}).get('provider', 'deepgram'),
                'voiceId': self.voice_id,
            },
            'maxDurationSeconds': (self.max_duration or 5) * 60,
        })
        
        # Add any additional platform-specific config
        if self.platform_config:
            config.update(self.platform_config)
        
        return config

    def _get_elevenlabs_config(self, base_config):
        """Get ElevenLabs specific configuration"""
        config = base_config.copy()
        config.update({
            'voice_id': self.voice_id,
            'voice_settings': {
                'similarity_boost': self.temperature,
                'stability': self.platform_config.get('voice_settings', {}).get('stability', 0.5),
            },
            'model_id': self.platform_config.get('model_id', 'eleven_monolingual_v1'),
        })
        
        # Add any additional platform-specific config
        if self.platform_config:
            config.update(self.platform_config)
        
        return config

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
