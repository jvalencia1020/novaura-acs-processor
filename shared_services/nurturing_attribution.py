"""
Resolve planning.MediaCampaign for ACS nurturing enrollment and read paths.

Semantics align with Django acs.services.attribution (without NurturingEnrollmentRoute,
which lives outside this processor).

Enrollment order (first CRM-consistent match wins):
  override -> originating_subscription.media_campaign -> nurturing_campaign.media_campaign

Participant read order:
  participant.media_campaign
  -> originating_subscription.media_campaign (only if CRM-consistent with nurturing campaign)
  -> nurturing_campaign.media_campaign
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from external_models.models.nurturing_campaigns import LeadNurturingCampaign, LeadNurturingParticipant


def _media_matches_nurturing_crm(
    media_campaign: Any,
    nurturing_crm_campaign_id: Optional[int],
) -> bool:
    if media_campaign is None:
        return False
    if nurturing_crm_campaign_id is None:
        return True
    return getattr(media_campaign, 'crm_campaign_id', None) == nurturing_crm_campaign_id


def resolve_media_campaign_for_enrollment(
    nurturing_campaign: Optional['LeadNurturingCampaign'],
    *,
    originating_subscription: Any = None,
    override: Any = None,
) -> Any:
    """
    Pick the media campaign to snapshot on LeadNurturingParticipant at enrollment.

    Skips any candidate whose MediaCampaign.crm_campaign_id does not match
    nurturing_campaign.crm_campaign_id when the latter is set (same as Django).
    """
    if nurturing_campaign is None:
        return None

    nc_crm_id = getattr(nurturing_campaign, 'crm_campaign_id', None)

    candidates = []
    if override is not None:
        candidates.append(override)
    if originating_subscription is not None:
        candidates.append(getattr(originating_subscription, 'media_campaign', None))
    candidates.append(getattr(nurturing_campaign, 'media_campaign', None))

    for mc in candidates:
        if not _media_matches_nurturing_crm(mc, nc_crm_id):
            continue
        return mc
    return None


def resolve_media_campaign_for_participant(
    participant: Optional['LeadNurturingParticipant'],
) -> Any:
    """
    Effective media campaign for analytics / payload tagging from a participant row.

    Snapshot on the participant wins; otherwise subscription (if CRM-consistent),
    then nurturing campaign default.
    """
    if participant is None:
        return None

    if getattr(participant, 'media_campaign_id', None):
        return participant.media_campaign

    nurturing_campaign = getattr(participant, 'nurturing_campaign', None)
    nc_crm_id = getattr(nurturing_campaign, 'crm_campaign_id', None) if nurturing_campaign else None

    subscription = getattr(participant, 'originating_subscription', None)
    if subscription is not None:
        sub_mc = getattr(subscription, 'media_campaign', None)
        if _media_matches_nurturing_crm(sub_mc, nc_crm_id):
            return sub_mc

    if nurturing_campaign is not None:
        nc_mc = getattr(nurturing_campaign, 'media_campaign', None)
        if _media_matches_nurturing_crm(nc_mc, nc_crm_id):
            return nc_mc

    return None
