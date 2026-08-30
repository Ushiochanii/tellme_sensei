"""TellMeSensei's provider-neutral analysis prompt contract."""

from __future__ import annotations

import base64
from typing import Any

from app.localization import (
    DEFAULT_ANSWER_LANGUAGE,
    answer_language_instruction,
)


def _text_system_prompt(language: str) -> str:
    return """You are an exam study assistant.
The user will provide an exam question recognized through OCR.
Understand the question, identify the answer, explain the reasoning, and summarize the key concepts.
For multiple-choice questions, clearly identify the correct option and explain why.
If OCR contains an obvious error, infer from context and mention the possible OCR error.
If the information is insufficient, do not invent an answer.

""" + answer_language_instruction(language)


def _vision_system_prompt(language: str) -> str:
    return """You are an exam study assistant.
The user will provide a question screenshot; the screenshot is the primary source and OCR must not be assumed.
Read the question, text, labels, axes, options, tables, diagrams, geometry, network topology, and flow structures.
For multiple-choice questions, clearly identify the selected option and explain why.
Do not guess information that cannot be read or determined.

""" + answer_language_instruction(language)


def _context_question_system_prompt(language: str) -> str:
    return """You are an exam study assistant.
The user will provide text recognized separately from a shared Context region and a current Question region.
Use the shared Context as background and answer only the current Question.
For multiple-choice questions, clearly identify the correct option and explain why.
If OCR contains an obvious error, infer from context and mention the possible OCR error.
If the information is insufficient, do not invent an answer.

""" + answer_language_instruction(language)


SYSTEM_PROMPT = _text_system_prompt(DEFAULT_ANSWER_LANGUAGE)
VISION_SYSTEM_PROMPT = _vision_system_prompt(DEFAULT_ANSWER_LANGUAGE)
CONTEXT_QUESTION_SYSTEM_PROMPT = _context_question_system_prompt(DEFAULT_ANSWER_LANGUAGE)


class AnalysisPromptBuilder:
    """Build the same analysis messages regardless of the selected provider."""

    def __init__(self, answer_language: str = DEFAULT_ANSWER_LANGUAGE) -> None:
        self.answer_language = answer_language

    def build_text(self, ocr_text: str) -> list[dict[str, Any]]:
        """Build one OCR-text analysis request."""

        return [
            {"role": "system", "content": _text_system_prompt(self.answer_language)},
            {"role": "user", "content": f"下面是 OCR 识别到的题目：\n\n{ocr_text}"},
        ]

    def build_context_question(
        self,
        context_text: str,
        question_text: str,
    ) -> list[dict[str, Any]]:
        """Build one Context + Question analysis request."""

        return [
            {
                "role": "system",
                "content": _context_question_system_prompt(self.answer_language),
            },
            {
                "role": "user",
                "content": (
                    "以下内容由两个截图区域分别 OCR 得到。\n\n"
                    f"【公共题干 / Context】\n{context_text or '（未识别到有效文字）'}\n\n"
                    f"【当前问题 / Question】\n{question_text}"
                ),
            },
        ]

    def build_vision(
        self,
        image_data_url: str | bytes | bytearray,
    ) -> list[dict[str, Any]]:
        """Build one direct screenshot analysis request."""

        if isinstance(image_data_url, (bytes, bytearray)):
            image_data_url = "data:image/png;base64," + base64.b64encode(
                bytes(image_data_url)
            ).decode("ascii")
        return [
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
                        "image_url": {"url": image_data_url},
                    },
                ],
            },
        ]


__all__ = [
    "AnalysisPromptBuilder",
    "CONTEXT_QUESTION_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "VISION_SYSTEM_PROMPT",
    "_context_question_system_prompt",
    "_text_system_prompt",
    "_vision_system_prompt",
]
