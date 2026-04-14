"""
Resolve ContactEndpoint + ContactEndpointEmailSettings and send via Mailgun (native).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from django.core.exceptions import ObjectDoesNotExist

from shared_services.email.base import EmailSendResult
from shared_services.email.registry import get_email_provider_adapter
from shared_services.email.secrets_loader import get_secret_json
from shared_services.template_variable_render import replace_template_variables

if TYPE_CHECKING:
    from external_models.models.channel_configs import EmailConfig
    from external_models.models.communications import ContactEndpoint

logger = logging.getLogger(__name__)


def load_credentials_for_email_settings(email_settings) -> Dict[str, Any]:
    """Resolve Secrets Manager JSON for a ContactEndpointEmailSettings row."""
    arn = getattr(email_settings, 'credentials_secret_arn', None) or ''
    region = getattr(email_settings, 'credentials_secret_region', None)
    return get_secret_json(arn or '', region)


def effective_email_subject(email_config: 'EmailConfig') -> str:
    """Subject for send: EmailConfig.subject wins, else version.subject_text for outbound / hosted."""
    subj = (email_config.subject or '').strip()
    if subj:
        return subj
    mode = getattr(email_config, 'email_content_mode', None)
    if mode in ('outbound_acs', 'hosted_mailgun') and getattr(
        email_config, 'hosted_template_version_id', None
    ):
        ver = email_config.hosted_template_version
        if ver:
            return (ver.subject_text or '').strip()
    return ''


def send_from_contact_endpoint(
    endpoint: 'ContactEndpoint',
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[str] = None,
    tags: Optional[List[str]] = None,
    log_context: Optional[Dict[str, Any]] = None,
) -> EmailSendResult:
    if not endpoint.channels.filter(channel='email').exists():
        raise ValueError('Contact endpoint does not include the email channel')

    try:
        email_settings = endpoint.email_settings
    except ObjectDoesNotExist as e:
        raise ValueError('Contact endpoint has no email_settings configured') from e

    credentials = load_credentials_for_email_settings(email_settings)
    adapter = get_email_provider_adapter(email_settings.provider)
    from_addr = from_email or endpoint.value
    if not from_addr:
        raise ValueError('from_email is required (endpoint.value or explicit from_email)')

    return adapter.send(
        credentials=credentials,
        config=email_settings.config or {},
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        from_email=from_addr,
        reply_to=reply_to,
        tags=tags,
        log_context=log_context,
    )


def _format_from_header(endpoint: 'ContactEndpoint', from_name: Optional[str]) -> str:
    addr = endpoint.value
    if not addr:
        raise ValueError('Contact endpoint value (from address) is missing')
    if from_name and from_name.strip():
        return f'{from_name.strip()} <{addr}>'
    return addr


def render_inline_email_body(
    email_config: 'EmailConfig',
    context: Optional[Dict[str, Any]] = None,
) -> tuple[str, Optional[str]]:
    """Resolve HTML (and optional plain text) for inline mode from MessageTemplate or raw content."""
    context = context or {}
    if email_config.template_id:
        html = email_config.template.replace_variables(context)
        return html, None
    return (email_config.content or '').strip(), None


def send_from_email_config(
    email_config: 'EmailConfig',
    *,
    to_email: str,
    context: Optional[Dict[str, Any]] = None,
    subject_override: Optional[str] = None,
    tags: Optional[List[str]] = None,
    merged_html_body: Optional[str] = None,
    log_context: Optional[Dict[str, Any]] = None,
) -> EmailSendResult:
    """
    inline: MessageTemplate/content via render_inline_email_body, OR merged_html_body when provided
    (e.g. nurturing bulk get_message_content already merged link/keyword).
    outbound_acs: merge hosted_template_version with replace_template_variables.
    """
    from external_models.models.channel_configs import EmailConfig

    if not email_config.from_endpoint_id:
        raise ValueError('EmailConfig.from_endpoint is required')

    endpoint = email_config.from_endpoint
    subject = (subject_override or '').strip() or effective_email_subject(email_config)
    if not subject:
        raise ValueError('subject is required')

    if email_config.email_content_mode == EmailConfig.MODE_INLINE:
        merge_ctx = context if context is not None else {}
        subject = replace_template_variables(subject, merge_ctx)
    if not subject:
        raise ValueError('subject is required')

    if email_config.email_content_mode == EmailConfig.MODE_OUTBOUND_ACS:
        ver = email_config.hosted_template_version
        if not ver:
            raise ValueError('hosted_template_version is required for outbound_acs mode')
        if ver.status != 'approved':
            raise ValueError('hosted_template_version must be approved before send')
        merge_ctx = context if context is not None else {}
        subject_rendered = replace_template_variables(subject, merge_ctx)
        html_body = replace_template_variables(ver.html_body or '', merge_ctx)
        tb = (ver.text_body or '').strip()
        text_body = replace_template_variables(tb, merge_ctx) if tb else None

        return send_from_contact_endpoint(
            endpoint,
            to_email=to_email,
            subject=subject_rendered,
            html_body=html_body,
            text_body=text_body,
            from_email=_format_from_header(endpoint, email_config.from_name),
            reply_to=(email_config.reply_to or None),
            tags=tags,
            log_context=log_context,
        )

    # inline
    if merged_html_body is not None and merged_html_body.strip():
        html_body = merged_html_body.strip()
        return send_from_contact_endpoint(
            endpoint,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=None,
            from_email=_format_from_header(endpoint, email_config.from_name),
            reply_to=(email_config.reply_to or None),
            tags=tags,
            log_context=log_context,
        )

    html_body, text_body = render_inline_email_body(email_config, context)
    if not html_body:
        raise ValueError('inline mode requires template or non-empty content')

    return send_from_contact_endpoint(
        endpoint,
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        from_email=_format_from_header(endpoint, email_config.from_name),
        reply_to=(email_config.reply_to or None),
        tags=tags,
        log_context=log_context,
    )
