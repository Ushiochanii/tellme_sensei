"""Curated first-version AI provider and model metadata.

The catalog is deliberately static.  It describes the small set of models
that TellMeSensei knows how to present in its Text and Vision selectors; a
user may still enter any provider-supported model through the Custom model
ID option.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.ai.models import AIAnalysisCapability


CUSTOM_MODEL_ID = "__custom__"
CUSTOM_MODEL_LABEL = "Custom model ID..."


@dataclass(frozen=True, slots=True)
class AIModelDescriptor:
    """One curated model and the product capabilities it supports."""

    provider_id: str
    model_id: str
    display_name: str
    capabilities: frozenset[AIAnalysisCapability]

    def supports(self, capability: AIAnalysisCapability) -> bool:
        return capability in self.capabilities

    @property
    def supports_text(self) -> bool:
        return self.supports("text")

    @property
    def supports_vision(self) -> bool:
        return self.supports("vision")


@dataclass(frozen=True, slots=True)
class AIProviderDescriptor:
    """Provider metadata used by configuration, Settings, and the factory."""

    provider_id: str
    display_name: str
    default_base_url: str
    api_key_env: str
    secret_account_name: str
    models: tuple[AIModelDescriptor, ...]

    def models_for(self, capability: AIAnalysisCapability | None = None) -> tuple[AIModelDescriptor, ...]:
        if capability is None:
            return self.models
        return tuple(model for model in self.models if model.supports(capability))

    def default_model(self, capability: AIAnalysisCapability) -> str:
        models = self.models_for(capability)
        if not models:
            raise ValueError(f"No {capability} model is catalogued for {self.provider_id}")
        return models[0].model_id


def _model(
    provider_id: str,
    model_id: str,
    capabilities: Iterable[AIAnalysisCapability],
    *,
    display_name: str | None = None,
) -> AIModelDescriptor:
    return AIModelDescriptor(
        provider_id=provider_id,
        model_id=model_id,
        display_name=display_name or model_id,
        capabilities=frozenset(capabilities),
    )


DEEPSEEK_MODELS = (
    _model("deepseek", "deepseek-v4-flash", ("text",)),
    _model("deepseek", "deepseek-v4-pro", ("text",)),
    # Keep the legacy model in the curated Text list so existing users do not
    # see their unchanged configuration become a custom entry after upgrade.
    _model("deepseek", "deepseek-chat", ("text",)),
    _model("deepseek", "deepseek-v4-flash-vision-exp", ("vision",)),
)

QWEN_MODELS = (
    _model("qwen", "qwen3.8-max", ("text",)),
    _model("qwen", "qwen3.8-flash", ("text",)),
    _model("qwen", "qwen3.7-plus", ("text", "vision")),
    _model("qwen", "qwen3-vl-plus", ("vision",)),
)

ZAI_MODELS = (
    _model("zai", "glm-5.1", ("text",)),
    _model("zai", "glm-4.6", ("text",)),
    _model("zai", "glm-5v-turbo", ("vision",)),
    _model("zai", "glm-4.6v", ("vision",)),
)


AI_PROVIDER_CATALOG: tuple[AIProviderDescriptor, ...] = (
    AIProviderDescriptor(
        provider_id="deepseek",
        display_name="DeepSeek",
        default_base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        secret_account_name="default",
        models=DEEPSEEK_MODELS,
    ),
    AIProviderDescriptor(
        provider_id="qwen",
        display_name="Qwen",
        # Model Studio permits regional/workspace endpoints; this public
        # compatible-mode endpoint is an editable default for standard keys.
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="QWEN_API_KEY",
        secret_account_name="qwen",
        models=QWEN_MODELS,
    ),
    AIProviderDescriptor(
        provider_id="zai",
        display_name="Z.AI (GLM)",
        default_base_url="https://api.z.ai/api/paas/v4",
        api_key_env="ZAI_API_KEY",
        secret_account_name="zai",
        models=ZAI_MODELS,
    ),
)

PROVIDER_CATALOG = AI_PROVIDER_CATALOG
AI_PROVIDERS = AI_PROVIDER_CATALOG
MODEL_CATALOG = tuple(model for provider in AI_PROVIDER_CATALOG for model in provider.models)
_PROVIDERS = {descriptor.provider_id: descriptor for descriptor in AI_PROVIDER_CATALOG}


def provider_ids() -> tuple[str, ...]:
    return tuple(descriptor.provider_id for descriptor in AI_PROVIDER_CATALOG)


def get_provider_descriptor(provider_id: str) -> AIProviderDescriptor:
    normalized = str(provider_id).strip().lower()
    try:
        return _PROVIDERS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported AI provider: {provider_id}") from exc


def models_for_provider(
    provider_id: str,
    capability: AIAnalysisCapability | None = None,
) -> tuple[AIModelDescriptor, ...]:
    return get_provider_descriptor(provider_id).models_for(capability)


def known_model(provider_id: str, model_id: str, capability: AIAnalysisCapability | None = None) -> bool:
    return any(
        model.model_id == model_id
        for model in models_for_provider(provider_id, capability)
    )


def default_model(provider_id: str, capability: AIAnalysisCapability) -> str:
    return get_provider_descriptor(provider_id).default_model(capability)


__all__ = [
    "AIModelDescriptor",
    "AIProviderDescriptor",
    "AI_PROVIDER_CATALOG",
    "AI_PROVIDERS",
    "CUSTOM_MODEL_ID",
    "CUSTOM_MODEL_LABEL",
    "DEEPSEEK_MODELS",
    "PROVIDER_CATALOG",
    "MODEL_CATALOG",
    "QWEN_MODELS",
    "ZAI_MODELS",
    "default_model",
    "get_provider_descriptor",
    "known_model",
    "models_for_provider",
    "provider_ids",
]
