from shared_services.email.base import EmailProviderAdapter, EmailSendResult
from shared_services.email.email_dispatch import (
    effective_email_subject,
    load_credentials_for_email_settings,
    send_from_contact_endpoint,
    send_from_email_config,
)

__all__ = [
    'EmailProviderAdapter',
    'EmailSendResult',
    'effective_email_subject',
    'load_credentials_for_email_settings',
    'send_from_contact_endpoint',
    'send_from_email_config',
]
