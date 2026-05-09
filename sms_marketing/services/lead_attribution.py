"""
Fill-missing semantics for Lead.media_campaign (SMS create-lead path only).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from external_models.models.external_references import Campaign, Lead
    from planning.models.campaigns import MediaCampaign


def maybe_fill_lead_media_campaign(
    lead: Optional['Lead'],
    crm_campaign: Optional['Campaign'],
    media_campaign: Optional['MediaCampaign'],
) -> bool:
    """
    Set lead.media_campaign only when null and media_campaign belongs to crm_campaign.

    Returns True if a save was performed.
    """
    if lead is None or crm_campaign is None or media_campaign is None:
        return False
    if getattr(lead, 'media_campaign_id', None):
        return False
    if getattr(media_campaign, 'crm_campaign_id', None) != getattr(crm_campaign, 'id', None):
        return False
    lead.media_campaign = media_campaign
    lead.save(update_fields=['media_campaign'])
    return True
