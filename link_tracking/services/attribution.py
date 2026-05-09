"""
Resolve CRM + planning.MediaCampaign from link_tracking LinkCampaign ↔ CRM mappings.

Precedence for media on a link: link.media_campaign → link.campaign.media_campaign
→ media from resolve_crm_and_media_campaign(link.campaign).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from django.db.models import Case, IntegerField, Value, When

if TYPE_CHECKING:
    from external_models.models.external_references import Campaign
    from link_tracking.models import Link, LinkCampaign
    from planning.models.campaigns import MediaCampaign


def resolve_crm_and_media_campaign(
    link_campaign: Optional['LinkCampaign'],
) -> Tuple[Optional['Campaign'], Optional['MediaCampaign']]:
    """
    Return (crm_campaign, media_campaign) from the best matching active
    LinkCampaignCrmCampaignMapping row.

    Ordering (first row wins):
    1. end_date null first (current mapping)
    2. start_date desc
    3. created_at desc
    """
    if link_campaign is None:
        return None, None

    rel = (
        link_campaign.crm_campaign_mappings.filter(is_active=True)
        .annotate(
            _open_ended=Case(
                When(end_date__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
        .order_by('-_open_ended', '-start_date', '-created_at')
        .first()
    )
    if not rel:
        return None, None
    return rel.crm_campaign, rel.media_campaign


def resolve_media_campaign_for_link(link: Optional['Link']) -> Optional['MediaCampaign']:
    """
    Per-link override wins, then campaign-level default, then CRM mapping resolution.
    """
    if link is None:
        return None
    if getattr(link, 'media_campaign_id', None):
        return link.media_campaign
    campaign = getattr(link, 'campaign', None)
    if campaign is not None and getattr(campaign, 'media_campaign_id', None):
        return campaign.media_campaign
    _, media = resolve_crm_and_media_campaign(campaign)
    return media
