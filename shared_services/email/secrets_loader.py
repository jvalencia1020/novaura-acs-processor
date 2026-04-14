"""Load JSON secrets from AWS Secrets Manager."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_secret_json(secret_arn: str, region: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch SecretString from Secrets Manager and parse as JSON object.
    Returns {} if arn is empty or secret has no SecretString.
    """
    if not secret_arn or not str(secret_arn).strip():
        return {}
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError as e:
        raise ImportError('boto3 is required to load email credentials from Secrets Manager') from e

    arn = str(secret_arn).strip()
    reg = (region or '').strip() or None
    client_kw: Dict[str, Any] = {}
    if reg:
        client_kw['region_name'] = reg
    client = boto3.client('secretsmanager', **client_kw)
    try:
        resp = client.get_secret_value(SecretId=arn)
    except ClientError:
        logger.exception('Secrets Manager get_secret_value failed for %s', arn)
        raise
    raw = resp.get('SecretString')
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error('Secret %s is not valid JSON', arn)
        return {}
