"""Postmark HTTP send (Email API only)."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from shared_services.email.base import EmailProviderAdapter, EmailSendResult
from shared_services.email.mailgun import html_to_plain_text

logger = logging.getLogger(__name__)

# Bounded retries for transient Postmark/network failures.
# Retrying after timeout can duplicate sends if the server accepted the request; keep attempts low.
POSTMARK_POST_MAX_ATTEMPTS = 3
POSTMARK_POST_BASE_DELAY_SEC = 0.5
POSTMARK_POST_MAX_BACKOFF_SEC = 8.0

POSTMARK_API = 'https://api.postmarkapp.com/email'
POSTMARK_DEFAULT_MESSAGE_STREAM = 'broadcast'
POSTMARK_TRACK_LINKS_VALUES = {'None', 'HtmlAndText', 'HtmlOnly', 'TextOnly', 'Subscription'}


def _resolve_server_token(credentials: Dict[str, Any]) -> str:
    token = (
        (credentials or {}).get('api_key')
        or (credentials or {}).get('server_token')
        or (credentials or {}).get('POSTMARK_SERVER_TOKEN')
    )
    if not token or not isinstance(token, str):
        raise ValueError('Postmark credentials missing api_key or server_token')
    return token.strip()


def _postmark_track_links_value(config: Dict[str, Any]) -> Optional[str]:
    raw = (config or {}).get('track_links')
    if raw is None or raw == '':
        return None
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if value not in POSTMARK_TRACK_LINKS_VALUES:
        raise ValueError(f'postmark track_links must be one of {sorted(POSTMARK_TRACK_LINKS_VALUES)}')
    return value


def _clean_postmark_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    clean: Dict[str, str] = {}
    for i, (key, value) in enumerate(metadata.items()):
        if i >= 10:
            break
        if key is None or value is None:
            continue
        key_str, value_str = str(key).strip(), str(value).strip()
        if not key_str:
            continue
        clean[key_str[:80]] = value_str[:256]
    return clean


def _optional_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ''


def _postmark_headers(extra_headers: Optional[Dict[str, str]]) -> List[Dict[str, str]]:
    if not extra_headers:
        return []
    headers: List[Dict[str, str]] = []
    for name, value in extra_headers.items():
        if name and value:
            headers.append({'Name': str(name), 'Value': str(value)})
    return headers


def _retry_after_seconds(response) -> Optional[float]:
    headers = getattr(response, 'headers', None) or {}
    raw = headers.get('Retry-After')
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _backoff_sleep(attempt: int, response=None) -> None:
    """Exponential backoff with jitter; honors Retry-After on 429 when parseable."""
    if response is not None and response.status_code == 429:
        retry_after = _retry_after_seconds(response)
        if retry_after is not None and retry_after >= 0:
            time.sleep(min(POSTMARK_POST_MAX_BACKOFF_SEC, retry_after + random.uniform(0, 0.5)))
            return
    base = min(
        POSTMARK_POST_MAX_BACKOFF_SEC,
        POSTMARK_POST_BASE_DELAY_SEC * (2**attempt),
    )
    time.sleep(base + random.uniform(0, min(1.0, base * 0.25)))


def _postmark_error_payload(response) -> Tuple[Optional[Any], str]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    error_code = payload.get('ErrorCode')
    message = payload.get('Message') or (getattr(response, 'text', '') or '')[:500]
    return error_code, message


def _raise_postmark_http_error(response) -> None:
    import requests

    error_code, message = _postmark_error_payload(response)
    detail = f'Postmark {response.status_code} ErrorCode={error_code} Message={message}'
    raise requests.HTTPError(detail, response=response)


def _post_postmark_email(
    *,
    headers: Dict[str, str],
    body: Dict[str, Any],
    timeout: int,
) -> Any:
    """POST with retries on timeout, connection errors, 5xx, and 429."""
    import requests
    from requests import RequestException

    for attempt in range(POSTMARK_POST_MAX_ATTEMPTS):
        try:
            resp = requests.post(
                POSTMARK_API,
                headers=headers,
                json=body,
                timeout=timeout,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < POSTMARK_POST_MAX_ATTEMPTS - 1:
                    logger.warning(
                        'postmark_post_retry status=%s attempt=%s/%s url=%s',
                        resp.status_code,
                        attempt + 1,
                        POSTMARK_POST_MAX_ATTEMPTS,
                        POSTMARK_API,
                    )
                    _backoff_sleep(attempt, resp)
                    continue
            if not resp.ok:
                _raise_postmark_http_error(resp)
            return resp
        except requests.Timeout:
            if attempt < POSTMARK_POST_MAX_ATTEMPTS - 1:
                logger.warning(
                    'postmark_post_retry timeout attempt=%s/%s url=%s',
                    attempt + 1,
                    POSTMARK_POST_MAX_ATTEMPTS,
                    POSTMARK_API,
                )
                _backoff_sleep(attempt, None)
                continue
            raise
        except requests.ConnectionError:
            if attempt < POSTMARK_POST_MAX_ATTEMPTS - 1:
                logger.warning(
                    'postmark_post_retry connection_error attempt=%s/%s url=%s',
                    attempt + 1,
                    POSTMARK_POST_MAX_ATTEMPTS,
                    POSTMARK_API,
                )
                _backoff_sleep(attempt, None)
                continue
            raise
        except RequestException:
            raise
    raise RuntimeError('postmark_post_retry exhausted without response')


def send_postmark_email(
    *,
    server_token: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str],
    from_email: str,
    reply_to: Optional[str] = None,
    tags: Optional[List[str]] = None,
    message_stream: Optional[str] = None,
    track_opens: Optional[bool] = None,
    track_links: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    log_context: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> EmailSendResult:
    try:
        from requests import HTTPError
    except ImportError as e:
        raise ImportError('requests is required for Postmark') from e

    if text_body is not None and text_body.strip():
        text = text_body
    elif html_body.strip():
        text = html_to_plain_text(html_body)
    else:
        text = '' if text_body is not None else ''

    body: Dict[str, Any] = {
        'From': from_email,
        'To': to_email,
        'Subject': subject,
        'HtmlBody': html_body,
        'TextBody': text,
    }
    if reply_to:
        body['ReplyTo'] = reply_to
    if message_stream:
        body['MessageStream'] = message_stream
    if tags:
        tag_values = [tag for tag in tags[:10] if tag]
        if tag_values:
            body['Tag'] = ','.join(tag_values)[:1000]
    if track_opens is not None:
        body['TrackOpens'] = bool(track_opens)
    if track_links is not None:
        body['TrackLinks'] = track_links

    clean_metadata = _clean_postmark_metadata(metadata)
    if clean_metadata:
        body['Metadata'] = clean_metadata

    headers_payload = _postmark_headers(extra_headers)
    if headers_payload:
        body['Headers'] = headers_payload

    headers = {
        'X-Postmark-Server-Token': server_token,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    ctx = log_context or {}
    try:
        resp = _post_postmark_email(headers=headers, body=body, timeout=30)
        result = resp.json()
        message_id_raw = result.get('MessageID')
        message_id = str(message_id_raw) if message_id_raw is not None else None
        logger.info(
            'postmark_send_ok postmark_message_id=%s contact_endpoint_id=%s nurturing_campaign_id=%s '
            'bulk_campaign_message_id=%s send_idempotency_key=%s',
            message_id,
            ctx.get('contact_endpoint_id'),
            ctx.get('nurturing_campaign_id'),
            ctx.get('bulk_campaign_message_id'),
            ctx.get('send_idempotency_key'),
        )
        return EmailSendResult(
            message_id=message_id,
            message=result.get('Message', 'OK'),
            raw_response=result,
        )
    except HTTPError as e:
        response = e.response
        status = response.status_code if response is not None else None
        error_code = None
        body_preview = ''
        if response is not None:
            error_code, _ = _postmark_error_payload(response)
            text_preview = getattr(response, 'text', '') or ''
            body_preview = (text_preview[:500] + '...') if len(text_preview) > 500 else text_preview
        logger.error(
            'postmark_send_fail http_status=%s ErrorCode=%s postmark_message_id=%s contact_endpoint_id=%s '
            'nurturing_campaign_id=%s bulk_campaign_message_id=%s send_idempotency_key=%s '
            'error=%s body_preview=%s',
            status,
            error_code,
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
            'postmark_send_fail postmark_message_id=%s contact_endpoint_id=%s nurturing_campaign_id=%s '
            'bulk_campaign_message_id=%s send_idempotency_key=%s error=%s',
            None,
            ctx.get('contact_endpoint_id'),
            ctx.get('nurturing_campaign_id'),
            ctx.get('bulk_campaign_message_id'),
            ctx.get('send_idempotency_key'),
            e,
        )
        raise


class PostmarkEmailAdapter(EmailProviderAdapter):
    provider_name = 'postmark'

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
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> EmailSendResult:
        token = _resolve_server_token(credentials)
        cfg = config or {}
        stream = _optional_str(cfg.get('message_stream')) or _optional_str(cfg.get('transactional_stream'))
        if not stream:
            stream = POSTMARK_DEFAULT_MESSAGE_STREAM
        raw_track_opens = cfg.get('track_opens')
        track_opens = raw_track_opens if isinstance(raw_track_opens, bool) else None
        track_links = _postmark_track_links_value(cfg)
        metadata = cfg.get('metadata') if isinstance(cfg.get('metadata'), dict) else None
        return send_postmark_email(
            server_token=token,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_email=from_email,
            reply_to=reply_to,
            tags=tags,
            message_stream=stream,
            track_opens=track_opens,
            track_links=track_links,
            metadata=metadata,
            log_context=log_context,
            extra_headers=extra_headers,
        )
