"""GUI pipeline coordinator used by both tray mode and the dev window."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.capture.overlay import CaptureOverlay
from app.config import ConfigError, ConfigManager
from app.services.deepseek_service import DeepSeekService
from app.services.ocr_service import OCRService
from app.state import AppState
from app.thread_info import current_thread_info
from app.ui.answer_window import AnswerWindow
from app.workers.processing_worker import ProcessingWorker

logger = logging.getLogger(__name__)


class MainWindow(QWidget):
    """Keep GUI state and route work to the existing services/worker."""

    processing_finished = Signal()

    def __init__(self, debug_capture_path: Path | None = None, tray_mode: bool = False) -> None:
        super().__init__()
        self.debug_capture_path = debug_capture_path
        self.tray_mode = tray_mode
        self.state = AppState.IDLE
        self._shutting_down = False
        self._overlay: CaptureOverlay | None = None
        self._answer_window: AnswerWindow | None = None
        self.processing_thread: QThread | None = None
        self.processing_worker: ProcessingWorker | None = None
        self._busy = False
        self._last_ocr_text = ""

        self.setWindowTitle("AI 学习助手")
        self.setFixedSize(260, 140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        label = QLabel("Phase 4–7 调试入口")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.capture_button = QPushButton("截图识别")
        self.capture_button.setMinimumHeight(38)
        self.capture_button.clicked.connect(self.start_capture)
        layout.addWidget(label)
        layout.addWidget(self.capture_button)

    @Slot()
    def start_capture(self) -> bool:
        """Start one capture unless the application is already busy."""

        if self._shutting_down or self.state is not AppState.IDLE or self._busy or self._overlay is not None:
            logger.info("capture ignored: application busy")
            return False

        logger.info("capture requested")
        self.state = AppState.CAPTURING
        self._busy = True
        self.capture_button.setEnabled(False)
        if not self.tray_mode:
            self.hide()
        try:
            self._overlay = CaptureOverlay(debug_path=self.debug_capture_path)
        except Exception as exc:
            logger.exception("创建截图 Overlay 失败")
            self._restore_idle()
            if not self.tray_mode:
                self.show()
            self._show_or_create_answer()
            self._answer_window.show_at_current_screen()
            self._answer_window.show_error(f"无法开始截图：{exc}")
            return False

        self._overlay.captured.connect(self._on_capture)
        self._overlay.cancelled.connect(self._on_capture_cancelled)
        self._overlay.begin()
        return True

    @Slot(QImage)
    def _on_capture(self, image: QImage) -> None:
        logger.info(
            "capture completed image=%sx%s [%s]",
            image.width(),
            image.height(),
            current_thread_info(),
        )
        self._overlay = None
        self._busy = True
        self.state = AppState.OCR_PROCESSING
        self.capture_button.setEnabled(False)
        self._last_ocr_text = ""
        self._show_or_create_answer()
        self._answer_window.show_processing()
        self._launch_worker(image.copy(), ocr_text=None)

    @Slot()
    def _on_capture_cancelled(self) -> None:
        self._overlay = None
        self._restore_idle()
        if not self.tray_mode:
            self.show()
            self.raise_()
            self.activateWindow()

    def _show_or_create_answer(self) -> None:
        if self._answer_window is not None:
            return
        self._answer_window = AnswerWindow()
        self._answer_window.closed.connect(self._on_answer_closed)
        self._answer_window.reanalyze_requested.connect(self._retry_analysis)

    def _launch_worker(self, image: QImage | None, ocr_text: str | None) -> None:
        logger.info(
            "start_processing called retry=%s [%s]",
            ocr_text is not None,
            current_thread_info(),
        )
        try:
            config = ConfigManager().load(require_api_key=False)
        except ConfigError as exc:
            self._answer_window.show_error(str(exc))
            self._restore_idle()
            self.processing_finished.emit()
            return

        ocr_service = OCRService(language=config.ocr_language)
        deepseek_service = DeepSeekService(config)
        thread = QThread(self)
        thread.setObjectName("StudyAssistantProcessingThread")
        logger.info("QThread created [%s]", current_thread_info())
        worker = ProcessingWorker(image, ocr_service, deepseek_service, ocr_text=ocr_text)
        logger.info("Worker created [%s]", current_thread_info())
        worker.moveToThread(thread)

        thread.started.connect(self._on_thread_started)
        thread.started.connect(worker.run)
        worker.ocr_started.connect(self._on_ocr_started)
        worker.ocr_finished.connect(self._on_ocr_finished)
        worker.ai_started.connect(self._on_ai_started)
        worker.result_ready.connect(self._on_result)
        worker.error_occurred.connect(self._on_error)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        # These are intentionally long-lived Python references. The worker must
        # remain alive until QThread.finished has run.
        self.processing_thread = thread
        self.processing_worker = worker
        thread.start()
        logger.info("QThread.start called [%s]", current_thread_info())

    @Slot()
    def _on_thread_started(self) -> None:
        logger.info("QThread.started emitted [%s]", current_thread_info())

    @Slot()
    def _on_ocr_started(self) -> None:
        self.state = AppState.OCR_PROCESSING
        if self._answer_window is not None:
            self._answer_window.set_status("正在识别题目...")

    @Slot(str)
    def _on_ocr_finished(self, text: str) -> None:
        self._last_ocr_text = text
        if self._answer_window is not None:
            self._answer_window.set_ocr_text(text)

    @Slot()
    def _on_ai_started(self) -> None:
        self.state = AppState.AI_PROCESSING
        if self._answer_window is not None:
            self._answer_window.set_ai_processing()

    @Slot(object)
    def _on_result(self, result) -> None:
        if self._answer_window is not None:
            self._answer_window.set_ocr_text(result.ocr.text)
            self._answer_window.set_result(result.answer)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self.state = AppState.ERROR
        if self._answer_window is not None:
            self._answer_window.show_error(message)

    @Slot()
    def _on_worker_finished(self) -> None:
        logger.info("Worker finished signal received [%s]", current_thread_info())

    @Slot()
    def _on_thread_finished(self) -> None:
        logger.info("QThread finished [%s]", current_thread_info())
        self.processing_thread = None
        self.processing_worker = None
        self._busy = False
        self.state = AppState.IDLE
        self.capture_button.setEnabled(True)
        if self._answer_window is not None:
            self._answer_window.set_retry_enabled(bool(self._last_ocr_text))
        self.processing_finished.emit()

    @Slot()
    def _retry_analysis(self) -> None:
        if self._busy or self.state is not AppState.IDLE or not self._last_ocr_text:
            logger.info("capture ignored: application busy")
            return
        self._busy = True
        self.state = AppState.AI_PROCESSING
        if self._answer_window is not None:
            self._answer_window.set_ai_processing()
        self._launch_worker(None, ocr_text=self._last_ocr_text)

    @Slot()
    def _on_answer_closed(self) -> None:
        answer = self._answer_window
        self._answer_window = None
        if answer is not None:
            answer.deleteLater()
        if not self.tray_mode and not self._shutting_down:
            self.show()
            self.raise_()
            self.activateWindow()

    def show_launcher(self) -> None:
        """Show the small development window from the tray Settings action."""

        self.show()
        self.raise_()
        self.activateWindow()

    def _restore_idle(self) -> None:
        self._busy = False
        self.state = AppState.IDLE
        self.capture_button.setEnabled(True)

    def shutdown(self) -> None:
        """Stop accepting work and synchronously clean up GUI-owned resources."""

        if self._shutting_down:
            return
        self._shutting_down = True
        self._restore_idle()
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

        thread = self.processing_thread
        if thread is not None and thread.isRunning():
            logger.info("waiting for processing worker during shutdown")
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(8000):
                logger.warning("processing worker did not stop in time; terminating thread")
                thread.terminate()
                thread.wait(2000)
        self.processing_thread = None
        self.processing_worker = None
        if self._answer_window is not None:
            self._answer_window.close()
            self._answer_window = None
