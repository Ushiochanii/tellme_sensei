"""Minimal settings UI with secure API-key storage and async connection testing."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig, ConfigError, ConfigManager
from app.local_ocr.component_manager import ComponentError, LocalOCRComponentManager
from app.local_ocr.download import LocalOCRDownloadWorker
from app.local_ocr.manifest import resolve_manifest_url
from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import DEFAULT_SHORTCUT, HotkeySpec, HotkeySpecError
from app.services.deepseek_service import DeepSeekCancelled, DeepSeekError, DeepSeekService
from app.settings.secret_store import SecretStoreError

logger = logging.getLogger(__name__)
CONNECTION_TEST_TIMEOUT = 10.0
API_KEY_ENV_OVERRIDE_MESSAGE = (
    "当前 API Key 由环境变量 DEEPSEEK_API_KEY 覆盖。"
    "在设置中保存新的 API Key 不会改变当前实际使用的 Key。"
)


class ConnectionTestWorker(QObject):
    """Run one minimal DeepSeek request outside the Qt GUI thread."""

    succeeded = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, config: AppConfig, cancel_event: threading.Event | None = None) -> None:
        super().__init__()
        self.config = config
        self.cancel_event = cancel_event or threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            DeepSeekService(self.config).test_connection(self.cancel_event)
            if not self.cancel_event.is_set():
                self.succeeded.emit()
        except DeepSeekCancelled:
            pass
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("settings connection test failed")
            self.failed.emit("连接测试过程中发生内部错误")
        finally:
            self.finished.emit()

    @Slot()
    def request_cancel(self) -> None:
        self.cancel_event.set()


class SettingsWindow(QWidget):
    """A single-instance settings window owned by MainWindow."""

    settings_saved = Signal()
    shutdown_ready = Signal()

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        hotkey_manager: GlobalHotkeyManager | None = None,
        component_manager: LocalOCRComponentManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager or ConfigManager()
        self.hotkey_manager = hotkey_manager
        self.component_manager = component_manager or LocalOCRComponentManager()
        self._connection_thread: QThread | None = None
        self._connection_worker: ConnectionTestWorker | None = None
        self._connection_cancel_event: threading.Event | None = None
        self._close_requested = False
        self._shutdown_requested = False
        self._shutdown_ready_emitted = False
        self._download_thread: QThread | None = None
        self._download_worker: LocalOCRDownloadWorker | None = None
        self._download_cancel_event: threading.Event | None = None

        self.setWindowTitle("设置")
        self.setMinimumWidth(430)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("输入 DeepSeek API Key")
        self.model_edit = QLineEdit()
        self.timeout_edit = QLineEdit()
        self.shortcut_edit = QKeySequenceEdit()
        self.shortcut_edit.setMaximumSequenceLength(1)
        form.addRow("DeepSeek API Key", self.api_key_edit)
        form.addRow("Model", self.model_edit)
        form.addRow("Request timeout", self.timeout_edit)
        form.addRow("Global shortcut", self.shortcut_edit)
        root.addLayout(form)

        ocr_group = QGroupBox("Local OCR")
        ocr_layout = QVBoxLayout(ocr_group)
        self.local_ocr_status_label = QLabel()
        self.local_ocr_size_label = QLabel()
        self.local_ocr_progress = QProgressBar()
        self.local_ocr_progress.setRange(0, 100)
        self.local_ocr_progress.setVisible(False)
        ocr_buttons = QHBoxLayout()
        self.download_ocr_button = QPushButton("Download Local OCR")
        self.cancel_download_button = QPushButton("Cancel")
        self.verify_ocr_button = QPushButton("Verify")
        self.remove_ocr_button = QPushButton("Remove Local OCR")
        self.cancel_download_button.setVisible(False)
        self.download_ocr_button.clicked.connect(self.download_local_ocr)
        self.cancel_download_button.clicked.connect(self.cancel_local_ocr_download)
        self.verify_ocr_button.clicked.connect(self.verify_local_ocr)
        self.remove_ocr_button.clicked.connect(self.remove_local_ocr)
        ocr_buttons.addWidget(self.download_ocr_button)
        ocr_buttons.addWidget(self.cancel_download_button)
        ocr_buttons.addWidget(self.verify_ocr_button)
        ocr_buttons.addWidget(self.remove_ocr_button)
        ocr_layout.addWidget(self.local_ocr_status_label)
        ocr_layout.addWidget(self.local_ocr_size_label)
        ocr_layout.addWidget(self.local_ocr_progress)
        ocr_layout.addLayout(ocr_buttons)
        root.addWidget(ocr_group)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.save_button = QPushButton("保存")
        self.cancel_button = QPushButton("取消")
        self.test_button.clicked.connect(self.test_connection)
        self.save_button.clicked.connect(self.save)
        self.cancel_button.clicked.connect(self.close)
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)

        self._load_current_values()
        self._refresh_local_ocr_state()

    def _load_current_values(self) -> None:
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError:
            config = AppConfig(api_key="")
        self.api_key_edit.setText(config.api_key)
        self.model_edit.setText(config.model)
        self.timeout_edit.setText(str(int(config.request_timeout) if config.request_timeout.is_integer() else config.request_timeout))
        self.shortcut_edit.setKeySequence(QKeySequence(config.global_shortcut))
        if self.config_manager.has_explicit_api_key():
            self._set_status(API_KEY_ENV_OVERRIDE_MESSAGE)

    def reload_values(self) -> None:
        """Reload persisted values when the window is shown again."""

        if not self.is_connection_running():
            self._load_current_values()
        if self._download_thread is None or not self._download_thread.isRunning():
            self._refresh_local_ocr_state()

    def _refresh_local_ocr_state(self) -> None:
        if self.component_manager.is_installed():
            self.local_ocr_status_label.setText(f"Installed · v{self.component_manager.version}")
            self.download_ocr_button.setVisible(False)
            self.verify_ocr_button.setEnabled(True)
            self.remove_ocr_button.setEnabled(True)
        else:
            self.local_ocr_status_label.setText("Not installed")
            self.download_ocr_button.setVisible(True)
            self.verify_ocr_button.setEnabled(False)
            self.remove_ocr_button.setEnabled(False)

    def _set_download_state(self, running: bool) -> None:
        connection_running = self.is_connection_running()
        self.download_ocr_button.setEnabled(not running and not connection_running)
        self.verify_ocr_button.setEnabled(not running and not connection_running and self.component_manager.is_installed())
        self.remove_ocr_button.setEnabled(not running and not connection_running and self.component_manager.is_installed())
        self.test_button.setEnabled(not running)
        self.cancel_download_button.setVisible(running)
        self.local_ocr_progress.setVisible(running)

    @Slot()
    def download_local_ocr(self) -> None:
        if self._download_thread is not None and self._download_thread.isRunning():
            return
        if self.is_connection_running():
            self._set_status("Wait for the connection test to finish before downloading Local OCR.")
            return
        manifest_url = resolve_manifest_url(self.config_manager.project_root)
        if "example.invalid" in manifest_url:
            self.local_ocr_status_label.setText("Download URL is not configured.")
            return
        self._download_cancel_event = threading.Event()
        worker = LocalOCRDownloadWorker(manifest_url, self.component_manager, self._download_cancel_event)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self.local_ocr_progress.setValue)
        worker.manifest_loaded.connect(self._on_local_ocr_manifest_loaded)
        worker.status_changed.connect(self.local_ocr_status_label.setText)
        worker.succeeded.connect(self._on_local_ocr_download_succeeded)
        worker.failed.connect(self._on_local_ocr_download_failed)
        worker.cancelled.connect(self._on_local_ocr_download_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_local_ocr_download_finished)
        self._download_worker = worker
        self._download_thread = thread
        self._set_download_state(True)
        self.local_ocr_progress.setValue(0)
        thread.start()

    @Slot()
    def cancel_local_ocr_download(self) -> None:
        if self._download_worker is not None:
            self._download_worker.request_cancel()
            self.local_ocr_status_label.setText("Cancelling...")
            self.cancel_download_button.setEnabled(False)

    @Slot(str)
    def _on_local_ocr_download_succeeded(self, installed_path: str) -> None:
        self.local_ocr_status_label.setText(f"Installed · v{self.component_manager.version}")
        self.local_ocr_size_label.setText("")

    @Slot(int)
    def _on_local_ocr_manifest_loaded(self, size: int) -> None:
        self.local_ocr_size_label.setText(f"Download size: {size / (1024 * 1024):.1f} MB")

    @Slot(str)
    def _on_local_ocr_download_failed(self, message: str) -> None:
        self.local_ocr_status_label.setText(f"Error: {message}")

    @Slot()
    def _on_local_ocr_download_cancelled(self) -> None:
        self.local_ocr_status_label.setText("Download cancelled")

    @Slot()
    def _on_local_ocr_download_finished(self) -> None:
        self._download_thread = None
        self._download_worker = None
        self._download_cancel_event = None
        self._set_download_state(False)
        self._refresh_local_ocr_state()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def verify_local_ocr(self) -> None:
        if not self.component_manager.verify_installation():
            self.local_ocr_status_label.setText("Local OCR installation is incomplete.")
            return
        self.local_ocr_status_label.setText("Verifying...")
        if self.component_manager.smoke_test():
            self.local_ocr_status_label.setText(f"Installed · v{self.component_manager.version} · verified")
        else:
            self.local_ocr_status_label.setText("Local OCR smoke test failed.")

    @Slot()
    def remove_local_ocr(self) -> None:
        if not self.component_manager.is_installed():
            self._refresh_local_ocr_state()
            return
        answer = QMessageBox.question(
            self,
            "Remove Local OCR",
            "Remove the installed Local OCR component?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.component_manager.remove()
            except (OSError, ComponentError) as exc:
                logger.warning("local OCR removal failed: %s", type(exc).__name__)
                self.local_ocr_status_label.setText(f"Failed to remove Local OCR: {exc}")
                return
            self._refresh_local_ocr_state()

    def _read_config_from_fields(self) -> AppConfig:
        model = self.model_edit.text().strip()
        if not model:
            raise ValueError("Model 不能为空")
        try:
            request_timeout = float(self.timeout_edit.text().strip())
        except ValueError as exc:
            raise ValueError("Request timeout 必须是正数") from exc
        if request_timeout <= 0:
            raise ValueError("Request timeout 必须是正数")
        sequence = self.shortcut_edit.keySequence()
        if sequence.count() != 1:
            raise ValueError("快捷键只能包含一个组合")
        try:
            global_shortcut = HotkeySpec.parse(
                sequence.toString(QKeySequence.SequenceFormat.PortableText)
            ).canonical
        except HotkeySpecError as exc:
            raise ValueError(str(exc)) from exc
        current = self.config_manager.load(require_api_key=False)
        return AppConfig(
            api_key=self.api_key_edit.text().strip(),
            model=model,
            base_url=current.base_url,
            request_timeout=request_timeout,
            ocr_language=current.ocr_language,
            global_shortcut=global_shortcut,
        )

    @Slot()
    def test_connection(self) -> None:
        if self._connection_thread is not None and self._connection_thread.isRunning():
            return
        if self._download_thread is not None and self._download_thread.isRunning():
            self._set_status("Wait for the Local OCR download to finish before testing the connection.")
            return
        try:
            config = self._read_config_from_fields()
        except (ConfigError, ValueError) as exc:
            self._set_status(str(exc))
            return
        if not config.api_key:
            self._set_status("请输入 API Key 后再测试连接")
            return

        config = replace(config, request_timeout=min(config.request_timeout, CONNECTION_TEST_TIMEOUT))
        self._close_requested = False
        self._connection_cancel_event = threading.Event()
        worker = ConnectionTestWorker(config, self._connection_cancel_event)
        thread = QThread(self)
        thread.setObjectName("SettingsConnectionTestThread")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_connection_success)
        worker.failed.connect(self._on_connection_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_connection_finished)
        self._connection_worker = worker
        self._connection_thread = thread
        self.test_button.setEnabled(False)
        self.download_ocr_button.setEnabled(False)
        self.verify_ocr_button.setEnabled(False)
        self.remove_ocr_button.setEnabled(False)
        self._set_status("正在测试连接...")
        thread.start()

    @Slot()
    def _on_connection_success(self) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self._set_status("连接成功")

    @Slot(str)
    def _on_connection_failed(self, message: str) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self._set_status(message)

    @Slot()
    def _on_connection_finished(self) -> None:
        self._connection_thread = None
        self._connection_worker = None
        self._connection_cancel_event = None
        self.test_button.setEnabled(True)
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._set_download_state(False)
        self._maybe_emit_shutdown_ready()

    @Slot()
    def save(self) -> None:
        old_shortcut = self.hotkey_manager.shortcut if self.hotkey_manager is not None else None
        rebound = False
        try:
            config = self._read_config_from_fields()
            if (
                self.hotkey_manager is not None
                and old_shortcut is not None
                and config.global_shortcut != old_shortcut
            ):
                if not self.hotkey_manager.rebind(config.global_shortcut):
                    self._set_status("快捷键注册失败，可能已被其他程序占用。")
                    return
                rebound = True
            self.config_manager.save_settings(
                config.api_key,
                config.model,
                config.request_timeout,
                config.global_shortcut,
            )
        except (ConfigError, SecretStoreError, ValueError) as exc:
            if rebound and self.hotkey_manager is not None and old_shortcut is not None:
                if not self.hotkey_manager.rebind(old_shortcut):
                    logger.error("failed to rollback shortcut after settings save failure")
            self._set_status(str(exc))
            return
        self._set_status("设置已保存")
        if self.config_manager.has_explicit_api_key():
            self._set_status(API_KEY_ENV_OVERRIDE_MESSAGE)
        self.settings_saved.emit()
        self.close()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def is_connection_running(self) -> bool:
        return self._connection_thread is not None and self._connection_thread.isRunning()

    def is_download_running(self) -> bool:
        return self._download_thread is not None and self._download_thread.isRunning()

    def has_running_background_operations(self) -> bool:
        return self.is_connection_running() or self.is_download_running()

    @Slot()
    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        self._close_requested = True
        if self.is_download_running():
            self.cancel_local_ocr_download()
        if self.is_connection_running():
            if self._connection_worker is not None:
                self._connection_worker.request_cancel()
        self.hide()
        self._maybe_emit_shutdown_ready()

    def _maybe_emit_shutdown_ready(self) -> None:
        if self._shutdown_requested and not self.has_running_background_operations():
            self._emit_shutdown_ready()

    def _emit_shutdown_ready(self) -> None:
        if self._shutdown_ready_emitted:
            return
        self._shutdown_ready_emitted = True
        self.shutdown_ready.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self._close_requested = True
        if self.is_download_running():
            self.cancel_local_ocr_download()
        if self.is_connection_running():
            if self._connection_worker is not None:
                self._connection_worker.request_cancel()
            self.hide()
            event.accept()
            return
        if self.is_download_running():
            self.hide()
            event.accept()
            return
        event.accept()
