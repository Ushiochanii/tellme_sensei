"""Provider-neutral orchestration for Text, Context + Question, and Vision."""

from __future__ import annotations

import base64
import threading
from typing import Any

from app.ai.errors import AIProviderError, AIRequestCancelled
from app.ai.models import AIRequest
from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.prompts import AnalysisPromptBuilder
from app.config import AppConfig
from app.localization import (
    DEFAULT_ANSWER_LANGUAGE,
    DEFAULT_INTERFACE_LANGUAGE,
    normalize_language,
    tr,
)


class AnalysisService:
    """Compose provider-neutral prompts with the configured AI provider."""

    def __init__(
        self,
        config: AppConfig,
        provider: Any | None = None,
        *,
        text_provider: Any | None = None,
        vision_provider: Any | None = None,
        prompt_builder: AnalysisPromptBuilder | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self._provider = provider
        self._text_provider = text_provider
        self._vision_provider = vision_provider
        self._client = client
        self._provider_cache: dict[str, Any] = {}
        self.prompt_builder = prompt_builder or AnalysisPromptBuilder(self.answer_language)

    @property
    def interface_language(self) -> str:
        return normalize_language(
            getattr(self.config, "interface_language", DEFAULT_INTERFACE_LANGUAGE),
            default=DEFAULT_INTERFACE_LANGUAGE,
        )

    @property
    def answer_language(self) -> str:
        return normalize_language(
            getattr(self.config, "answer_language", DEFAULT_ANSWER_LANGUAGE),
            default=DEFAULT_ANSWER_LANGUAGE,
        )

    def analyze(
        self,
        ocr_text: str,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Analyze OCR text and return a complete answer."""

        text = ocr_text.strip()
        if not text:
            raise AIProviderError(tr("error.deepseek_empty_ocr", self.interface_language))
        self._raise_if_cancelled(cancel_event)
        backend = self.config.text_ai
        request = AIRequest(
            model_id=backend.model_id,
            capability="text",
            messages=tuple(self.prompt_builder.build_text(text)),
        )
        return self._provider_for("text").complete(request, cancel_event=cancel_event)

    def analyze_context_question(
        self,
        context_text: str,
        question_text: str,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Analyze separately OCRed Context and Question text as one pair."""

        context = context_text.strip()
        question = question_text.strip()
        if not question:
            raise AIProviderError(
                tr("error.deepseek_empty_question_ocr", self.interface_language)
            )
        self._raise_if_cancelled(cancel_event)
        backend = self.config.text_ai
        request = AIRequest(
            model_id=backend.model_id,
            capability="text",
            messages=tuple(self.prompt_builder.build_context_question(context, question)),
        )
        return self._provider_for("text").complete(request, cancel_event=cancel_event)

    def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Send one in-memory screenshot through the resolved Vision AI config."""

        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise AIProviderError(tr("error.deepseek_empty_image", self.interface_language))
        mime_type = mime_type.strip().lower()
        if mime_type != "image/png":
            raise AIProviderError(tr("error.deepseek_png_only", self.interface_language))
        self._raise_if_cancelled(cancel_event)
        encoded = base64.b64encode(bytes(image_bytes)).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        backend = self.config.vision_ai
        request = AIRequest(
            model_id=backend.model_id,
            capability="vision",
            messages=tuple(self.prompt_builder.build_vision(data_url)),
        )
        return self._provider_for("vision").complete(request, cancel_event=cancel_event)

    def test_connection(
        self,
        cancel_event: threading.Event | None = None,
        capability: str = "text",
    ) -> bool:
        """Test the selected Text or Vision AI backend."""

        if capability not in {"text", "vision"}:
            raise ValueError("capability must be 'text' or 'vision'")
        backend = self.config.text_ai if capability == "text" else self.config.vision_ai
        return self._provider_for(capability).test_connection(
            model_id=backend.model_id,
            capability=capability,
            cancel_event=cancel_event,
        )

    def _provider_for(self, capability: str) -> Any:
        if capability == "text" and self._text_provider is not None:
            return self._text_provider
        if capability == "vision" and self._vision_provider is not None:
            return self._vision_provider
        if self._provider is not None:
            return self._provider
        cached = self._provider_cache.get(capability)
        if cached is not None:
            return cached
        backend = self.config.text_ai if capability == "text" else self.config.vision_ai
        if backend.provider_id == "deepseek":
            provider = DeepSeekProvider(
                backend,
                client=self._client,
                interface_language=self.interface_language,
            )
            self._provider_cache[capability] = provider
            return provider
        raise AIProviderError(f"Unsupported AI provider: {backend.provider_id}")

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AIRequestCancelled("AI request cancelled")


__all__ = ["AnalysisService"]
