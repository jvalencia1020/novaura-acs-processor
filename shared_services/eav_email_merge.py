"""
EAV placeholder merge for email (after ACS / template variable merge).

Token syntax (case-insensitive whitespace):
  {{ lead_field.<api_name> }}  — values from LeadFieldValue + definitions
  {{ intake.<api_name> }}      — values from LeadIntakeValue + intake fields

Unknown tokens become empty string. No-op when ``lead`` is not an ORM Lead
or has no campaign, matching CRM behavior.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, FrozenSet, Optional, Tuple

if TYPE_CHECKING:
    from external_models.models.external_references import Lead

_LEAD_FIELD_TOKEN = re.compile(
    r'\{\{\s*lead_field\.(?P<name>[a-zA-Z0-9_]+)\s*\}\}',
    re.IGNORECASE,
)
_INTAKE_TOKEN = re.compile(
    r'\{\{\s*intake\.(?P<name>[a-zA-Z0-9_]+)\s*\}\}',
    re.IGNORECASE,
)


def extract_eav_placeholders(text: str) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """Return unique lowercased api_names for lead_field.* and intake.* tokens."""
    if not text:
        return frozenset(), frozenset()
    lf_names = {m.group('name').lower() for m in _LEAD_FIELD_TOKEN.finditer(text)}
    intake_names = {m.group('name').lower() for m in _INTAKE_TOKEN.finditer(text)}
    return frozenset(lf_names), frozenset(intake_names)


def apply_eav_placeholders(*, text: str, lead: Optional['Lead']) -> str:
    """
    Substitute EAV tokens for this lead. Unknown or missing values become empty string.
    No-op when ``lead`` is not a Lead instance or has no campaign.
    """
    if not text:
        return ''

    from external_models.models.external_references import Lead as LeadModel
    from external_models.models.lead_eav import LeadFieldValue, LeadIntakeValue

    if not isinstance(lead, LeadModel) or not getattr(lead, 'campaign_id', None):
        return text

    campaign = lead.campaign
    if campaign is None:
        return text

    lf_names, intake_names = extract_eav_placeholders(text)
    if not lf_names and not intake_names:
        return text

    lf_values: dict[str, str] = {}
    if lf_names:
        for row in LeadFieldValue.objects.filter(
            lead=lead,
            field_definition__api_name__in=list(lf_names),
            field_definition__account_id=campaign.account_id,
            field_definition__campaign_model_id=campaign.campaign_model_id,
        ).select_related('field_definition'):
            key = (row.field_definition.api_name or '').lower()
            lf_values[key] = (row.value or '') if row.value is not None else ''

    intake_values: dict[str, str] = {}
    if intake_names:
        for row in LeadIntakeValue.objects.filter(
            lead=lead,
            intake_field__api_name__in=list(intake_names),
            intake_field__intake_section__campaign_id=campaign.id,
        ).select_related('intake_field'):
            key = (row.intake_field.api_name or '').lower()
            intake_values[key] = (row.value or '') if row.value is not None else ''

    out = text
    for name in lf_names:
        val = lf_values.get(name, '')
        pat = re.compile(r'\{\{\s*lead_field\.' + re.escape(name) + r'\s*\}\}', re.IGNORECASE)
        out = pat.sub(val, out)
    for name in intake_names:
        val = intake_values.get(name, '')
        pat = re.compile(r'\{\{\s*intake\.' + re.escape(name) + r'\s*\}\}', re.IGNORECASE)
        out = pat.sub(val, out)
    return out


def apply_eav_placeholders_to_email_parts(
    *,
    subject: str,
    html_body: str,
    text_body: Optional[str],
    lead: Optional['Lead'],
) -> tuple[str, str, Optional[str]]:
    """Apply EAV substitution to subject, HTML, and optional plain text."""
    sub = apply_eav_placeholders(text=subject, lead=lead)
    html = apply_eav_placeholders(text=html_body, lead=lead)
    if text_body is None:
        txt: Optional[str] = None
    else:
        txt = apply_eav_placeholders(text=text_body, lead=lead)
    return sub, html, txt
