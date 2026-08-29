"""GUI pipeline coordinator used by the floating controller and tray mode."""

from __future__ import annotations

import inspect
import logging
import uuid
from pathlib import Path

import threading

from PySide6.QtCore import QThread, Qt, QTimer, Signal, Slot
from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import (
    QHBoxLayout,
    QButtonGroup,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QRadioButton,
    QWidget,
)

from app.analysis import AnalysisMode
from app.ocr.types import OCRLine, OCRResult
from app.pipeline import ContextQuestionPipelineResult, PipelineResult
from app.capture.overlay import CaptureOverlay
from app.config import ConfigError, ConfigManager
from app.local_ocr.component_manager import LocalOCRComponentManager
from app.ocr.factory import create_ocr_provider
from app.ocr.local_session import LocalOCRSession
from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import DEFAULT_SHORTCUT, DEFAULT_VISION_SHORTCUT
from app.platform import screen_permissions
from app.services.deepseek_service import DeepSeekService
from app.state import AppState
from app.thread_info import current_thread_info
from app.ui.answer_window import AnswerWindow
from app.ui.settings_window import SettingsWindow
from app.ui.theme import (
    SECONDARY_TEXT,
    TEXT_ACCENT,
    VISION_ACCENT,
    ModeButton,
    controller_stylesheet,
    mode_icon,
    settings_icon,
)
from app.workers.processing_worker import ProcessingWorker
from app.workers.local_ocr_prewarm_worker import LocalOCRPrewarmWorker
from app.workers.vision_processing_worker import VisionProcessingWorker
from app.auto_watch.models import ContextQuestionRegions, WatchRegion
from app.ui.auto_watch_session import AutoWatchSession
from app.ui.context_question_auto_watch_session import ContextQuestionAutoWatchSession
from app.ui.watch_mini_controller import WatchMiniController

logger = logging.getLogger(__name__)


class _AutoWatchFakeHandle(QObject):
    """Local-only handle used by the manual UI demo; never calls a provider."""
    result_ready = Signal(object)
    error_occurred = Signal(str)
    finished = Signal()
    cancelled = Signal()

    def __init__(self, request=None):
        super().__init__()
        self.request = request
        self._started = False
        self._done = False
        self._cancelled = False

    def start(self):
        if self._done or self._started:
            return
        self._started = True
        QTimer.singleShot(0, self._emit_fake_result)

    def _emit_fake_result(self):
        if self._done:
            return
        generation = getattr(self.request, "generation", None)
        mode = getattr(self.request, "mode", None)
        if mode is AnalysisMode.VISION:
            result = "Fake Vision answer"
        elif hasattr(self.request, "context_image"):
            result = ContextQuestionPipelineResult(
                context_ocr=OCRResult("Fake OCR context", (OCRLine("Fake OCR context"),)),
                question_ocr=OCRResult("Fake OCR question", (OCRLine("Fake OCR question"),)),
                answer="Fake OCR answer",
                context_revision=getattr(self.request, "context_revision", 1),
                question_revision=getattr(self.request, "question_revision", 1),
            )
        else:
            result = PipelineResult(
                ocr=OCRResult("Fake OCR question", (OCRLine("Fake OCR question"),)),
                answer="Fake OCR answer",
            )
        self.result_ready.emit(result)
        self._done = True
        self.finished.emit()

    def request_cancel(self):
        if self._done or self._cancelled:
            return
        self._cancelled = True
        self.cancelled.emit()
        self._done = True
        self.finished.emit()


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
        vision_hotkey_manager: GlobalHotkeyManager | None = None,
        local_ocr_session: LocalOCRSession | None = None,
        component_manager: LocalOCRComponentManager | None = None,
        auto_watch_fake: bool = False,
    ) -> None:
        super().__init__()
        self.debug_capture_path = debug_capture_path
        self.tray_mode = tray_mode
        self.config_manager = config_manager or ConfigManager()
        self.hotkey_manager = hotkey_manager
        self.vision_hotkey_manager = vision_hotkey_manager
        self._local_ocr_session = local_ocr_session or LocalOCRSession()
        self._component_manager = component_manager or LocalOCRComponentManager()
        self.state = AppState.IDLE
        self._shutting_down = False
        self._overlay: CaptureOverlay | None = None
        self._auto_watch_selection_overlay: CaptureOverlay | None = None
        self._answer_window: AnswerWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self.processing_thread: QThread | None = None
        self.processing_worker: ProcessingWorker | VisionProcessingWorker | None = None
        self._active_job_id: str | None = None
        self._cancelled_job_id: str | None = None
        self._busy = False
        self._screen_permission_request_attempted = False
        self._last_ocr_text = ""
        self._last_vision_image: QImage | None = None
        self._capture_mode = AnalysisMode.TEXT
        self._active_mode = AnalysisMode.TEXT
        self._shutdown_ready_emitted = False
        self._prewarm_thread: QThread | None = None
        self._prewarm_worker: LocalOCRPrewarmWorker | None = None
        self._prewarm_cancel_event: threading.Event | None = None
        self._auto_watch_session = None
        self._auto_watch_active = False
        self._auto_watch_in_setup = False
        self._auto_watch_fake = auto_watch_fake
        self._auto_watch_restore_visible = False
        self._auto_watch_session_id = None
        self._auto_watch_generation = 0
        self._auto_watch_region = None
        self._auto_watch_regions = None
        self._auto_watch_context_region = None
        self._auto_watch_question_region = None
        self._auto_watch_region_mode = "single"
        self.setWindowTitle("TellMeSensei")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setObjectName("mainController")
        # Keep the launcher's established size; setup rows are compact so the
        # new Region Mode controls fit without changing Single Region layout.
        self.setFixedSize(340, 330)
        self.setStyleSheet(controller_stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("TellMeSensei")
        title.setObjectName("titleLabel")
        settings_button = QPushButton()
        settings_button.setObjectName("settingsButton")
        settings_button.setToolTip("Settings")
        settings_button.setAccessibleName("Settings")
        settings_button.setIcon(QIcon(settings_icon()))
        settings_button.clicked.connect(self.show_settings)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(settings_button)
        self.settings_button = settings_button

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(10)
        text_shortcut, vision_shortcut = self._configured_shortcuts()
        self.text_mode_button = ModeButton(
            "Text / OCR",
            text_shortcut,
            mode_icon("text", TEXT_ACCENT),
            TEXT_ACCENT,
        )
        self.text_mode_button.setObjectName("textModeButton")
        self.text_mode_button.setProperty("mode", AnalysisMode.TEXT.value)
        self.text_mode_button.clicked.connect(self.start_text_capture)
        self.vision_mode_button = ModeButton(
            "Vision",
            vision_shortcut,
            mode_icon("vision", VISION_ACCENT),
            VISION_ACCENT,
        )
        self.vision_mode_button.setObjectName("visionModeButton")
        self.vision_mode_button.setProperty("mode", AnalysisMode.VISION.value)
        self.vision_mode_button.clicked.connect(self.start_vision_capture)
        for button in (self.text_mode_button, self.vision_mode_button):
            button.setObjectName(button.objectName())
            button.setProperty("class", "modeButton")
            button.setMinimumHeight(108)
            button.setToolTip("Text / OCR capture" if button is self.text_mode_button else "Vision capture")
            mode_layout.addWidget(button)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self._set_status(AppState.IDLE)

        layout.addLayout(header)
        self.auto_watch_main_view = QWidget(self)
        main_view_layout = QVBoxLayout(self.auto_watch_main_view)
        main_view_layout.setContentsMargins(0, 0, 0, 0)
        mode_view = QWidget(self.auto_watch_main_view)
        mode_view.setLayout(mode_layout)
        main_view_layout.addWidget(mode_view)
        self.auto_watch_button = QPushButton("Auto Watch")
        self.auto_watch_button.setObjectName("autoWatchButton")
        self.auto_watch_button.clicked.connect(self.enter_auto_watch_setup)
        main_view_layout.addWidget(self.auto_watch_button)
        layout.addWidget(self.auto_watch_main_view)
        self.auto_watch_setup = QWidget(self)
        setup_layout = QVBoxLayout(self.auto_watch_setup)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(6)
        self.auto_watch_text_radio = QRadioButton("Text / OCR", self.auto_watch_setup)
        self.auto_watch_vision_radio = QRadioButton("Vision", self.auto_watch_setup)
        self.auto_watch_text_radio.setChecked(True)
        self.auto_watch_analysis_mode_group = QButtonGroup(self)
        self.auto_watch_analysis_mode_group.setExclusive(True)
        self.auto_watch_analysis_mode_group.addButton(self.auto_watch_text_radio)
        self.auto_watch_analysis_mode_group.addButton(self.auto_watch_vision_radio)
        analysis_row = QHBoxLayout()
        analysis_row.addWidget(QLabel("Analysis Mode"))
        analysis_row.addWidget(self.auto_watch_text_radio)
        analysis_row.addWidget(self.auto_watch_vision_radio)
        analysis_row.addStretch(1)
        setup_layout.addLayout(analysis_row)

        self.auto_watch_single_region_radio = QRadioButton("Single Region", self.auto_watch_setup)
        self.auto_watch_context_question_radio = QRadioButton("Context + Question", self.auto_watch_setup)
        self.auto_watch_single_region_radio.setChecked(True)
        self.auto_watch_region_mode_group = QButtonGroup(self)
        self.auto_watch_region_mode_group.setExclusive(True)
        self.auto_watch_region_mode_group.addButton(self.auto_watch_single_region_radio)
        self.auto_watch_region_mode_group.addButton(self.auto_watch_context_question_radio)
        self.auto_watch_single_region_radio.toggled.connect(self._on_auto_watch_region_mode_changed)
        self.auto_watch_context_question_radio.toggled.connect(self._on_auto_watch_region_mode_changed)
        region_mode_row = QHBoxLayout()
        region_mode_row.addWidget(QLabel("Region Mode"))
        region_mode_row.addWidget(self.auto_watch_single_region_radio)
        region_mode_row.addWidget(self.auto_watch_context_question_radio)
        region_mode_row.addStretch(1)
        setup_layout.addLayout(region_mode_row)

        self.auto_watch_context_selection_status = QLabel("Context: Not selected", self.auto_watch_setup)
        self.auto_watch_question_selection_status = QLabel("Question: Not selected", self.auto_watch_setup)
        self.auto_watch_context_status = self.auto_watch_context_selection_status
        self.auto_watch_question_status = self.auto_watch_question_selection_status
        selection_status_row = QHBoxLayout()
        selection_status_row.addWidget(self.auto_watch_context_selection_status)
        selection_status_row.addWidget(self.auto_watch_question_selection_status)
        selection_status_row.addStretch(1)
        setup_layout.addLayout(selection_status_row)
        self.auto_watch_select_button = QPushButton("Select Region")
        self.auto_watch_start_button = QPushButton("Start Auto Watch")
        self.auto_watch_back_button = QPushButton("Back")
        self.auto_watch_setup_status = QLabel("Region is kept for this session only.")
        self.auto_watch_setup_status.setWordWrap(True)
        setup_layout.addWidget(self.auto_watch_select_button)
        setup_layout.addWidget(self.auto_watch_start_button)
        setup_layout.addWidget(self.auto_watch_back_button)
        setup_layout.addWidget(self.auto_watch_setup_status)
        self.auto_watch_select_button.clicked.connect(self.start_auto_watch_selection)
        self.auto_watch_start_button.clicked.connect(self.start_context_question_auto_watch)
        self.auto_watch_back_button.clicked.connect(self.exit_auto_watch_setup)
        layout.addWidget(self.auto_watch_setup)
        self.auto_watch_setup.hide()
        layout.addWidget(self.status_label)
        self._update_auto_watch_setup()

    def _set_capture_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable both direct mode capture controls together."""

        self.text_mode_button.setEnabled(enabled)
        self.vision_mode_button.setEnabled(enabled)
        if hasattr(self, "auto_watch_button"): self.auto_watch_button.setEnabled(enabled and not self._auto_watch_active)

    def _is_context_question_mode(self) -> bool:
        return self.auto_watch_context_question_radio.isChecked()

    def _on_auto_watch_region_mode_changed(self, checked: bool) -> None:
        if not checked:
            return
        self._auto_watch_region_mode = "context_question" if self._is_context_question_mode() else "single"
        if self._auto_watch_region_mode == "single":
            self._clear_context_question_selection()
        self._update_auto_watch_setup()

    def _clear_context_question_selection(self) -> None:
        self._auto_watch_context_region = None
        self._auto_watch_question_region = None
        self._auto_watch_regions = None

    def _update_auto_watch_setup(self) -> None:
        dual = self._is_context_question_mode()
        context_selected = self._auto_watch_context_region is not None
        question_selected = self._auto_watch_question_region is not None
        self.auto_watch_context_selection_status.setVisible(dual)
        self.auto_watch_question_selection_status.setVisible(dual)
        if dual:
            self.auto_watch_context_selection_status.setText(
                "Context: ✓ Selected" if context_selected else "Context: Not selected"
            )
            self.auto_watch_question_selection_status.setText(
                "Question: ✓ Selected" if question_selected else "Question: Not selected"
            )
            self.auto_watch_select_button.setText(
                "Select Context" if not context_selected else "Select Question"
            )
            self.auto_watch_select_button.setVisible(not question_selected)
            self.auto_watch_start_button.setVisible(True)
            self.auto_watch_start_button.setEnabled(context_selected and question_selected)
        else:
            self.auto_watch_select_button.setText("Select Region")
            self.auto_watch_select_button.setVisible(True)
            self.auto_watch_start_button.setVisible(False)
            self.auto_watch_start_button.setEnabled(False)
        self.auto_watch_select_button.setEnabled(
            not self._auto_watch_active
            and self._auto_watch_selection_overlay is None
            and (not dual or not question_selected)
        )

    def enter_auto_watch_setup(self):
        if self._auto_watch_active or self._auto_watch_selection_overlay is not None:
            return False
        self._clear_context_question_selection()
        self._auto_watch_region_mode = "single"
        self.auto_watch_single_region_radio.setChecked(True)
        self._auto_watch_in_setup = True
        self.auto_watch_setup_status.setText("Region is kept for this session only.")
        self._update_auto_watch_setup()
        self.auto_watch_main_view.hide(); self.auto_watch_setup.show()
        self._set_capture_controls_enabled(False)
        return True

    def exit_auto_watch_setup(self):
        if self._auto_watch_selection_overlay is not None:
            self._auto_watch_selection_overlay.close()
            self._auto_watch_selection_overlay = None
        self._clear_context_question_selection()
        self._auto_watch_region_mode = "single"
        self.auto_watch_single_region_radio.setChecked(True)
        self._auto_watch_in_setup = False
        self.auto_watch_setup.hide(); self.auto_watch_main_view.show(); self._restore_idle()

    def start_auto_watch_selection(self):
        if (self._shutting_down or self._auto_watch_active or self._overlay is not None
                or self._auto_watch_selection_overlay is not None or self._busy
                or not self._auto_watch_in_setup
                or (self._is_context_question_mode() and self._auto_watch_question_region is not None)
                or not self._ensure_screen_recording_permission()):
            return False
        try:
            self._auto_watch_selection_overlay = CaptureOverlay()
        except Exception as exc:
            self.auto_watch_setup_status.setText(str(exc)); return False
        self._auto_watch_selection_overlay.captured.connect(self._on_auto_watch_capture)
        self._auto_watch_selection_overlay.cancelled.connect(self._on_auto_watch_selection_cancelled)
        self._update_auto_watch_setup()
        self._auto_watch_selection_overlay.begin(); return True

    def _on_auto_watch_selection_cancelled(self):
        self._auto_watch_selection_overlay = None
        self._auto_watch_in_setup = True
        self._update_auto_watch_setup()
        self.auto_watch_setup.show(); self.auto_watch_main_view.hide()

    def _cleanup_failed_auto_watch_session(self, session) -> None:
        cleanup = getattr(session, "shutdown", None) or getattr(session, "stop", None)
        try:
            if callable(cleanup):
                cleanup()
        except Exception:
            logger.exception("failed to clean up Auto Watch session after start failure")
        finally:
            self._auto_watch_session = None
            self._auto_watch_in_setup = True
            self._update_auto_watch_setup()
            self.auto_watch_setup.show(); self.auto_watch_main_view.hide()

    @staticmethod
    def _same_auto_watch_screen(first, second) -> bool:
        if first is second:
            return True
        try:
            return bool(first == second)
        except Exception:
            return False

    def _on_context_question_capture(self, screen, roi) -> bool:
        context = self._auto_watch_context_region
        if context is None:
            try:
                context = WatchRegion.create(screen, roi, uuid.uuid4().hex)
            except (TypeError, ValueError) as exc:
                self.auto_watch_setup_status.setText(str(exc))
                return False
            self._auto_watch_context_region = context
            self.auto_watch_setup_status.setText("Context selected. Please select the Question region.")
            self._update_auto_watch_setup()
            return True

        if not self._same_auto_watch_screen(context.screen, screen):
            self._update_auto_watch_setup()
            self.auto_watch_setup_status.setText(
                "Context and Question must be on the same display.\n"
                "Please select the Question region again."
            )
            return False
        try:
            question = WatchRegion.create(screen, roi, context.session_id)
            regions = ContextQuestionRegions.create(context, question)
        except (TypeError, ValueError) as exc:
            self._update_auto_watch_setup()
            self.auto_watch_setup_status.setText(str(exc))
            return False
        self._auto_watch_question_region = question
        self._auto_watch_regions = regions
        self._update_auto_watch_setup()
        self.auto_watch_setup_status.setText("Context and Question selected. Start Auto Watch when ready.")
        return True

    def _start_single_region_session(self, region: WatchRegion) -> bool:
        mode = AnalysisMode.VISION if self.auto_watch_vision_radio.isChecked() else AnalysisMode.TEXT
        worker_factory = (lambda request: _AutoWatchFakeHandle(request)) if self._auto_watch_fake else None
        session = AutoWatchSession(
            region,
            mode,
            config_manager=self.config_manager,
            local_ocr_session=self._local_ocr_session,
            worker_factory=worker_factory,
        )
        return self._activate_auto_watch_session(session, region, None)

    def start_context_question_auto_watch(self) -> bool:
        if (not self._auto_watch_in_setup or not self._is_context_question_mode()
                or self._auto_watch_regions is None or self._auto_watch_active
                or self._auto_watch_selection_overlay is not None or self._busy):
            return False
        mode = AnalysisMode.VISION if self.auto_watch_vision_radio.isChecked() else AnalysisMode.TEXT
        worker_factory = (lambda request: _AutoWatchFakeHandle(request)) if self._auto_watch_fake else None
        session = None
        try:
            session = ContextQuestionAutoWatchSession(
                self._auto_watch_regions,
                mode,
                config_manager=self.config_manager,
                local_ocr_session=self._local_ocr_session,
                worker_factory=worker_factory,
            )
            return self._activate_auto_watch_session(session, self._auto_watch_regions, self._auto_watch_regions)
        except Exception as exc:
            if session is not None:
                self._cleanup_failed_auto_watch_session(session)
            self.auto_watch_setup_status.setText(str(exc))
            self._auto_watch_in_setup = True
            self.auto_watch_setup.show(); self.auto_watch_main_view.hide()
            return False

    _start_context_question_watch = start_context_question_auto_watch

    def _activate_auto_watch_session(self, session, region_identity, regions) -> bool:
        self._auto_watch_session = session
        self._auto_watch_session_id = region_identity.session_id
        self._auto_watch_regions = regions
        self._auto_watch_region = region_identity if isinstance(region_identity, WatchRegion) else None
        self._connect_auto_watch_signals(session, region_identity)
        try:
            started = session.start()
        except Exception as exc:
            self._cleanup_failed_auto_watch_session(session)
            self.auto_watch_setup_status.setText(str(exc))
            return False
        if not started:
            self._cleanup_failed_auto_watch_session(session)
            self.auto_watch_setup_status.setText("Unable to start Auto Watch.")
            return False
        self._auto_watch_restore_visible = self.isVisible()
        self._auto_watch_active = True
        self._auto_watch_in_setup = False
        self.auto_watch_main_view.hide(); self.auto_watch_setup.hide(); self._set_capture_controls_enabled(False)
        if not self.tray_mode:
            self.hide()
        return True

    def _on_auto_watch_capture(self, _image):
        overlay = self._auto_watch_selection_overlay; self._auto_watch_selection_overlay = None
        if overlay is None:
            return False
        try:
            screen, roi = overlay.selection_metadata
            if self._is_context_question_mode():
                return self._on_context_question_capture(screen, roi)
            region = WatchRegion.create(screen, roi)
            return self._start_single_region_session(region)
        except Exception as exc:
            logger.exception("Auto Watch selection failed")
            self.auto_watch_setup_status.setText(str(exc))
            self._auto_watch_in_setup = True
            self._update_auto_watch_setup()
            self.auto_watch_setup.show(); self.auto_watch_main_view.hide()
            return False

    def _on_auto_watch_stopped(self):
        if self._answer_window is not None and self._auto_watch_session is not None:
            self._answer_window.end_auto_watch()
        self._auto_watch_session = None; self._auto_watch_active = False
        self._auto_watch_session_id = None; self._auto_watch_generation = 0
        self._auto_watch_region = None; self._auto_watch_regions = None
        self._clear_context_question_selection()
        if not self._shutting_down:
            self.auto_watch_main_view.show(); self.auto_watch_setup.hide(); self._restore_idle()
            if self._auto_watch_restore_visible and not self.tray_mode:
                self.show(); self.raise_()
        self._auto_watch_restore_visible = False

    def _connect_auto_watch_signals(self, session, region) -> None:
        """Connect one session's callbacks with immutable session identity guards."""
        expected_id = region.session_id
        callbacks = {
            "analysis_requested": lambda payload, s=session, sid=expected_id: self._on_auto_watch_requested(s, sid, payload),
            "analysis_started": lambda payload, s=session, sid=expected_id: self._on_auto_watch_started(s, sid, payload),
            "analysis_result": lambda payload, s=session, sid=expected_id: self._on_auto_watch_result(s, sid, payload),
            "analysis_error": lambda payload, s=session, sid=expected_id: self._on_auto_watch_error(s, sid, payload),
            "analysis_cancelled": lambda payload, s=session, sid=expected_id: self._on_auto_watch_cancelled(s, sid, payload),
            "analysis_finished": lambda payload, s=session, sid=expected_id: self._on_auto_watch_finished(s, sid, payload),
            "session_stopped": lambda s=session, sid=expected_id: self._on_auto_watch_session_stopped(s, sid),
        }
        for name, callback in callbacks.items():
            signal = getattr(session, name, None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(callback)

    def _auto_watch_payload(self, session, expected_id, payload):
        if self._auto_watch_session is not session or self._auto_watch_session_id != expected_id:
            return None
        request = payload if hasattr(payload, "generation") else (payload or {}).get("request")
        generation = getattr(request, "generation", None)
        if generation is None:
            generation = (payload or {}).get("generation")
        session_id = getattr(request, "session_id", None)
        if session_id is None:
            session_id = (payload or {}).get("session_id") or (payload or {}).get("session")
        if session_id != expected_id or not isinstance(generation, int):
            return None
        return request, generation

    def _auto_watch_answer(self, mode, generation):
        region = self._auto_watch_region
        regions = self._auto_watch_regions
        if regions is not None:
            avoid_rois = [regions.context.global_roi, regions.question.global_roi]
            screen = regions.screen
            begin_pair = lambda answer: answer.begin_auto_watch(
                mode,
                generation,
                screen=screen,
                avoid_rois=avoid_rois,
                region_mode="Context + Question",
            )
        else:
            roi = region.global_roi if region is not None else None
            screen = region.screen if region is not None else None
            begin_pair = lambda answer: answer.begin_auto_watch(mode, generation, roi, screen)
        if self._answer_window is None:
            self._show_or_create_answer()
            begin_pair(self._answer_window)
        elif not getattr(self._answer_window, "_auto_watch_active", False):
            begin_pair(self._answer_window)
        return self._answer_window

    def _on_auto_watch_requested(self, session, expected_id, payload):
        checked = self._auto_watch_payload(session, expected_id, payload)
        if checked is None:
            return
        request, generation = checked
        if generation < self._auto_watch_generation:
            return
        self._auto_watch_generation = generation
        answer = self._auto_watch_answer(request.mode, generation)
        answer.show_auto_watch_analyzing(generation)

    def _on_auto_watch_started(self, session, expected_id, payload):
        checked = self._auto_watch_payload(session, expected_id, payload)
        if checked is None or checked[1] != self._auto_watch_generation:
            return
        request, generation = checked
        answer = self._auto_watch_answer(getattr(request, "mode", self._active_mode), generation)
        answer.show_auto_watch_analyzing(generation)

    def _on_auto_watch_result(self, session, expected_id, payload):
        checked = self._auto_watch_payload(session, expected_id, payload)
        if checked is None or checked[1] != self._auto_watch_generation:
            return
        request, generation = checked
        answer = self._auto_watch_answer(payload.get("mode", request.mode), generation)
        answer.show_auto_watch_result(generation, payload.get("result"))

    def _on_auto_watch_error(self, session, expected_id, payload):
        checked = self._auto_watch_payload(session, expected_id, payload)
        if checked is None or checked[1] != self._auto_watch_generation:
            return
        _request, generation = checked
        self._auto_watch_answer(payload.get("mode", self._active_mode), generation).show_auto_watch_error(generation, payload.get("error", "Unknown error"))

    def _on_auto_watch_cancelled(self, session, expected_id, payload):
        checked = self._auto_watch_payload(session, expected_id, payload)
        if checked is None or checked[1] != self._auto_watch_generation:
            return
        _request, generation = checked
        if self._answer_window is not None:
            self._answer_window.show_auto_watch_cancelled(generation)

    def _on_auto_watch_finished(self, session, expected_id, payload):
        checked = self._auto_watch_payload(session, expected_id, payload)
        if checked is None or checked[1] != self._auto_watch_generation:
            return

    def _on_auto_watch_session_stopped(self, session, expected_id):
        if self._auto_watch_session is not session or self._auto_watch_session_id != expected_id:
            return
        self._on_auto_watch_stopped()

    def _set_state(self, state: AppState) -> None:
        self.state = state
        self._set_status(state)

    def _set_status(self, state: AppState) -> None:
        labels = {
            AppState.IDLE: "●  Ready",
            AppState.CAPTURING: "●  Capturing…",
            AppState.OCR_PROCESSING: "●  Processing…",
            AppState.AI_PROCESSING: "●  Processing…",
            AppState.CANCELLING: "●  Cancelling…",
            AppState.ERROR: "●  Ready",
        }
        self.status_label.setText(labels[state])
        self.status_label.setProperty("state", "ready" if state is AppState.IDLE else "busy")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _set_selected_mode(self, mode: AnalysisMode) -> None:
        self._active_mode = mode
        self.text_mode_button.setProperty("selected", mode is AnalysisMode.TEXT)
        self.vision_mode_button.setProperty("selected", mode is AnalysisMode.VISION)
        self.text_mode_button.style().unpolish(self.text_mode_button)
        self.text_mode_button.style().polish(self.text_mode_button)
        self.vision_mode_button.style().unpolish(self.vision_mode_button)
        self.vision_mode_button.style().polish(self.vision_mode_button)

    def _configured_shortcuts(self) -> tuple[str, str]:
        """Use registered hotkeys first, then config/default values for display."""

        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError:
            config = None
        try:
            text = self.hotkey_manager.shortcut if self.hotkey_manager is not None else None
        except (AttributeError, NotImplementedError):
            text = None
        try:
            vision = (
                self.vision_hotkey_manager.shortcut
                if self.vision_hotkey_manager is not None
                else None
            )
        except (AttributeError, NotImplementedError):
            vision = None
        text = text or getattr(config, "global_shortcut", DEFAULT_SHORTCUT)
        vision = vision or getattr(config, "vision_global_shortcut", DEFAULT_VISION_SHORTCUT)
        return text, vision

    def refresh_shortcut_labels(self) -> None:
        """Refresh the two visible shortcut pills after settings are saved."""

        text, vision = self._configured_shortcuts()
        self.text_mode_button.set_shortcut(text)
        self.vision_mode_button.set_shortcut(vision)

    @Slot()
    def start_capture(self) -> bool:
        """Backward-compatible Text Mode capture entry point."""

        return self.start_text_capture()

    @Slot()
    def start_text_capture(self) -> bool:
        """Start one Text Mode capture."""

        self._set_selected_mode(AnalysisMode.TEXT)
        return self._start_capture(AnalysisMode.TEXT)

    @Slot()
    def start_vision_capture(self) -> bool:
        """Start one Vision Mode capture using the shared overlay."""

        self._set_selected_mode(AnalysisMode.VISION)
        return self._start_capture(AnalysisMode.VISION)

    def _start_capture(self, mode: AnalysisMode) -> bool:
        """Start one explicitly selected capture mode unless the app is busy."""

        if (self._shutting_down or self._auto_watch_active or self._auto_watch_in_setup or self._auto_watch_selection_overlay is not None
                or self.auto_watch_setup.isVisible() or self.state is not AppState.IDLE
                or self._busy or self._overlay is not None):
            logger.info("capture ignored: application busy")
            return False

        if not self._ensure_screen_recording_permission():
            return False

        logger.info("capture requested mode=%s", mode.value)
        self._capture_mode = mode
        self._set_state(AppState.CAPTURING)
        self._busy = True
        self._set_capture_controls_enabled(False)
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
            self._answer_window.set_mode(mode)
            self._answer_window.show_at_current_screen()
            self._answer_window.show_error(f"无法开始截图：{exc}")
            return False

        self._overlay.captured.connect(self._on_capture)
        self._overlay.cancelled.connect(self._on_capture_cancelled)
        self._overlay.begin()
        return True

    def _ensure_screen_recording_permission(self) -> bool:
        """Check permission before changing capture state or creating an overlay."""

        try:
            if screen_permissions.has_screen_recording_permission():
                return True
            if not self._screen_permission_request_attempted:
                self._screen_permission_request_attempted = True
                logger.info("screen capture permission request initiated")
                screen_permissions.request_screen_recording_permission()
                if screen_permissions.has_screen_recording_permission():
                    return True
            logger.info("screen capture permission unavailable")
        except Exception:
            logger.exception("screen capture permission check failed")
        self._show_screen_recording_permission_error()
        return False

    def _show_screen_recording_permission_error(self) -> None:
        QMessageBox.warning(
            None,
            "Screen Recording Permission Required",
            "TellMeSensei needs Screen Recording permission to capture the screen.\n\n"
            "Please enable TellMeSensei in:\n"
            "System Settings / System Preferences\n"
            "→ Privacy & Security\n"
            "→ Screen Recording\n\n"
            "Then restart TellMeSensei.",
            QMessageBox.StandardButton.Ok,
        )

    @Slot()
    def request_shutdown(self) -> None:
        """Request non-blocking shutdown and emit when the worker is stopped."""

        if self._shutting_down:
            return
        self._shutting_down = True
        self._busy = True
        self._set_capture_controls_enabled(False)

        if self._auto_watch_selection_overlay is not None:
            self._auto_watch_selection_overlay.close()
            self._auto_watch_selection_overlay = None

        if self._auto_watch_session is not None:
            self._auto_watch_session.session_stopped.connect(self._continue_shutdown_after_watch)
            self._auto_watch_session.stop()
            return

        self._continue_shutdown_after_watch()

    def _continue_shutdown_after_watch(self) -> None:
        """Continue the existing shutdown chain after Auto Watch cleanup."""

        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

        if self._settings_window is not None:
            self._settings_window.request_shutdown()

        if self._answer_window is not None:
            self._answer_window.close()

        self._cancel_local_ocr_prewarm()

        thread = self.processing_thread
        if thread is not None and thread.isRunning():
            self._set_state(AppState.CANCELLING)
            if self._answer_window is not None:
                self._answer_window.set_cancelling()
            if self.processing_worker is not None:
                self.processing_worker.request_cancel()
            logger.info("shutdown waiting for processing thread to finish")
            self._local_ocr_session.stop()
            return

        if self._settings_window is not None and self._settings_window.has_running_background_operations():
            logger.info("shutdown waiting for settings background operations to finish")
            self._local_ocr_session.stop()
            return

        if self._prewarm_thread is not None and self._prewarm_thread.isRunning():
            logger.info("shutdown waiting for Local OCR prewarm to finish")
            return

        self._local_ocr_session.stop()
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
        mode = self._capture_mode
        self._set_selected_mode(mode)
        self._active_mode = mode
        self._set_state(AppState.OCR_PROCESSING if mode is AnalysisMode.TEXT else AppState.AI_PROCESSING)
        self._set_capture_controls_enabled(False)
        self._last_ocr_text = ""
        self._last_vision_image = image.copy() if mode is AnalysisMode.VISION else None
        if not self.tray_mode:
            self.show()
            self.raise_()
        self._show_or_create_answer()
        self._answer_window.set_mode(mode)
        if mode is AnalysisMode.VISION:
            self._answer_window.show_vision_processing()
            self._launch_vision_worker(image.copy())
        else:
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

        try:
            factory_parameters = inspect.signature(create_ocr_provider).parameters
        except (TypeError, ValueError):
            factory_parameters = {}
        if "local_ocr_session" in factory_parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in factory_parameters.values()
        ):
            ocr_provider = create_ocr_provider(
                config,
                local_ocr_session=self._local_ocr_session,
            )
        else:
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

    def _launch_vision_worker(self, image: QImage) -> None:
        """Launch the direct image-to-DeepSeek Vision worker without OCR."""

        job_id = uuid.uuid4().hex
        logger.info("start_vision_processing called job_id=%s [%s]", job_id, current_thread_info())
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError as exc:
            self._answer_window.show_error(str(exc))
            self._restore_idle()
            self.processing_finished.emit()
            return

        deepseek_service = DeepSeekService(config)
        thread = QThread(self)
        thread.setObjectName("VisionProcessingThread")
        thread.setProperty("processing_job_id", job_id)
        worker = VisionProcessingWorker(image, deepseek_service, job_id)
        worker.moveToThread(thread)

        thread.started.connect(self._on_thread_started)
        thread.started.connect(worker.run)
        worker.job_ai_started.connect(self._on_ai_started)
        worker.job_result_ready.connect(self._on_vision_result)
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
        logger.info("Vision QThread.start called job_id=%s [%s]", job_id, current_thread_info())

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
        self._set_state(AppState.OCR_PROCESSING)
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
        self._set_state(AppState.AI_PROCESSING)
        if self._answer_window is not None:
            if self._active_mode is AnalysisMode.VISION:
                self._answer_window.set_vision_ai_processing()
            else:
                self._answer_window.set_ai_processing()

    @Slot(str, object)
    def _on_result(self, job_id: str, result) -> None:
        if not self._is_active_job(job_id, "result_ready"):
            return
        if self._answer_window is not None:
            self._answer_window.set_ocr_text(result.ocr.text)
            self._answer_window.set_result(result.answer)

    @Slot(str, str)
    def _on_vision_result(self, job_id: str, answer: str) -> None:
        if not self._is_active_job(job_id, "vision_result_ready"):
            return
        if self._answer_window is not None:
            self._answer_window.set_result(answer)

    @Slot(str, str)
    def _on_error(self, job_id: str, message: str | None = None) -> None:
        if message is None:
            message = job_id
            job_id = self._active_job_id
            if job_id is None:
                self._set_state(AppState.ERROR)
                if self._answer_window is not None:
                    self._answer_window.show_error(message)
                return
        if not self._is_active_job(job_id, "error"):
            return
        self._set_state(AppState.ERROR)
        if self._answer_window is not None:
            self._answer_window.show_error(message)

    @Slot(str)
    def _on_cancelled(self, job_id: str) -> None:
        if not self._is_active_job(job_id, "cancelled"):
            return
        self._cancelled_job_id = job_id
        self._set_state(AppState.CANCELLING)
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
        self._set_state(AppState.IDLE)
        self._set_capture_controls_enabled(True)
        if self._answer_window is not None:
            if self._cancelled_job_id == job_id:
                self._answer_window.show_cancelled()
            self._answer_window.set_retry_enabled()
        self._cancelled_job_id = None
        self.processing_finished.emit()
        self._stop_local_session_if_online()
        if self._shutting_down:
            self._maybe_emit_shutdown_ready()

    @Slot()
    def _on_settings_shutdown_ready(self) -> None:
        self._maybe_emit_shutdown_ready()

    def _maybe_emit_shutdown_ready(self) -> None:
        if self._shutting_down:
            if self.processing_thread is not None and self.processing_thread.isRunning():
                return
            if self._settings_window is not None and self._settings_window.has_running_background_operations():
                return
            if self._prewarm_thread is not None and self._prewarm_thread.isRunning():
                return
            if self._auto_watch_session is not None:
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
        self._set_state(AppState.CANCELLING)
        if self._answer_window is not None:
            self._answer_window.set_cancelling()
        self.processing_worker.request_cancel()

    @Slot()
    def _retry_analysis(self) -> None:
        can_retry = self._active_mode is AnalysisMode.VISION and self._last_vision_image is not None
        can_retry = can_retry or (self._active_mode is AnalysisMode.TEXT and bool(self._last_ocr_text))
        if self._busy or self.state is not AppState.IDLE or not can_retry:
            logger.info("capture ignored: application busy")
            return
        self._busy = True
        self._set_state(AppState.AI_PROCESSING)
        if self._answer_window is not None:
            if self._active_mode is AnalysisMode.VISION:
                self._answer_window.set_vision_ai_processing()
            else:
                self._answer_window.set_ai_processing()
        if self._active_mode is AnalysisMode.VISION:
            self._launch_vision_worker(self._last_vision_image.copy())
        else:
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
        if self._active_mode is AnalysisMode.VISION:
            self.start_vision_capture()
        else:
            self.start_text_capture()

    @Slot()
    def _on_answer_closed(self) -> None:
        answer = self._answer_window
        self._answer_window = None
        if answer is not None:
            answer.deleteLater()
        self._last_vision_image = None
        if self._auto_watch_active:
            return
        if not self.tray_mode and not self._shutting_down:
            self.show()
            self.raise_()
            self.activateWindow()

    def show_launcher(self) -> None:
        """Show the persistent floating capture controller."""

        self.show()
        self.raise_()
        self.activateWindow()

    def show_settings(self) -> None:
        """Show one reusable SettingsWindow from the system tray."""

        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                config_manager=self.config_manager,
                hotkey_manager=self.hotkey_manager,
                vision_hotkey_manager=self.vision_hotkey_manager,
                component_manager=self._component_manager,
                local_ocr_session=self._local_ocr_session,
            )
            self._settings_window.shutdown_ready.connect(self._on_settings_shutdown_ready)
            self._settings_window.settings_saved.connect(self._on_settings_saved)
            self._settings_window.local_ocr_component_changed.connect(
                self._on_local_ocr_component_changed
            )
        self._settings_window.reload_values()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _restore_idle(self) -> None:
        self._busy = False
        self._set_state(AppState.IDLE)
        self._set_capture_controls_enabled(True)

    @Slot()
    def _on_settings_saved(self) -> None:
        self.refresh_shortcut_labels()
        self._schedule_or_stop_local_ocr()

    @Slot()
    def _on_local_ocr_component_changed(self) -> None:
        self._schedule_or_stop_local_ocr()

    @Slot()
    def request_local_ocr_prewarm(self) -> None:
        """Schedule one conditional, lazy Local OCR initialization."""

        if self._shutting_down:
            return
        if self._prewarm_thread is not None:
            return
        if self._local_ocr_session.is_running() or self._local_ocr_session.capability_unsupported:
            return
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError:
            return
        if config.ocr_provider != "local" or not self._component_manager.is_installed():
            return

        cancel_event = threading.Event()
        worker = LocalOCRPrewarmWorker(self._local_ocr_session, cancel_event)
        thread = QThread(self)
        thread.setObjectName("LocalOCRPrewarmThread")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_local_ocr_prewarm_succeeded)
        worker.failed.connect(self._on_local_ocr_prewarm_failed)
        worker.cancelled.connect(self._on_local_ocr_prewarm_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_local_ocr_prewarm_finished)
        self._prewarm_cancel_event = cancel_event
        self._prewarm_worker = worker
        self._prewarm_thread = thread
        logger.info("local OCR prewarm scheduled")
        thread.start()

    def _cancel_local_ocr_prewarm(self) -> None:
        if self._prewarm_worker is not None:
            self._prewarm_worker.request_cancel()
        self._local_ocr_session.stop()

    @Slot()
    def _on_local_ocr_prewarm_succeeded(self) -> None:
        logger.info("local OCR prewarm ready")

    @Slot(str)
    def _on_local_ocr_prewarm_failed(self, message: str) -> None:
        logger.warning("Local OCR prewarm failed: %s", message or "UnknownError")

    @Slot()
    def _on_local_ocr_prewarm_cancelled(self) -> None:
        logger.info("local OCR prewarm cancelled")

    @Slot()
    def _on_local_ocr_prewarm_finished(self) -> None:
        self._prewarm_thread = None
        self._prewarm_worker = None
        self._prewarm_cancel_event = None
        if self._shutting_down:
            self._maybe_emit_shutdown_ready()

    def _schedule_or_stop_local_ocr(self) -> None:
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError:
            return
        if config.ocr_provider == "local":
            QTimer.singleShot(0, self.request_local_ocr_prewarm)
        else:
            self._cancel_local_ocr_prewarm()

    def _stop_local_session_if_online(self) -> None:
        if self._local_ocr_session.is_busy():
            return
        try:
            config = self.config_manager.load(require_api_key=False)
        except ConfigError:
            return
        if config.ocr_provider != "local":
            self._local_ocr_session.stop()

    def shutdown(self) -> None:
        """Backward-compatible alias for the non-blocking shutdown request."""

        self.request_shutdown()
        if self._answer_window is not None:
            self._answer_window.close()
            self._answer_window = None
