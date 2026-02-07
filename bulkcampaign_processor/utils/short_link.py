"""
Build short URLs for bulk campaign messages (drip/reminder) with step attribution params.
Follows the same pattern as SMS marketing: base URL + query params (e.g. drip_step_id, reminder_message_id).
"""
from typing import Optional
from urllib.parse import urlencode


def build_bulk_short_url(
    link,
    drip_step_id: Optional[int] = None,
    reminder_message_id: Optional[int] = None,
    sms_msg_id: Optional[int] = None,
) -> str:
    """
    Build the full short URL with attribution query params for bulk campaign messages.

    Args:
        link: Link model instance (from DripCampaignMessageStep.short_link or ReminderMessage.short_link).
        drip_step_id: Optional DripCampaignMessageStep.id for drip campaigns.
        reminder_message_id: Optional ReminderMessage.id for reminder campaigns.
        sms_msg_id: Optional SmsMessage.id if a send record is created for tracking.

    Returns:
        Full URL string, e.g. https://go.example.com/ABC?drip_step_id=123
    """
    base_url = link.get_full_url()
    params = {}
    if drip_step_id is not None:
        params['drip_step_id'] = drip_step_id
    if reminder_message_id is not None:
        params['reminder_message_id'] = reminder_message_id
    if sms_msg_id is not None:
        params['sms_msg_id'] = sms_msg_id
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"
