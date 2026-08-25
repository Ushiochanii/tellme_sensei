"""Minimal settings UI with secure API-key storage and async connection testing."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig, ConfigError, ConfigManager
from app.local_ocr.component_manager import ComponentError, LocalOCRComponentManager
from app.local_ocr.download import LocalOCRDownloadWorker
from app.local_ocr.manifest import manifest_url_available, resolve_manifest_url
from app.ocr.local_session import LocalOCRSession
from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import HotkeySpec, HotkeySpecError
from app.ocr.providers.google_vision import GoogleVisionOCRProvider
from app.ocr.types import OCRCancelled, OCRError
from app.platform.ocr import is_local_ocr_supported
from app.services.deepseek_service import DeepSeekCancelled, DeepSeekError, DeepSeekService
from app.settings.secret_store import SecretStoreError

logger = logging.getLogger(__name__)
CONNECTION_TEST_TIMEOUT = 10.0
API_KEY_ENV_OVERRIDE_MESSAGE = (
    "当前 API Key 由环境变量 DEEPSEEK_API_KEY 覆盖。"
    "在设置中保存新的 API Key 不会改变当前实际使用的 Key。"
)
GOOGLE_VISION_ENV_OVERRIDE_MESSAGE = (
    "Google Vision API Key is currently overridden by the environment variable "
    "GOOGLE_VISION_API_KEY. "
    "Saving a different key will not change the key currently in use."
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


class GoogleVisionTestWorker(QObject):
    """Run a generated-image Google Vision diagnostic outside the GUI thread."""

    succeeded = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        api_key: str,
        language: str,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.language = language
        self.timeout = timeout
        self.cancel_event = cancel_event or threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            GoogleVisionOCRProvider(
                api_key=self.api_key,
                language=self.language,
                timeout=self.timeout,
            ).test_connection(self.cancel_event)
            if not self.cancel_event.is_set():
                self.succeeded.emit()
        except OCRCancelled:
            pass
        except OCRError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Google Vision connection test failed")
            self.failed.emit("Google Vision connection test failed.")
        finally:
            self.finished.emit()

    @Slot()
    def request_cancel(self) -> None:
        self.cancel_event.set()


class SettingsWindow(QWidget):
    """A single-instance settings window owned by MainWindow."""

    settings_saved = Signal()
    local_ocr_component_changed = Signal()
    shutdown_ready = Signal()

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        hotkey_manager: GlobalHotkeyManager | None = None,
        vision_hotkey_manager: GlobalHotkeyManager | None = None,
        component_manager: LocalOCRComponentManager | None = None,
        local_ocr_session: LocalOCRSession | None = None,
        parent: QWidget | None = None,
        local_ocr_supported: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager or ConfigManager()
        self.hotkey_manager = hotkey_manager
        self.vision_hotkey_manager = vision_hotkey_manager
        self.component_manager = component_manager or LocalOCRComponentManager()
        self.local_ocr_session = local_ocr_session
        self._local_ocr_supported = (
            is_local_ocr_supported() if local_ocr_supported is None else local_ocr_supported
        )
        self._connection_thread: QThread | None = None
        self._connection_worker: ConnectionTestWorker | None = None
        self._connection_cancel_event: threading.Event | None = None
        self._close_requested = False
        self._shutdown_requested = False
        self._shutdown_ready_emitted = False
        self._download_thread: QThread | None = None
        self._download_worker: LocalOCRDownloadWorker | None = None
        self._download_cancel_event: threading.Event | None = None
        self._google_thread: QThread | None = None
        self._google_worker: GoogleVisionTestWorker | None = None
        self._google_cancel_event: threading.Event | None = None

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
        self.vision_shortcut_edit = QKeySequenceEdit()
        self.vision_shortcut_edit.setMaximumSequenceLength(1)
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.local_mode_radio = QRadioButton("Local")
        self.online_mode_radio = QRadioButton("Online")
        self.ocr_mode_group = QButtonGroup(self)
        self.ocr_mode_group.setExclusive(True)
        self.ocr_mode_group.addButton(self.local_mode_radio)
        self.ocr_mode_group.addButton(self.online_mode_radio)
        self.local_mode_radio.toggled.connect(self._on_provider_changed)
        self.online_mode_radio.toggled.connect(self._on_provider_changed)
        mode_layout.addWidget(self.local_mode_radio)
        mode_layout.addWidget(self.online_mode_radio)
        mode_layout.addStretch(1)
        self.local_engine_combo = QComboBox()
        self.local_engine_combo.addItem("PaddleOCR", "local")
        self.online_service_combo = QComboBox()
        self.online_service_combo.addItem("Google Cloud Vision", "google_vision")
        self.ocr_provider_override_label = QLabel(
            "OCR Provider is controlled by the OCR_PROVIDER environment variable."
        )
        self.ocr_provider_override_label.setWordWrap(True)
        self.ocr_provider_override_label.setVisible(False)
        self.local_ocr_unsupported_label = QLabel(
            "Local OCR for macOS is not installed/supported in this build."
        )
        self.local_ocr_unsupported_label.setWordWrap(True)
        self.local_ocr_unsupported_label.setVisible(False)
        form.addRow("DeepSeek API Key", self.api_key_edit)
        form.addRow("Text model", self.model_edit)
        form.addRow("Request timeout", self.timeout_edit)
        form.addRow("Text shortcut", self.shortcut_edit)
        form.addRow("Vision shortcut", self.vision_shortcut_edit)
        form.addRow("OCR Mode", mode_widget)
        root.addLayout(form)
        root.addWidget(self.ocr_provider_override_label)
        root.addWidget(self.local_ocr_unsupported_label)

        self.local_ocr_group = QGroupBox("Local OCR Engine")
        ocr_layout = QVBoxLayout(self.local_ocr_group)
        local_engine_form = QFormLayout()
        local_engine_form.addRow("Local OCR Engine", self.local_engine_combo)
        ocr_layout.addLayout(local_engine_form)
        self.local_ocr_privacy_label = QLabel(
            "Screenshots are processed on this device."
        )
        self.local_ocr_privacy_label.setWordWrap(True)
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
        ocr_layout.addWidget(self.local_ocr_privacy_label)
        ocr_layout.addWidget(self.local_ocr_status_label)
        ocr_layout.addWidget(self.local_ocr_size_label)
        ocr_layout.addWidget(self.local_ocr_progress)
        ocr_layout.addLayout(ocr_buttons)
        root.addWidget(self.local_ocr_group)

        self.google_vision_group = QGroupBox("Online OCR Service")
        google_layout = QVBoxLayout(self.google_vision_group)
        online_service_form = QFormLayout()
        online_service_form.addRow("Online OCR Service", self.online_service_combo)
        google_layout.addLayout(online_service_form)
        self.google_vision_privacy_label = QLabel(
            "Online OCR. Screenshots will be uploaded to Google Cloud Vision for OCR."
        )
        self.google_vision_privacy_label.setWordWrap(True)
        self.google_vision_api_key_edit = QLineEdit()
        self.google_vision_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_vision_api_key_edit.setPlaceholderText("Enter Google Vision API Key")
        google_key_form = QFormLayout()
        google_key_form.addRow("Google Vision API Key", self.google_vision_api_key_edit)
        self.google_vision_override_label = QLabel(
            "Google Vision API Key is controlled by GOOGLE_VISION_API_KEY."
        )
        self.google_vision_override_label.setWordWrap(True)
        self.google_vision_override_label.setVisible(False)
        self.google_vision_test_button = QPushButton("Test Google Vision")
        self.google_vision_test_button.clicked.connect(self.test_google_vision)
        self.google_vision_status_label = QLabel()
        self.google_vision_status_label.setWordWrap(True)
        google_layout.addWidget(self.google_vision_privacy_label)
        google_layout.addLayout(google_key_form)
        google_layout.addWidget(self.google_vision_override_label)
        google_layout.addWidget(self.google_vision_test_button)
        google_layout.addWidget(self.google_vision_status_label)
        root.addWidget(self.google_vision_group)

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
        self._apply_local_ocr_capability()

    def _apply_local_ocr_capability(self) -> None:
        """Apply separate platform-capability and distribution-availability states."""

        if self._local_ocr_supported and (
            self.component_manager.is_installed()
            or manifest_url_available(self.config_manager.project_root)
        ):
            self.local_ocr_unsupported_label.setVisible(False)
            return
        if self._local_ocr_supported:
            self.local_ocr_unsupported_label.setText(
                "Local OCR is supported on this Mac, but no component distribution is configured yet."
            )
        else:
            self.local_ocr_unsupported_label.setText(
                "Local OCR for macOS is not installed/supported in this build."
            )
        self.online_mode_radio.setChecked(True)
        self.local_mode_radio.setEnabled(False)
        self.local_engine_combo.setEnabled(False)
        self.download_ocr_button.setVisible(False)
        self.cancel_download_button.setVisible(False)
        self.verify_ocr_button.setVisible(False)
        self.remove_ocr_button.setVisible(False)
        self.local_ocr_size_label.setVisible(False)
        self.local_ocr_progress.setVisible(False)
        self.local_ocr_unsupported_label.setVisible(True)
        self._on_provider_changed()

    def _local_ocr_distribution_available(self) -> bool:
        """Return whether download actions have a configured manifest source."""

        return manifest_url_available(self.config_manager.project_root)

    def _local_ocr_is_usable(self) -> bool:
        """Return whether Local OCR is installed or can be downloaded here."""

        return self._local_ocr_supported and (
            self.component_manager.is_installed()
            or self._local_ocr_distribution_available()
        )

    def _load_current_values(self) -> None:
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError:
            config = AppConfig(api_key="")
        self.api_key_edit.setText(config.api_key)
        self.google_vision_api_key_edit.setText(config.google_vision_api_key)
        google_env_override = self.config_manager.has_explicit_google_vision_api_key()
        self.google_vision_api_key_edit.setReadOnly(google_env_override)
        self.google_vision_api_key_edit.setEnabled(not google_env_override)
        self.google_vision_override_label.setVisible(google_env_override)
        self.model_edit.setText(config.model)
        self.timeout_edit.setText(str(int(config.request_timeout) if config.request_timeout.is_integer() else config.request_timeout))
        self.shortcut_edit.setKeySequence(QKeySequence(config.global_shortcut))
        self.vision_shortcut_edit.setKeySequence(QKeySequence(config.vision_global_shortcut))
        is_online = config.ocr_provider == "google_vision" or not self._local_ocr_is_usable()
        provider_env_override = self.config_manager.has_explicit_ocr_provider()
        self.local_mode_radio.setChecked(not is_online)
        self.online_mode_radio.setChecked(is_online)
        self.local_engine_combo.setCurrentIndex(
            max(0, self.local_engine_combo.findData("local"))
        )
        self.online_service_combo.setCurrentIndex(
            max(0, self.online_service_combo.findData("google_vision"))
        )
        self.local_mode_radio.setEnabled(not provider_env_override)
        self.online_mode_radio.setEnabled(not provider_env_override)
        self.local_engine_combo.setEnabled(not provider_env_override)
        self.online_service_combo.setEnabled(not provider_env_override)
        self.ocr_provider_override_label.setVisible(provider_env_override)
        self._on_provider_changed()
        self._show_environment_override_warnings()

    def reload_values(self) -> None:
        """Reload persisted values when the window is shown again."""

        if not self.has_running_background_operations():
            self._load_current_values()
        if not self.is_download_running():
            self._refresh_local_ocr_state()

    @Slot()
    def _on_provider_changed(self) -> None:
        is_google = self.online_mode_radio.isChecked()
        self.local_ocr_group.setVisible(not is_google)
        self.google_vision_group.setVisible(is_google)
        self._refresh_operation_controls()

    def _current_provider_from_ui(self) -> str:
        if self.local_mode_radio.isChecked():
            return str(self.local_engine_combo.currentData() or "local")
        return str(self.online_service_combo.currentData() or "google_vision")

    def _show_environment_override_warnings(self) -> None:
        warnings: list[str] = []
        if self.config_manager.has_explicit_api_key():
            warnings.append(API_KEY_ENV_OVERRIDE_MESSAGE)
        if self.config_manager.has_explicit_google_vision_api_key():
            warnings.append(GOOGLE_VISION_ENV_OVERRIDE_MESSAGE)
        if warnings:
            self._set_status("\n".join(warnings))

    def _refresh_local_ocr_state(self) -> None:
        if not self._local_ocr_supported:
            self._apply_local_ocr_capability()
            self.local_ocr_status_label.setText(
                "Local OCR for macOS is not installed/supported in this build."
            )
            return
        if self.component_manager.is_installed():
            self.local_ocr_status_label.setText(f"Installed · v{self.component_manager.version}")
            self.download_ocr_button.setVisible(False)
        elif not self._local_ocr_distribution_available():
            self.local_ocr_status_label.setText(
                "Local OCR is supported on this Mac, but no component distribution is configured yet."
            )
        else:
            self.local_ocr_status_label.setText("Not installed")
            self.download_ocr_button.setVisible(True)
        self._apply_local_ocr_capability()
        self._refresh_operation_controls()

    def _refresh_operation_controls(
        self,
        *,
        connection_running: bool | None = None,
        download_running: bool | None = None,
        google_running: bool | None = None,
    ) -> None:
        connection_running = (
            self.is_connection_running() if connection_running is None else connection_running
        )
        download_running = (
            self.is_download_running() if download_running is None else download_running
        )
        google_running = (
            self.is_google_test_running() if google_running is None else google_running
        )
        busy = connection_running or download_running or google_running
        self.download_ocr_button.setEnabled(self._local_ocr_supported and not busy)
        self.verify_ocr_button.setEnabled(
            self._local_ocr_supported and not busy and self.component_manager.is_installed()
        )
        self.remove_ocr_button.setEnabled(
            self._local_ocr_supported and not busy and self.component_manager.is_installed()
        )
        self.test_button.setEnabled(not busy)
        self.google_vision_test_button.setEnabled(not busy)
        provider_editable = not busy and not self.config_manager.has_explicit_ocr_provider()
        self.local_mode_radio.setEnabled(provider_editable)
        self.online_mode_radio.setEnabled(provider_editable)
        self.local_engine_combo.setEnabled(provider_editable)
        self.online_service_combo.setEnabled(provider_editable)
        self.cancel_download_button.setVisible(download_running)
        self.cancel_download_button.setEnabled(download_running)
        self.local_ocr_progress.setVisible(download_running)
        if not self._local_ocr_supported:
            self.local_mode_radio.setEnabled(False)
            self.local_engine_combo.setEnabled(False)
            self.download_ocr_button.setVisible(False)
            self.cancel_download_button.setVisible(False)
            self.verify_ocr_button.setVisible(False)
            self.remove_ocr_button.setVisible(False)
            self.local_ocr_progress.setVisible(False)
        elif not self._local_ocr_is_usable():
            self.local_mode_radio.setEnabled(False)
            self.local_engine_combo.setEnabled(False)
            self.download_ocr_button.setVisible(False)
            self.cancel_download_button.setVisible(False)
            self.verify_ocr_button.setVisible(False)
            self.remove_ocr_button.setVisible(False)
            self.local_ocr_progress.setVisible(False)

    def _set_download_state(self, running: bool) -> None:
        self._refresh_operation_controls(download_running=running)

    @Slot()
    def download_local_ocr(self) -> None:
        if not self._local_ocr_supported:
            self._set_status("Local OCR for macOS is not installed/supported in this build.")
            return
        manifest_url = resolve_manifest_url(self.config_manager.project_root)
        if not manifest_url:
            self._set_status(
                "Local OCR is supported on this Mac, but no component distribution is configured yet."
            )
            self._refresh_local_ocr_state()
            return
        if self._download_thread is not None and self._download_thread.isRunning():
            return
        if (
            self.local_ocr_session is not None
            and getattr(self.local_ocr_session, "is_preparing", lambda: False)()
        ):
            self._set_status("Local OCR is preparing. Please try again in a moment.")
            return
        if self.is_connection_running() or self.is_google_test_running():
            self._set_status("Wait for the active OCR or connection test to finish before downloading Local OCR.")
            return
        session_preparing = bool(
            self.local_ocr_session is not None
            and getattr(self.local_ocr_session, "is_preparing", lambda: False)()
        )
        if self.local_ocr_session is not None and self.local_ocr_session.is_busy() and not session_preparing:
            self._set_status("Local OCR is currently in use. Please wait for recognition to finish.")
            return
        if self.local_ocr_session is not None:
            self.local_ocr_session.stop()
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
        if self.local_ocr_session is not None:
            self.local_ocr_session.reset_capability()
        self.local_ocr_status_label.setText(f"Installed · v{self.component_manager.version}")
        self.local_ocr_size_label.setText("")
        self.local_ocr_component_changed.emit()

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
        self._refresh_operation_controls()
        self._refresh_local_ocr_state()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def verify_local_ocr(self) -> None:
        if not self._local_ocr_supported:
            self.local_ocr_status_label.setText(
                "Local OCR for macOS is not installed/supported in this build."
            )
            return
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
        if not self._local_ocr_supported:
            self.local_ocr_status_label.setText(
                "Local OCR for macOS is not installed/supported in this build."
            )
            return
        if not self.component_manager.is_installed():
            self._refresh_local_ocr_state()
            return
        if (
            self.local_ocr_session is not None
            and getattr(self.local_ocr_session, "is_preparing", lambda: False)()
        ):
            self.local_ocr_status_label.setText(
                "Local OCR is preparing. Please try again in a moment."
            )
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
                if self.local_ocr_session is not None:
                    session_preparing = bool(
                        getattr(self.local_ocr_session, "is_preparing", lambda: False)()
                    )
                    if session_preparing:
                        self.local_ocr_status_label.setText(
                            "Local OCR is preparing. Please try again in a moment."
                        )
                        return
                    if self.local_ocr_session.is_busy() and not session_preparing:
                        self.local_ocr_status_label.setText(
                            "Local OCR is currently in use. Please wait for recognition to finish."
                        )
                        return
                    self.local_ocr_session.stop()
                self.component_manager.remove()
            except (OSError, ComponentError) as exc:
                logger.warning("local OCR removal failed: %s", type(exc).__name__)
                self.local_ocr_status_label.setText(f"Failed to remove Local OCR: {exc}")
                return
            if self.local_ocr_session is not None:
                self.local_ocr_session.reset_capability()
            self._refresh_local_ocr_state()
            self.local_ocr_component_changed.emit()

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
        global_shortcut = self._parse_shortcut(sequence)
        vision_shortcut = self._parse_shortcut(self.vision_shortcut_edit.keySequence())
        if global_shortcut == vision_shortcut:
            raise ValueError("Text and Vision shortcuts must be different.")
        current = self.config_manager.load(require_api_key=False)
        return AppConfig(
            api_key=self.api_key_edit.text().strip(),
            model=model,
            base_url=current.base_url,
            request_timeout=request_timeout,
            ocr_language=current.ocr_language,
            global_shortcut=global_shortcut,
            vision_global_shortcut=vision_shortcut,
            ocr_provider=self._current_provider_from_ui(),
            google_vision_api_key=self.google_vision_api_key_edit.text().strip(),
            online_ocr_timeout=current.online_ocr_timeout,
        )

    @staticmethod
    def _parse_shortcut(sequence: QKeySequence) -> str:
        if sequence.count() != 1:
            raise ValueError("快捷键只能包含一个组合")
        try:
            return HotkeySpec.parse(
                sequence.toString(QKeySequence.SequenceFormat.PortableText)
            ).canonical
        except HotkeySpecError as exc:
            raise ValueError(str(exc)) from exc

    @Slot()
    def test_connection(self) -> None:
        if self._connection_thread is not None and self._connection_thread.isRunning():
            return
        if self.is_download_running() or self.is_google_test_running():
            self._set_status("Wait for the active OCR operation to finish before testing the connection.")
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
        self._refresh_operation_controls(connection_running=True)
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
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._refresh_operation_controls()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def test_google_vision(self) -> None:
        if self.is_google_test_running():
            return
        if self.is_connection_running() or self.is_download_running():
            self._set_status("Wait for the active operation to finish before testing Google Vision.")
            return
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError as exc:
            self.google_vision_status_label.setText(str(exc))
            return
        api_key = (
            config.google_vision_api_key
            if self.config_manager.has_explicit_google_vision_api_key()
            else self.google_vision_api_key_edit.text().strip()
        )
        if not api_key:
            self.google_vision_status_label.setText("Enter a Google Vision API Key first.")
            return

        self._close_requested = False
        self._google_cancel_event = threading.Event()
        worker = GoogleVisionTestWorker(
            api_key=api_key,
            language=config.ocr_language,
            timeout=min(config.online_ocr_timeout, CONNECTION_TEST_TIMEOUT),
            cancel_event=self._google_cancel_event,
        )
        thread = QThread(self)
        thread.setObjectName("SettingsGoogleVisionTestThread")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_google_test_success)
        worker.failed.connect(self._on_google_test_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_google_test_finished)
        self._google_worker = worker
        self._google_thread = thread
        self.google_vision_test_button.setText("Testing...")
        self.google_vision_status_label.setText("Testing...")
        self._refresh_operation_controls(google_running=True)
        thread.start()

    @Slot()
    def cancel_google_vision_test(self) -> None:
        if self._google_worker is not None:
            self._google_worker.request_cancel()
            self.google_vision_status_label.setText("Cancelling...")

    @Slot()
    def _on_google_test_success(self) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.google_vision_status_label.setText("Google Vision connection successful.")

    @Slot(str)
    def _on_google_test_failed(self, message: str) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.google_vision_status_label.setText(message)

    @Slot()
    def _on_google_test_finished(self) -> None:
        self._google_thread = None
        self._google_worker = None
        self._google_cancel_event = None
        self.google_vision_test_button.setText("Test Google Vision")
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._refresh_operation_controls()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def save(self) -> None:
        old_shortcuts: list[tuple[GlobalHotkeyManager, str, bool]] = []
        try:
            config = self._read_config_from_fields()
            requested = (
                (self.hotkey_manager, config.global_shortcut),
                (self.vision_hotkey_manager, config.vision_global_shortcut),
            )
            rebind_failed = False
            for manager, shortcut in requested:
                if manager is None or manager.shortcut == shortcut:
                    continue
                old_shortcuts.append((manager, manager.shortcut, False))
                if not manager.rebind(shortcut):
                    rebind_failed = True
                else:
                    old_shortcuts[-1] = (manager, old_shortcuts[-1][1], True)
            if rebind_failed:
                for rebound_manager, old_shortcut, rebound in reversed(old_shortcuts):
                    if rebound and not rebound_manager.rebind(old_shortcut):
                        logger.error("failed to rollback shortcut after rebind failure")
                self._set_status("快捷键注册失败，可能已被其他程序占用。")
                return
            provider_to_save = None
            if not self.config_manager.has_explicit_ocr_provider():
                provider_to_save = config.ocr_provider
            google_key_to_save = None
            if not self.config_manager.has_explicit_google_vision_api_key():
                google_key_to_save = config.google_vision_api_key
            self.config_manager.save_settings(
                config.api_key,
                config.model,
                config.request_timeout,
                config.global_shortcut,
                vision_global_shortcut=config.vision_global_shortcut,
                ocr_provider=provider_to_save,
                google_vision_api_key=google_key_to_save,
                online_ocr_timeout=config.online_ocr_timeout,
            )
        except (ConfigError, SecretStoreError, ValueError) as exc:
            for manager, old_shortcut, rebound in reversed(old_shortcuts):
                if rebound and not manager.rebind(old_shortcut):
                    logger.error("failed to rollback shortcut after settings save failure")
            self._set_status(str(exc))
            return
        self._set_status("设置已保存")
        self._show_environment_override_warnings()
        self.settings_saved.emit()
        self.close()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def is_connection_running(self) -> bool:
        return self._connection_thread is not None and self._connection_thread.isRunning()

    def is_download_running(self) -> bool:
        return self._download_thread is not None and self._download_thread.isRunning()

    def is_google_test_running(self) -> bool:
        return self._google_thread is not None and self._google_thread.isRunning()

    def has_running_background_operations(self) -> bool:
        return (
            self.is_connection_running()
            or self.is_download_running()
            or self.is_google_test_running()
        )

    @Slot()
    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        self._close_requested = True
        if self.is_download_running():
            self.cancel_local_ocr_download()
        if self.is_connection_running():
            if self._connection_worker is not None:
                self._connection_worker.request_cancel()
        if self.is_google_test_running():
            self.cancel_google_vision_test()
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
        if self.is_google_test_running():
            self.cancel_google_vision_test()
        if self.has_running_background_operations():
            self.hide()
            event.accept()
            return
        event.accept()
