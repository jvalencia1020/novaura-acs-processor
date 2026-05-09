"""
Resolve CRM + planning.MediaCampaign from SMS keyword campaign ↔ CRM mapping rows.

Semantics mirror sms_marketing.services.attribution on the Django control plane:
active rows only; prefer primary; prefer open-ended mappings (end_date null); then recency.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from django.db.models import Case, IntegerField, Value, When

if TYPE_CHECKING:
    from external_models.models.external_references import Campaign
    from planning.models.campaigns import MediaCampaign
    from sms_marketing.models import SmsKeywordCampaign


def resolve_crm_and_media_campaign(
    sms_campaign: Optional['SmsKeywordCampaign'],
) -> Tuple[Optional['Campaign'], Optional['MediaCampaign']]:
    """
    Return (crm_campaign, media_campaign) from the best matching active
    SmsKeywordCampaignCrmCampaign row for this SMS keyword campaign.

    Ordering (first row wins):
    1. is_primary desc (primary first)
    2. end_date null first (current / open-ended mapping)
    3. start_date desc (most recent effective start)
    4. assigned_at desc
    """
    if sms_campaign is None:
        return None, None

    rel = (
        sms_campaign.crm_campaign_relations.filter(is_active=True)
        .annotate(
            _open_ended=Case(
                When(end_date__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
        .order_by('-is_primary', '-_open_ended', '-start_date', '-assigned_at')
        .first()
    )
    if not rel:
        return None, None
    return rel.crm_campaign, rel.media_campaign
