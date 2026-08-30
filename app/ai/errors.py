"""Provider-neutral errors used across analysis workers and services."""

from __future__ import annotations


class AIProviderError(RuntimeError):
    """A user-facing, key-safe AI provider or request error."""


class AIRequestCancelled(AIProviderError):
    """Raised when a streaming request is cooperatively cancelled."""


__all__ = ["AIProviderError", "AIRequestCancelled"]
