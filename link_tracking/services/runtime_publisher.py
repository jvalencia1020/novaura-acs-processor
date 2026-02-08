"""
Publish Link records to the DynamoDB table consumed by the link runtime service.

The link runtime only reads from DynamoDB (GetItem by PK/SK). This publisher
ensures that when the ACS processor sends messages containing short redirect
links (SMS, email, journey), the corresponding record exists so the runtime
can perform the 302 redirect.

Table name must match the runtime's DYNAMODB_TABLE_NAME (see LINK_RUNTIME_TABLE_NAME).

Attribute types must match the runtime expectations. See docs/DYNAMODB_PUBLISHER_CHECKLIST.md:
- active, append_query_params: native bool (not string "true"/"false")
- dynamic_param_allowlist: List (L) of strings, not a single string
- resolved_query_params: Map (M), resolved from GlobalUTMPolicy + campaign utm_template + link utm_overrides
- PK = DOMAIN#<domain>, SK = SLUG#<slug>
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

from link_tracking.models import Domain, GlobalUTMPolicy, Link

logger = logging.getLogger(__name__)


def _resolve_acs_placeholders(value: str, acs_context: Dict[str, Any]) -> str:
    """
    Resolve ACS template variable placeholders (e.g. {{lead.first_name}}, {{campaign.name}}) in a string.
    Uses the same MessageTemplate.replace_variables() and context shape as message body replacement.
    """
    if not value or "{{" not in value:
        return value
    try:
        from external_models.models.messages import MessageTemplate
        return MessageTemplate(content=value).replace_variables(acs_context)
    except Exception as e:
        logger.debug("ACS placeholder resolution failed for UTM value, using as-is: %s", e)
        return value


def _get_table_name() -> str:
    """DynamoDB table name; must match link runtime's DYNAMODB_TABLE_NAME."""
    return getattr(settings, 'LINK_RUNTIME_TABLE_NAME', 'link-runtime-production')


def _get_aws_region() -> str:
    return getattr(settings, 'AWS_REGION', 'us-east-1')


def _utm_template_context(
    link: Link,
    utm_context: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Build context for UTM template variable substitution (slug, campaign_id, keyword, etc.).

    When publishing from the SMS flow, pass utm_context with:
      - keyword: the SMS keyword that triggered the message (e.g. from SmsKeywordRule.keyword.keyword)
      - short_code: the from number / endpoint value (e.g. ContactEndpoint.value)
    If utm_context is omitted, keyword comes from link.keyword and short_code is empty.
    """
    domain: Domain = link.domain
    ctx = utm_context or {}
    return {
        'slug': link.slug_canonical or '',
        'campaign_id': link.campaign_identifier or '',
        'keyword': ctx['keyword'] if 'keyword' in ctx else (link.keyword or ''),
        'channel': link.channel or '',
        'short_code': ctx.get('short_code', ''),
        'domain': domain.domain_name or '',
        'slug_type': link.slug_type or 'system',
        'created_date': link.created_at.strftime('%Y-%m-%d') if link.created_at else '',
    }


def _substitute_utm_template(value: str, context: Dict[str, str]) -> str:
    """Replace ${var_name} placeholders in a string with context values."""
    if not isinstance(value, str):
        return str(value)
    result = value
    for key, val in context.items():
        result = result.replace(f'${{{key}}}', str(val))
    # Replace any remaining ${...} with empty string
    result = re.sub(r'\$\{[^}]+\}', '', result)
    return result


def _resolve_utm_params(
    link: Link,
    utm_context: Optional[Dict[str, str]] = None,
    acs_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    Resolve UTM/query params from GlobalUTMPolicy + campaign utm_template + link utm_overrides.

    Order: global defaults, then campaign template (with variable substitution), then link overrides.
    - utm_context (optional): when publishing from SMS, pass {'keyword': rule keyword, 'short_code': endpoint value}.
    - acs_context (optional): same context used for message body replacement (lead, campaign, etc.); any
      {{category.name}} placeholders in UTM values are resolved using MessageTemplate.replace_variables().
    Result is stored as resolved_query_params in the DynamoDB record (resolved at publish time).
    All keys and values are strings for DynamoDB Map (M).
    """
    context = _utm_template_context(link, utm_context=utm_context)
    resolved = {}

    def _finalize(v: str) -> str:
        out = _substitute_utm_template(str(v), context)
        if acs_context and "{{" in out:
            out = _resolve_acs_placeholders(out, acs_context)
        return str(out)

    # 1. Global defaults
    try:
        global_policy = GlobalUTMPolicy.get_instance()
        if global_policy.default_utm_params and isinstance(global_policy.default_utm_params, dict):
            for k, v in global_policy.default_utm_params.items():
                resolved[str(k)] = _finalize(v)
    except Exception as e:
        logger.debug("GlobalUTMPolicy not available for UTM resolution: %s", e)

    # 2. Campaign utm_template (with variable substitution)
    campaign = getattr(link, 'campaign', None)
    if campaign and getattr(campaign, 'utm_template', None) and isinstance(campaign.utm_template, dict):
        for k, v in campaign.utm_template.items():
            resolved[str(k)] = _finalize(v)

    # 3. Link utm_overrides (highest precedence)
    raw_overrides = link.utm_overrides
    if isinstance(raw_overrides, dict):
        for k, v in raw_overrides.items():
            resolved[str(k)] = _finalize(v)
    elif isinstance(raw_overrides, str) and raw_overrides.strip():
        try:
            parsed = json.loads(raw_overrides)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    resolved[str(k)] = _finalize(v)
        except (json.JSONDecodeError, TypeError):
            pass

    return {k: str(v) for k, v in resolved.items()}


def _normalize_dynamic_param_allowlist(link: Link) -> List[str]:
    """
    Build dynamic_param_allowlist as a List (L) of strings for DynamoDB.
    Runtime expects a real list (e.g. ["click_id", "sms_msg_id"]), not a single string.
    Ensures sms_msg_id is included when channel is sms.
    Includes drip_step_id and reminder_message_id so links used in drip/reminder campaigns
    forward those params from the request onto the redirect URL (attribution).
    """
    raw = link.dynamic_param_allowlist
    if isinstance(raw, list):
        allowlist = [str(x) for x in raw if x]
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            allowlist = [str(x) for x in parsed] if isinstance(parsed, list) else ['click_id']
        except (json.JSONDecodeError, TypeError):
            allowlist = ['click_id']
    else:
        allowlist = ['click_id']
    if link.channel == 'sms' and 'sms_msg_id' not in allowlist:
        allowlist.append('sms_msg_id')
    # So drip/reminder short URLs (e.g. ...?drip_step_id=128) get these params forwarded to destination
    for param in ('drip_step_id', 'reminder_message_id'):
        if param not in allowlist:
            allowlist.append(param)
    return allowlist


def build_runtime_record(
    link: Link,
    utm_context: Optional[Dict[str, str]] = None,
    acs_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a DynamoDB item from a Link instance in the shape the link runtime expects.

    utm_context (optional): when publishing from SMS, pass {'keyword': rule keyword, 'short_code': endpoint value}
    so resolved_query_params gets the actual keyword and short code for template substitution.
    acs_context (optional): same context as message body replacement (lead, campaign, etc.) so that
    {{lead.first_name}}, {{campaign.name}}, etc. in UTM values are resolved via ACS template variables.

    Keys: PK = DOMAIN#<domain_name>, SK = SLUG#<slug_canonical>.
    Required attributes: destination_url, fallback_url, active, append_query_params,
    dynamic_param_allowlist. Optional: expires_at_epoch, max_clicks, resolved_query_params,
    routing_rules, signature_required, signature_key_id, campaign_id, keyword, channel,
    runtime_version, published_at_epoch, updated_at_epoch.

    Returns:
        Dict suitable for boto3 put_item (native Python types).
    """
    domain: Domain = link.domain
    domain_name = domain.domain_name
    slug_canonical = link.slug_canonical

    pk = f"DOMAIN#{domain_name}"
    sk = f"SLUG#{slug_canonical}"

    fallback_url = link.fallback_url.strip() if link.fallback_url else f"https://{domain_name}/disabled"
    # Checklist: active must be bool (not string "true"/"false"). Publish as True so the link we send redirects when clicked.
    active = True
    # Checklist: append_query_params must be bool
    append_query_params = bool(link.append_query_params)
    # Checklist: dynamic_param_allowlist = List (L) of strings; resolved_query_params = Map (M)
    dynamic_allowlist = _normalize_dynamic_param_allowlist(link)
    resolved_query_params = _resolve_utm_params(
        link, utm_context=utm_context, acs_context=acs_context
    )

    now_epoch = int(time.time())
    updated_epoch = int(link.updated_at.timestamp()) if link.updated_at else now_epoch

    record = {
        'PK': pk,
        'SK': sk,
        'link_id': str(link.id),
        'destination_url': str(link.destination_url),
        'fallback_url': fallback_url,
        'active': active,
        'append_query_params': append_query_params,
        'resolved_query_params': resolved_query_params,
        'dynamic_param_allowlist': dynamic_allowlist,
        'runtime_version': int(link.runtime_version),
        'published_at_epoch': now_epoch,
        'updated_at_epoch': updated_epoch,
    }

    if link.expires_at:
        record['expires_at_epoch'] = int(link.expires_at.timestamp())
    if link.max_clicks is not None:
        record['max_clicks'] = int(link.max_clicks)
    if link.routing_rules and isinstance(link.routing_rules, dict):
        record['routing_rules'] = dict(link.routing_rules)
    if link.signature_required:
        record['signature_required'] = True
        if link.signature_secret_ref:
            record['signature_key_id'] = str(link.signature_secret_ref)
    if link.campaign_identifier:
        record['campaign_id'] = str(link.campaign_identifier)
    if link.keyword:
        record['keyword'] = str(link.keyword)
    if link.channel:
        record['channel'] = str(link.channel)

    return record


def ensure_link_published(
    link: Link,
    utm_context: Optional[Dict[str, str]] = None,
    acs_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Ensure the link is published to DynamoDB so the runtime can redirect.

    Builds the runtime record from the Link and PutItem to the table.
    Use this before sending any message that contains this short link (SMS, email, journey).

    utm_context (optional): when publishing from SMS, pass {'keyword': <rule keyword>, 'short_code': <endpoint value>}
    so UTM template variables ${keyword} and ${short_code} are resolved for the message being sent.
    acs_context (optional): same context as message body replacement (lead, campaign, subscriber, etc.) so that
    {{lead.first_name}}, {{campaign.name}}, and other ACS template variable placeholders in UTM params are resolved.

    Returns:
        True if publish succeeded, False otherwise. Logs errors.
    """
    table_name = _get_table_name()
    region = _get_aws_region()

    try:
        record = build_runtime_record(
            link, utm_context=utm_context, acs_context=acs_context
        )
        resource = boto3.resource('dynamodb', region_name=region)
        table = resource.Table(table_name)
        table.put_item(Item=record)
        logger.info(
            "Published link to DynamoDB: domain=%s slug=%s table=%s",
            link.domain.domain_name,
            link.slug_canonical,
            table_name,
        )
        return True
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == 'ResourceNotFoundException':
            logger.error(
                "DynamoDB table '%s' not found in region=%s. Create the table in AWS (e.g. via Terraform) "
                "or set LINK_RUNTIME_TABLE_NAME to an existing table name. link_id=%s",
                table_name,
                region,
                link.id,
            )
        else:
            logger.exception(
                "DynamoDB PutItem failed: link_id=%s domain=%s slug=%s table=%s error=%s",
                link.id,
                link.domain.domain_name,
                link.slug_canonical,
                table_name,
                e,
            )
        return False
    except Exception as e:
        logger.exception(
            "Failed to publish link to DynamoDB: link_id=%s domain=%s slug=%s table=%s error=%s",
            link.id,
            link.domain.domain_name,
            link.slug_canonical,
            table_name,
            e,
        )
        return False
