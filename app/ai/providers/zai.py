"""Z.AI / GLM provider adapter over the shared OpenAI-compatible transport."""

from __future__ import annotations

from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.localization import tr


class ZAIProvider(OpenAICompatibleProvider):
    """Keep Z.AI's identity and diagnostics explicit while sharing transport."""

    provider_id = "zai"
    display_name = "Z.AI (GLM)"
    default_base_url = "https://api.z.ai/api/paas/v4"

    def _format_error(self, exc: Exception) -> str:
        return self._provider_error(exc)

    def _missing_api_key_message(self) -> str:
        return tr("error.zai_missing_api_key", self.interface_language)

    def _missing_api_key_environment_message(self) -> str:
        return tr("error.zai_missing_api_key_env", self.interface_language)

    def _missing_openai_message(self) -> str:
        return tr("error.zai_missing_openai", self.interface_language)

    def _empty_answer_message(self) -> str:
        return tr("error.zai_empty_answer", self.interface_language)

    def _provider_error(self, exc: Exception) -> str:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            return tr("error.zai_401", self.interface_language)
        if status_code == 403:
            return tr("error.zai_403", self.interface_language)
        if status_code == 429:
            return tr("error.zai_429", self.interface_language)
        if isinstance(status_code, int) and status_code >= 500:
            return tr("error.zai_5xx", self.interface_language, status_code=status_code)
        name = type(exc).__name__.lower()
        if "timeout" in name:
            return tr("error.zai_timeout", self.interface_language)
        if "connection" in name:
            return tr("error.zai_connection", self.interface_language)
        return tr("error.zai_generic", self.interface_language)


ZaiProvider = ZAIProvider


__all__ = ["ZAIProvider", "ZaiProvider"]
