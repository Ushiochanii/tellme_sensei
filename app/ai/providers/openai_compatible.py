"""Shared streaming transport for OpenAI-compatible AI providers."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.ai.errors import AIProviderError, AIRequestCancelled
from app.ai.models import AIRequest, AIStreamResult

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """Implement the common chat-completions and streaming lifecycle."""

    provider_id = "openai-compatible"
    display_name = "AI provider"

    def __init__(
        self,
        config,
        client: Any | None = None,
        *,
        interface_language: str = "en",
    ) -> None:
        self.config = config
        self._client = client
        self.interface_language = interface_language

    def complete(
        self,
        request: AIRequest,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Stream one provider-neutral request and return visible content."""

        self._raise_if_cancelled(cancel_event)
        client = self._get_client()
        logger.info(
            "%s API request started mode=%s model=%s",
            self.display_name,
            request.capability,
            request.model_id,
        )
        response = None
        try:
            request_kwargs: dict[str, Any] = {
                "model": request.model_id,
                "messages": list(request.messages),
                "temperature": request.temperature,
                "timeout": self.config.request_timeout,
                "stream": True,
            }
            extra_body = self._extra_body(request)
            if extra_body:
                request_kwargs["extra_body"] = extra_body
            response = client.chat.completions.create(**request_kwargs)
            stream_result = self._consume_stream(response, cancel_event)
        except AIRequestCancelled:
            logger.info("%s API request cancelled", self.display_name)
            raise
        except Exception as exc:  # SDK exception classes vary across versions.
            error = self._format_error(exc)
            logger.error("%s API request failed: %s", self.display_name, error)
            raise AIProviderError(error) from exc
        finally:
            self._close_stream(response)

        if not stream_result.visible_content.strip():
            logger.error(
                "%s API response had no visible content model=%s "
                "visible_content_chars=%d reasoning_content_present=%s "
                "reasoning_content_chars=%d finish_reasons=%s",
                self.display_name,
                request.model_id,
                len(stream_result.visible_content.strip()),
                bool(stream_result.reasoning_content),
                len(stream_result.reasoning_content),
                list(stream_result.finish_reasons),
            )
            raise AIProviderError(self._empty_answer_message())
        logger.info(
            "%s API request completed model=%s visible_content_chars=%d "
            "reasoning_content_present=%s reasoning_content_chars=%d finish_reasons=%s",
            self.display_name,
            request.model_id,
            len(stream_result.visible_content.strip()),
            bool(stream_result.reasoning_content),
            len(stream_result.reasoning_content),
            list(stream_result.finish_reasons),
        )
        return stream_result.visible_content.strip()

    def test_connection(
        self,
        model_id: str | None = None,
        capability: str = "text",
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Make a minimal non-streaming request for Settings diagnostics."""

        self._raise_if_cancelled(cancel_event)
        if not self.config.api_key:
            raise AIProviderError(self._missing_api_key_message())
        client = self._get_client()
        response = None
        try:
            response = client.chat.completions.create(
                model=model_id or self.config.model_id,
                messages=[{"role": "user", "content": "ping"}],
                temperature=0,
                max_tokens=1,
                timeout=self.config.request_timeout,
                stream=False,
            )
            self._raise_if_cancelled(cancel_event)
        except AIRequestCancelled:
            raise
        except Exception as exc:  # SDK exception classes vary across versions.
            raise AIProviderError(self._format_error(exc)) from exc
        finally:
            self._close_stream(response)
        return True

    def _consume_stream(
        self,
        response: Any,
        cancel_event: threading.Event | None,
    ) -> AIStreamResult:
        visible_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reasons: set[str] = set()
        for chunk in response:
            self._raise_if_cancelled(cancel_event)
            content, reasoning, finish_reason = self._chunk_metadata(chunk)
            if content:
                visible_parts.append(content)
            if reasoning:
                reasoning_parts.append(reasoning)
            if finish_reason:
                finish_reasons.add(finish_reason)
        self._raise_if_cancelled(cancel_event)
        return AIStreamResult(
            visible_content="".join(visible_parts),
            reasoning_content="".join(reasoning_parts),
            finish_reasons=tuple(sorted(finish_reasons)),
        )

    def _extra_body(self, _request: AIRequest) -> dict[str, Any] | None:
        """Return provider-specific request extras for one request."""

        return None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.config.api_key:
            raise AIProviderError(self._missing_api_key_environment_message())
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIProviderError(self._missing_openai_message()) from exc
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.request_timeout,
            max_retries=0,
        )
        return self._client

    def _format_error(self, _exc: Exception) -> str:
        return f"{self.display_name} API request failed. Check the network, API Key, and model configuration."

    def _missing_api_key_message(self) -> str:
        return f"No {self.display_name} API Key is configured. Save one in Settings."

    def _missing_api_key_environment_message(self) -> str:
        return (
            f"No {self.display_name} API Key is configured. "
            "Save one in Settings or check the .env file."
        )

    def _missing_openai_message(self) -> str:
        return "The openai dependency is missing. Run python -m pip install -r requirements.txt."

    def _empty_answer_message(self) -> str:
        return f"{self.display_name} returned an empty answer."

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AIRequestCancelled("AI request cancelled")

    @staticmethod
    def _chunk_content(chunk: Any) -> str:
        """Extract visible text from OpenAI SDK chunks and test doubles."""

        return OpenAICompatibleProvider._chunk_metadata(chunk)[0]

    @staticmethod
    def _chunk_metadata(chunk: Any) -> tuple[str, str, str | None]:
        """Extract visible/reasoning content and finish metadata from a chunk."""

        try:
            choices = chunk["choices"] if isinstance(chunk, dict) else chunk.choices
            choice = choices[0]
            delta = choice.get("delta") if isinstance(choice, dict) else choice.delta
            content = delta.get("content") if isinstance(delta, dict) else delta.content
            reasoning = (
                delta.get("reasoning_content")
                if isinstance(delta, dict)
                else getattr(delta, "reasoning_content", None)
            )
            if reasoning is None:
                reasoning = (
                    choice.get("reasoning_content")
                    if isinstance(choice, dict)
                    else getattr(choice, "reasoning_content", None)
                )
            finish_reason = (
                choice.get("finish_reason")
                if isinstance(choice, dict)
                else getattr(choice, "finish_reason", None)
            )
        except (AttributeError, IndexError, KeyError, TypeError):
            return "", "", None
        return (
            content if isinstance(content, str) else "",
            reasoning if isinstance(reasoning, str) else "",
            finish_reason if isinstance(finish_reason, str) else None,
        )

    @staticmethod
    def _close_stream(response: Any) -> None:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.debug("AI stream close failed", exc_info=True)


__all__ = ["OpenAICompatibleProvider"]
