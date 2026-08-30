"""DeepSeek-specific adapter over the shared OpenAI-compatible transport."""

from __future__ import annotations

from typing import Any

from app.ai.models import (
    AIRequest,
    DEFAULT_DEEPSEEK_PROVIDER,
    DEFAULT_DEEPSEEK_VISION_MODEL,
)
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.localization import tr


DEEPSEEK_VISION_MODEL = DEFAULT_DEEPSEEK_VISION_MODEL


class DeepSeekProvider(OpenAICompatibleProvider):
    """Preserve DeepSeek request extras and user-facing error wording."""

    provider_id = DEFAULT_DEEPSEEK_PROVIDER
    display_name = "DeepSeek"

    def _extra_body(self, request: AIRequest) -> dict[str, Any] | None:
        if request.capability == "vision":
            return {"thinking": {"type": "enabled"}}
        return None

    def _format_error(self, exc: Exception) -> str:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            return tr("error.deepseek_401", self.interface_language)
        if status_code == 403:
            return tr("error.deepseek_403", self.interface_language)
        if status_code == 429:
            return tr("error.deepseek_429", self.interface_language)
        if isinstance(status_code, int) and status_code >= 500:
            return tr("error.deepseek_5xx", self.interface_language, status_code=status_code)
        name = type(exc).__name__.lower()
        if "timeout" in name:
            return tr("error.deepseek_timeout", self.interface_language)
        if "connection" in name:
            return tr("error.deepseek_connection", self.interface_language)
        return tr("error.deepseek_generic", self.interface_language)

    def _missing_api_key_message(self) -> str:
        return tr("error.deepseek_missing_api_key", self.interface_language)

    def _missing_api_key_environment_message(self) -> str:
        return tr("error.deepseek_missing_api_key_env", self.interface_language)

    def _missing_openai_message(self) -> str:
        return tr("error.deepseek_missing_openai", self.interface_language)

    def _empty_answer_message(self) -> str:
        return tr("error.deepseek_empty_answer", self.interface_language)


__all__ = ["DEEPSEEK_VISION_MODEL", "DeepSeekProvider"]
