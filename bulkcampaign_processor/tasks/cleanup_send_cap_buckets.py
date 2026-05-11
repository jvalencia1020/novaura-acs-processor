"""Delete aged nurturing send-cap bucket rows (dispatcher-owned retention)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from acs.models.send_caps import NurturingCampaignSendBucket

logger = logging.getLogger(__name__)

RETENTION_BY_PERIOD = {
    'hourly': timedelta(days=14),
    'daily': timedelta(days=30),
    'weekly': timedelta(days=60),
    'monthly': timedelta(days=180),
    'custom': timedelta(days=30),
}


def cleanup_send_cap_buckets() -> int:
    """Delete buckets whose window ended before the retention cutoff for that cap period.

    Returns total rows deleted.
    """
    now = timezone.now()
    total_deleted = 0
    for period, retention in RETENTION_BY_PERIOD.items():
        cutoff = now - retention
        deleted, _ = NurturingCampaignSendBucket.objects.filter(
            cap__period=period,
            window_end__lt=cutoff,
        ).exclude(period_key__startswith='rolling:').delete()
        total_deleted += deleted
    if total_deleted:
        logger.info('cleanup_send_cap_buckets deleted=%s', total_deleted)
    return total_deleted
