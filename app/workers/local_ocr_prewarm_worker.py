"""Cancellable background initialization for the persistent Local OCR session."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from app.ocr.local_session import LocalOCRSession
from app.ocr.types import OCRCancelled

logger = logging.getLogger(__name__)


class LocalOCRPrewarmWorker(QObject):
    succeeded = Signal()
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        session: LocalOCRSession,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.session = session
        self.cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        try:
            self.session.prepare(cancel_event=self.cancel_event)
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit()
        except OCRCancelled:
            self.cancelled.emit()
        except Exception as exc:
            logger.warning("Local OCR prewarm failed: %s", type(exc).__name__)
            self.failed.emit(type(exc).__name__)
        finally:
            self.finished.emit()

    @Slot()
    def request_cancel(self) -> None:
        self.cancel_event.set()
