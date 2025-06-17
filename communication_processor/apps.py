from django.apps import AppConfig


class CommunicationProcessorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'communication_processor'
    verbose_name = 'Communication Processor'
    
    def ready(self):
        """Import signals when the app is ready."""
        import communication_processor.signals
