"""QThread worker for cancellable OCR and DeepSeek processing."""

from __future__ import annotations

import inspect
import logging
import threading
import uuid
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.ocr.base import OCRProvider
from app.ocr.types import OCRError, OCRLine, OCRResult
from app.pipeline import PipelineError, PipelineResult
from app.services.deepseek_service import DeepSeekCancelled, DeepSeekError, DeepSeekService
from app.thread_info import current_thread_info

logger = logging.getLogger(__name__)


class ProcessingCancelled(RuntimeError):
    """Internal control flow for a cooperative worker cancellation."""


class ProcessingWorker(QObject):
    """Run one OCR/AI task outside the Qt GUI thread."""

    # Legacy signals are retained for service compatibility. The job_* signals
    # are used by the GUI and carry the job identifier for stale-result checks.
    ocr_started = Signal()
    ocr_finished = Signal(str)
    ai_started = Signal()
    result_ready = Signal(object)
    error_occurred = Signal(str)
    job_ocr_started = Signal(str)
    job_ocr_finished = Signal(str, str)
    job_ai_started = Signal(str)
    job_result_ready = Signal(str, object)
    job_error_occurred = Signal(str, str)
    cancelled = Signal(str)
    job_finished = Signal(str)
    finished = Signal()

    def __init__(
        self,
        image: Any | None,
        ocr_service: OCRProvider,
        deepseek_service: DeepSeekService,
        ocr_text: str | None = None,
        job_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.image = image
        self.ocr_service = ocr_service
        self.deepseek_service = deepseek_service
        self.job_id = job_id or uuid.uuid4().hex
        self._ocr_text = ocr_text
        self._cancel_event = cancel_event or threading.Event()
        self._cancelled_emitted = False

    @Slot()
    def request_cancel(self) -> None:
        """Request cooperative cancellation; safe to call from the GUI thread."""

        self._cancel_event.set()
        logger.info("processing cancellation requested job_id=%s", self.job_id)

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @Slot()
    def run(self) -> None:
        """Execute the task and communicate only through Qt signals."""

        logger.info("Worker.run entered job_id=%s [%s]", self.job_id, current_thread_info())
        try:
            self._raise_if_cancelled()
            if self._ocr_text is None:
                logger.info("OCR started job_id=%s [%s]", self.job_id, current_thread_info())
                self.ocr_started.emit()
                self.job_ocr_started.emit(self.job_id)
                if self.image is None:
                    raise PipelineError("没有可处理的截图。")
                logger.info("before OCRService.recognize job_id=%s [%s]", self.job_id, current_thread_info())
                ocr_result = self.ocr_service.recognize(self.image)
                logger.info(
                    "after OCRService.recognize job_id=%s text_length=%d [%s]",
                    self.job_id,
                    len(ocr_result.text),
                    current_thread_info(),
                )
                self._ocr_text = ocr_result.text
            else:
                logger.info("OCR skipped for re-analysis job_id=%s [%s]", self.job_id, current_thread_info())
                ocr_result = OCRResult(
                    text=self._ocr_text,
                    lines=(OCRLine(self._ocr_text),) if self._ocr_text else (),
                )

            self.ocr_finished.emit(self._ocr_text or "")
            self.job_ocr_finished.emit(self.job_id, self._ocr_text or "")
            logger.info(
                "OCR finished job_id=%s text_length=%d [%s]",
                self.job_id,
                len(self._ocr_text or ""),
                current_thread_info(),
            )
            self._raise_if_cancelled()
            if not self._ocr_text:
                raise PipelineError("没有识别到有效文字，请重新截取题目区域。")

            self._raise_if_cancelled()
            logger.info("AI started job_id=%s [%s]", self.job_id, current_thread_info())
            self.ai_started.emit()
            self.job_ai_started.emit(self.job_id)
            answer = self._analyze_with_cancellation(self._ocr_text)
            self._raise_if_cancelled()
            logger.info(
                "AI finished job_id=%s answer_length=%d [%s]",
                self.job_id,
                len(answer),
                current_thread_info(),
            )
            result = PipelineResult(ocr=ocr_result, answer=answer)
            self.result_ready.emit(result)
            self.job_result_ready.emit(self.job_id, result)
        except (ProcessingCancelled, DeepSeekCancelled):
            self._emit_cancelled()
        except (OCRError, DeepSeekError, PipelineError) as exc:
            logger.error("GUI processing failed job_id=%s: %s [%s]", self.job_id, exc, current_thread_info())
            self.error_occurred.emit(str(exc))
            self.job_error_occurred.emit(self.job_id, str(exc))
        except Exception:
            logger.exception("GUI Worker internal error job_id=%s [%s]", self.job_id, current_thread_info())
            message = "处理过程中发生内部错误，请重试。"
            self.error_occurred.emit(message)
            self.job_error_occurred.emit(self.job_id, message)
        finally:
            logger.info("Worker finished job_id=%s [%s]", self.job_id, current_thread_info())
            self.job_finished.emit(self.job_id)
            self.finished.emit()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise ProcessingCancelled

    def _emit_cancelled(self) -> None:
        if self._cancelled_emitted:
            return
        self._cancelled_emitted = True
        logger.info("Worker cancelled job_id=%s [%s]", self.job_id, current_thread_info())
        self.cancelled.emit(self.job_id)

    def _analyze_with_cancellation(self, text: str) -> str:
        analyze = self.deepseek_service.analyze
        try:
            parameters = inspect.signature(analyze).parameters
            accepts_cancel = "cancel_event" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            accepts_cancel = True
        if accepts_cancel:
            return analyze(text, cancel_event=self._cancel_event)
        return analyze(text)
