"""link_tracking services (lazy exports for attribution helpers)."""

__all__ = [
    'resolve_crm_and_media_campaign',
    'resolve_media_campaign_for_link',
]


def __getattr__(name: str):
    if name == 'resolve_crm_and_media_campaign':
        from link_tracking.services.attribution import resolve_crm_and_media_campaign

        return resolve_crm_and_media_campaign
    if name == 'resolve_media_campaign_for_link':
        from link_tracking.services.attribution import resolve_media_campaign_for_link

        return resolve_media_campaign_for_link
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
