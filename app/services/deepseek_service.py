"""DeepSeek chat-completion service."""

from __future__ import annotations

import logging
from typing import Any

from app.config import AppConfig

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一个考试学习助手。

用户会提供通过 OCR 识别得到的考试题目。

请：
1. 判断题目的含义。
2. 如果是选择题，首先明确指出正确选项。
3. 给出简洁但完整的解析。
4. 说明这道题涉及的核心知识点。
5. 如果 OCR 内容明显存在错误，可以根据上下文进行合理推断，但必须指出可能存在 OCR 错误。
6. 如果信息不足以判断答案，不要编造答案。

请严格按照以下格式回答：

【答案】
...

【解析】
...

【知识点】
...
"""


class DeepSeekError(RuntimeError):
    """A user-facing, key-safe DeepSeek request error."""


class DeepSeekService:
    """Send normalized OCR text to DeepSeek through the OpenAI-compatible SDK."""

    def __init__(self, config: AppConfig, client: Any | None = None) -> None:
        self.config = config
        self._client = client

    def analyze(self, ocr_text: str) -> str:
        """Analyze OCR text and return the assistant's complete answer."""

        text = ocr_text.strip()
        if not text:
            raise DeepSeekError("OCR 没有识别到有效文字，无法请求 DeepSeek。")

        client = self._get_client()
        logger.info("DeepSeek API 请求开始（文本长度=%d）", len(text))
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"下面是 OCR 识别得到的题目：\n\n{text}",
                    },
                ],
                temperature=0.2,
                timeout=self.config.request_timeout,
            )
        except Exception as exc:  # SDK exception classes vary across versions.
            error = self._format_error(exc)
            logger.error("DeepSeek API 请求失败: %s", error)
            raise DeepSeekError(error) from exc

        try:
            answer = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise DeepSeekError("DeepSeek 返回了无法解析的响应。") from exc

        if not isinstance(answer, str) or not answer.strip():
            raise DeepSeekError("DeepSeek 返回了空答案。")
        logger.info("DeepSeek API 请求成功")
        return answer.strip()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.config.api_key:
            raise DeepSeekError(
                "未配置 DeepSeek API Key。请复制 .env.example 为 .env，"
                "并填写 DEEPSEEK_API_KEY。"
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
