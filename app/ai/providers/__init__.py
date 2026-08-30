"""First-version AI provider adapters."""

from app.ai.providers.base import AIProvider
from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider

__all__ = ["AIProvider", "DeepSeekProvider", "OpenAICompatibleProvider"]
