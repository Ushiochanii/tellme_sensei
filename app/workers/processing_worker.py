"""QThread worker for OCR and DeepSeek processing."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.pipeline import PipelineError, PipelineResult
from app.services.deepseek_service import DeepSeekError, DeepSeekService
from app.services.ocr_service import OCRError, OCRLine, OCRResult, OCRService
from app.thread_info import current_thread_info

logger = logging.getLogger(__name__)


class ProcessingWorker(QObject):
    """Run one OCR/AI task outside the Qt GUI thread."""

    ocr_started = Signal()
    ocr_finished = Signal(str)
    ai_started = Signal()
    result_ready = Signal(object)
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        image: Any | None,
        ocr_service: OCRService,
        deepseek_service: DeepSeekService,
        ocr_text: str | None = None,
    ) -> None:
        super().__init__()
        self.image = image
        self.ocr_service = ocr_service
        self.deepseek_service = deepseek_service
        self._ocr_text = ocr_text

    @Slot()
    def run(self) -> None:
        """Execute the task and communicate only through Qt signals."""

        logger.info("Worker.run entered [%s]", current_thread_info())
        try:
            logger.info("OCR started [%s]", current_thread_info())
            self.ocr_started.emit()
            if self._ocr_text is None:
                if self.image is None:
                    raise PipelineError("没有可处理的截图。")
                logger.info("before OCRService.recognize [%s]", current_thread_info())
                ocr_result = self.ocr_service.recognize(self.image)
                logger.info(
                    "after OCRService.recognize text_length=%d [%s]",
                    len(ocr_result.text),
                    current_thread_info(),
                )
                self._ocr_text = ocr_result.text
            else:
                logger.info("OCR skipped for re-analysis [%s]", current_thread_info())
                ocr_result = OCRResult(
                    text=self._ocr_text,
                    lines=(OCRLine(self._ocr_text),) if self._ocr_text else (),
                )

            self.ocr_finished.emit(self._ocr_text or "")
            logger.info(
                "OCR finished text_length=%d [%s]",
                len(self._ocr_text or ""),
                current_thread_info(),
            )
            if not self._ocr_text:
                raise PipelineError("没有识别到有效文字，请重新截取题目区域。")

            logger.info("AI started [%s]", current_thread_info())
            self.ai_started.emit()
            answer = self.deepseek_service.analyze(self._ocr_text)
            logger.info("AI finished answer_length=%d [%s]", len(answer), current_thread_info())
            self.result_ready.emit(PipelineResult(ocr=ocr_result, answer=answer))
        except (OCRError, DeepSeekError, PipelineError) as exc:
            logger.error("GUI 处理失败: %s [%s]", exc, current_thread_info())
            self.error_occurred.emit(str(exc))
        except Exception:
            logger.exception("GUI Worker 内部异常 [%s]", current_thread_info())
            self.error_occurred.emit("处理过程中发生内部错误，请重试。")
        finally:
            logger.info("Worker finished [%s]", current_thread_info())
            self.finished.emit()
