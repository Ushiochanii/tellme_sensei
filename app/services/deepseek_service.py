"""DeepSeek chat-completion service with cooperative stream cancellation."""

from __future__ import annotations

import base64
import logging
import threading
from typing import Any

from app.config import AppConfig
from app.localization import (
    DEFAULT_ANSWER_LANGUAGE,
    DEFAULT_INTERFACE_LANGUAGE,
    answer_language_instruction,
    tr,
)

logger = logging.getLogger(__name__)


VISION_MODEL = "deepseek-v4-flash-vision-exp"


def _answer_contract(language: str) -> str:
    return answer_language_instruction(language)


def _text_system_prompt(language: str) -> str:
    return """You are an exam study assistant.
The user will provide an exam question recognized through OCR.
Understand the question, identify the answer, explain the reasoning, and summarize the key concepts.
For multiple-choice questions, clearly identify the correct option and explain why.
If OCR contains an obvious error, infer from context and mention the possible OCR error.
If the information is insufficient, do not invent an answer.

""" + _answer_contract(language)


def _vision_system_prompt(language: str) -> str:
    return """You are an exam study assistant.
The user will provide a question screenshot; the screenshot is the primary source and OCR must not be assumed.
Read the question, text, labels, axes, options, tables, diagrams, geometry, network topology, and flow structures.
For multiple-choice questions, clearly identify the selected option and explain why.
Do not guess information that cannot be read or determined.

""" + _answer_contract(language)


def _context_question_system_prompt(language: str) -> str:
    return """You are an exam study assistant.
The user will provide text recognized separately from a shared Context region and a current Question region.
Use the shared Context as background and answer only the current Question.
For multiple-choice questions, clearly identify the correct option and explain why.
If OCR contains an obvious error, infer from context and mention the possible OCR error.
If the information is insufficient, do not invent an answer.

""" + _answer_contract(language)


# Keep the public constants for integrations that imported them before answer
# language preferences existed.  Runtime requests use the config-aware helpers
# above so all three analysis paths share one language contract.
SYSTEM_PROMPT = _text_system_prompt(DEFAULT_ANSWER_LANGUAGE)
VISION_SYSTEM_PROMPT = _vision_system_prompt(DEFAULT_ANSWER_LANGUAGE)
CONTEXT_QUESTION_SYSTEM_PROMPT = _context_question_system_prompt(DEFAULT_ANSWER_LANGUAGE)


class DeepSeekError(RuntimeError):
    """A user-facing, key-safe DeepSeek request error."""


class DeepSeekCancelled(DeepSeekError):
    """Raised when a streaming request is cooperatively cancelled."""


class DeepSeekService:
    """Send Text and Vision requests through the OpenAI-compatible SDK."""

    def __init__(self, config: AppConfig, client: Any | None = None) -> None:
        self.config = config
        self._client = client

    @property
    def interface_language(self) -> str:
        return getattr(self.config, "interface_language", DEFAULT_INTERFACE_LANGUAGE)

    @property
    def answer_language(self) -> str:
        return getattr(self.config, "answer_language", DEFAULT_ANSWER_LANGUAGE)

    def analyze(
        self,
        ocr_text: str,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Analyze OCR text and return a complete answer assembled from stream chunks."""

        text = ocr_text.strip()
        if not text:
            raise DeepSeekError(tr("error.deepseek_empty_ocr", self.interface_language))
        self._raise_if_cancelled(cancel_event)

        return self._stream_completion(
            model=self.config.model,
            messages=[
                {"role": "system", "content": _text_system_prompt(self.answer_language)},
                {"role": "user", "content": f"下面是 OCR 识别到的题目：\n\n{text}"},
            ],
            cancel_event=cancel_event,
            log_context=f"text_length={len(text)}",
        )

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
            raise DeepSeekError(
                tr("error.deepseek_empty_question_ocr", self.interface_language)
            )
        self._raise_if_cancelled(cancel_event)
        return self._stream_completion(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": _context_question_system_prompt(self.answer_language),
                },
                {
                    "role": "user",
                    "content": (
                        "以下内容由两个截图区域分别 OCR 得到。\n\n"
                        f"【公共题干 / Context】\n{context or '（未识别到有效文字）'}\n\n"
                        f"【当前问题 / Question】\n{question}"
                    ),
                },
            ],
            cancel_event=cancel_event,
            log_context=(
                f"context_text_length={len(context)} question_text_length={len(question)}"
            ),
        )

    def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Send one in-memory screenshot directly to the fixed Vision model."""

        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise DeepSeekError(tr("error.deepseek_empty_image", self.interface_language))
        mime_type = mime_type.strip().lower()
        if mime_type != "image/png":
            raise DeepSeekError(tr("error.deepseek_png_only", self.interface_language))
        self._raise_if_cancelled(cancel_event)
        encoded = base64.b64encode(bytes(image_bytes)).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        return self._stream_completion(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": _vision_system_prompt(self.answer_language),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this question screenshot directly and follow the specified answer format.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ],
            cancel_event=cancel_event,
            log_context=f"mode=vision image_bytes={len(image_bytes)} model={VISION_MODEL}",
            extra_body={"thinking": {"type": "enabled"}},
        )

    def _stream_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        cancel_event: threading.Event | None,
        log_context: str,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        client = self._get_client()
        logger.info("DeepSeek API request started %s", log_context)
        response = None
        visible_content_chars = 0
        reasoning_content_chars = 0
        finish_reasons: set[str] = set()
        try:
            request_kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "timeout": self.config.request_timeout,
                "stream": True,
            }
            if extra_body is not None:
                request_kwargs["extra_body"] = extra_body
            response = client.chat.completions.create(**request_kwargs)
            answer_parts: list[str] = []
            for chunk in response:
                self._raise_if_cancelled(cancel_event)
                content, reasoning, finish_reason = self._chunk_metadata(chunk)
                if content:
                    answer_parts.append(content)
                    visible_content_chars += len(content.strip())
                if reasoning:
                    reasoning_content_chars += len(reasoning)
                if finish_reason:
                    finish_reasons.add(finish_reason)
            self._raise_if_cancelled(cancel_event)
            answer = "".join(answer_parts)
        except DeepSeekCancelled:
            logger.info("DeepSeek API request cancelled")
            raise
        except Exception as exc:  # SDK exception classes vary across versions.
            error = self._format_error(exc)
            logger.error("DeepSeek API request failed: %s", error)
            raise DeepSeekError(error) from exc
        finally:
            self._close_stream(response)

        if not isinstance(answer, str) or not answer.strip():
            logger.error(
                "DeepSeek API response had no visible content model=%s "
                "visible_content_chars=%d reasoning_content_present=%s "
                "reasoning_content_chars=%d finish_reasons=%s",
                model,
                visible_content_chars,
                reasoning_content_chars > 0,
                reasoning_content_chars,
                sorted(finish_reasons),
            )
            raise DeepSeekError(tr("error.deepseek_empty_answer", self.interface_language))
        logger.info(
            "DeepSeek API request completed model=%s visible_content_chars=%d "
            "reasoning_content_present=%s reasoning_content_chars=%d finish_reasons=%s",
            model,
            len(answer.strip()),
            reasoning_content_chars > 0,
            reasoning_content_chars,
            sorted(finish_reasons),
        )
        return answer.strip()

    def test_connection(self, cancel_event: threading.Event | None = None) -> bool:
        """Make a minimal non-streaming request for the Settings window."""

        self._raise_if_cancelled(cancel_event)
        if not self.config.api_key:
            raise DeepSeekError(tr("error.deepseek_missing_api_key", self.interface_language))

        client = self._get_client()
        response = None
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": "ping"}],
                temperature=0,
                max_tokens=1,
                timeout=self.config.request_timeout,
                stream=False,
            )
            self._raise_if_cancelled(cancel_event)
        except DeepSeekCancelled:
            raise
        except Exception as exc:  # SDK exception classes vary across versions.
            raise DeepSeekError(self._format_error(exc)) from exc
        finally:
            self._close_stream(response)
        return True

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise DeepSeekCancelled("DeepSeek request cancelled")

    @staticmethod
    def _chunk_content(chunk: Any) -> str:
        """Extract text from OpenAI SDK chunks and simple test doubles."""

        return DeepSeekService._chunk_metadata(chunk)[0]

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
                logger.debug("DeepSeek stream close failed", exc_info=True)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.config.api_key:
            raise DeepSeekError(tr("error.deepseek_missing_api_key_env", self.interface_language))
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise DeepSeekError(tr("error.deepseek_missing_openai", self.interface_language)) from exc
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.request_timeout,
            max_retries=0,
        )
        return self._client

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
