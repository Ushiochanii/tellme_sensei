"""DeepSeek chat-completion service with cooperative stream cancellation."""

from __future__ import annotations

import base64
import logging
import threading
from typing import Any

from app.config import AppConfig

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一个考试学习助手。
用户会提供通过 OCR 识别得到的考试题目。
请判断题目含义；选择题先明确指出正确选项；给出简洁完整的解析；说明核心知识点。
如果 OCR 内容明显有错误，请根据上下文合理推断并指出可能存在 OCR 错误。
如果信息不足以判断答案，不要编造答案。
请使用以下格式回答：

【答案】...

【解析】...

【知识点】...
"""

VISION_MODEL = "deepseek-v4-flash-vision-exp"
VISION_SYSTEM_PROMPT = """你是一个考试学习助手。
用户会提供一张题目截图，截图本身是主要信息来源，不要假设已经完成 OCR。
请识别题目、相关文字/标签/坐标轴/选项，并在存在图表、表格、几何图形、网络拓扑、流程图或其他视觉结构时结合图形进行推理。
对于选择题，请明确指出所选选项并解释理由；不要猜测无法读清或无法判断的信息。
请使用以下格式回答：

【答案】...

【解析】...

【知识点】...
"""


class DeepSeekError(RuntimeError):
    """A user-facing, key-safe DeepSeek request error."""


class DeepSeekCancelled(DeepSeekError):
    """Raised when a streaming request is cooperatively cancelled."""


class DeepSeekService:
    """Send Text and Vision requests through the OpenAI-compatible SDK."""

    def __init__(self, config: AppConfig, client: Any | None = None) -> None:
        self.config = config
        self._client = client

    def analyze(
        self,
        ocr_text: str,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Analyze OCR text and return a complete answer assembled from stream chunks."""

        text = ocr_text.strip()
        if not text:
            raise DeepSeekError("OCR 没有识别到有效文字，无法请求 DeepSeek。")
        self._raise_if_cancelled(cancel_event)

        return self._stream_completion(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"下面是 OCR 识别到的题目：\n\n{text}"},
            ],
            cancel_event=cancel_event,
            log_context=f"text_length={len(text)}",
        )

    def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Send one in-memory screenshot directly to the fixed Vision model."""

        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise DeepSeekError("截图内容为空，无法请求 DeepSeek Vision。")
        mime_type = mime_type.strip().lower()
        if mime_type != "image/png":
            raise DeepSeekError("Vision Mode 当前只支持 PNG 截图。")
        self._raise_if_cancelled(cancel_event)
        encoded = base64.b64encode(bytes(image_bytes)).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        return self._stream_completion(
            model=VISION_MODEL,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请直接分析这张题目截图，并按指定格式给出答案、解析和知识点。",
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
            raise DeepSeekError("DeepSeek 返回了空答案。")
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
            raise DeepSeekError("未配置 DeepSeek API Key，请在设置中保存 API Key。")

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
            raise DeepSeekError(
                "未配置 DeepSeek API Key，请在设置中保存 API Key，或检查 .env 配置。"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise DeepSeekError(
                "未安装 openai 依赖，请先执行 python -m pip install -r requirements.txt。"
            ) from exc
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.request_timeout,
            max_retries=0,
        )
        return self._client

    @staticmethod
    def _format_error(exc: Exception) -> str:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            return "DeepSeek API Key 无效（401）。请前往设置检查 API Key。"
        if status_code == 403:
            return "DeepSeek API 访问被拒绝（403）。请检查账户权限或 API Key。"
        if status_code == 429:
            return "DeepSeek API 请求过于频繁（429），请稍后重试。"
        if isinstance(status_code, int) and status_code >= 500:
            return f"DeepSeek 服务暂时不可用（{status_code}），请稍后重试。"
        name = type(exc).__name__.lower()
        if "timeout" in name:
            return "DeepSeek API 请求超时，请检查网络后重试。"
        if "connection" in name:
            return "连接 DeepSeek API 失败，请检查网络连接。"
        return "DeepSeek API 请求失败，请检查网络、API Key 和模型配置。"
