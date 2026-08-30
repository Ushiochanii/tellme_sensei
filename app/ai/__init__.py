"""Provider-neutral AI contracts and analysis orchestration."""

from app.ai.errors import AIProviderError, AIRequestCancelled
from app.ai.catalog import (
    AIModelDescriptor,
    AIProviderDescriptor,
    AI_PROVIDER_CATALOG,
    CUSTOM_MODEL_ID,
    CUSTOM_MODEL_LABEL,
)
from app.ai.models import AIBackendConfig, AIRequest
from app.ai.prompts import AnalysisPromptBuilder
from app.ai.providers.base import AIProvider

__all__ = [
    "AIBackendConfig",
    "AIModelDescriptor",
    "AIProviderDescriptor",
    "AI_PROVIDER_CATALOG",
    "AIProvider",
    "AIProviderError",
    "AIRequest",
    "AIRequestCancelled",
    "AnalysisPromptBuilder",
    "CUSTOM_MODEL_ID",
    "CUSTOM_MODEL_LABEL",
]
