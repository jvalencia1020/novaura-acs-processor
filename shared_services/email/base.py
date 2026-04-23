"""Email provider adapter contract (minimal: raw send only)."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EmailSendResult:
    message_id: Optional[str]
    message: str = ''
    raw_response: Dict[str, Any] = field(default_factory=dict)


class EmailProviderAdapter(abc.ABC):
    provider_name: str = ''

    @abc.abstractmethod
    def send(
        self,
        *,
        credentials: Dict[str, Any],
        config: Dict[str, Any],
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str],
        from_email: str,
        reply_to: Optional[str],
        tags: Optional[List[str]] = None,
        log_context: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> EmailSendResult:
        raise NotImplementedError
