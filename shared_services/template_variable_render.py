"""ACS {{category.name}} placeholder replacement (outbound_acs / hosted HTML). Mirrors CRM template_variable_render."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from django.utils import timezone

from external_models.models.messages import TemplateVariable


def _is_blank_for_fallback(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == '':
        return True
    return False


def replace_template_variables(content: str, context: Dict[str, Any]) -> str:
    """
    Replace {{category.variable}} using TemplateVariable rows and nested context.
    context keys are category names (e.g. lead, campaign); values are dicts or model instances.
    """
    if not content:
        return ''

    variables = TemplateVariable.objects.filter(
        category__is_active=True,
        is_active=True,
    ).select_related('category')

    out = content
    for var in variables:
        placeholder = var.get_placeholder()
        if placeholder not in out:
            continue
        category = var.category.name
        if category == 'system':
            if var.name == 'current_date':
                raw: Any = timezone.now().strftime('%Y-%m-%d')
            elif var.name == 'current_time':
                raw = timezone.now().strftime('%I:%M %p')
            else:
                raw = ''
        else:
            model_data = context.get(category, {})
            if isinstance(model_data, dict):
                raw = model_data.get(var.name, '')
            else:
                raw = getattr(model_data, var.field_name, '')

        if _is_blank_for_fallback(raw):
            fb = (getattr(var, 'fallback_value', None) or '')
            if isinstance(fb, str):
                fb = fb.strip()
            value = fb
        else:
            value = str(raw)
        out = out.replace(placeholder, value)
    return out


def placeholders_remaining_in_content(content: str) -> List[str]:
    """Return deduplicated inner placeholder tokens still present as {{...}}."""
    found = re.findall(r'\{\{([^}]+)\}\}', content or '')
    seen: set[str] = set()
    ordered: List[str] = []
    for token in found:
        t = token.strip()
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def build_nested_template_context(
    *,
    lead: Optional[Any] = None,
    nurturing_campaign: Optional[Any] = None,
    sender_user: Optional[Any] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Assemble context for replace_template_variables (category -> model or dict).
    """
    ctx: Dict[str, Any] = {}
    if lead is not None:
        ctx['lead'] = lead
    if nurturing_campaign is not None:
        ctx['campaign'] = nurturing_campaign
    if sender_user is not None:
        ctx['sender'] = sender_user
    if extra:
        for key, val in extra.items():
            if val is not None:
                ctx[key] = val
    return ctx
