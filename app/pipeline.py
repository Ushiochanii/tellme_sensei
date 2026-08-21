"""Phase 3 image -> OCR -> DeepSeek console pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.deepseek_service import DeepSeekError, DeepSeekService
from app.services.ocr_service import OCRError, OCRResult, OCRService

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """A user-facing pipeline error."""


@dataclass(frozen=True)
class PipelineResult:
    """Both the normalized OCR text and the LLM answer."""

    ocr: OCRResult
    answer: str


class StudyPipeline:
    """Coordinate OCR and DeepSeek without coupling either service to the CLI."""

    def __init__(self, ocr_service: OCRService, deepseek_service: DeepSeekService) -> None:
        self.ocr_service = ocr_service
        self.deepseek_service = deepseek_service

    def run(self, image: str | Path | Any) -> PipelineResult:
        try:
            ocr_result = self.ocr_service.recognize(image)
        except OCRError as exc:
            raise PipelineError(str(exc)) from exc
        if not ocr_result.text.strip():
            raise PipelineError("没有识别到有效文字，请重新截取题目区域。")

        try:
            answer = self.deepseek_service.analyze(ocr_result.text)
        except DeepSeekError as exc:
            raise PipelineError(str(exc)) from exc
        return PipelineResult(ocr=ocr_result, answer=answer)
