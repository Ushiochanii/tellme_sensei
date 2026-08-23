"""GUI pipeline coordinator used by both tray mode and the dev window."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.capture.overlay import CaptureOverlay
from app.config import ConfigError, ConfigManager
from app.ocr.factory import create_ocr_provider
from app.platform.base import GlobalHotkeyManager
from app.services.deepseek_service import DeepSeekService
from app.state import AppState
from app.thread_info import current_thread_info
from app.ui.answer_window import AnswerWindow
from app.ui.settings_window import SettingsWindow
from app.workers.processing_worker import ProcessingWorker

logger = logging.getLogger(__name__)


class MainWindow(QWidget):
    """Keep GUI state and route work to the existing services/worker."""

    processing_finished = Signal()
    shutdown_ready = Signal()

    def __init__(
        self,
        debug_capture_path: Path | None = None,
        tray_mode: bool = False,
        config_manager: ConfigManager | None = None,
        hotkey_manager: GlobalHotkeyManager | None = None,
    ) -> None:
        super().__init__()
        self.debug_capture_path = debug_capture_path
        self.tray_mode = tray_mode
        self.config_manager = config_manager or ConfigManager()
        self.hotkey_manager = hotkey_manager
        self.state = AppState.IDLE
        self._shutting_down = False
        self._overlay: CaptureOverlay | None = None
        self._answer_window: AnswerWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self.processing_thread: QThread | None = None
        self.processing_worker: ProcessingWorker | None = None
        self._active_job_id: str | None = None
        self._cancelled_job_id: str | None = None
        self._busy = False
        self._last_ocr_text = ""
        self._shutdown_ready_emitted = False

        self.setWindowTitle("AI 学习助手")
        self.setFixedSize(260, 140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        label = QLabel("Phase 4-7 调试入口")
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

    @Slot()
    def request_shutdown(self) -> None:
        """Request non-blocking shutdown and emit when the worker is stopped."""

        if self._shutting_down:
            return
        self._shutting_down = True
        self._busy = True
        self.capture_button.setEnabled(False)

        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

        if self._settings_window is not None:
            self._settings_window.request_shutdown()

        if self._answer_window is not None:
            self._answer_window.close()

        thread = self.processing_thread
        if thread is not None and thread.isRunning():
            self.state = AppState.CANCELLING
            if self._answer_window is not None:
                self._answer_window.set_cancelling()
            if self.processing_worker is not None:
                self.processing_worker.request_cancel()
            logger.info("shutdown waiting for processing thread to finish")
            return

        if self._settings_window is not None and self._settings_window.is_connection_running():
            logger.info("shutdown waiting for settings connection test to finish")
            return

        self._emit_shutdown_ready()

    def _emit_shutdown_ready(self) -> None:
        if self._shutdown_ready_emitted:
            return
        self._shutdown_ready_emitted = True
        logger.info("main window shutdown ready")
        self.shutdown_ready.emit()

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
        self._answer_window = AnswerWindow(
            settings_repository=self.config_manager.settings_repository
        )
        self._answer_window.closed.connect(self._on_answer_closed)
        self._answer_window.reanalyze_requested.connect(self._retry_analysis)
        self._answer_window.stop_requested.connect(self.cancel_processing)
        self._answer_window.recapture_requested.connect(self._recapture_requested)

    def _launch_worker(self, image: QImage | None, ocr_text: str | None) -> None:
        job_id = uuid.uuid4().hex
        logger.info(
            "start_processing called job_id=%s retry=%s [%s]",
            job_id,
            ocr_text is not None,
            current_thread_info(),
        )
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError as exc:
            self._answer_window.show_error(str(exc))
            self._restore_idle()
            self.processing_finished.emit()
            return

        ocr_provider = create_ocr_provider(config)
        deepseek_service = DeepSeekService(config)
        thread = QThread(self)
        thread.setObjectName("StudyAssistantProcessingThread")
        thread.setProperty("processing_job_id", job_id)
        logger.info("QThread created job_id=%s [%s]", job_id, current_thread_info())
        worker = ProcessingWorker(image, ocr_provider, deepseek_service, ocr_text=ocr_text, job_id=job_id)
        logger.info("Worker created job_id=%s [%s]", job_id, current_thread_info())
        worker.moveToThread(thread)

        thread.started.connect(self._on_thread_started)
        thread.started.connect(worker.run)
        worker.job_ocr_started.connect(self._on_ocr_started)
        worker.job_ocr_finished.connect(self._on_ocr_finished)
        worker.job_ai_started.connect(self._on_ai_started)
        worker.job_result_ready.connect(self._on_result)
        worker.job_error_occurred.connect(self._on_error)
        worker.cancelled.connect(self._on_cancelled)
        worker.job_finished.connect(self._on_worker_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._active_job_id = job_id
        self._cancelled_job_id = None
        self.processing_thread = thread
        self.processing_worker = worker
        thread.start()
        logger.info("QThread.start called job_id=%s [%s]", job_id, current_thread_info())

    @Slot()
    def _on_thread_started(self, job_id: str | None = None) -> None:
        if job_id is None:
            sender = self.sender()
            job_id = sender.property("processing_job_id") if sender is not None else self._active_job_id
        logger.info("QThread.started emitted job_id=%s [%s]", job_id, current_thread_info())

    def _is_active_job(self, job_id: str, signal_name: str) -> bool:
        if job_id != self._active_job_id:
            logger.info("ignored stale %s job_id=%s active_job_id=%s", signal_name, job_id, self._active_job_id)
            return False
        return True

    @Slot(str)
    def _on_ocr_started(self, job_id: str) -> None:
        if not self._is_active_job(job_id, "ocr_started"):
            return
        self.state = AppState.OCR_PROCESSING
        if self._answer_window is not None:
            self._answer_window.set_ocr_processing()

    @Slot(str, str)
    def _on_ocr_finished(self, job_id: str, text: str) -> None:
        if not self._is_active_job(job_id, "ocr_finished"):
            return
        self._last_ocr_text = text
        if self._answer_window is not None:
            self._answer_window.set_ocr_text(text)

    @Slot(str)
    def _on_ai_started(self, job_id: str) -> None:
        if not self._is_active_job(job_id, "ai_started"):
            return
        self.state = AppState.AI_PROCESSING
        if self._answer_window is not None:
            self._answer_window.set_ai_processing()

    @Slot(str, object)
    def _on_result(self, job_id: str, result) -> None:
        if not self._is_active_job(job_id, "result_ready"):
            return
        if self._answer_window is not None:
            self._answer_window.set_ocr_text(result.ocr.text)
            self._answer_window.set_result(result.answer)

    @Slot(str, str)
    def _on_error(self, job_id: str, message: str | None = None) -> None:
        if message is None:
            message = job_id
            job_id = self._active_job_id
            if job_id is None:
                self.state = AppState.ERROR
                if self._answer_window is not None:
                    self._answer_window.show_error(message)
                return
        if not self._is_active_job(job_id, "error"):
            return
        self.state = AppState.ERROR
        if self._answer_window is not None:
            self._answer_window.show_error(message)

    @Slot(str)
    def _on_cancelled(self, job_id: str) -> None:
        if not self._is_active_job(job_id, "cancelled"):
            return
        self._cancelled_job_id = job_id
        self.state = AppState.CANCELLING
        if self._answer_window is not None:
            self._answer_window.show_cancelled()

    @Slot(str)
    def _on_worker_finished(self, job_id: str) -> None:
        if self._is_active_job(job_id, "worker_finished"):
            logger.info("Worker finished signal received job_id=%s [%s]", job_id, current_thread_info())

    @Slot()
    def _on_thread_finished(self, job_id: str | None = None) -> None:
        if job_id is None:
            sender = self.sender()
            job_id = sender.property("processing_job_id") if sender is not None else self._active_job_id
        if not self._is_active_job(job_id, "thread_finished"):
            return
        logger.info("QThread finished job_id=%s [%s]", job_id, current_thread_info())
        self.processing_thread = None
        self.processing_worker = None
        self._active_job_id = None
        self._busy = False
        self.state = AppState.IDLE
        self.capture_button.setEnabled(True)
        if self._answer_window is not None:
            if self._cancelled_job_id == job_id:
                self._answer_window.show_cancelled()
            self._answer_window.set_retry_enabled(bool(self._last_ocr_text))
        self._cancelled_job_id = None
        self.processing_finished.emit()
        if self._shutting_down:
            self._maybe_emit_shutdown_ready()

    @Slot()
    def _on_settings_shutdown_ready(self) -> None:
        self._maybe_emit_shutdown_ready()

    def _maybe_emit_shutdown_ready(self) -> None:
        if self._shutting_down:
            if self.processing_thread is not None and self.processing_thread.isRunning():
                return
            if self._settings_window is not None and self._settings_window.is_connection_running():
                return
            self._emit_shutdown_ready()

    @Slot()
    def cancel_processing(self) -> None:
        """Request a cooperative stop for the active OCR/AI job."""

        if self.state is AppState.CANCELLING:
            logger.info("cancel ignored: already cancelling")
            return
        if self.state not in (AppState.OCR_PROCESSING, AppState.AI_PROCESSING):
            logger.info("cancel ignored: no processing job")
            return
        if self.processing_worker is None or self._active_job_id is None:
            logger.info("cancel ignored: processing worker unavailable")
            return
        self.state = AppState.CANCELLING
        if self._answer_window is not None:
            self._answer_window.set_cancelling()
        self.processing_worker.request_cancel()

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
    def _recapture_requested(self) -> None:
        if self._busy or self.state is not AppState.IDLE:
            logger.info("capture ignored: application busy")
            return
        answer = self._answer_window
        self._answer_window = None
        if answer is not None:
            answer.close()
            answer.deleteLater()
        self.start_capture()

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

    def show_settings(self) -> None:
        """Show one reusable SettingsWindow from the system tray."""

        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                config_manager=self.config_manager,
                hotkey_manager=self.hotkey_manager,
            )
            self._settings_window.shutdown_ready.connect(self._on_settings_shutdown_ready)
        self._settings_window.reload_values()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _restore_idle(self) -> None:
        self._busy = False
        self.state = AppState.IDLE
        self.capture_button.setEnabled(True)

    def shutdown(self) -> None:
        """Backward-compatible alias for the non-blocking shutdown request."""

        self.request_shutdown()
        if self._answer_window is not None:
            self._answer_window.close()
            self._answer_window = None
