"""Resolve email provider adapter by ContactEndpointEmailSettings.provider value."""

from __future__ import annotations

from shared_services.email.base import EmailProviderAdapter

_PROVIDER_MAILGUN = 'mailgun'


def get_email_provider_adapter(provider: str) -> EmailProviderAdapter:
    if provider == _PROVIDER_MAILGUN:
        from shared_services.email.mailgun import MailgunEmailAdapter

        return MailgunEmailAdapter()
    raise ValueError(f'Unknown or unsupported email provider: {provider!r}')
