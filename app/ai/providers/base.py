"""Structural contract shared by AI provider adapters."""

from __future__ import annotations

import threading
from typing import Protocol

from app.ai.errors import AIProviderError, AIRequestCancelled
from app.ai.models import AIRequest


class AIProvider(Protocol):
    """Minimal provider surface required by the analysis service."""

    def complete(
        self,
        request: AIRequest,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Return visible content for one provider-neutral request."""

    def test_connection(
        self,
        model_id: str | None = None,
        capability: str = "text",
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Validate one selected provider/model capability."""


__all__ = ["AIProvider", "AIProviderError", "AIRequestCancelled"]
