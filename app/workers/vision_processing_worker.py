"""QThread worker for direct screenshot analysis through Vision AI."""

from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QBuffer, QObject, QIODevice, Signal, Slot
from PySide6.QtGui import QImage

from app.ai.errors import AIProviderError, AIRequestCancelled
from app.thread_info import current_thread_info

logger = logging.getLogger(__name__)


class VisionProcessingWorker(QObject):
    """Encode one QImage in memory and send it to the Vision API once."""

    ai_started = Signal()
    result_ready = Signal(str)
    error_occurred = Signal(str)
    job_ai_started = Signal(str)
    job_result_ready = Signal(str, str)
    job_error_occurred = Signal(str, str)
    cancelled = Signal(str)
    job_finished = Signal(str)
    finished = Signal()

    def __init__(
        self,
        image: QImage,
        analysis_service,
        job_id: str,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.image = image
        self.analysis_service = analysis_service
        self.job_id = job_id
        self._cancel_event = cancel_event or threading.Event()
        self._cancelled_emitted = False

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_event.set()
        logger.info("vision cancellation requested job_id=%s", self.job_id)

    @Slot()
    def run(self) -> None:
        logger.info("Vision worker entered job_id=%s [%s]", self.job_id, current_thread_info())
        try:
            self._raise_if_cancelled()
            image_bytes = self.encode_png(self.image)
            self._raise_if_cancelled()
            logger.info(
                "Vision analysis started job_id=%s image=%sx%s encoded_bytes=%d",
                self.job_id,
                self.image.width(),
                self.image.height(),
                len(image_bytes),
            )
            self.ai_started.emit()
            self.job_ai_started.emit(self.job_id)
            answer = self.analysis_service.analyze_image(
                image_bytes,
                cancel_event=self._cancel_event,
            )
            self._raise_if_cancelled()
            self.result_ready.emit(answer)
            self.job_result_ready.emit(self.job_id, answer)
        except AIRequestCancelled:
            self._emit_cancelled()
        except AIProviderError as exc:
            logger.error("Vision analysis failed job_id=%s: %s", self.job_id, exc)
            self.error_occurred.emit(str(exc))
            self.job_error_occurred.emit(self.job_id, str(exc))
        except Exception:
            logger.exception("Vision worker internal error job_id=%s", self.job_id)
            message = "图像分析过程中发生内部错误，请重试。"
            self.error_occurred.emit(message)
            self.job_error_occurred.emit(self.job_id, message)
        finally:
            self.job_finished.emit(self.job_id)
            self.finished.emit()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise AIRequestCancelled("AI request cancelled")

    def _emit_cancelled(self) -> None:
        if self._cancelled_emitted:
            return
        self._cancelled_emitted = True
        self.cancelled.emit(self.job_id)

    @staticmethod
    def encode_png(image: Any) -> bytes:
        if not isinstance(image, QImage) or image.isNull():
            raise AIProviderError("截图内容为空，无法进行 Vision 分析。")
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise AIProviderError("无法编码 Vision 截图。")
        try:
            if not image.save(buffer, "PNG"):
                raise AIProviderError("无法编码 Vision 截图。")
            return bytes(buffer.data())
        finally:
            buffer.close()


__all__ = ["VisionProcessingWorker"]
