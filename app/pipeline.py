"""Phase 3 image -> OCR -> DeepSeek console pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ocr.base import OCRProvider
from app.ocr.types import OCRError, OCRResult
from app.ai.errors import AIProviderError

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """A user-facing pipeline error."""


@dataclass(frozen=True)
class PipelineResult:
    """Both the normalized OCR text and the LLM answer."""

    ocr: OCRResult
    answer: str


@dataclass(frozen=True)
class ContextQuestionPipelineResult:
    """OCR output and answer for one Context + Question pair."""

    context_ocr: OCRResult
    question_ocr: OCRResult
    answer: str
    context_revision: int
    question_revision: int


class StudyPipeline:
    """Coordinate OCR and DeepSeek without coupling either service to the CLI."""

    def __init__(self, ocr_service: OCRProvider, analysis_service) -> None:
        self.ocr_service = ocr_service
        self.analysis_service = analysis_service

    def run(self, image: str | Path | Any) -> PipelineResult:
        try:
            ocr_result = self.ocr_service.recognize(image)
        except OCRError as exc:
            raise PipelineError(str(exc)) from exc
        if not ocr_result.text.strip():
            raise PipelineError("没有识别到有效文字，请重新截取题目区域。")

        try:
            answer = self.analysis_service.analyze(ocr_result.text)
        except AIProviderError as exc:
            raise PipelineError(str(exc)) from exc
        return PipelineResult(ocr=ocr_result, answer=answer)
