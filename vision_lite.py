"""Minimal Vision-only TellMeSensei Lite application entry point.

This entry point deliberately does not import the Full application's MainWindow,
OCR providers, Local OCR runtime, settings UI, or tray controller.
"""

from __future__ import annotations

import logging
import sys
import uuid

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app.capture.overlay import CaptureOverlay
from app.config import AppConfig, ConfigError, ConfigManager
from app.lite_settings import VisionLiteSettings
from app.lite_tray import VisionLiteTray
from app.platform.factory import create_global_hotkey_manager
from app.platform.hotkey import DEFAULT_VISION_SHORTCUT, VISION_HOTKEY_ID
from app.platform import screen_permissions
from app.services.deepseek_service import DeepSeekService
from app.single_instance import SingleInstanceGuard
from app.ui.answer_window import AnswerWindow
from app.workers.vision_processing_worker import VisionProcessingWorker

logger = logging.getLogger(__name__)
LITE_SERVER_NAME = "tellme-sensei-lite-single-instance"


class VisionLiteWindow(QWidget):
    """Small floating controller for one direct screenshot-to-Vision flow."""

    shutdown_requested = Signal()

    def __init__(
        self,
        *,
        config_manager: ConfigManager | None = None,
        hotkey_manager=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager or ConfigManager()
        self.hotkey_manager = hotkey_manager
        self._overlay: CaptureOverlay | None = None
        self._answer_window: AnswerWindow | None = None
        self._processing_thread: QThread | None = None
        self._processing_worker: VisionProcessingWorker | None = None
        self._active_job_id: str | None = None
        self._last_image = None
        self._busy = False
        self._closing = False
        self._screen_permission_request_attempted = False
        self._settings_window: VisionLiteSettings | None = None

        self.setWindowTitle("TellMeSensei Lite")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setFixedSize(240, 120)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("TellMeSensei Lite"))
        self.capture_button = QPushButton("截图分析")
        self.capture_button.clicked.connect(self.start_capture)
        layout.addWidget(self.capture_button)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel(DEFAULT_VISION_SHORTCUT))

        if self.hotkey_manager is not None:
            self.hotkey_manager.triggered.connect(self.start_capture)

    @property
    def busy(self) -> bool:
        return self._busy

    @Slot()
    def start_capture(self) -> bool:
        """Start a Vision capture unless another capture/job is active."""

        if self._closing or self._busy or self._overlay is not None:
            logger.info("Vision Lite capture ignored: busy")
            return False
        if not self._load_config_for_request():
            return False
        if not self._ensure_screen_recording_permission():
            return False

        self._busy = True
        self.capture_button.setEnabled(False)
        self.hide()
        try:
            self._overlay = CaptureOverlay()
        except Exception as exc:
            logger.exception("Vision Lite overlay creation failed")
            self._restore_idle()
            self.show()
            QMessageBox.warning(self, "截图失败", f"无法开始截图：{exc}")
            return False
        self._overlay.captured.connect(self._on_capture)
        self._overlay.cancelled.connect(self._on_capture_cancelled)
        self._overlay.begin()
        return True

    def _load_config_for_request(self) -> AppConfig | None:
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return None
        if config.api_key:
            self._request_config = config
            return config

        self.show_settings(missing_key=True)
        return None

    @Slot()
    def show_controller(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    @Slot()
    def show_settings(self, missing_key: bool = False) -> None:
        if self._settings_window is None:
            self._settings_window = VisionLiteSettings(
                self.config_manager,
                self.hotkey_manager,
                self,
            )
            self._settings_window.finished.connect(self._on_settings_finished)
        if missing_key:
            self._settings_window.show_missing_key_message()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    @Slot(int)
    def _on_settings_finished(self, _result: int) -> None:
        if self._settings_window is not None:
            self._settings_window.hide()

    def show_hotkey_warning(self) -> None:
        self.status_label.setText("快捷键注册失败，请在 Settings 中修改快捷键。")

    def _ensure_screen_recording_permission(self) -> bool:
        try:
            if screen_permissions.has_screen_recording_permission():
                return True
            if not self._screen_permission_request_attempted:
                self._screen_permission_request_attempted = True
                screen_permissions.request_screen_recording_permission()
                if screen_permissions.has_screen_recording_permission():
                    return True
        except Exception:
            logger.exception("Vision Lite screen permission check failed")
        QMessageBox.warning(
            self,
            "需要屏幕录制权限",
            "请在系统设置的隐私与安全性 → 屏幕录制中允许 TellMeSensei Lite。",
        )
        return False

    @Slot(object)
    def _on_capture(self, image) -> None:
        self._overlay = None
        self._last_image = image.copy()
        self.show()
        self.raise_()
        self._show_answer_window()
        self._answer_window.show_vision_processing()
        self._launch_worker(image.copy())

    @Slot()
    def _on_capture_cancelled(self) -> None:
        self._overlay = None
        self._restore_idle()
        if not self._closing:
            self.show()
            self.raise_()

    def _show_answer_window(self) -> None:
        if self._answer_window is not None:
            return
        self._answer_window = AnswerWindow(settings_repository=self.config_manager.settings_repository)
        self._answer_window.stop_requested.connect(self.cancel_processing)
        self._answer_window.reanalyze_requested.connect(self._reanalyze)
        self._answer_window.recapture_requested.connect(self._recapture)
        self._answer_window.closed.connect(self._on_answer_closed)

    def _launch_worker(self, image) -> None:
        config = getattr(self, "_request_config", None)
        if config is None:
            self._restore_idle()
            return
        job_id = uuid.uuid4().hex
        thread = QThread(self)
        thread.setObjectName("VisionLiteProcessingThread")
        thread.setProperty("processing_job_id", job_id)
        worker = VisionProcessingWorker(image, DeepSeekService(config), job_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.job_result_ready.connect(self._on_result)
        worker.job_error_occurred.connect(self._on_error)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._active_job_id = job_id
        self._processing_thread = thread
        self._processing_worker = worker
        thread.start()

    @Slot(str, str)
    def _on_result(self, job_id: str, answer: str) -> None:
        if job_id == self._active_job_id and self._answer_window is not None:
            self._answer_window.set_result(answer)

    @Slot(str, str)
    def _on_error(self, job_id: str, message: str) -> None:
        if job_id == self._active_job_id and self._answer_window is not None:
            self._answer_window.show_error(message)

    @Slot(str)
    def _on_cancelled(self, job_id: str) -> None:
        if job_id == self._active_job_id and self._answer_window is not None:
            self._answer_window.show_cancelled()

    @Slot()
    def cancel_processing(self) -> None:
        if self._processing_worker is not None and self._busy:
            self._processing_worker.request_cancel()

    @Slot()
    def _on_thread_finished(self) -> None:
        self._processing_thread = None
        self._processing_worker = None
        self._active_job_id = None
        self._restore_idle()
        if self._closing:
            QApplication.quit()

    @Slot()
    def _reanalyze(self) -> None:
        if self._busy or self._last_image is None:
            return
        self._busy = True
        self.capture_button.setEnabled(False)
        self._answer_window.show_vision_processing()
        self._launch_worker(self._last_image.copy())

    @Slot()
    def _recapture(self) -> None:
        if self._busy:
            return
        if self._answer_window is not None:
            self._answer_window.close()
            self._answer_window = None
        self.start_capture()

    @Slot()
    def _on_answer_closed(self) -> None:
        self._answer_window = None

    def _restore_idle(self) -> None:
        self._busy = False
        self.capture_button.setEnabled(True)

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        if self.hotkey_manager is not None:
            self.hotkey_manager.unregister()
        if self._answer_window is not None:
            self._answer_window.close()
            self._answer_window = None
        if self._settings_window is not None:
            self._settings_window.close()
            self._settings_window = None
        if self._processing_worker is not None:
            self._processing_worker.request_cancel()
        else:
            QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._closing:
            event.accept()
            return
        self.hide()
        event.ignore()


def main(argv: list[str] | None = None) -> int:
    del argv
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("TellMeSensei Lite")
    guard = SingleInstanceGuard(server_name=LITE_SERVER_NAME, parent=app)
    if not guard.acquire():
        return 0
    config_manager = ConfigManager()
    try:
        config = config_manager.load(require_api_key=False)
        shortcut = config.vision_global_shortcut
    except ConfigError:
        shortcut = DEFAULT_VISION_SHORTCUT
    hotkey = create_global_hotkey_manager(parent=app, shortcut=shortcut, hotkey_id=VISION_HOTKEY_ID)
    if not hotkey.register():
        logger.warning("Vision Lite global hotkey registration failed")
    window = VisionLiteWindow(config_manager=config_manager, hotkey_manager=hotkey)
    tray = VisionLiteTray(parent=app)
    tray.capture_requested.connect(window.start_capture)
    tray.show_controller_requested.connect(window.show_controller)
    tray.settings_requested.connect(window.show_settings)
    tray.quit_requested.connect(tray.hide)
    tray.quit_requested.connect(window.shutdown)
    app.aboutToQuit.connect(window.shutdown)
    app.aboutToQuit.connect(guard.release)
    window.show()
    tray.show()
    if not hotkey.registered:
        window.show_hotkey_warning()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
