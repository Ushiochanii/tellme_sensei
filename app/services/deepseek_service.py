"""DeepSeek chat-completion service with cooperative stream cancellation."""

from __future__ import annotations

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


class DeepSeekError(RuntimeError):
    """A user-facing, key-safe DeepSeek request error."""


class DeepSeekCancelled(DeepSeekError):
    """Raised when a streaming request is cooperatively cancelled."""


class DeepSeekService:
    """Send normalized OCR text to DeepSeek through the OpenAI-compatible SDK."""

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

        client = self._get_client()
        logger.info("DeepSeek API request started text_length=%d", len(text))
        response = None
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"下面是 OCR 识别到的题目：\n\n{text}"},
                ],
                temperature=0.2,
                timeout=self.config.request_timeout,
                stream=True,
            )
            answer_parts: list[str] = []
            for chunk in response:
                self._raise_if_cancelled(cancel_event)
                content = self._chunk_content(chunk)
                if content:
                    answer_parts.append(content)
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
            raise DeepSeekError("DeepSeek 返回了空答案。")
        logger.info("DeepSeek API request completed")
        return answer.strip()

    def test_connection(self, cancel_event: threading.Event | None = None) -> bool:
        """Make a minimal non-streaming request for the Settings window."""

        self._raise_if_cancelled(cancel_event)
        if not self.config.api_key:
            raise DeepSeekError("未配置 DeepSeek API Key。")

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

        try:
            choices = chunk["choices"] if isinstance(chunk, dict) else chunk.choices
            choice = choices[0]
            delta = choice.get("delta") if isinstance(choice, dict) else choice.delta
            content = delta.get("content") if isinstance(delta, dict) else delta.content
        except (AttributeError, IndexError, KeyError, TypeError):
            return ""
        return content if isinstance(content, str) else ""

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
                "未配置 DeepSeek API Key。请复制 .env.example 为 .env，并填写 DEEPSEEK_API_KEY。"
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
            return "DeepSeek API Key 无效（401）。请检查 .env 中的 DEEPSEEK_API_KEY。"
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
