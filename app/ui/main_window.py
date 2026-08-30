"""GUI pipeline coordinator used by the floating controller and tray mode."""

from __future__ import annotations

import inspect
import logging
import uuid
from enum import Enum
from pathlib import Path

import threading

from PySide6.QtCore import QThread, Qt, QTimer, Signal, Slot
from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
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
    WATCH_ACCENT,
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


class AutoWatchSelectionPhase(Enum):
    """The small UI-owned state machine between a Watch entry and its session."""

    IDLE = "idle"
    SELECTING_SINGLE = "selecting_single"
    SELECTING_CONTEXT = "selecting_context"
    SELECTING_QUESTION = "selecting_question"
    ACTIVE = "active"


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
        watch_hotkey_manager: GlobalHotkeyManager | None = None,
        context_watch_hotkey_manager: GlobalHotkeyManager | None = None,
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
        self.watch_hotkey_manager = watch_hotkey_manager
        self.context_watch_hotkey_manager = context_watch_hotkey_manager
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
        self._auto_watch_fake = auto_watch_fake
        self._auto_watch_restore_visible = False
        self._auto_watch_session_id = None
        self._auto_watch_generation = 0
        self._auto_watch_region = None
        self._auto_watch_regions = None
        self._auto_watch_context_region = None
        self._auto_watch_question_region = None
        self._auto_watch_selection_phase = AutoWatchSelectionPhase.IDLE
        self._auto_watch_selection_generation = 0
        self._auto_watch_workflow_mode: AnalysisMode | None = None
        self.setWindowTitle("TellMeSensei")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setObjectName("mainController")
        # Keep the launcher's established size; the four-card entry grid and
        # compact status strip deliberately reuse this footprint.
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

        mode_layout = QGridLayout()
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setHorizontalSpacing(10)
        mode_layout.setVerticalSpacing(10)
        mode_layout.setColumnStretch(0, 1)
        mode_layout.setColumnStretch(1, 1)
        self.text_mode_button = ModeButton(
            "Text / OCR",
            "Text extraction",
            mode_icon("text", TEXT_ACCENT),
            TEXT_ACCENT,
        )
        self.text_mode_button.setObjectName("textModeButton")
        self.text_mode_button.setProperty("mode", AnalysisMode.TEXT.value)
        self.text_mode_button.clicked.connect(self.start_text_capture)
        self.vision_mode_button = ModeButton(
            "Vision",
            "Visual analysis",
            mode_icon("vision", VISION_ACCENT),
            VISION_ACCENT,
        )
        self.vision_mode_button.setObjectName("visionModeButton")
        self.vision_mode_button.setProperty("mode", AnalysisMode.VISION.value)
        self.vision_mode_button.clicked.connect(self.start_vision_capture)
        self.watch_mode_button = ModeButton(
            "Watch",
            "Single region",
            mode_icon("watch", WATCH_ACCENT),
            WATCH_ACCENT,
        )
        self.watch_mode_button.setObjectName("watchModeButton")
        self.watch_mode_button.setProperty("mode", "watch")
        self.context_watch_mode_button = ModeButton(
            "Context Watch",
            "Context + question",
            mode_icon("context_watch", WATCH_ACCENT),
            WATCH_ACCENT,
        )
        self.context_watch_mode_button.setObjectName("contextWatchModeButton")
        self.context_watch_mode_button.setProperty("mode", "context_watch")
        self._entry_buttons = (
            self.text_mode_button,
            self.vision_mode_button,
            self.watch_mode_button,
            self.context_watch_mode_button,
        )
        for button in self._entry_buttons:
            button.setObjectName(button.objectName())
            button.setProperty("class", "modeButton")
            button.setMinimumHeight(88)
            button.setMaximumHeight(92)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.text_mode_button.setToolTip("Capture a question for text extraction")
        self.vision_mode_button.setToolTip("Capture a question for visual analysis")
        self.watch_mode_button.setToolTip("Watch one screen region for new questions")
        self.context_watch_mode_button.setToolTip(
            "Watch a context region and a question region"
        )
        mode_layout.addWidget(self.text_mode_button, 0, 0)
        mode_layout.addWidget(self.vision_mode_button, 0, 1)
        mode_layout.addWidget(self.watch_mode_button, 1, 0)
        mode_layout.addWidget(self.context_watch_mode_button, 1, 1)
        self.watch_mode_button.clicked.connect(self.start_watch)
        self.context_watch_mode_button.clicked.connect(self.start_context_watch)
        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setProperty("fluentRole", "statusBar")
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.status_label.setMinimumHeight(36)
        self.status_label.setMaximumHeight(40)
        self._set_status(AppState.IDLE)

        layout.addLayout(header)
        self.auto_watch_main_view = QWidget(self)
        main_view_layout = QVBoxLayout(self.auto_watch_main_view)
        main_view_layout.setContentsMargins(0, 0, 0, 0)
        mode_view = QWidget(self.auto_watch_main_view)
        mode_view.setObjectName("modeCardGrid")
        mode_view.setLayout(mode_layout)
        main_view_layout.addWidget(mode_view)
        main_view_layout.addStretch(1)
        layout.addWidget(self.auto_watch_main_view, 1)
        layout.addWidget(self.status_label)
        QWidget.setTabOrder(self.settings_button, self.text_mode_button)
        QWidget.setTabOrder(self.text_mode_button, self.vision_mode_button)
        QWidget.setTabOrder(self.vision_mode_button, self.watch_mode_button)
        QWidget.setTabOrder(self.watch_mode_button, self.context_watch_mode_button)

    def _set_capture_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable both direct mode capture controls together."""

        for button in getattr(self, "_entry_buttons", ()):
            button.setEnabled(enabled and not self._auto_watch_active)

    def _auto_watch_entry_allowed(self) -> bool:
        """Return whether a new Watch workflow may claim the capture surface."""

        return not any(
            (
                self._shutting_down,
                self._auto_watch_active,
                self._auto_watch_session is not None,
                self._auto_watch_selection_phase is not AutoWatchSelectionPhase.IDLE,
                self._auto_watch_selection_overlay is not None,
                self._overlay is not None,
                self._busy,
                self.state is not AppState.IDLE,
            )
        )

    def _read_auto_watch_analysis_mode(self) -> AnalysisMode:
        """Read the shared launch preference, safely defaulting old settings to Text."""

        repository = self.config_manager.settings_repository
        try:
            getter = getattr(repository, "auto_watch_analysis_mode", None)
            value = getter() if callable(getter) else repository.load().get(
                "auto_watch_analysis_mode", AnalysisMode.TEXT.value
            )
            return AnalysisMode(value)
        except (AttributeError, TypeError, ValueError):
            logger.warning("invalid Auto Watch analysis mode; using Text")
            return AnalysisMode.TEXT
        except Exception:
            logger.exception("failed to read Auto Watch analysis mode; using Text")
            return AnalysisMode.TEXT

    def _set_auto_watch_status(self, message: str) -> None:
        """Expose a concise selection error through the controller status strip."""

        self.status_label.setText(f"●  {message}")
        self.status_label.setProperty("state", "error")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _begin_auto_watch_workflow(self, phase: AutoWatchSelectionPhase) -> bool:
        """Claim the controller and begin the first direct-selection overlay."""

        if not self._auto_watch_entry_allowed():
            logger.info("Auto Watch entry ignored: application busy")
            return False
        if not self._ensure_screen_recording_permission():
            return False

        self._auto_watch_workflow_mode = self._read_auto_watch_analysis_mode()
        self._auto_watch_restore_visible = self.isVisible()
        self._auto_watch_context_region = None
        self._auto_watch_question_region = None
        self._auto_watch_regions = None
        if self.isVisible():
            self.hide()
        return self._begin_auto_watch_selection(phase)

    def _begin_auto_watch_selection(self, phase: AutoWatchSelectionPhase) -> bool:
        """Create exactly one selection overlay for the current workflow stage."""

        if phase not in (
            AutoWatchSelectionPhase.SELECTING_SINGLE,
            AutoWatchSelectionPhase.SELECTING_CONTEXT,
            AutoWatchSelectionPhase.SELECTING_QUESTION,
        ):
            return False
        if phase is AutoWatchSelectionPhase.SELECTING_QUESTION and self._auto_watch_context_region is None:
            self._abort_auto_watch_workflow("Context selection is no longer available.")
            return False
        if self._shutting_down or self._auto_watch_active or self._overlay is not None or self._busy:
            return False
        if not self._ensure_screen_recording_permission():
            self._abort_auto_watch_workflow()
            return False

        try:
            overlay = CaptureOverlay()
        except Exception as exc:
            logger.exception("failed to create Auto Watch selection overlay")
            self._abort_auto_watch_workflow(str(exc))
            return False

        self._auto_watch_selection_generation += 1
        generation = self._auto_watch_selection_generation
        self._auto_watch_selection_overlay = overlay
        self._auto_watch_selection_phase = phase
        try:
            overlay.captured.connect(
                lambda image, expected=overlay, token=generation:
                self._on_auto_watch_capture(image, expected, token)
            )
            overlay.cancelled.connect(
                lambda expected=overlay, token=generation:
                self._on_auto_watch_selection_cancelled(expected, token)
            )
            overlay.begin()
        except Exception as exc:
            logger.exception("failed to begin Auto Watch selection overlay")
            self._abort_auto_watch_workflow(str(exc))
            return False
        return True

    def _is_current_auto_watch_selection(
        self,
        overlay,
        generation: int | None,
    ) -> bool:
        return (
            not self._shutting_down
            and self._auto_watch_selection_phase
            in (
                AutoWatchSelectionPhase.SELECTING_SINGLE,
                AutoWatchSelectionPhase.SELECTING_CONTEXT,
                AutoWatchSelectionPhase.SELECTING_QUESTION,
            )
            and overlay is self._auto_watch_selection_overlay
            and (
                generation is None
                or generation == self._auto_watch_selection_generation
            )
        )

    def _abort_auto_watch_workflow(self, reason: str | None = None) -> None:
        """Close selection UI and clear every pending value before re-entry."""

        overlay = self._auto_watch_selection_overlay
        self._auto_watch_selection_overlay = None
        self._auto_watch_selection_generation += 1
        self._auto_watch_selection_phase = AutoWatchSelectionPhase.IDLE
        self._auto_watch_context_region = None
        self._auto_watch_question_region = None
        self._auto_watch_regions = None
        self._auto_watch_workflow_mode = None
        restore_visible = self._auto_watch_restore_visible
        self._auto_watch_restore_visible = False
        if overlay is not None:
            try:
                overlay.close()
            except Exception:
                logger.exception("failed to close Auto Watch selection overlay")

        self.auto_watch_main_view.show()
        if self._shutting_down:
            self._set_capture_controls_enabled(False)
            return
        self._restore_idle()
        if restore_visible:
            self.show()
            self.raise_()
            self.activateWindow()
        if reason:
            self._set_auto_watch_status(reason)

    def _on_auto_watch_selection_cancelled(
        self,
        overlay=None,
        generation: int | None = None,
    ) -> bool:
        if not self._is_current_auto_watch_selection(overlay, generation):
            return False
        self._abort_auto_watch_workflow()
        return True

    def _cleanup_failed_auto_watch_session(
        self,
        session,
        reason: str | None = None,
    ) -> None:
        """Stop a partially-created session before returning to an idle controller."""

        if self._auto_watch_session is session:
            self._auto_watch_session = None
            self._auto_watch_active = False
            self._auto_watch_session_id = None
            self._auto_watch_generation = 0
            self._auto_watch_region = None
            self._auto_watch_regions = None
        cleanup = getattr(session, "shutdown", None) or getattr(session, "stop", None)
        try:
            if callable(cleanup):
                cleanup()
        except Exception:
            logger.exception("failed to clean up Auto Watch session after start failure")
        self._abort_auto_watch_workflow(reason)

    @staticmethod
    def _same_auto_watch_screen(first, second) -> bool:
        if first is second:
            return True
        try:
            return bool(first == second)
        except Exception:
            return False

    def _start_single_region_session(self, region: WatchRegion) -> bool:
        mode = self._auto_watch_workflow_mode or AnalysisMode.TEXT
        worker_factory = (
            (lambda request: _AutoWatchFakeHandle(request))
            if self._auto_watch_fake
            else None
        )
        session = None
        try:
            session = AutoWatchSession(
                region,
                mode,
                config_manager=self.config_manager,
                local_ocr_session=self._local_ocr_session,
                worker_factory=worker_factory,
            )
            return self._activate_auto_watch_session(session, region, None)
        except Exception as exc:
            logger.exception("failed to create Auto Watch session")
            if session is not None:
                self._cleanup_failed_auto_watch_session(session, str(exc))
            else:
                self._abort_auto_watch_workflow(str(exc))
            return False

    def _start_context_question_session(
        self,
        regions: ContextQuestionRegions,
    ) -> bool:
        mode = self._auto_watch_workflow_mode or AnalysisMode.TEXT
        worker_factory = (
            (lambda request: _AutoWatchFakeHandle(request))
            if self._auto_watch_fake
            else None
        )
        session = None
        try:
            session = ContextQuestionAutoWatchSession(
                regions,
                mode,
                config_manager=self.config_manager,
                local_ocr_session=self._local_ocr_session,
                worker_factory=worker_factory,
            )
            return self._activate_auto_watch_session(session, regions, regions)
        except Exception as exc:
            logger.exception("failed to create Context + Question Auto Watch session")
            if session is not None:
                self._cleanup_failed_auto_watch_session(session, str(exc))
            else:
                self._abort_auto_watch_workflow(str(exc))
            return False

    def _activate_auto_watch_session(self, session, region_identity, regions) -> bool:
        self._auto_watch_session = session
        self._auto_watch_session_id = region_identity.session_id
        self._auto_watch_regions = regions
        self._auto_watch_region = region_identity if isinstance(region_identity, WatchRegion) else None
        try:
            self._connect_auto_watch_signals(session, region_identity)
            started = session.start()
        except Exception as exc:
            self._cleanup_failed_auto_watch_session(session, str(exc))
            return False
        if not started:
            self._cleanup_failed_auto_watch_session(session, "Unable to start Auto Watch.")
            return False

        self._auto_watch_selection_overlay = None
        self._auto_watch_selection_phase = AutoWatchSelectionPhase.ACTIVE
        self._auto_watch_context_region = None
        self._auto_watch_question_region = None
        self._auto_watch_active = True
        self._set_state(AppState.IDLE)
        self.auto_watch_main_view.hide()
        self._set_capture_controls_enabled(False)
        if not self.tray_mode:
            self.hide()
        return True

    def _on_auto_watch_capture(
        self,
        _image,
        overlay=None,
        generation: int | None = None,
    ) -> bool:
        if overlay is None:
            overlay = self._auto_watch_selection_overlay
        if not self._is_current_auto_watch_selection(overlay, generation):
            return False

        phase = self._auto_watch_selection_phase
        self._auto_watch_selection_overlay = None
        try:
            screen, roi = overlay.selection_metadata
        except Exception as exc:
            logger.exception("Auto Watch selection metadata failed")
            self._abort_auto_watch_workflow(str(exc))
            return False
        try:
            overlay.close()
        except Exception:
            logger.exception("failed to close completed Auto Watch selection overlay")

        if phase is AutoWatchSelectionPhase.SELECTING_SINGLE:
            try:
                region = WatchRegion.create(screen, roi)
            except (TypeError, ValueError) as exc:
                self._abort_auto_watch_workflow(str(exc))
                return False
            return self._start_single_region_session(region)

        if phase is AutoWatchSelectionPhase.SELECTING_CONTEXT:
            try:
                self._auto_watch_context_region = WatchRegion.create(screen, roi)
                self._auto_watch_question_region = None
                self._auto_watch_regions = None
            except (TypeError, ValueError) as exc:
                self._abort_auto_watch_workflow(str(exc))
                return False
            # The valid Context is intentionally retained only while the
            # immediately-following Question overlay is active.
            return self._begin_auto_watch_selection(
                AutoWatchSelectionPhase.SELECTING_QUESTION
            )

        if phase is AutoWatchSelectionPhase.SELECTING_QUESTION:
            context = self._auto_watch_context_region
            try:
                if context is None:
                    raise ValueError("Please select the Context region first.")
                if not self._same_auto_watch_screen(context.screen, screen):
                    raise ValueError(
                        "Context and Question must be on the same display. "
                        "Please select the Question region again."
                    )
                question = WatchRegion.create(screen, roi, context.session_id)
                regions = ContextQuestionRegions.create(context, question)
                self._auto_watch_question_region = question
                self._auto_watch_regions = regions
            except (TypeError, ValueError) as exc:
                if context is None:
                    self._abort_auto_watch_workflow(str(exc))
                    return False
                # Same-screen validation is the sole recoverable selection
                # failure. Keep Context transiently and immediately retry.
                self._set_auto_watch_status(str(exc))
                self._begin_auto_watch_selection(
                    AutoWatchSelectionPhase.SELECTING_QUESTION
                )
                return False
            return self._start_context_question_session(regions)

        self._abort_auto_watch_workflow("Auto Watch selection is no longer active.")
        return False

    def _on_auto_watch_stopped(self):
        session = self._auto_watch_session
        session_overlay = getattr(session, "overlay", None) if session is not None else None
        if session_overlay is not None:
            # Real sessions close and release this overlay themselves.  The
            # extra idempotent close also covers injected session doubles.
            session_overlay.close()
        if self._answer_window is not None and self._auto_watch_session is not None:
            self._answer_window.end_auto_watch()
        self._auto_watch_session = None
        self._auto_watch_active = False
        self._auto_watch_session_id = None
        self._auto_watch_generation = 0
        self._auto_watch_region = None
        self._auto_watch_regions = None
        self._auto_watch_context_region = None
        self._auto_watch_question_region = None
        self._auto_watch_workflow_mode = None
        self._auto_watch_selection_phase = AutoWatchSelectionPhase.IDLE
        self._auto_watch_selection_generation += 1
        if not self._shutting_down:
            self.auto_watch_main_view.show()
            self._restore_idle()
            if self._auto_watch_restore_visible and not self.tray_mode:
                self.show()
                self.raise_()
        self._auto_watch_restore_visible = False

    def _connect_auto_watch_signals(self, session, region) -> None:
        """Connect one session's callbacks with immutable session identity guards."""
        expected_id = region.session_id
        callbacks = {
            "analysis_requested": lambda payload, s=session, sid=expected_id: self._on_auto_watch_requested(s, sid, payload),
            "analysis_started": lambda payload, s=session, sid=expected_id: self._on_auto_watch_started(s, sid, payload),
            "analysis_result": lambda payload, s=session, sid=expected_id: self._on_auto_watch_result(s, sid, payload),
            "analysis_ocr_ready": lambda payload, s=session, sid=expected_id: self._on_auto_watch_ocr(s, sid, payload),
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

    def _on_auto_watch_ocr(self, session, expected_id, payload):
        checked = self._auto_watch_payload(session, expected_id, payload)
        if checked is None or checked[1] != self._auto_watch_generation:
            return
        request, generation = checked
        if not isinstance(payload, dict) or payload.get("stage") not in {"context", "question"}:
            return
        answer = self._auto_watch_answer(payload.get("mode", request.mode), generation)
        answer.show_auto_watch_ocr(generation, payload["stage"], payload.get("text", ""))

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

    def refresh_shortcut_labels(self) -> None:
        """Compatibility hook; card footers are stable feature descriptions."""

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

        if (
            self._shutting_down
            or self._auto_watch_active
            or self._auto_watch_selection_phase is not AutoWatchSelectionPhase.IDLE
            or self._auto_watch_selection_overlay is not None
            or self.state is not AppState.IDLE
            or self._busy
            or self._overlay is not None
        ):
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

        if self._auto_watch_selection_phase is not AutoWatchSelectionPhase.IDLE:
            self._abort_auto_watch_workflow()

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

    @Slot()
    def start_watch(self, _checked: bool = False) -> bool:
        """Start the canonical direct-selection Single Region workflow."""

        return self._begin_auto_watch_workflow(
            AutoWatchSelectionPhase.SELECTING_SINGLE
        )

    @Slot()
    def start_context_watch(self, _checked: bool = False) -> bool:
        """Start the canonical direct-selection Context + Question workflow."""

        return self._begin_auto_watch_workflow(
            AutoWatchSelectionPhase.SELECTING_CONTEXT
        )

    def show_settings(self) -> None:
        """Show one reusable SettingsWindow from the system tray."""

        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                config_manager=self.config_manager,
                hotkey_manager=self.hotkey_manager,
                vision_hotkey_manager=self.vision_hotkey_manager,
                watch_hotkey_manager=self.watch_hotkey_manager,
                context_watch_hotkey_manager=self.context_watch_hotkey_manager,
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
