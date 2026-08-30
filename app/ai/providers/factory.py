"""Small explicit AI provider factory for the shipped first-version vendors."""

from __future__ import annotations

from typing import Any

from app.ai.errors import AIProviderError
from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.providers.qwen import QwenProvider
from app.ai.providers.zai import ZAIProvider


_PROVIDER_TYPES = {
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
    "zai": ZAIProvider,
}
PROVIDER_TYPES = _PROVIDER_TYPES


def create_ai_provider(
    config: Any,
    *,
    client: Any | None = None,
    interface_language: str = "en",
) -> Any:
    """Construct one of the explicitly supported provider adapters."""

    provider_type = _PROVIDER_TYPES.get(str(config.provider_id).strip().lower())
    if provider_type is None:
        raise AIProviderError(f"Unsupported AI provider: {config.provider_id}")
    return provider_type(config, client=client, interface_language=interface_language)


__all__ = ["PROVIDER_TYPES", "create_ai_provider"]
