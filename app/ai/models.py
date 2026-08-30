"""Provider-neutral runtime values used by the AI analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


AIAnalysisCapability = Literal["text", "vision"]

DEFAULT_DEEPSEEK_PROVIDER = "deepseek"
DEFAULT_DEEPSEEK_TEXT_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_VISION_MODEL = "deepseek-v4-flash-vision-exp"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_REQUEST_TIMEOUT = 60.0


@dataclass(frozen=True, slots=True)
class AIBackendConfig:
    """Resolved immutable configuration for one AI capability."""

    provider_id: str = DEFAULT_DEEPSEEK_PROVIDER
    model_id: str = DEFAULT_DEEPSEEK_TEXT_MODEL
    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT

    def __post_init__(self) -> None:
        for name in ("provider_id", "model_id", "base_url"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.api_key, str):
            raise ValueError("api_key must be a string")
        object.__setattr__(self, "api_key", self.api_key.strip())
        try:
            timeout = float(self.request_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("request_timeout must be positive") from exc
        if timeout <= 0:
            raise ValueError("request_timeout must be positive")
        object.__setattr__(self, "request_timeout", timeout)

    @property
    def provider(self) -> str:
        """Short alias for callers using product-level terminology."""

        return self.provider_id

    @property
    def model(self) -> str:
        """Short alias for callers using the legacy model vocabulary."""

        return self.model_id


@dataclass(frozen=True, slots=True)
class AIRequest:
    """Provider-neutral chat request handed to an AI provider."""

    model_id: str
    capability: AIAnalysisCapability
    messages: tuple[Mapping[str, Any], ...]
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id must be a non-empty string")
        object.__setattr__(self, "model_id", self.model_id.strip())
        if self.capability not in {"text", "vision"}:
            raise ValueError("capability must be 'text' or 'vision'")
        normalized_messages: list[Mapping[str, Any]] = []
        for message in self.messages:
            if not isinstance(message, Mapping):
                raise ValueError("messages must contain mappings")
            normalized_messages.append(dict(message))
        object.__setattr__(self, "messages", tuple(normalized_messages))

    @property
    def model(self) -> str:
        """Readable alias used by provider implementations."""

        return self.model_id

    @property
    def mode(self) -> AIAnalysisCapability:
        """Analysis-mode alias for callers that use product terminology."""

        return self.capability


@dataclass(frozen=True, slots=True)
class AIStreamResult:
    """Visible and reasoning content collected from one streamed response."""

    visible_content: str
    reasoning_content: str = ""
    finish_reasons: tuple[str, ...] = ()


__all__ = [
    "AIAnalysisCapability",
    "AIBackendConfig",
    "AIRequest",
    "AIStreamResult",
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_PROVIDER",
    "DEFAULT_DEEPSEEK_TEXT_MODEL",
    "DEFAULT_DEEPSEEK_VISION_MODEL",
    "DEFAULT_REQUEST_TIMEOUT",
]
