"""
SMS Marketing services for processing inbound messages.
"""
from .actions import (
    execute_action,
    ActionExecutionResult,
    link_lead_for_subscriber,
    enroll_subscriber_in_follow_up_nurturing,
    get_welcome_message_for_opt_in,
)
from .message_sender import SMSMarketingMessageSender

__all__ = [
    'SMSMarketingRouter',
    'RouteResult',
    'SMSMarketingStateManager',
    'execute_action',
    'ActionExecutionResult',
    'link_lead_for_subscriber',
    'enroll_subscriber_in_follow_up_nurturing',
    'get_welcome_message_for_opt_in',
    'SMSMarketingProcessor',
    'SMSMarketingMessageSender',
]


def __getattr__(name):
    """Lazy-load router, state, and processor to avoid pulling external_models/Django too early (e.g. in tests)."""
    if name == 'SMSMarketingRouter':
        from .router import SMSMarketingRouter
        return SMSMarketingRouter
    if name == 'RouteResult':
        from .router import RouteResult
        return RouteResult
    if name == 'SMSMarketingStateManager':
        from .state import SMSMarketingStateManager
        return SMSMarketingStateManager
    if name == 'SMSMarketingProcessor':
        from .processor import SMSMarketingProcessor
        return SMSMarketingProcessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

