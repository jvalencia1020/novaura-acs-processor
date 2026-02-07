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
- resolved_query_params: Map (M), not string
- PK = DOMAIN#<domain>, SK = SLUG#<slug>
"""

import json
import logging
import time
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

from link_tracking.models import Domain, Link

logger = logging.getLogger(__name__)


def _get_table_name() -> str:
    """DynamoDB table name; must match link runtime's DYNAMODB_TABLE_NAME."""
    return getattr(settings, 'LINK_RUNTIME_TABLE_NAME', 'link-runtime-production')


def _get_aws_region() -> str:
    return getattr(settings, 'AWS_REGION', 'us-east-1')


def _normalize_resolved_query_params(link: Link) -> Dict[str, str]:
    """
    Build resolved_query_params as a Map (M) for DynamoDB.
    Runtime expects a dict, not a string. Uses link.utm_overrides; full UTM can be added later.
    """
    raw = link.utm_overrides
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _normalize_dynamic_param_allowlist(link: Link) -> List[str]:
    """
    Build dynamic_param_allowlist as a List (L) of strings for DynamoDB.
    Runtime expects a real list (e.g. ["click_id", "sms_msg_id"]), not a single string.
    Ensures sms_msg_id is included when channel is sms.
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
    return allowlist


def build_runtime_record(link: Link) -> Dict[str, Any]:
    """
    Build a DynamoDB item from a Link instance in the shape the link runtime expects.

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
    # Checklist: active must be bool (not string "true"/"false")
    active = bool(link.active and domain.active)
    # Checklist: append_query_params must be bool
    append_query_params = bool(link.append_query_params)
    # Checklist: dynamic_param_allowlist = List (L) of strings; resolved_query_params = Map (M)
    dynamic_allowlist = _normalize_dynamic_param_allowlist(link)
    resolved_query_params = _normalize_resolved_query_params(link)

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


def ensure_link_published(link: Link) -> bool:
    """
    Ensure the link is published to DynamoDB so the runtime can redirect.

    Builds the runtime record from the Link and PutItem to the table.
    Use this before sending any message that contains this short link (SMS, email, journey).

    Returns:
        True if publish succeeded, False otherwise. Logs errors.
    """
    table_name = _get_table_name()
    region = _get_aws_region()

    try:
        record = build_runtime_record(link)
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
