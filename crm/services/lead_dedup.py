"""
Shared lead deduplication and create-or-update logic.

Used by reporting (create-lead, Bland AI, scheduled follow-up) and SMS marketing
(CREATE_LEAD action) to avoid duplicate leads. Lookup is by scope (campaign and/or
account) plus contact (phone_number and/or email). Update applies only non-null values.
Phone numbers are normalized to lead storage format (XXX-XXX-XXXX) so E.164 from
SMS and other formats match existing records.
"""
import logging
from typing import Any, Dict, Optional, Tuple

from django.db.models import Q

from utils.phone import normalize_phone_for_lead_storage

from external_models.models.external_references import Lead, B2BLead, D2CLead, Campaign, CampaignDefaultFunnel

logger = logging.getLogger(__name__)


def get_lead_model(lead_type: Optional[str]):
    """Return the Lead model class for the given type (base, b2b, or d2c)."""
    if not lead_type or lead_type not in ('b2b', 'd2c'):
        return Lead
    if lead_type == 'b2b':
        return B2BLead
    return D2CLead


def find_existing_lead(
    *,
    campaign: Optional[Campaign] = None,
    funnel=None,
    account=None,
    phone_number: Optional[str] = None,
    email: Optional[str] = None,
    lead_type: Optional[str] = 'd2c',
) -> Optional[Lead]:
    """
    Find an existing lead by scope and contact, matching reporting and SMS behavior.

    Scope (in order of use):
      - If campaign is set: match by campaign (and optionally funnel).
      - Else if account is set: match by campaign__account (any campaign in account).
    Contact: match by phone_number and/or email (OR). At least one of phone_number,
    email, or scope must be provided.

    lead_type: 'b2b' | 'd2c' | None. None uses base Lead (e.g. SMS); otherwise
    filters on B2BLead/D2CLead so type is consistent.

    Phone numbers are normalized to XXX-XXX-XXXX (lead storage format) so that
    E.164 (+12035835289) from SMS matches leads stored as 203-583-5289.
    """
    phone_normalized = normalize_phone_for_lead_storage(phone_number) if phone_number else None
    if not (phone_normalized or email):
        return None

    model = get_lead_model(lead_type)

    contact_query = Q()
    if phone_normalized:
        contact_query |= Q(phone_number=phone_normalized)
    if email:
        contact_query |= Q(email=email)

    if campaign is not None:
        base_query = Q(campaign=campaign)
        if funnel is not None:
            base_query &= Q(funnel=funnel)
    elif account is not None:
        base_query = Q(campaign__account=account)
    else:
        return None

    return model.objects.filter(base_query & contact_query).first()


def update_lead_non_null(lead: Lead, data: Dict[str, Any]) -> None:
    """
    Update lead with only non-null values from data; only sets attributes that exist
    on the model. Saves the lead. Mirrors reporting "update only non-null" behavior.
    """
    for key, value in data.items():
        if value is not None and hasattr(lead, key):
            setattr(lead, key, value)
    lead.save()


def create_or_update_lead(
    *,
    campaign: Optional[Campaign] = None,
    funnel=None,
    account=None,
    phone_number: Optional[str] = None,
    email: Optional[str] = None,
    lead_data: Optional[Dict[str, Any]] = None,
    lead_type: Optional[str] = 'd2c',
) -> Tuple[Lead, bool]:
    """
    Find existing lead by campaign/account + phone/email; if found update with
    non-null values from lead_data and return (lead, False). Otherwise create
    a new lead with campaign, funnel, phone_number, email, and lead_data and
    return (lead, True).

    For creation, campaign is required. Funnel defaults to campaign's default funnel
    if not in lead_data. lead_data is merged into the created lead (and must not
    include invalid fields for the model).

    Phone numbers are normalized to XXX-XXX-XXXX for both lookup and storage so
    E.164 from SMS matches existing leads.
    """
    lead_data = lead_data or {}
    phone_normalized = normalize_phone_for_lead_storage(phone_number) if phone_number else None
    existing = find_existing_lead(
        campaign=campaign,
        funnel=funnel,
        account=account,
        phone_number=phone_normalized,
        email=email,
        lead_type=lead_type,
    )

    if existing:
        merged = {
            'phone_number': phone_normalized,
            'email': email,
            **{k: v for k, v in lead_data.items() if v is not None},
        }
        if campaign is not None:
            merged['campaign'] = campaign
        if funnel is not None:
            merged['funnel'] = funnel
        update_lead_non_null(existing, merged)
        return existing, False

    if not campaign:
        raise ValueError("create_or_update_lead requires campaign to create a new lead.")

    model = get_lead_model(lead_type)
    default_funnel = None
    try:
        default_funnel = CampaignDefaultFunnel.objects.get(campaign=campaign).funnel
    except CampaignDefaultFunnel.DoesNotExist:
        pass

    create_kwargs = {
        'campaign': campaign,
        'email': email,
        **{k: v for k, v in lead_data.items() if v is not None},
    }
    if phone_normalized is not None:
        create_kwargs['phone_number'] = phone_normalized
    if funnel is not None:
        create_kwargs['funnel'] = funnel
    elif default_funnel is not None and 'funnel' not in create_kwargs:
        create_kwargs['funnel'] = default_funnel

    lead = model.objects.create(**create_kwargs)
    return lead, True
