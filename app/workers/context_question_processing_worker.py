"""QThread worker for separate Context and Question OCR analysis."""

from __future__ import annotations

import inspect
import logging
import threading
import uuid
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from app.ocr.base import OCRProvider
from app.ocr.types import OCRCancelled, OCRError, OCRResult
from app.pipeline import ContextQuestionPipelineResult, PipelineError
from app.ai.errors import AIProviderError, AIRequestCancelled
from app.thread_info import current_thread_info
from app.workers.processing_worker import ProcessingCancelled

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.auto_watch.context_ocr_cache import ContextOCRCache


class ContextQuestionProcessingWorker(QObject):
    """Run Context OCR, Question OCR, and one structured AI request."""

    context_ocr_started = Signal()
    context_ocr_finished = Signal(str)
    question_ocr_started = Signal()
    question_ocr_finished = Signal(str)
    ocr_started = Signal()
    ocr_finished = Signal(str)
    ai_started = Signal()
    result_ready = Signal(object)
    error_occurred = Signal(str)
    job_context_ocr_started = Signal(str)
    job_context_ocr_finished = Signal(str, str)
    job_question_ocr_started = Signal(str)
    job_question_ocr_finished = Signal(str, str)
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
        context_image: QImage,
        question_image: QImage,
        ocr_service: OCRProvider,
        analysis_service,
        context_revision: int,
        question_revision: int,
        job_id: str | None = None,
        context_ocr_cache: ContextOCRCache | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.context_image = self._copy_image(context_image, "context_image")
        self.question_image = self._copy_image(question_image, "question_image")
        self.ocr_service = ocr_service
        self.analysis_service = analysis_service
        self.context_revision = self._validate_revision(context_revision, "context_revision")
        self.question_revision = self._validate_revision(question_revision, "question_revision")
        self.job_id = job_id or uuid.uuid4().hex
        if context_ocr_cache is None:
            # Keep direct worker imports independent from auto_watch's eager
            # public exports; dispatcher imports this worker while that package
            # is still being initialized.
            from app.auto_watch.context_ocr_cache import ContextOCRCache

            context_ocr_cache = ContextOCRCache()
        self.context_ocr_cache = context_ocr_cache
        self._cancel_event = cancel_event or threading.Event()
        self._cancelled_emitted = False

    @Slot()
    def request_cancel(self) -> None:
        """Request cooperative cancellation; safe to call from the GUI thread."""

        self._cancel_event.set()
        logger.info("context/question cancellation requested job_id=%s", self.job_id)

    @Slot()
    def run(self) -> None:
        logger.info(
            "Context/question worker entered job_id=%s context_revision=%s question_revision=%s [%s]",
            self.job_id,
            self.context_revision,
            self.question_revision,
            current_thread_info(),
        )
        try:
            self._raise_if_cancelled()
            self.ocr_started.emit()
            self.job_ocr_started.emit(self.job_id)

            context_ocr = self.context_ocr_cache.get(self.context_revision)
            if context_ocr is None:
                cache_clear_generation = self.context_ocr_cache.clear_generation
                logger.info("Context OCR started job_id=%s revision=%s", self.job_id, self.context_revision)
                self.context_ocr_started.emit()
                self.job_context_ocr_started.emit(self.job_id)
                context_ocr = self._recognize_with_cancellation(self.context_image)
                self._raise_if_cancelled()
                self.context_ocr_cache.put(
                    self.context_revision,
                    context_ocr,
                    clear_generation=cache_clear_generation,
                )
            else:
                logger.info("Context OCR cache hit job_id=%s revision=%s", self.job_id, self.context_revision)
            self.context_ocr_finished.emit(context_ocr.text)
            self.job_context_ocr_finished.emit(self.job_id, context_ocr.text)

            self._raise_if_cancelled()
            logger.info("Question OCR started job_id=%s revision=%s", self.job_id, self.question_revision)
            self.question_ocr_started.emit()
            self.job_question_ocr_started.emit(self.job_id)
            question_ocr = self._recognize_with_cancellation(self.question_image)
            self._raise_if_cancelled()
            self.question_ocr_finished.emit(question_ocr.text)
            self.job_question_ocr_finished.emit(self.job_id, question_ocr.text)
            self.ocr_finished.emit(question_ocr.text)
            self.job_ocr_finished.emit(self.job_id, question_ocr.text)

            if not question_ocr.text.strip():
                raise PipelineError("没有识别到有效问题文字，请重新截取 Question 区域。")

            self._raise_if_cancelled()
            logger.info("Context/question AI started job_id=%s [%s]", self.job_id, current_thread_info())
            self.ai_started.emit()
            self.job_ai_started.emit(self.job_id)
            answer = self._analyze_with_cancellation(context_ocr.text, question_ocr.text)
            self._raise_if_cancelled()
            result = ContextQuestionPipelineResult(
                context_ocr=context_ocr,
                question_ocr=question_ocr,
                answer=answer,
                context_revision=self.context_revision,
                question_revision=self.question_revision,
            )
            self.result_ready.emit(result)
            self.job_result_ready.emit(self.job_id, result)
        except (ProcessingCancelled, OCRCancelled, AIRequestCancelled):
            self._emit_cancelled()
        except (OCRError, AIProviderError, PipelineError) as exc:
            logger.error("Context/question processing failed job_id=%s: %s", self.job_id, exc)
            self.error_occurred.emit(str(exc))
            self.job_error_occurred.emit(self.job_id, str(exc))
        except Exception:
            logger.exception("Context/question worker internal error job_id=%s", self.job_id)
            message = "上下文和题目处理过程中发生内部错误，请重试。"
            self.error_occurred.emit(message)
            self.job_error_occurred.emit(self.job_id, message)
        finally:
            self.job_finished.emit(self.job_id)
            self.finished.emit()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise ProcessingCancelled

    def _emit_cancelled(self) -> None:
        if self._cancelled_emitted:
            return
        self._cancelled_emitted = True
        logger.info("Context/question worker cancelled job_id=%s [%s]", self.job_id, current_thread_info())
        self.cancelled.emit(self.job_id)

    def _analyze_with_cancellation(self, context_text: str, question_text: str) -> str:
        analyze = self.analysis_service.analyze_context_question
        try:
            parameters = inspect.signature(analyze).parameters
            accepts_cancel = "cancel_event" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            accepts_cancel = True
        if accepts_cancel:
            return analyze(context_text, question_text, cancel_event=self._cancel_event)
        return analyze(context_text, question_text)

    def _recognize_with_cancellation(self, image: Any) -> OCRResult:
        recognize = self.ocr_service.recognize
        try:
            parameters = inspect.signature(recognize).parameters
            accepts_cancel = "cancel_event" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            accepts_cancel = True
        if accepts_cancel:
            return recognize(image, cancel_event=self._cancel_event)
        return recognize(image)

    @staticmethod
    def _copy_image(image: QImage, name: str) -> QImage:
        if not isinstance(image, QImage) or image.isNull() or image.width() <= 0 or image.height() <= 0:
            raise ValueError(f"{name} must be a non-empty QImage")
        return image.copy()

    @staticmethod
    def _validate_revision(value: int, name: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value


__all__ = ["ContextQuestionProcessingWorker", "ContextQuestionPipelineResult"]
