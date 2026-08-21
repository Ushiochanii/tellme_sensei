"""Minimal settings UI with secure API-key storage and async connection testing."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig, ConfigError, ConfigManager
from app.services.deepseek_service import DeepSeekCancelled, DeepSeekError, DeepSeekService
from app.settings.secret_store import SecretStoreError

logger = logging.getLogger(__name__)


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager or ConfigManager()
        self._connection_thread: QThread | None = None
        self._connection_worker: ConnectionTestWorker | None = None
        self._connection_cancel_event: threading.Event | None = None
        self._close_requested = False
        self._shutdown_requested = False
        self._shutdown_ready_emitted = False

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
        form.addRow("DeepSeek API Key", self.api_key_edit)
        form.addRow("Model", self.model_edit)
        form.addRow("Request timeout", self.timeout_edit)
        root.addLayout(form)

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

    def _load_current_values(self) -> None:
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError:
            config = AppConfig(api_key="")
        self.api_key_edit.setText(config.api_key)
        self.model_edit.setText(config.model)
        self.timeout_edit.setText(str(int(config.request_timeout) if config.request_timeout.is_integer() else config.request_timeout))

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
        current = self.config_manager.load(require_api_key=False)
        return AppConfig(
            api_key=self.api_key_edit.text().strip(),
            model=model,
            base_url=current.base_url,
            request_timeout=request_timeout,
            ocr_language=current.ocr_language,
        )

    @Slot()
    def test_connection(self) -> None:
        if self._connection_thread is not None and self._connection_thread.isRunning():
            return
        try:
            config = self._read_config_from_fields()
        except (ConfigError, ValueError) as exc:
            self._set_status(str(exc))
            return
        if not config.api_key:
            self._set_status("请输入 API Key 后再测试连接")
            return

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
        if self._shutdown_requested:
            self._emit_shutdown_ready()

    @Slot()
    def save(self) -> None:
        try:
            config = self._read_config_from_fields()
            self.config_manager.save_settings(
                config.api_key,
                config.model,
                config.request_timeout,
            )
        except (ConfigError, SecretStoreError, ValueError) as exc:
            self._set_status(str(exc))
            return
        self._set_status("设置已保存")
        self.settings_saved.emit()
        self.close()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def is_connection_running(self) -> bool:
        return self._connection_thread is not None and self._connection_thread.isRunning()

    @Slot()
    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        if self.is_connection_running():
            if self._connection_worker is not None:
                self._connection_worker.request_cancel()
            self._close_requested = True
            self.hide()
            return
        self.hide()
        self._emit_shutdown_ready()

    def _emit_shutdown_ready(self) -> None:
        if self._shutdown_ready_emitted:
            return
        self._shutdown_ready_emitted = True
        self.shutdown_ready.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self.is_connection_running():
            self._close_requested = True
            if self._connection_worker is not None:
                self._connection_worker.request_cancel()
            self.hide()
            event.accept()
            return
        event.accept()
