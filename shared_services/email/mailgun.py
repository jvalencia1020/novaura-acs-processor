"""Mailgun HTTP send (messages API only)."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from shared_services.email.base import EmailProviderAdapter, EmailSendResult

logger = logging.getLogger(__name__)

# Bounded retries for transient Mailgun/network failures.
# Retrying after timeout can duplicate sends if the server accepted the request; keep attempts low.
MAILGUN_POST_MAX_ATTEMPTS = 3
MAILGUN_POST_BASE_DELAY_SEC = 0.5
MAILGUN_POST_MAX_BACKOFF_SEC = 8.0

MAILGUN_US_API = 'https://api.mailgun.net/v3'
MAILGUN_EU_API = 'https://api.eu.mailgun.net/v3'


def mailgun_api_base(config: Dict[str, Any]) -> str:
    if config.get('eu_region'):
        return MAILGUN_EU_API
    return MAILGUN_US_API


def resolve_mailgun_domain(config: Dict[str, Any], credentials: Dict[str, Any]) -> str:
    domain = (config or {}).get('domain') or (credentials or {}).get('domain')
    if not domain or not isinstance(domain, str):
        raise ValueError('Mailgun domain is required in email settings config.domain or secret.domain')
    return domain.strip()


def _retry_after_seconds(response) -> Optional[float]:
    raw = response.headers.get('Retry-After')
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _backoff_sleep(attempt: int, response=None) -> None:
    """Exponential backoff with jitter; honors Retry-After on 429 when parseable."""
    if response is not None and response.status_code == 429:
        ra = _retry_after_seconds(response)
        if ra is not None and ra >= 0:
            time.sleep(min(MAILGUN_POST_MAX_BACKOFF_SEC, ra + random.uniform(0, 0.5)))
            return
    base = min(
        MAILGUN_POST_MAX_BACKOFF_SEC,
        MAILGUN_POST_BASE_DELAY_SEC * (2**attempt),
    )
    time.sleep(base + random.uniform(0, min(1.0, base * 0.25)))


def _post_mailgun_messages(
    *,
    url: str,
    api_key: str,
    form_pairs: List[Tuple[str, str]],
    timeout: int,
) -> Any:
    """POST with retries on timeout, connection errors, 5xx, and 429."""
    import requests
    from requests import RequestException

    for attempt in range(MAILGUN_POST_MAX_ATTEMPTS):
        try:
            resp = requests.post(
                url,
                auth=('api', api_key),
                data=form_pairs,
                timeout=timeout,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < MAILGUN_POST_MAX_ATTEMPTS - 1:
                    logger.warning(
                        'mailgun_post_retry status=%s attempt=%s/%s url=%s',
                        resp.status_code,
                        attempt + 1,
                        MAILGUN_POST_MAX_ATTEMPTS,
                        url,
                    )
                    _backoff_sleep(attempt, resp)
                    continue
            resp.raise_for_status()
            return resp
        except requests.Timeout:
            if attempt < MAILGUN_POST_MAX_ATTEMPTS - 1:
                logger.warning(
                    'mailgun_post_retry timeout attempt=%s/%s url=%s',
                    attempt + 1,
                    MAILGUN_POST_MAX_ATTEMPTS,
                    url,
                )
                _backoff_sleep(attempt, None)
                continue
            raise
        except requests.ConnectionError:
            if attempt < MAILGUN_POST_MAX_ATTEMPTS - 1:
                logger.warning(
                    'mailgun_post_retry connection_error attempt=%s/%s url=%s',
                    attempt + 1,
                    MAILGUN_POST_MAX_ATTEMPTS,
                    url,
                )
                _backoff_sleep(attempt, None)
                continue
            raise
        except RequestException:
            raise
    raise RuntimeError('mailgun_post_retry exhausted without response')


def send_mailgun_message(
    *,
    api_key: str,
    domain: str,
    api_base: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str],
    from_email: str,
    reply_to: Optional[str] = None,
    tags: Optional[List[str]] = None,
    log_context: Optional[Dict[str, Any]] = None,
) -> EmailSendResult:
    try:
        from requests import HTTPError
    except ImportError as e:
        raise ImportError('requests is required for Mailgun') from e

    url = f'{api_base.rstrip("/")}/{domain}/messages'
    text = (
        text_body
        if text_body is not None
        else (html_body[:1000] if len(html_body) > 1000 else html_body)
    )
    form_pairs = [
        ('from', from_email),
        ('to', to_email),
        ('subject', subject),
        ('html', html_body),
        ('text', text),
    ]
    if reply_to:
        form_pairs.append(('h:Reply-To', reply_to))
    if tags:
        for tag in tags[:3]:
            if tag:
                form_pairs.append(('o:tag', tag[:128]))

    ctx = log_context or {}
    try:
        resp = _post_mailgun_messages(
            url=url,
            api_key=api_key,
            form_pairs=form_pairs,
            timeout=30,
        )
        result = resp.json()
        message_id = result.get('id')
        logger.info(
            'mailgun_send_ok mailgun_message_id=%s contact_endpoint_id=%s nurturing_campaign_id=%s '
            'bulk_campaign_message_id=%s send_idempotency_key=%s',
            message_id,
            ctx.get('contact_endpoint_id'),
            ctx.get('nurturing_campaign_id'),
            ctx.get('bulk_campaign_message_id'),
            ctx.get('send_idempotency_key'),
        )
        return EmailSendResult(
            message_id=message_id,
            message=result.get('message', 'Queued'),
            raw_response=result,
        )
    except HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        body_preview = ''
        if e.response is not None and e.response.text:
            body_preview = (e.response.text[:500] + '…') if len(e.response.text) > 500 else e.response.text
        logger.error(
            'mailgun_send_fail http_status=%s mailgun_message_id=%s contact_endpoint_id=%s '
            'nurturing_campaign_id=%s bulk_campaign_message_id=%s send_idempotency_key=%s '
            'error=%s body_preview=%s',
            status,
            None,
            ctx.get('contact_endpoint_id'),
            ctx.get('nurturing_campaign_id'),
            ctx.get('bulk_campaign_message_id'),
            ctx.get('send_idempotency_key'),
            e,
            body_preview,
        )
        raise
    except Exception as e:
        logger.error(
            'mailgun_send_fail mailgun_message_id=%s contact_endpoint_id=%s nurturing_campaign_id=%s '
            'bulk_campaign_message_id=%s send_idempotency_key=%s error=%s',
            None,
            ctx.get('contact_endpoint_id'),
            ctx.get('nurturing_campaign_id'),
            ctx.get('bulk_campaign_message_id'),
            ctx.get('send_idempotency_key'),
            e,
        )
        raise


class MailgunEmailAdapter(EmailProviderAdapter):
    provider_name = 'mailgun'

    def send(
        self,
        *,
        credentials: Dict[str, Any],
        config: Dict[str, Any],
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str],
        from_email: str,
        reply_to: Optional[str] = None,
        tags: Optional[List[str]] = None,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> EmailSendResult:
        api_key = credentials.get('api_key') or credentials.get('MAILGUN_API_KEY')
        if not api_key:
            raise ValueError('Mailgun credentials missing api_key')
        domain = resolve_mailgun_domain(config, credentials)
        base = mailgun_api_base(config)
        return send_mailgun_message(
            api_key=api_key,
            domain=domain,
            api_base=base,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_email=from_email,
            reply_to=reply_to,
            tags=tags,
            log_context=log_context,
        )
