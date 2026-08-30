"""Minimal settings UI with secure API-key storage and async connection testing."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    AppConfig,
    ConfigError,
    ConfigManager,
    DEFAULT_LOCAL_OCR_ENGINE,
    DEFAULT_ONLINE_OCR_PROVIDER,
)
from app.analysis import AnalysisMode
from app.localization import (
    DEFAULT_ANSWER_LANGUAGE,
    DEFAULT_INTERFACE_LANGUAGE,
    LANGUAGE_DISPLAY_NAMES,
    SUPPORTED_LANGUAGES,
    normalize_language,
    tr,
)
from app.local_ocr.component_manager import ComponentError, LocalOCRComponentManager
from app.local_ocr.download import LocalOCRDownloadWorker
from app.local_ocr.manifest import manifest_url_available, resolve_manifest_url
from app.logging_config import (
    DEFAULT_LOG_TAIL_BYTES,
    DEFAULT_LOG_TAIL_LINES,
    default_log_path,
    read_log_tail,
)
from app.ocr.local_session import LocalOCRSession
from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import HotkeySpec, HotkeySpecError, validate_unique_shortcuts
from app.ocr.providers.google_vision import GoogleVisionOCRProvider
from app.ocr.types import OCRCancelled, OCRError
from app.platform.ocr import is_local_ocr_supported
from app.ai.errors import AIProviderError, AIRequestCancelled
from app.ai.catalog import (
    AI_PROVIDER_CATALOG,
    CUSTOM_MODEL_ID,
    CUSTOM_MODEL_LABEL,
    get_provider_descriptor,
    models_for_provider,
)
from app.ai.models import AIBackendConfig
from app.ai.service import AnalysisService
from app.settings.secret_store import SecretStoreError
from app.auto_watch.models import AutoWatchSettings
from app.ui.theme import settings_window_stylesheet
from app.update_service import (
    ReleaseAsset,
    UpdateCancelled,
    UpdateCheckResult,
    UpdateError,
    UpdateService,
)
from app.version import __version__

logger = logging.getLogger(__name__)
CONNECTION_TEST_TIMEOUT = 10.0
GOOGLE_VISION_ENV_OVERRIDE_MESSAGE = (
    "Google Vision API Key is currently overridden by the environment variable "
    "GOOGLE_VISION_API_KEY. "
    "Saving a different key will not change the key currently in use."
)


class ModelSelector(QComboBox):
    """Editable model selector backed by the curated catalog."""


class ConnectionTestWorker(QObject):
    """Run one minimal AI request outside the Qt GUI thread."""

    succeeded = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        config: AppConfig,
        cancel_event: threading.Event | None = None,
        capability: str = "text",
    ) -> None:
        super().__init__()
        self.config = config
        self.cancel_event = cancel_event or threading.Event()
        self.capability = capability

    @Slot()
    def run(self) -> None:
        try:
            service = AnalysisService(self.config)
            if self.capability == "text":
                service.test_connection(self.cancel_event)
            else:
                service.test_connection(self.cancel_event, capability=self.capability)
            if not self.cancel_event.is_set():
                self.succeeded.emit()
        except AIRequestCancelled:
            pass
        except AIProviderError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("settings connection test failed")
            self.failed.emit(
                tr(
                    "settings.connection_internal_error",
                    getattr(self.config, "interface_language", DEFAULT_INTERFACE_LANGUAGE),
                )
            )
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
        interface_language: str = DEFAULT_INTERFACE_LANGUAGE,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.language = language
        self.timeout = timeout
        self.cancel_event = cancel_event or threading.Event()
        self.interface_language = interface_language

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
            self.failed.emit(tr("settings.google_connection_failed", self.interface_language))
        finally:
            self.finished.emit()

    @Slot()
    def request_cancel(self) -> None:
        self.cancel_event.set()


class UpdateCheckWorker(QObject):
    """Check GitHub Releases outside the Qt GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        service: UpdateService,
        cancel_event: threading.Event,
        interface_language: str = DEFAULT_INTERFACE_LANGUAGE,
    ) -> None:
        super().__init__()
        self.service = service
        self.cancel_event = cancel_event
        self.interface_language = interface_language

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.check_for_update(__version__, self.cancel_event)
            if not self.cancel_event.is_set():
                self.succeeded.emit(result)
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as exc:
            self.failed.emit(
                tr(
                    "settings.update_error",
                    self.interface_language,
                    detail=exc,
                )
            )
        except Exception:
            logger.exception("application update check failed")
            self.failed.emit(
                tr("settings.update_check_failed", self.interface_language)
            )
        finally:
            self.finished.emit()

    @Slot()
    def request_cancel(self) -> None:
        self.cancel_event.set()


class UpdateDownloadWorker(QObject):
    """Download and open one selected update package off the GUI thread."""

    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        service: UpdateService,
        asset: ReleaseAsset,
        cancel_event: threading.Event,
        interface_language: str = DEFAULT_INTERFACE_LANGUAGE,
    ) -> None:
        super().__init__()
        self.service = service
        self.asset = asset
        self.cancel_event = cancel_event
        self.interface_language = interface_language

    @Slot()
    def run(self) -> None:
        try:
            path = self.service.download_and_launch(self.asset, self.cancel_event)
            if not self.cancel_event.is_set():
                self.succeeded.emit(str(path))
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as exc:
            self.failed.emit(
                tr(
                    "settings.update_error",
                    self.interface_language,
                    detail=exc,
                )
            )
        except Exception:
            logger.exception("application update download failed")
            self.failed.emit(
                tr("settings.update_download_failed", self.interface_language)
            )
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

    def _tr(self, key: str, **values: object) -> str:
        return tr(key, self._interface_language, **values)

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        hotkey_manager: GlobalHotkeyManager | None = None,
        vision_hotkey_manager: GlobalHotkeyManager | None = None,
        watch_hotkey_manager: GlobalHotkeyManager | None = None,
        context_watch_hotkey_manager: GlobalHotkeyManager | None = None,
        component_manager: LocalOCRComponentManager | None = None,
        local_ocr_session: LocalOCRSession | None = None,
        update_service: UpdateService | None = None,
        parent: QWidget | None = None,
        local_ocr_supported: bool | None = None,
        log_path: Path | str | None = None,
        interface_language: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager or ConfigManager()
        self.hotkey_manager = hotkey_manager
        self.vision_hotkey_manager = vision_hotkey_manager
        self.watch_hotkey_manager = watch_hotkey_manager
        self.context_watch_hotkey_manager = context_watch_hotkey_manager
        self.component_manager = component_manager or LocalOCRComponentManager()
        self.local_ocr_session = local_ocr_session
        self.update_service = update_service or UpdateService()
        self._local_ocr_supported = (
            is_local_ocr_supported() if local_ocr_supported is None else local_ocr_supported
        )
        self._log_path = log_path
        settings_repository = getattr(self.config_manager, "settings_repository", None)
        repository_language_getter = getattr(
            settings_repository, "interface_language", None
        )
        repository_interface_language = (
            repository_language_getter()
            if callable(repository_language_getter)
            else DEFAULT_INTERFACE_LANGUAGE
        )
        self._interface_language = normalize_language(
            interface_language
            if interface_language is not None
            else repository_interface_language,
            default=DEFAULT_INTERFACE_LANGUAGE,
        )
        self._loaded_interface_language = DEFAULT_INTERFACE_LANGUAGE
        self._loaded_answer_language = DEFAULT_ANSWER_LANGUAGE
        self._connection_thread: QThread | None = None
        self._connection_worker: ConnectionTestWorker | None = None
        self._connection_cancel_event: threading.Event | None = None
        self._vision_connection_thread: QThread | None = None
        self._vision_connection_worker: ConnectionTestWorker | None = None
        self._vision_connection_cancel_event: threading.Event | None = None
        self._close_requested = False
        self._shutdown_requested = False
        self._shutdown_ready_emitted = False
        self._download_thread: QThread | None = None
        self._download_worker: LocalOCRDownloadWorker | None = None
        self._download_cancel_event: threading.Event | None = None
        self._google_thread: QThread | None = None
        self._google_worker: GoogleVisionTestWorker | None = None
        self._google_cancel_event: threading.Event | None = None
        self._update_check_thread: QThread | None = None
        self._update_check_worker: UpdateCheckWorker | None = None
        self._update_check_cancel_event: threading.Event | None = None
        self._update_download_thread: QThread | None = None
        self._update_download_worker: UpdateDownloadWorker | None = None
        self._update_download_cancel_event: threading.Event | None = None
        self._pending_update: UpdateCheckResult | None = None
        self._loaded_provider_keys: dict[str, str] = {}
        self._loaded_provider_endpoints: dict[str, str] = {}
        self._provider_key_values: dict[str, str] = {}
        self._provider_endpoint_values: dict[str, str] = {}
        self._loaded_google_vision_api_key = ""
        self._loaded_auto_watch_values: dict[str, int | float] = {}
        self._loaded_auto_watch_analysis_mode = AnalysisMode.TEXT
        self._local_ocr_download_terminal_status: str | None = None

        self.setWindowTitle(self._tr("settings.window_title"))
        self.setMinimumSize(760, 540)
        self.resize(860, 680)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setObjectName("settingsWindow")
        self.setStyleSheet(settings_window_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)
        surface = QFrame()
        surface.setObjectName("settingsSurface")
        root.addWidget(surface)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(22, 20, 22, 18)
        surface_layout.setSpacing(14)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel(self._tr("settings.title"))
        title.setObjectName("settingsTitle")
        subtitle = QLabel(self._tr("settings.subtitle"))
        subtitle.setObjectName("settingsSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        surface_layout.addLayout(header)
        self.text_provider_combo = QComboBox()
        self.text_provider_combo.setObjectName("textAIProviderCombo")
        self.text_ai_provider_combo = self.text_provider_combo
        self.vision_provider_combo = QComboBox()
        self.vision_provider_combo.setObjectName("visionAIProviderCombo")
        self.vision_ai_provider_combo = self.vision_provider_combo
        for descriptor in AI_PROVIDER_CATALOG:
            self.text_provider_combo.addItem(descriptor.display_name, descriptor.provider_id)
            self.vision_provider_combo.addItem(descriptor.display_name, descriptor.provider_id)
        self.text_model_combo = ModelSelector()
        self.text_model_combo.setObjectName("textAIModelCombo")
        self.text_model_combo.setEditable(True)
        self.text_ai_model_combo = self.text_model_combo
        self.text_model_combo.currentIndexChanged.connect(
            lambda _index: self._clear_custom_placeholder(self.text_model_combo)
        )
        self.vision_model_combo = ModelSelector()
        self.vision_model_combo.setObjectName("visionAIModelCombo")
        self.vision_model_combo.setEditable(True)
        self.vision_ai_model_combo = self.vision_model_combo
        self.vision_model_combo.currentIndexChanged.connect(
            lambda _index: self._clear_custom_placeholder(self.vision_model_combo)
        )
        self.provider_credentials_combo = QComboBox()
        self.provider_credentials_combo.setObjectName("providerCredentialsCombo")
        self.provider_combo = self.provider_credentials_combo
        for descriptor in AI_PROVIDER_CATALOG:
            self.provider_credentials_combo.addItem(
                descriptor.display_name,
                descriptor.provider_id,
            )
        self.text_provider_combo.currentIndexChanged.connect(
            self._on_text_provider_changed
        )
        self.vision_provider_combo.currentIndexChanged.connect(
            self._on_vision_provider_changed
        )
        self.provider_credentials_combo.currentIndexChanged.connect(
            self._on_credentials_provider_changed
        )
        self.provider_api_key_edit = QLineEdit()
        self.provider_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.provider_api_key_edit.setPlaceholderText(
            self._tr("settings.provider_api_key_placeholder")
        )
        self.provider_endpoint_edit = QLineEdit()
        self.provider_endpoint_edit.setPlaceholderText("https://…/v1")
        self.timeout_edit = QLineEdit()
        self.shortcut_edit = QKeySequenceEdit()
        self.shortcut_edit.setObjectName("textShortcutEdit")
        self.shortcut_edit.setMaximumSequenceLength(1)
        self.vision_shortcut_edit = QKeySequenceEdit()
        self.vision_shortcut_edit.setObjectName("visionShortcutEdit")
        self.vision_shortcut_edit.setMaximumSequenceLength(1)
        self.watch_shortcut_edit = QKeySequenceEdit()
        self.watch_shortcut_edit.setObjectName("watchShortcutEdit")
        self.watch_shortcut_edit.setMaximumSequenceLength(1)
        self.context_watch_shortcut_edit = QKeySequenceEdit()
        self.context_watch_shortcut_edit.setObjectName("contextWatchShortcutEdit")
        self.context_watch_shortcut_edit.setMaximumSequenceLength(1)
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.local_mode_radio = QRadioButton(self._tr("settings.local"))
        self.online_mode_radio = QRadioButton(self._tr("settings.online"))
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
        self.local_engine_combo.addItem("PaddleOCR", DEFAULT_LOCAL_OCR_ENGINE)
        self.online_service_combo = QComboBox()
        self.online_service_combo.addItem("Google Cloud Vision", "google_vision")
        self.ocr_provider_override_label = QLabel(
            self._tr("settings.ocr_provider_env_override")
        )
        self.ocr_provider_override_label.setObjectName("settingsWarningLabel")
        self.ocr_provider_override_label.setWordWrap(True)
        self.ocr_provider_override_label.setVisible(False)
        self.local_ocr_unsupported_label = QLabel(
            self._tr("settings.local_ocr_unsupported")
        )
        self.local_ocr_unsupported_label.setWordWrap(True)
        self.local_ocr_unsupported_label.setVisible(False)
        self.api_key_override_label = QLabel(self._tr("settings.api_key_env_override"))
        self.api_key_override_label.setObjectName("settingsWarningLabel")
        self.api_key_override_label.setWordWrap(True)
        self.api_key_override_label.setVisible(False)
        self.local_ocr_group = QGroupBox()
        self.local_ocr_group.setObjectName("localOcrCard")
        ocr_layout = QVBoxLayout(self.local_ocr_group)
        ocr_layout.setContentsMargins(16, 14, 16, 16)
        ocr_layout.setSpacing(10)
        local_engine_form = QFormLayout()
        local_engine_form.addRow(self._tr("settings.engine"), self.local_engine_combo)
        ocr_layout.addLayout(local_engine_form)
        self.local_ocr_privacy_label = QLabel(
            self._tr("settings.local_ocr_privacy")
        )
        self.local_ocr_privacy_label.setWordWrap(True)
        self.local_ocr_status_label = QLabel()
        self.local_ocr_size_label = QLabel()
        self.local_ocr_progress = QProgressBar()
        self.local_ocr_progress.setRange(0, 100)
        self.local_ocr_progress.setVisible(False)
        ocr_buttons = QHBoxLayout()
        self.download_ocr_button = QPushButton(self._tr("settings.download"))
        self.download_ocr_button.setObjectName("downloadOcrButton")
        self.cancel_download_button = QPushButton(self._tr("settings.cancel"))
        self.cancel_download_button.setObjectName("cancelDownloadButton")
        self.verify_ocr_button = QPushButton(self._tr("settings.verify"))
        self.verify_ocr_button.setObjectName("verifyOcrButton")
        self.remove_ocr_button = QPushButton(self._tr("settings.remove_local_ocr"))
        self.remove_ocr_button.setObjectName("removeOcrButton")
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
        self.google_vision_group = QGroupBox()
        self.google_vision_group.setObjectName("googleVisionCard")
        google_layout = QVBoxLayout(self.google_vision_group)
        google_layout.setContentsMargins(16, 14, 16, 16)
        google_layout.setSpacing(10)
        online_service_form = QFormLayout()
        online_service_form.addRow(self._tr("settings.service"), self.online_service_combo)
        google_layout.addLayout(online_service_form)
        self.google_vision_privacy_label = QLabel(
            self._tr("settings.online_ocr_privacy")
        )
        self.google_vision_privacy_label.setWordWrap(True)
        self.google_vision_api_key_edit = QLineEdit()
        self.google_vision_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_vision_api_key_edit.setPlaceholderText(
            self._tr("settings.google_api_key_placeholder")
        )
        google_key_form = QFormLayout()
        google_key_form.addRow(
            "Google Vision API Key", self.google_vision_api_key_edit
        )
        self.google_vision_override_label = QLabel(
            self._tr("settings.google_api_key_env_override")
        )
        self.google_vision_override_label.setObjectName("settingsWarningLabel")
        self.google_vision_override_label.setWordWrap(True)
        self.google_vision_override_label.setVisible(False)
        self.google_vision_test_button = QPushButton(
            self._tr("settings.test_google_vision")
        )
        self.google_vision_test_button.setObjectName("googleVisionTestButton")
        self.google_vision_test_button.clicked.connect(self.test_google_vision)
        self.google_vision_status_label = QLabel()
        self.google_vision_status_label.setWordWrap(True)
        google_layout.addWidget(self.google_vision_privacy_label)
        google_layout.addLayout(google_key_form)
        google_layout.addWidget(self.google_vision_override_label)
        google_layout.addWidget(self.google_vision_test_button)
        google_layout.addWidget(self.google_vision_status_label)
        self.text_test_button = QPushButton(self._tr("settings.test_text_ai"))
        self.text_test_button.setObjectName("testTextAIButton")
        self.text_test_button.clicked.connect(self.test_text_connection)
        self.text_cancel_button = QPushButton(self._tr("settings.cancel"))
        self.text_cancel_button.setObjectName("cancelTextAIButton")
        self.text_cancel_button.clicked.connect(self.cancel_text_connection)
        self.text_cancel_button.setVisible(False)
        self.vision_test_button = QPushButton(self._tr("settings.test_vision_ai"))
        self.vision_test_button.setObjectName("testVisionAIButton")
        self.vision_test_button.clicked.connect(self.test_vision_connection)
        self.vision_cancel_button = QPushButton(self._tr("settings.cancel"))
        self.vision_cancel_button.setObjectName("cancelVisionAIButton")
        self.vision_cancel_button.clicked.connect(self.cancel_vision_connection)
        self.vision_cancel_button.setVisible(False)
        self.text_ai_status_label = QLabel()
        self.text_ai_status_label.setWordWrap(True)
        self.vision_ai_status_label = QLabel()
        self.vision_ai_status_label.setWordWrap(True)

        self.interface_language_combo = QComboBox()
        self.interface_language_combo.setObjectName("interfaceLanguageCombo")
        self.answer_language_combo = QComboBox()
        self.answer_language_combo.setObjectName("answerLanguageCombo")
        for combo in (self.interface_language_combo, self.answer_language_combo):
            for code in SUPPORTED_LANGUAGES:
                combo.addItem(LANGUAGE_DISPLAY_NAMES[code], code)
        self.interface_language_combo.currentIndexChanged.connect(
            self._on_interface_language_changed
        )

        self.poll_interval_ms_spin = QSpinBox()
        self.poll_interval_ms_spin.setRange(1, 60000)
        self.poll_interval_ms_spin.setSuffix(" ms")
        self.pixel_delta_threshold_spin = QSpinBox()
        self.pixel_delta_threshold_spin.setRange(1, 255)
        self.novelty_ratio_spin = QDoubleSpinBox()
        self.stability_ratio_spin = QDoubleSpinBox()
        for control in (self.novelty_ratio_spin, self.stability_ratio_spin):
            control.setRange(0.0, 100.0)
            control.setDecimals(2)
            control.setSingleStep(0.5)
            control.setSuffix(" %")
        self.stable_samples_required_spin = QSpinBox()
        self.stable_samples_required_spin.setRange(1, 1000)
        self.analysis_delay_ms_spin = QSpinBox()
        self.analysis_delay_ms_spin.setRange(0, 60000)
        self.analysis_delay_ms_spin.setSuffix(" ms")
        auto_watch_mode_widget = QWidget()
        auto_watch_mode_layout = QHBoxLayout(auto_watch_mode_widget)
        auto_watch_mode_layout.setContentsMargins(0, 0, 0, 0)
        self.auto_watch_text_radio = QRadioButton("Text / OCR")
        self.auto_watch_text_radio.setAccessibleName("Auto Watch Text / OCR")
        self.auto_watch_vision_radio = QRadioButton("Vision")
        self.auto_watch_vision_radio.setAccessibleName("Auto Watch Vision")
        self.auto_watch_analysis_mode_group = QButtonGroup(self)
        self.auto_watch_analysis_mode_group.setExclusive(True)
        self.auto_watch_analysis_mode_group.addButton(self.auto_watch_text_radio)
        self.auto_watch_analysis_mode_group.addButton(self.auto_watch_vision_radio)
        auto_watch_mode_layout.addWidget(self.auto_watch_text_radio)
        auto_watch_mode_layout.addWidget(self.auto_watch_vision_radio)
        auto_watch_mode_layout.addStretch(1)
        self.expected_stability_label = QLabel()
        self.expected_stability_label.setWordWrap(True)
        self.restore_auto_watch_button = QPushButton(self._tr("settings.restore_defaults"))
        self.restore_auto_watch_button.clicked.connect(self._restore_auto_watch_defaults)
        self.poll_interval_ms_spin.valueChanged.connect(self._refresh_expected_stability)
        self.stable_samples_required_spin.valueChanged.connect(self._refresh_expected_stability)

        def make_page(page_title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(4, 2, 4, 8)
            page_layout.setSpacing(12)
            page_heading = QLabel(page_title)
            page_heading.setObjectName("pageTitle")
            page_description = QLabel(description)
            page_description.setObjectName("pageDescription")
            page_description.setWordWrap(True)
            page_layout.addWidget(page_heading)
            page_layout.addWidget(page_description)
            return page, page_layout

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("settingsPages")
        ai_page, ai_layout = make_page(
            self._tr("settings.ai_title"), self._tr("settings.ai_description")
        )

        text_card = QFrame()
        text_card.setObjectName("settingsCard")
        text_card_layout = QVBoxLayout(text_card)
        text_card_layout.setContentsMargins(16, 14, 16, 16)
        text_card_layout.setSpacing(8)
        text_heading = QLabel(self._tr("settings.text_ai_title"))
        text_heading.setObjectName("cardTitle")
        text_description = QLabel(self._tr("settings.text_ai_description"))
        text_description.setWordWrap(True)
        text_form = QFormLayout()
        text_form.addRow(self._tr("settings.provider"), self.text_provider_combo)
        text_form.addRow(self._tr("settings.model"), self.text_model_combo)
        text_card_layout.addWidget(text_heading)
        text_card_layout.addWidget(text_description)
        text_card_layout.addLayout(text_form)
        text_buttons = QHBoxLayout()
        text_buttons.addWidget(self.text_test_button)
        text_buttons.addWidget(self.text_cancel_button)
        text_buttons.addStretch(1)
        text_card_layout.addLayout(text_buttons)
        text_card_layout.addWidget(self.text_ai_status_label)

        vision_card = QFrame()
        vision_card.setObjectName("settingsCard")
        vision_card_layout = QVBoxLayout(vision_card)
        vision_card_layout.setContentsMargins(16, 14, 16, 16)
        vision_card_layout.setSpacing(8)
        vision_heading = QLabel(self._tr("settings.vision_ai_title"))
        vision_heading.setObjectName("cardTitle")
        vision_description = QLabel(self._tr("settings.vision_ai_description"))
        vision_description.setWordWrap(True)
        vision_form = QFormLayout()
        vision_form.addRow(self._tr("settings.provider"), self.vision_provider_combo)
        vision_form.addRow(self._tr("settings.model"), self.vision_model_combo)
        vision_card_layout.addWidget(vision_heading)
        vision_card_layout.addWidget(vision_description)
        vision_card_layout.addLayout(vision_form)
        vision_buttons = QHBoxLayout()
        vision_buttons.addWidget(self.vision_test_button)
        vision_buttons.addWidget(self.vision_cancel_button)
        vision_buttons.addStretch(1)
        vision_card_layout.addLayout(vision_buttons)
        vision_card_layout.addWidget(self.vision_ai_status_label)

        credentials_card = QFrame()
        credentials_card.setObjectName("settingsCard")
        credentials_layout = QVBoxLayout(credentials_card)
        credentials_layout.setContentsMargins(16, 14, 16, 16)
        credentials_layout.setSpacing(8)
        credentials_layout.addWidget(QLabel(self._tr("settings.provider_credentials")))
        credentials_form = QFormLayout()
        credentials_form.addRow(self._tr("settings.provider"), self.provider_credentials_combo)
        credentials_form.addRow(self._tr("settings.api_key"), self.provider_api_key_edit)
        credentials_form.addRow(self._tr("settings.endpoint"), self.provider_endpoint_edit)
        credentials_form.addRow(self._tr("settings.request_timeout"), self.timeout_edit)
        credentials_layout.addLayout(credentials_form)
        credentials_layout.addWidget(self.api_key_override_label)
        self.provider_endpoint_override_label = QLabel()
        self.provider_endpoint_override_label.setObjectName("settingsWarningLabel")
        self.provider_endpoint_override_label.setWordWrap(True)
        self.provider_endpoint_override_label.setVisible(False)
        credentials_layout.addWidget(self.provider_endpoint_override_label)

        ai_layout.addWidget(text_card)
        ai_layout.addWidget(vision_card)
        ai_layout.addWidget(credentials_card)
        ai_layout.addStretch(1)

        shortcuts_page, shortcuts_layout = make_page(
            self._tr("settings.shortcuts_title"),
            self._tr("settings.shortcuts_description"),
        )
        shortcuts_card = QFrame()
        shortcuts_card.setObjectName("settingsCard")
        shortcuts_form = QFormLayout(shortcuts_card)
        shortcuts_form.setContentsMargins(16, 14, 16, 16)
        shortcuts_form.setVerticalSpacing(14)
        shortcuts_form.addRow("Text / OCR", self.shortcut_edit)
        shortcuts_form.addRow("Vision", self.vision_shortcut_edit)
        shortcuts_form.addRow("Watch", self.watch_shortcut_edit)
        shortcuts_form.addRow("Context Watch", self.context_watch_shortcut_edit)
        shortcuts_layout.addWidget(shortcuts_card)
        shortcuts_layout.addStretch(1)

        ocr_page, ocr_page_layout = make_page(
            "OCR", self._tr("settings.ocr_description")
        )
        ocr_card = QFrame()
        ocr_card.setObjectName("settingsCard")
        ocr_card_layout = QVBoxLayout(ocr_card)
        ocr_card_layout.setContentsMargins(16, 14, 16, 16)
        ocr_card_layout.setSpacing(10)
        ocr_card_layout.addWidget(QLabel(self._tr("settings.ocr_provider")))
        ocr_card_layout.addWidget(mode_widget)
        ocr_card_layout.addWidget(self.ocr_provider_override_label)

        def provider_summary(title: str, description: str, page_index: int) -> QFrame:
            card = QFrame()
            card.setObjectName("providerSummaryCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 8, 10, 8)
            text = QVBoxLayout()
            text.setSpacing(1)
            name = QLabel(title)
            name.setObjectName("providerSummaryTitle")
            detail = QLabel(description)
            detail.setObjectName("providerSummaryDetail")
            detail.setWordWrap(True)
            text.addWidget(name)
            text.addWidget(detail)
            row.addLayout(text, 1)
            manage = QPushButton(self._tr("settings.manage"))
            manage.setObjectName("manageButton")
            manage.clicked.connect(lambda: self._select_page(page_index))
            row.addWidget(manage)
            return card

        self.ocr_local_summary = provider_summary(
            "Local OCR", self._tr("settings.local_ocr_summary"), 3
        )
        self.ocr_google_summary = provider_summary(
            "Google Cloud Vision", self._tr("settings.google_vision_summary"), 4
        )
        ocr_card_layout.addWidget(self.ocr_local_summary)
        ocr_card_layout.addWidget(self.ocr_google_summary)
        ocr_page_layout.addWidget(ocr_card)
        ocr_page_layout.addStretch(1)

        local_page, local_page_layout = make_page(
            "Local OCR", self._tr("settings.local_ocr_description")
        )
        local_page_layout.addWidget(self.local_ocr_group)
        local_page_layout.addWidget(self.local_ocr_unsupported_label)
        local_page_layout.addStretch(1)

        google_page, google_page_layout = make_page(
            "Google Vision", self._tr("settings.google_vision_description")
        )
        google_page_layout.addWidget(self.google_vision_group)
        google_page_layout.addStretch(1)

        auto_watch_page, auto_watch_layout = make_page(
            "Auto Watch", self._tr("settings.auto_watch_description")
        )
        auto_watch_card = QFrame()
        auto_watch_card.setObjectName("settingsCard")
        auto_watch_card_layout = QVBoxLayout(auto_watch_card)
        auto_watch_card_layout.setContentsMargins(16, 14, 16, 16)
        auto_watch_form = QFormLayout()
        auto_watch_form.addRow(self._tr("settings.analysis_mode"), auto_watch_mode_widget)
        auto_watch_form.addRow(self._tr("settings.detection_interval"), self.poll_interval_ms_spin)
        auto_watch_form.addRow(self._tr("settings.pixel_delta_threshold"), self.pixel_delta_threshold_spin)
        auto_watch_form.addRow(self._tr("settings.new_question_ratio"), self.novelty_ratio_spin)
        auto_watch_form.addRow(self._tr("settings.stability_ratio"), self.stability_ratio_spin)
        auto_watch_form.addRow(self._tr("settings.stable_samples_required"), self.stable_samples_required_spin)
        auto_watch_form.addRow(self._tr("settings.analysis_delay"), self.analysis_delay_ms_spin)
        auto_watch_card_layout.addLayout(auto_watch_form)
        auto_watch_card_layout.addWidget(QLabel(
            self._tr("settings.auto_watch_ratios_help")
        ))
        auto_watch_card_layout.addWidget(self.expected_stability_label)
        auto_watch_buttons = QHBoxLayout()
        auto_watch_buttons.addWidget(self.restore_auto_watch_button)
        auto_watch_buttons.addStretch(1)
        auto_watch_card_layout.addLayout(auto_watch_buttons)
        auto_watch_layout.addWidget(auto_watch_card)
        auto_watch_layout.addStretch(1)

        updates_page, updates_layout = make_page(
            self._tr("settings.updates_title"), self._tr("settings.updates_description")
        )
        updates_card = QFrame()
        updates_card.setObjectName("settingsCard")
        updates_card_layout = QVBoxLayout(updates_card)
        updates_card_layout.setContentsMargins(16, 14, 16, 16)
        updates_card_layout.setSpacing(10)
        updates_form = QFormLayout()
        self.current_version_label = QLabel(__version__)
        self.current_version_label.setObjectName("currentVersionLabel")
        self.latest_version_label = QLabel(self._tr("settings.not_checked"))
        self.latest_version_label.setObjectName("latestVersionLabel")
        updates_form.addRow(self._tr("settings.current_version"), self.current_version_label)
        updates_form.addRow(self._tr("settings.latest_version"), self.latest_version_label)
        updates_card_layout.addLayout(updates_form)
        self.update_status_label = QLabel(
            self._tr("settings.update_status")
        )
        self.update_status_label.setObjectName("updateStatusLabel")
        self.update_status_label.setWordWrap(True)
        updates_card_layout.addWidget(self.update_status_label)
        update_buttons = QHBoxLayout()
        self.check_update_button = QPushButton(self._tr("settings.check_updates"))
        self.check_update_button.setObjectName("checkUpdateButton")
        self.check_update_button.clicked.connect(self.check_for_updates)
        self.update_button = QPushButton(self._tr("settings.update"))
        self.update_button.setObjectName("updateButton")
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self.install_update)
        update_buttons.addWidget(self.check_update_button)
        update_buttons.addWidget(self.update_button)
        update_buttons.addStretch(1)
        updates_card_layout.addLayout(update_buttons)
        updates_layout.addWidget(updates_card)
        updates_layout.addStretch(1)

        debug_page, debug_layout = make_page(
            self._tr("settings.debug_title"), self._tr("settings.debug_description")
        )
        debug_card = QFrame()
        debug_card.setObjectName("settingsCard")
        debug_card_layout = QVBoxLayout(debug_card)
        debug_card_layout.setContentsMargins(16, 14, 16, 16)
        debug_card_layout.setSpacing(10)
        self.debug_log_view = QPlainTextEdit()
        self.debug_log_view.setObjectName("debugLogView")
        self.debug_log_view.setReadOnly(True)
        self.debug_log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.debug_log_view.setMaximumBlockCount(DEFAULT_LOG_TAIL_LINES)
        # Compatibility aliases keep the widget discoverable for UI tests and
        # callers that use the more conventional ``*_edit`` naming.
        self.debug_log_edit = self.debug_log_view
        self.debug_log_status_label = QLabel()
        self.debug_log_status_label.setObjectName("debugLogStatusLabel")
        self.debug_log_status_label.setWordWrap(True)
        self.debug_log_status = self.debug_log_status_label
        self.debug_log_refresh_button = QPushButton(self._tr("settings.refresh"))
        self.debug_log_refresh_button.setObjectName("debugLogRefreshButton")
        self.debug_log_refresh_button.clicked.connect(self.refresh_debug_log)
        self.refresh_log_button = self.debug_log_refresh_button
        debug_card_layout.addWidget(self.debug_log_view, 1)
        debug_card_layout.addWidget(self.debug_log_status_label)
        debug_card_layout.addWidget(
            self.debug_log_refresh_button, 0, Qt.AlignmentFlag.AlignLeft
        )
        debug_layout.addWidget(debug_card, 1)

        language_page, language_layout = make_page(
            self._tr("settings.language_title"),
            self._tr("settings.language_description"),
        )
        language_card = QFrame()
        language_card.setObjectName("settingsCard")
        language_card_layout = QVBoxLayout(language_card)
        language_card_layout.setContentsMargins(16, 14, 16, 16)
        language_card_layout.setSpacing(10)
        language_form = QFormLayout()
        language_form.addRow(
            self._tr("settings.interface_language"), self.interface_language_combo
        )
        language_form.addRow(
            self._tr("settings.answer_language"), self.answer_language_combo
        )
        language_card_layout.addLayout(language_form)
        self.interface_language_restart_label = QLabel(
            self._tr("settings.restart_required")
        )
        self.interface_language_restart_label.setObjectName("settingsWarningLabel")
        self.interface_language_restart_label.setWordWrap(True)
        language_card_layout.addWidget(self.interface_language_restart_label)
        language_layout.addWidget(language_card)
        language_layout.addStretch(1)

        for page in (
            ai_page,
            shortcuts_page,
            ocr_page,
            local_page,
            google_page,
            auto_watch_page,
            updates_page,
            debug_page,
            language_page,
        ):
            self.page_stack.addWidget(page)

        page_scroll = QScrollArea()
        page_scroll.setObjectName("settingsPageScroll")
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_scroll.setWidget(self.page_stack)
        self.page_scroll = page_scroll

        content = QHBoxLayout()
        content.setSpacing(14)
        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(170)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 10, 8, 10)
        sidebar_layout.setSpacing(4)
        self._navigation_buttons: list[QPushButton] = []
        for index, label in enumerate(
            (
                self._tr("settings.ai_title"),
                self._tr("settings.shortcuts_title"),
                "OCR",
                "Local OCR",
                "Google Vision",
                "Auto Watch",
                self._tr("settings.updates_title"),
                self._tr("settings.debug_title"),
                self._tr("settings.language_title"),
            )
        ):
            nav_button = QPushButton(label)
            nav_button.setObjectName("navigationButton")
            nav_button.setProperty("navLevel", "child" if index in (3, 4) else "primary")
            nav_button.setCheckable(True)
            nav_button.clicked.connect(
                lambda _checked=False, page_index=index: self._select_page(page_index)
            )
            sidebar_layout.addWidget(nav_button)
            self._navigation_buttons.append(nav_button)
        sidebar_layout.addStretch(1)
        content.addWidget(sidebar)
        content.addWidget(page_scroll, 1)
        surface_layout.addLayout(content, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("settingsStatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        surface_layout.addWidget(self.status_label)

        self.save_button = QPushButton(self._tr("settings.save"))
        self.save_button.setObjectName("saveButton")
        self.cancel_button = QPushButton(self._tr("settings.close"))
        self.cancel_button.setObjectName("cancelButton")
        self.save_button.clicked.connect(self.save)
        self.cancel_button.clicked.connect(self.close)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        surface_layout.addLayout(footer)

        self._load_current_values()
        self._refresh_local_ocr_state()
        self._apply_local_ocr_capability()
        self.refresh_debug_log()
        self._select_page(0)

    def _refresh_expected_stability(self) -> None:
        milliseconds = self.poll_interval_ms_spin.value() * self.stable_samples_required_spin.value()
        self.expected_stability_label.setText(
            self._tr("settings.expected_stability", milliseconds=milliseconds)
        )

    def _load_auto_watch_values(self) -> None:
        saved = self.config_manager.settings_repository.load()
        settings = self.config_manager.settings_repository.auto_watch_settings()
        mode_getter = getattr(
            self.config_manager.settings_repository,
            "auto_watch_analysis_mode",
            None,
        )
        if callable(mode_getter):
            try:
                mode = AnalysisMode(mode_getter())
            except (TypeError, ValueError):
                mode = AnalysisMode.TEXT
        else:
            try:
                mode = AnalysisMode(
                    saved.get("auto_watch_analysis_mode", AnalysisMode.TEXT.value)
                )
            except (TypeError, ValueError):
                mode = AnalysisMode.TEXT
        self._loaded_auto_watch_analysis_mode = mode
        self.auto_watch_text_radio.setChecked(mode is AnalysisMode.TEXT)
        self.auto_watch_vision_radio.setChecked(mode is AnalysisMode.VISION)
        self._loaded_auto_watch_values = {
            key: saved[key]
            for key in (
                "poll_interval_ms", "pixel_delta_threshold", "novelty_ratio",
                "stability_ratio", "stable_samples_required", "analysis_delay_ms",
            ) if key in saved
        }
        self.poll_interval_ms_spin.setValue(settings.poll_interval_ms)
        self.pixel_delta_threshold_spin.setValue(settings.pixel_delta_threshold)
        self.novelty_ratio_spin.setValue(settings.novelty_ratio * 100.0)
        self.stability_ratio_spin.setValue(settings.stability_ratio * 100.0)
        self.stable_samples_required_spin.setValue(settings.stable_samples_required)
        self.analysis_delay_ms_spin.setValue(settings.analysis_delay_ms)
        self._refresh_expected_stability()

    def _auto_watch_values(self) -> dict[str, int | float | str]:
        return {
            "auto_watch_analysis_mode": (
                AnalysisMode.VISION.value
                if self.auto_watch_vision_radio.isChecked()
                else AnalysisMode.TEXT.value
            ),
            "poll_interval_ms": self.poll_interval_ms_spin.value(),
            "pixel_delta_threshold": self.pixel_delta_threshold_spin.value(),
            "novelty_ratio": self.novelty_ratio_spin.value() / 100.0,
            "stability_ratio": self.stability_ratio_spin.value() / 100.0,
            "stable_samples_required": self.stable_samples_required_spin.value(),
            "analysis_delay_ms": self.analysis_delay_ms_spin.value(),
        }

    def _changed_auto_watch_values(self) -> dict[str, int | float | str]:
        current = self._auto_watch_values()
        defaults = AutoWatchSettings()
        changed: dict[str, int | float | str] = {
            key: value
            for key, value in current.items()
            if key != "auto_watch_analysis_mode"
            and value != self._loaded_auto_watch_values.get(key, getattr(defaults, key))
        }
        if current["auto_watch_analysis_mode"] != self._loaded_auto_watch_analysis_mode.value:
            changed["auto_watch_analysis_mode"] = current["auto_watch_analysis_mode"]
        return changed

    @Slot()
    def _restore_auto_watch_defaults(self) -> None:
        defaults = AutoWatchSettings()
        self.auto_watch_text_radio.setChecked(True)
        self.poll_interval_ms_spin.setValue(defaults.poll_interval_ms)
        self.pixel_delta_threshold_spin.setValue(defaults.pixel_delta_threshold)
        self.novelty_ratio_spin.setValue(defaults.novelty_ratio * 100.0)
        self.stability_ratio_spin.setValue(defaults.stability_ratio * 100.0)
        self.stable_samples_required_spin.setValue(defaults.stable_samples_required)
        self.analysis_delay_ms_spin.setValue(defaults.analysis_delay_ms)
        self._refresh_expected_stability()

    def _select_page(self, index: int) -> None:
        """Switch pages without changing provider or persisted configuration."""

        self.page_stack.setCurrentIndex(index)
        for page_index, button in enumerate(self._navigation_buttons):
            button.setChecked(page_index == index)

    @Slot()
    def check_for_updates(self) -> None:
        if self.is_update_check_running() or self.is_update_download_running():
            return
        self._close_requested = False
        self._pending_update = None
        self._update_check_cancel_event = threading.Event()
        worker = UpdateCheckWorker(
            self.update_service,
            self._update_check_cancel_event,
            self._interface_language,
        )
        thread = QThread(self)
        thread.setObjectName("SettingsUpdateCheckThread")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_update_check_success)
        worker.failed.connect(self._on_update_check_failed)
        worker.cancelled.connect(self._on_update_check_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_update_check_finished)
        self._update_check_worker = worker
        self._update_check_thread = thread
        self.latest_version_label.setText(self._tr("settings.checking"))
        self.update_status_label.setText(self._tr("settings.checking_releases"))
        self._refresh_update_controls()
        thread.start()

    @Slot(object)
    def _on_update_check_success(self, result: object) -> None:
        if self._close_requested or self._shutdown_requested:
            return
        if not isinstance(result, UpdateCheckResult):
            self._on_update_check_failed("GitHub Releases returned an unexpected result.")
            return
        self.latest_version_label.setText(result.latest_version)
        if result.update_available:
            self._pending_update = result
            self.update_status_label.setText(
                self._tr("settings.update_available", version=result.latest_version)
            )
        else:
            self._pending_update = None
            self.update_status_label.setText(self._tr("settings.up_to_date"))
        self._refresh_update_controls()

    @Slot(str)
    def _on_update_check_failed(self, message: str) -> None:
        self._pending_update = None
        if not self._close_requested and not self._shutdown_requested:
            self.latest_version_label.setText(self._tr("settings.unavailable"))
            self.update_status_label.setText(message)
        self._refresh_update_controls()

    @Slot()
    def _on_update_check_cancelled(self) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.update_status_label.setText(self._tr("settings.update_check_cancelled"))

    @Slot()
    def _on_update_check_finished(self) -> None:
        self._update_check_thread = None
        self._update_check_worker = None
        self._update_check_cancel_event = None
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._refresh_update_controls()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def install_update(self) -> None:
        result = self._pending_update
        if (
            result is None
            or not result.update_available
            or self.is_update_check_running()
            or self.is_update_download_running()
        ):
            return
        self._close_requested = False
        self._update_download_cancel_event = threading.Event()
        worker = UpdateDownloadWorker(
            self.update_service,
            result.asset,
            self._update_download_cancel_event,
            self._interface_language,
        )
        thread = QThread(self)
        thread.setObjectName("SettingsUpdateDownloadThread")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_update_download_success)
        worker.failed.connect(self._on_update_download_failed)
        worker.cancelled.connect(self._on_update_download_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_update_download_finished)
        self._update_download_worker = worker
        self._update_download_thread = thread
        self.update_status_label.setText(
            self._tr("settings.downloading_version", version=result.latest_version)
        )
        self._refresh_update_controls()
        thread.start()

    @Slot(str)
    def _on_update_download_success(self, _path: str) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.update_status_label.setText(
                self._tr("settings.update_package_opened")
            )
        self._pending_update = None

    @Slot(str)
    def _on_update_download_failed(self, message: str) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.update_status_label.setText(message)

    @Slot()
    def _on_update_download_cancelled(self) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.update_status_label.setText(self._tr("settings.update_download_cancelled"))

    @Slot()
    def _on_update_download_finished(self) -> None:
        self._update_download_thread = None
        self._update_download_worker = None
        self._update_download_cancel_event = None
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._refresh_update_controls()
        self._maybe_emit_shutdown_ready()

    def _refresh_update_controls(self) -> None:
        busy = self.is_update_check_running() or self.is_update_download_running()
        self.check_update_button.setEnabled(not busy)
        result = self._pending_update
        self.update_button.setEnabled(
            not busy and result is not None and result.update_available
        )
        if self.is_update_download_running():
            self.update_button.setText(self._tr("settings.downloading"))
        elif result is not None and result.update_available:
            self.update_button.setText(
                self._tr("settings.update_to", version=result.latest_version)
            )
        else:
            self.update_button.setText(self._tr("settings.update"))

    @Slot()
    def refresh_debug_log(self) -> None:
        """Refresh the bounded, read-only tail of the operational log."""

        try:
            path = Path(self._log_path) if self._log_path is not None else default_log_path()
            text = read_log_tail(
                path,
                max_bytes=DEFAULT_LOG_TAIL_BYTES,
                max_lines=DEFAULT_LOG_TAIL_LINES,
            )
        except FileNotFoundError:
            self.debug_log_view.clear()
            self.debug_log_status_label.setText(self._tr("settings.ready_log"))
            return
        except (OSError, RuntimeError) as exc:
            logger.warning("debug log read failed: %s", type(exc).__name__)
            self.debug_log_view.clear()
            self.debug_log_status_label.setText(self._tr("settings.log_read_error"))
            return

        self.debug_log_view.setPlainText(text)
        line_count = len(text.splitlines())
        if line_count:
            self.debug_log_status_label.setText(
                self._tr(
                    "settings.log_lines",
                    count=line_count,
                    size=DEFAULT_LOG_TAIL_BYTES // 1024,
                )
            )
        else:
            self.debug_log_status_label.setText(self._tr("settings.log_empty"))

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
                self._tr("settings.local_ocr_no_distribution")
            )
        else:
            self.local_ocr_unsupported_label.setText(
                self._tr("settings.local_ocr_unsupported")
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
            config = self.config_manager.load()
        except ConfigError:
            config = AppConfig()
        self._loaded_interface_language = normalize_language(
            getattr(config, "interface_language", DEFAULT_INTERFACE_LANGUAGE),
            default=DEFAULT_INTERFACE_LANGUAGE,
        )
        self._loaded_answer_language = normalize_language(
            getattr(config, "answer_language", DEFAULT_ANSWER_LANGUAGE),
            default=DEFAULT_ANSWER_LANGUAGE,
        )
        for combo, value in (
            (self.interface_language_combo, self._loaded_interface_language),
            (self.answer_language_combo, self._loaded_answer_language),
        ):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        self._loaded_provider_keys = {}
        self._loaded_provider_endpoints = {}
        for descriptor in AI_PROVIDER_CATALOG:
            key_getter = getattr(self.config_manager, "get_provider_api_key", None)
            endpoint_getter = getattr(self.config_manager, "get_provider_base_url", None)
            self._loaded_provider_keys[descriptor.provider_id] = (
                key_getter(descriptor.provider_id)
                if callable(key_getter)
                else (
                    config.text_ai.api_key
                    if descriptor.provider_id == config.text_ai.provider_id
                    else ""
                )
            )
            self._loaded_provider_endpoints[descriptor.provider_id] = (
                endpoint_getter(descriptor.provider_id)
                if callable(endpoint_getter)
                else (
                    config.text_ai.base_url
                    if descriptor.provider_id == config.text_ai.provider_id
                    else descriptor.default_base_url
                )
            )
        self._provider_key_values = dict(self._loaded_provider_keys)
        self._provider_endpoint_values = dict(self._loaded_provider_endpoints)
        self._loaded_google_vision_api_key = config.google_vision_api_key
        self.text_provider_combo.blockSignals(True)
        self.text_provider_combo.setCurrentIndex(
            max(0, self.text_provider_combo.findData(config.text_ai.provider_id))
        )
        self.text_provider_combo.blockSignals(False)
        self.vision_provider_combo.blockSignals(True)
        self.vision_provider_combo.setCurrentIndex(
            max(0, self.vision_provider_combo.findData(config.vision_ai.provider_id))
        )
        self.vision_provider_combo.blockSignals(False)
        self._populate_model_selector(
            self.text_model_combo,
            config.text_ai.provider_id,
            "text",
            config.text_ai.model_id,
        )
        self._populate_model_selector(
            self.vision_model_combo,
            config.vision_ai.provider_id,
            "vision",
            config.vision_ai.model_id,
        )
        self.provider_credentials_combo.blockSignals(True)
        self.provider_credentials_combo.setCurrentIndex(
            max(0, self.provider_credentials_combo.findData(config.text_ai.provider_id))
        )
        self.provider_credentials_combo.blockSignals(False)
        self._on_credentials_provider_changed()
        self.google_vision_api_key_edit.setText(config.google_vision_api_key)
        google_env_override = self.config_manager.has_explicit_google_vision_api_key()
        self.google_vision_api_key_edit.setReadOnly(google_env_override)
        self.google_vision_api_key_edit.setEnabled(not google_env_override)
        self.google_vision_override_label.setVisible(google_env_override)
        api_env_override = self.config_manager.has_explicit_provider_api_key(
            config.text_ai.provider_id
        )
        self.api_key_override_label.setVisible(api_env_override)
        request_timeout = config.text_ai.request_timeout
        self.timeout_edit.setText(str(int(request_timeout) if request_timeout.is_integer() else request_timeout))
        self.shortcut_edit.setKeySequence(QKeySequence(config.global_shortcut))
        self.vision_shortcut_edit.setKeySequence(QKeySequence(config.vision_global_shortcut))
        self.watch_shortcut_edit.setKeySequence(QKeySequence(config.watch_global_shortcut))
        self.context_watch_shortcut_edit.setKeySequence(
            QKeySequence(config.context_watch_global_shortcut)
        )
        is_online = config.ocr_mode == "online" or not self._local_ocr_is_usable()
        provider_env_override = self.config_manager.has_explicit_ocr_mode()
        self.local_mode_radio.setChecked(not is_online)
        self.online_mode_radio.setChecked(is_online)
        self.local_engine_combo.setCurrentIndex(
            max(
                0,
                self.local_engine_combo.findData(
                    config.local_ocr_engine or DEFAULT_LOCAL_OCR_ENGINE
                ),
            )
        )
        self.online_service_combo.setCurrentIndex(
            max(
                0,
                self.online_service_combo.findData(
                    config.online_ocr_provider or DEFAULT_ONLINE_OCR_PROVIDER
                ),
            )
        )
        self.local_mode_radio.setEnabled(not provider_env_override)
        self.online_mode_radio.setEnabled(not provider_env_override)
        self.local_engine_combo.setEnabled(not provider_env_override)
        self.online_service_combo.setEnabled(not provider_env_override)
        self.ocr_provider_override_label.setVisible(provider_env_override)
        self._on_provider_changed()
        self._show_environment_override_warnings()
        self._load_auto_watch_values()

    def _on_interface_language_changed(self, _index: int) -> None:
        """Keep the restart contract explicit without retranslating live widgets."""

        self.interface_language_restart_label.setText(
            self._tr("settings.restart_required")
        )

    def _populate_model_selector(
        self,
        selector: ModelSelector,
        provider_id: str,
        capability: str,
        selected_model: str,
    ) -> None:
        """Render known models plus a lossless Custom entry for saved IDs."""

        selector.blockSignals(True)
        selector.clear()
        try:
            models = models_for_provider(provider_id, capability)  # type: ignore[arg-type]
        except ValueError:
            models = ()
        for model in models:
            selector.addItem(model.display_name, model.model_id)
        selector.addItem(self._tr("settings.custom_model_id"), CUSTOM_MODEL_ID)
        known_index = selector.findData(selected_model)
        if known_index >= 0:
            selector.setCurrentIndex(known_index)
        else:
            custom_index = selector.findData(CUSTOM_MODEL_ID)
            selector.setCurrentIndex(max(0, custom_index))
            selector.setEditText(selected_model)
        selector.blockSignals(False)

    @staticmethod
    def _selected_model(selector: ModelSelector) -> str:
        value = selector.currentData()
        text = selector.currentText().strip()
        if value == CUSTOM_MODEL_ID or value is None:
            return text
        # QComboBox keeps the selected item's userData when a user edits the
        # line edit directly. Treat a changed display value as a custom model
        # so typing an unlisted ID does not silently save the old selection.
        if selector.isEditable() and selector.currentIndex() >= 0:
            if text != selector.itemText(selector.currentIndex()).strip():
                return text
        return str(value).strip()

    @staticmethod
    def _clear_custom_placeholder(selector: ModelSelector) -> None:
        if selector.currentData() == CUSTOM_MODEL_ID and selector.currentText() in {
            CUSTOM_MODEL_LABEL,
            "自定义模型 ID…",
        }:
            selector.setEditText("")

    def _provider_id(self, combo: QComboBox) -> str:
        return str(combo.currentData() or "deepseek").strip().lower()

    @Slot(int)
    def _on_text_provider_changed(self, _index: int) -> None:
        provider_id = self._provider_id(self.text_provider_combo)
        current_model = self._selected_model(self.text_model_combo)
        known = {model.model_id for model in models_for_provider(provider_id, "text")}
        selected = current_model if current_model in known else get_provider_descriptor(provider_id).default_model("text")
        self._populate_model_selector(
            self.text_model_combo,
            provider_id,
            "text",
            selected,
        )

    @Slot(int)
    def _on_vision_provider_changed(self, _index: int) -> None:
        provider_id = self._provider_id(self.vision_provider_combo)
        current_model = self._selected_model(self.vision_model_combo)
        known = {model.model_id for model in models_for_provider(provider_id, "vision")}
        selected = current_model if current_model in known else get_provider_descriptor(provider_id).default_model("vision")
        self._populate_model_selector(
            self.vision_model_combo,
            provider_id,
            "vision",
            selected,
        )

    def _capture_provider_editor(self) -> None:
        provider_id = self._provider_id(self.provider_credentials_combo)
        self._provider_key_values[provider_id] = self.provider_api_key_edit.text().strip()
        self._provider_endpoint_values[provider_id] = self.provider_endpoint_edit.text().strip()

    @Slot(int)
    def _on_credentials_provider_changed(self, _index: int = -1) -> None:
        previous_provider = getattr(self, "_active_credentials_provider", None)
        if previous_provider is not None:
            self._provider_key_values[previous_provider] = self.provider_api_key_edit.text().strip()
            self._provider_endpoint_values[previous_provider] = self.provider_endpoint_edit.text().strip()
        provider_id = self._provider_id(self.provider_credentials_combo)
        self._active_credentials_provider = provider_id
        self.provider_api_key_edit.setText(self._provider_key_values.get(provider_id, ""))
        self.provider_endpoint_edit.setText(
            self._provider_endpoint_values.get(
                provider_id,
                get_provider_descriptor(provider_id).default_base_url,
            )
        )
        explicit_key = self.config_manager.has_explicit_provider_api_key(provider_id)
        self.provider_api_key_edit.setReadOnly(explicit_key)
        self.provider_api_key_edit.setEnabled(not explicit_key)
        self.api_key_override_label.setText(
            self._tr(
                "settings.provider_api_key_env_override",
                provider=get_provider_descriptor(provider_id).display_name,
                environment_name=get_provider_descriptor(provider_id).api_key_env,
            )
        )
        self.api_key_override_label.setVisible(explicit_key)
        explicit_endpoint = self.config_manager.has_explicit_provider_base_url(provider_id)
        self.provider_endpoint_edit.setReadOnly(explicit_endpoint)
        self.provider_endpoint_edit.setEnabled(not explicit_endpoint)
        self.provider_endpoint_override_label.setText(
            self._tr(
                "settings.provider_endpoint_env_override",
                provider=get_provider_descriptor(provider_id).display_name,
                environment_name=f"{provider_id.upper()}_BASE_URL",
            )
        )
        self.provider_endpoint_override_label.setVisible(explicit_endpoint)

    def reload_values(self) -> None:
        """Reload persisted values when the window is shown again."""

        if not self.has_running_background_operations():
            self._load_current_values()
        if not self.is_download_running():
            self._refresh_local_ocr_state()

    @Slot()
    def _on_provider_changed(self) -> None:
        # Navigation keeps both service pages available; the radios still
        # determine which provider is used by Text mode.
        self._refresh_operation_controls()

    def _ocr_mode_from_ui(self) -> str:
        return "local" if self.local_mode_radio.isChecked() else "online"

    def _show_environment_override_warnings(self) -> None:
        self._on_credentials_provider_changed()
        self.google_vision_override_label.setVisible(
            self.config_manager.has_explicit_google_vision_api_key()
        )

    def _refresh_local_ocr_state(self) -> None:
        if not self._local_ocr_supported:
            self._apply_local_ocr_capability()
            self.local_ocr_status_label.setText(
                self._tr("settings.local_ocr_unsupported")
            )
            return
        if self.component_manager.is_installed():
            self.local_ocr_status_label.setText(
                self._tr("settings.local_ocr_installed", version=self.component_manager.version)
            )
            self.download_ocr_button.setVisible(False)
        elif not self._local_ocr_distribution_available():
            self.local_ocr_status_label.setText(
                self._tr("settings.local_ocr_no_distribution")
            )
        else:
            self.local_ocr_status_label.setText(self._tr("settings.local_ocr_not_installed"))
            self.download_ocr_button.setVisible(True)
        self._apply_local_ocr_capability()
        self._refresh_operation_controls()

    def _set_local_ocr_worker_status(self, status: str) -> None:
        """Translate the bounded status vocabulary emitted by the download worker."""

        status_key = {
            "Downloading...": "settings.downloading",
            "Verifying...": "settings.verifying",
            "Installing...": "settings.installing",
        }.get(status)
        self.local_ocr_status_label.setText(
            self._tr(status_key) if status_key is not None else status
        )

    def _refresh_operation_controls(
        self,
        *,
        connection_running: bool | None = None,
        vision_connection_running: bool | None = None,
        download_running: bool | None = None,
        google_running: bool | None = None,
    ) -> None:
        connection_running = (
            self.is_connection_running() if connection_running is None else connection_running
        )
        vision_connection_running = (
            self.is_vision_connection_running()
            if vision_connection_running is None
            else vision_connection_running
        )
        download_running = (
            self.is_download_running() if download_running is None else download_running
        )
        google_running = (
            self.is_google_test_running() if google_running is None else google_running
        )
        busy = connection_running or vision_connection_running or download_running or google_running
        self.download_ocr_button.setEnabled(self._local_ocr_supported and not busy)
        self.verify_ocr_button.setEnabled(
            self._local_ocr_supported and not busy and self.component_manager.is_installed()
        )
        self.remove_ocr_button.setEnabled(
            self._local_ocr_supported and not busy and self.component_manager.is_installed()
        )
        self.text_test_button.setEnabled(not busy)
        self.vision_test_button.setEnabled(not busy)
        self.text_cancel_button.setVisible(connection_running)
        self.text_cancel_button.setEnabled(connection_running)
        self.vision_cancel_button.setVisible(vision_connection_running)
        self.vision_cancel_button.setEnabled(vision_connection_running)
        self.google_vision_test_button.setEnabled(not busy)
        provider_editable = not busy and not self.config_manager.has_explicit_ocr_mode()
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
            self._set_status(self._tr("settings.download_local_ocr_unavailable"))
            return
        manifest_url = resolve_manifest_url(self.config_manager.project_root)
        if not manifest_url:
            self._set_status(
                self._tr("settings.download_local_ocr_no_distribution")
            )
            self._refresh_local_ocr_state()
            return
        if self._download_thread is not None and self._download_thread.isRunning():
            return
        if (
            self.local_ocr_session is not None
            and getattr(self.local_ocr_session, "is_preparing", lambda: False)()
        ):
            self._set_status(self._tr("settings.local_ocr_preparing"))
            return
        if self.is_connection_running() or self.is_google_test_running():
            self._set_status(self._tr("settings.download_wait_test"))
            return
        session_preparing = bool(
            self.local_ocr_session is not None
            and getattr(self.local_ocr_session, "is_preparing", lambda: False)()
        )
        if self.local_ocr_session is not None and self.local_ocr_session.is_busy() and not session_preparing:
            self._set_status(self._tr("settings.local_ocr_in_use"))
            return
        if self.local_ocr_session is not None:
            self.local_ocr_session.stop()
        self._local_ocr_download_terminal_status = None
        self._download_cancel_event = threading.Event()
        worker = LocalOCRDownloadWorker(manifest_url, self.component_manager, self._download_cancel_event)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self.local_ocr_progress.setValue)
        worker.manifest_loaded.connect(self._on_local_ocr_manifest_loaded)
        worker.status_changed.connect(self._set_local_ocr_worker_status)
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
            self.local_ocr_status_label.setText(self._tr("settings.cancelling"))
            self.cancel_download_button.setEnabled(False)

    @Slot(str)
    def _on_local_ocr_download_succeeded(self, installed_path: str) -> None:
        self._local_ocr_download_terminal_status = None
        if self.local_ocr_session is not None:
            self.local_ocr_session.reset_capability()
        self.local_ocr_status_label.setText(
            self._tr("settings.local_ocr_installed", version=self.component_manager.version)
        )
        self.local_ocr_size_label.setText("")
        self.local_ocr_component_changed.emit()

    @Slot(int)
    def _on_local_ocr_manifest_loaded(self, size: int) -> None:
        self.local_ocr_size_label.setText(
            self._tr("settings.download_size", size=size / (1024 * 1024))
        )

    @Slot(str)
    def _on_local_ocr_download_failed(self, message: str) -> None:
        self._local_ocr_download_terminal_status = self._tr(
            "settings.download_error", detail=message
        )
        self.local_ocr_status_label.setText(self._local_ocr_download_terminal_status)

    @Slot()
    def _on_local_ocr_download_cancelled(self) -> None:
        self._local_ocr_download_terminal_status = self._tr("settings.download_cancelled")
        self.local_ocr_status_label.setText(self._local_ocr_download_terminal_status)

    @Slot()
    def _on_local_ocr_download_finished(self) -> None:
        terminal_status = self._local_ocr_download_terminal_status
        self._download_thread = None
        self._download_worker = None
        self._download_cancel_event = None
        self._refresh_operation_controls()
        self._refresh_local_ocr_state()
        if terminal_status and not self.component_manager.is_installed():
            # ``_refresh_local_ocr_state`` reports the durable installation
            # state, but must not erase the actionable error/cancel result that
            # just arrived from the background worker.
            self.local_ocr_status_label.setText(terminal_status)
        self._maybe_emit_shutdown_ready()

    @Slot()
    def verify_local_ocr(self) -> None:
        if not self._local_ocr_supported:
            self.local_ocr_status_label.setText(
                self._tr("settings.local_ocr_unsupported")
            )
            return
        if not self.component_manager.verify_installation():
            self.local_ocr_status_label.setText(self._tr("settings.local_ocr_incomplete"))
            return
        self.local_ocr_status_label.setText(self._tr("settings.local_ocr_verifying"))
        if self.component_manager.smoke_test():
            self.local_ocr_status_label.setText(
                self._tr(
                    "settings.local_ocr_verified",
                    version=self.component_manager.version,
                )
            )
        else:
            self.local_ocr_status_label.setText(self._tr("settings.local_ocr_smoke_failed"))

    @Slot()
    def remove_local_ocr(self) -> None:
        if not self._local_ocr_supported:
            self.local_ocr_status_label.setText(
                self._tr("settings.local_ocr_unsupported")
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
                self._tr("settings.local_ocr_preparing")
            )
            return
        answer = QMessageBox.question(
            self,
            self._tr("settings.remove_local_ocr"),
            self._tr("settings.remove_local_ocr_question"),
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
                            self._tr("settings.local_ocr_preparing")
                        )
                        return
                    if self.local_ocr_session.is_busy() and not session_preparing:
                        self.local_ocr_status_label.setText(
                            self._tr("settings.local_ocr_in_use")
                        )
                        return
                    self.local_ocr_session.stop()
                self.component_manager.remove()
            except (OSError, ComponentError) as exc:
                logger.warning("local OCR removal failed: %s", type(exc).__name__)
                self.local_ocr_status_label.setText(
                    self._tr("settings.error_remove_local_ocr", detail=exc)
                )
                return
            if self.local_ocr_session is not None:
                self.local_ocr_session.reset_capability()
            self._refresh_local_ocr_state()
            self.local_ocr_component_changed.emit()

    def _read_config_from_fields(self) -> AppConfig:
        text_provider = self._provider_id(self.text_provider_combo)
        vision_provider = self._provider_id(self.vision_provider_combo)
        text_model = self._selected_model(self.text_model_combo)
        vision_model = self._selected_model(self.vision_model_combo)
        if not text_model or not vision_model:
            raise ValueError(self._tr("settings.validation_model_empty"))
        try:
            request_timeout = float(self.timeout_edit.text().strip())
        except ValueError as exc:
            raise ValueError(self._tr("settings.validation_timeout")) from exc
        if request_timeout <= 0:
            raise ValueError(self._tr("settings.validation_timeout"))
        sequence = self.shortcut_edit.keySequence()
        global_shortcut = self._parse_shortcut(sequence)
        vision_shortcut = self._parse_shortcut(self.vision_shortcut_edit.keySequence())
        watch_shortcut = self._parse_shortcut(self.watch_shortcut_edit.keySequence())
        context_watch_shortcut = self._parse_shortcut(
            self.context_watch_shortcut_edit.keySequence()
        )
        try:
            validate_unique_shortcuts(
                (
                    global_shortcut,
                    vision_shortcut,
                    watch_shortcut,
                    context_watch_shortcut,
                )
            )
        except HotkeySpecError as exc:
            raise ValueError(self._tr("settings.validation_shortcuts")) from exc
        self._capture_provider_editor()
        current = self.config_manager.load()
        for provider_id in {text_provider, vision_provider}:
            if not self._provider_endpoint_values.get(provider_id, "").strip():
                raise ValueError(self._tr("settings.validation_endpoint_empty"))
        return AppConfig(
            text_ai=AIBackendConfig(
                provider_id=text_provider,
                model_id=text_model,
                api_key=self._provider_key_values.get(text_provider, ""),
                base_url=self._provider_endpoint_values.get(
                    text_provider,
                    current.text_ai.base_url,
                ),
                request_timeout=request_timeout,
            ),
            vision_ai=AIBackendConfig(
                provider_id=vision_provider,
                model_id=vision_model,
                api_key=self._provider_key_values.get(vision_provider, ""),
                base_url=self._provider_endpoint_values.get(
                    vision_provider,
                    current.vision_ai.base_url,
                ),
                request_timeout=request_timeout,
            ),
            ocr_language=current.ocr_language,
            global_shortcut=global_shortcut,
            vision_global_shortcut=vision_shortcut,
            watch_global_shortcut=watch_shortcut,
            context_watch_global_shortcut=context_watch_shortcut,
            ocr_mode=self._ocr_mode_from_ui(),
            local_ocr_engine=str(
                self.local_engine_combo.currentData() or DEFAULT_LOCAL_OCR_ENGINE
            ),
            online_ocr_provider=str(
                self.online_service_combo.currentData() or DEFAULT_ONLINE_OCR_PROVIDER
            ),
            google_vision_api_key=self.google_vision_api_key_edit.text().strip(),
            online_ocr_timeout=current.online_ocr_timeout,
            interface_language=self.interface_language_combo.currentData(),
            answer_language=self.answer_language_combo.currentData(),
        )

    def _parse_shortcut(self, sequence: QKeySequence) -> str:
        if sequence.count() != 1:
            raise ValueError(self._tr("settings.validation_one_shortcut"))
        try:
            return HotkeySpec.parse(
                sequence.toString(QKeySequence.SequenceFormat.PortableText)
            ).canonical
        except HotkeySpecError as exc:
            raise ValueError(str(exc)) from exc

    def _start_ai_connection(self, capability: str) -> None:
        if capability not in {"text", "vision"}:
            raise ValueError("capability must be 'text' or 'vision'")
        if (
            self.is_connection_running()
            or self.is_vision_connection_running()
        ):
            return
        if self.is_download_running() or self.is_google_test_running():
            self._set_status(self._tr("settings.wait_operation_before_ai"))
            return
        try:
            config = self._read_config_from_fields()
        except (ConfigError, ValueError) as exc:
            self._set_status(str(exc))
            return
        backend = config.text_ai if capability == "text" else config.vision_ai
        if not backend.api_key:
            self._set_status(self._tr("settings.enter_provider_api_key"))
            return

        config = replace(
            config,
            text_ai=replace(
                config.text_ai,
                request_timeout=min(config.text_ai.request_timeout, CONNECTION_TEST_TIMEOUT),
            ),
            vision_ai=replace(
                config.vision_ai,
                request_timeout=min(config.vision_ai.request_timeout, CONNECTION_TEST_TIMEOUT),
            ),
        )
        self._close_requested = False
        cancel_event = threading.Event()
        worker = ConnectionTestWorker(config, cancel_event, capability)
        thread = QThread(self)
        thread.setObjectName(
            "SettingsVisionConnectionTestThread"
            if capability == "vision"
            else "SettingsConnectionTestThread"
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if capability == "vision":
            worker.succeeded.connect(self._on_vision_connection_success)
            worker.failed.connect(self._on_vision_connection_failed)
            thread.finished.connect(self._on_vision_connection_finished)
            self._vision_connection_worker = worker
            self._vision_connection_thread = thread
            self._vision_connection_cancel_event = cancel_event
        else:
            worker.succeeded.connect(self._on_connection_success)
            worker.failed.connect(self._on_connection_failed)
            thread.finished.connect(self._on_connection_finished)
            self._connection_worker = worker
            self._connection_thread = thread
            self._connection_cancel_event = cancel_event
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._refresh_operation_controls(
            connection_running=capability == "text",
            vision_connection_running=capability == "vision",
        )
        if capability == "vision":
            self.vision_test_button.setText(self._tr("settings.testing"))
            self.vision_ai_status_label.setText(self._tr("settings.connection_testing"))
        else:
            self._set_status(self._tr("settings.connection_testing"))
            self.text_test_button.setText(self._tr("settings.testing"))
        thread.start()

    @Slot()
    def test_text_connection(self) -> None:
        self._start_ai_connection("text")

    @Slot()
    def test_vision_connection(self) -> None:
        self._start_ai_connection("vision")

    @Slot()
    def _on_connection_success(self) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self._set_status(self._tr("settings.connection_success"))
            self.text_ai_status_label.setText(self._tr("settings.text_ai_connection_success"))

    @Slot(str)
    def _on_connection_failed(self, message: str) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self._set_status(message)
            self.text_ai_status_label.setText(message)

    @Slot()
    def _on_connection_finished(self) -> None:
        self._connection_thread = None
        self._connection_worker = None
        self._connection_cancel_event = None
        self.text_test_button.setText(self._tr("settings.test_text_ai"))
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._refresh_operation_controls()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def _on_vision_connection_success(self) -> None:
        if not self._close_requested and not self._shutdown_requested:
            message = self._tr("settings.vision_ai_connection_success")
            self.vision_ai_status_label.setText(message)
            self._set_status(message)

    @Slot(str)
    def _on_vision_connection_failed(self, message: str) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.vision_ai_status_label.setText(message)
            self._set_status(message)

    @Slot()
    def _on_vision_connection_finished(self) -> None:
        self._vision_connection_thread = None
        self._vision_connection_worker = None
        self._vision_connection_cancel_event = None
        self.vision_test_button.setText(self._tr("settings.test_vision_ai"))
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._refresh_operation_controls()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def cancel_text_connection(self) -> None:
        if self._connection_worker is not None:
            self._connection_worker.request_cancel()
            self._set_status(self._tr("settings.cancelling"))

    @Slot()
    def cancel_vision_connection(self) -> None:
        if self._vision_connection_worker is not None:
            self._vision_connection_worker.request_cancel()
            self.vision_ai_status_label.setText(self._tr("settings.cancelling"))

    @Slot()
    def test_google_vision(self) -> None:
        if self.is_google_test_running():
            return
        if self.is_connection_running() or self.is_vision_connection_running() or self.is_download_running():
            self._set_status(self._tr("settings.wait_operation_before_google"))
            return
        try:
            config = self.config_manager.load()
        except ConfigError as exc:
            self.google_vision_status_label.setText(str(exc))
            return
        api_key = (
            config.google_vision_api_key
            if self.config_manager.has_explicit_google_vision_api_key()
            else self.google_vision_api_key_edit.text().strip()
        )
        if not api_key:
            self.google_vision_status_label.setText(
                self._tr("settings.enter_google_api_key")
            )
            return

        self._close_requested = False
        self._google_cancel_event = threading.Event()
        worker = GoogleVisionTestWorker(
            api_key=api_key,
            language=config.ocr_language,
            timeout=min(config.online_ocr_timeout, CONNECTION_TEST_TIMEOUT),
            cancel_event=self._google_cancel_event,
            interface_language=self._interface_language,
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
        self.google_vision_test_button.setText(self._tr("settings.testing"))
        self.google_vision_status_label.setText(self._tr("settings.testing"))
        self._refresh_operation_controls(google_running=True)
        thread.start()

    @Slot()
    def cancel_google_vision_test(self) -> None:
        if self._google_worker is not None:
            self._google_worker.request_cancel()
            self.google_vision_status_label.setText(self._tr("settings.cancelling"))

    @Slot()
    def _on_google_test_success(self) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.google_vision_status_label.setText(
                self._tr("settings.google_connection_success")
            )

    @Slot(str)
    def _on_google_test_failed(self, message: str) -> None:
        if not self._close_requested and not self._shutdown_requested:
            self.google_vision_status_label.setText(message)

    @Slot()
    def _on_google_test_finished(self) -> None:
        self._google_thread = None
        self._google_worker = None
        self._google_cancel_event = None
        self.google_vision_test_button.setText(self._tr("settings.test_google_vision"))
        if self._close_requested or self._shutdown_requested:
            self.hide()
        self._refresh_operation_controls()
        self._maybe_emit_shutdown_ready()

    @Slot()
    def save(self) -> None:
        changed_shortcuts: list[tuple[GlobalHotkeyManager, str, bool, str]] = []
        try:
            config = self._read_config_from_fields()
            requested = (
                (self.hotkey_manager, config.global_shortcut),
                (self.vision_hotkey_manager, config.vision_global_shortcut),
                (self.watch_hotkey_manager, config.watch_global_shortcut),
                (self.context_watch_hotkey_manager, config.context_watch_global_shortcut),
            )
            for manager, shortcut in requested:
                if manager is None or manager.shortcut == shortcut:
                    continue
                changed_shortcuts.append(
                    (
                        manager,
                        manager.shortcut,
                        self._hotkey_is_registered(manager),
                        shortcut,
                    )
                )
            if not self._apply_shortcut_changes(changed_shortcuts):
                self._set_status(self._tr("settings.shortcut_registration_failed"))
                return
            mode_to_save = None
            if not self.config_manager.has_explicit_ocr_mode():
                mode_to_save = config.ocr_mode
            self._capture_provider_editor()
            provider_keys_to_save: dict[str, str] = {}
            provider_endpoints_to_save: dict[str, str] = {}
            for descriptor in AI_PROVIDER_CATALOG:
                provider_id = descriptor.provider_id
                if not self.config_manager.has_explicit_provider_api_key(provider_id):
                    current_key = self._provider_key_values.get(provider_id, "")
                    if current_key != self._loaded_provider_keys.get(provider_id, ""):
                        provider_keys_to_save[provider_id] = current_key
                endpoint_override = getattr(
                    self.config_manager,
                    "has_explicit_provider_base_url",
                    lambda _provider_id: False,
                )
                if not endpoint_override(provider_id):
                    current_endpoint = self._provider_endpoint_values.get(provider_id, "")
                    if current_endpoint != self._loaded_provider_endpoints.get(provider_id, ""):
                        provider_endpoints_to_save[provider_id] = current_endpoint
            google_key_to_save = None
            if not self.config_manager.has_explicit_google_vision_api_key():
                if config.google_vision_api_key != self._loaded_google_vision_api_key:
                    google_key_to_save = config.google_vision_api_key
            self.config_manager.save_settings(
                text_ai_provider=config.text_ai.provider_id,
                text_ai_model=config.text_ai.model_id,
                vision_ai_provider=config.vision_ai.provider_id,
                vision_ai_model=config.vision_ai.model_id,
                request_timeout=config.text_ai.request_timeout,
                provider_api_keys=provider_keys_to_save,
                provider_base_urls=provider_endpoints_to_save,
                global_shortcut=config.global_shortcut,
                vision_global_shortcut=config.vision_global_shortcut,
                watch_global_shortcut=config.watch_global_shortcut,
                context_watch_global_shortcut=config.context_watch_global_shortcut,
                ocr_mode=mode_to_save,
                local_ocr_engine=config.local_ocr_engine,
                online_ocr_provider=config.online_ocr_provider,
                google_vision_api_key=google_key_to_save,
                online_ocr_timeout=config.online_ocr_timeout,
                interface_language=(
                    config.interface_language
                    if config.interface_language != self._loaded_interface_language
                    else None
                ),
                answer_language=(
                    config.answer_language
                    if config.answer_language != self._loaded_answer_language
                    else None
                ),
            )
            changed_auto_watch = self._changed_auto_watch_values()
            if changed_auto_watch:
                self.config_manager.settings_repository.update(changed_auto_watch)
        except (ConfigError, SecretStoreError, OSError, ValueError) as exc:
            self._restore_shortcut_changes(changed_shortcuts)
            self._set_status(str(exc))
            return
        self._set_status(self._tr("settings.saved"))
        self._show_environment_override_warnings()
        self.settings_saved.emit()
        self.close()

    @staticmethod
    def _hotkey_is_registered(manager: GlobalHotkeyManager) -> bool:
        return bool(manager.registered)

    @staticmethod
    def _release_hotkey(manager: GlobalHotkeyManager) -> None:
        manager.unregister()

    @staticmethod
    def _register_hotkey(manager: GlobalHotkeyManager) -> bool:
        return bool(manager.register())

    def _apply_shortcut_changes(
        self,
        changes: list[tuple[GlobalHotkeyManager, str, bool, str]],
    ) -> bool:
        """Claim a changed shortcut set without making a swap collide with itself."""

        if len(changes) > 1:
            for manager, _old_shortcut, was_registered, _new_shortcut in changes:
                if was_registered:
                    self._release_hotkey(manager)

        all_registered = True
        for manager, _old_shortcut, was_registered, new_shortcut in changes:
            if not manager.rebind(new_shortcut):
                all_registered = False
                continue
            if not was_registered:
                self._release_hotkey(manager)

        if all_registered:
            return True
        self._restore_shortcut_changes(changes)
        return False

    def _restore_shortcut_changes(
        self,
        changes: list[tuple[GlobalHotkeyManager, str, bool, str]],
    ) -> None:
        """Restore both shortcut values and their pre-save registration states."""

        for manager, _old_shortcut, _was_registered, _new_shortcut in changes:
            if self._hotkey_is_registered(manager):
                self._release_hotkey(manager)
        for manager, old_shortcut, was_registered, _new_shortcut in reversed(changes):
            if manager.shortcut != old_shortcut:
                if not manager.rebind(old_shortcut):
                    logger.error("failed to rollback shortcut after rebind failure")
                    continue
            if was_registered:
                if not self._hotkey_is_registered(manager) and not self._register_hotkey(manager):
                    logger.error("failed to restore hotkey registration: %s", old_shortcut)
            else:
                self._release_hotkey(manager)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text.strip()))

    def is_connection_running(self) -> bool:
        return self._connection_thread is not None and self._connection_thread.isRunning()

    def is_text_connection_running(self) -> bool:
        return self.is_connection_running()

    def is_vision_connection_running(self) -> bool:
        return (
            self._vision_connection_thread is not None
            and self._vision_connection_thread.isRunning()
        )

    def is_download_running(self) -> bool:
        return self._download_thread is not None and self._download_thread.isRunning()

    def is_google_test_running(self) -> bool:
        return self._google_thread is not None and self._google_thread.isRunning()

    def is_update_check_running(self) -> bool:
        return self._update_check_thread is not None and self._update_check_thread.isRunning()

    def is_update_download_running(self) -> bool:
        return self._update_download_thread is not None and self._update_download_thread.isRunning()

    def has_running_background_operations(self) -> bool:
        return (
            self.is_connection_running()
            or self.is_vision_connection_running()
            or self.is_download_running()
            or self.is_google_test_running()
            or self.is_update_check_running()
            or self.is_update_download_running()
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
        if self.is_vision_connection_running():
            if self._vision_connection_worker is not None:
                self._vision_connection_worker.request_cancel()
        if self.is_google_test_running():
            self.cancel_google_vision_test()
        if self.is_update_check_running() and self._update_check_worker is not None:
            self._update_check_worker.request_cancel()
        if self.is_update_download_running() and self._update_download_worker is not None:
            self._update_download_worker.request_cancel()
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
        if self.is_vision_connection_running():
            if self._vision_connection_worker is not None:
                self._vision_connection_worker.request_cancel()
        if self.is_google_test_running():
            self.cancel_google_vision_test()
        if self.is_update_check_running() and self._update_check_worker is not None:
            self._update_check_worker.request_cancel()
        if self.is_update_download_running() and self._update_download_worker is not None:
            self._update_download_worker.request_cancel()
        if self.has_running_background_operations():
            self.hide()
            event.accept()
            return
        event.accept()
