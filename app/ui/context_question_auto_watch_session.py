"""Session-owned lifecycle for Context + Question Auto Watch."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from app.analysis import AnalysisMode
from app.auto_watch.context_ocr_cache import ContextOCRCache
from app.auto_watch.dispatcher import AnalysisDispatcher, AutoWatchDispatcherBridge
from app.auto_watch.models import ContextQuestionRegions, MonitorState, PairSnapshot
from app.auto_watch.pair_coordinator import PairCoordinator
from app.auto_watch.pair_sampler import ContextQuestionImages, ContextQuestionSampler
from app.config import ConfigManager
from app.localization import DEFAULT_INTERFACE_LANGUAGE, normalize_language, tr
from app.ocr.local_session import LocalOCRSession

from .watch_mini_controller import WatchMiniController
from .watch_overlay import ContextQuestionWatchOverlay

logger = logging.getLogger(__name__)


class ContextQuestionAutoWatchSession(QObject):
    """Own the dual-region monitor without changing Single Region lifecycle."""

    analysis_requested = Signal(object)
    analysis_started = Signal(object)
    analysis_result = Signal(object)
    analysis_ocr_ready = Signal(object)
    # Short alias for integrations that use the event name rather than the
    # more explicit ``analysis_ocr_ready`` name.
    analysis_ocr = analysis_ocr_ready
    analysis_error = Signal(object)
    analysis_cancelled = Signal(object)
    analysis_finished = Signal(object)
    monitor_state_changed = Signal(object)
    analysis_state_changed = Signal(object)
    session_stopped = Signal()

    def __init__(
        self,
        regions: ContextQuestionRegions,
        mode: AnalysisMode,
        *,
        config_manager=None,
        settings_repository=None,
        local_ocr_session=None,
        dispatcher=None,
        context_ocr_cache=None,
        overlay=None,
        mini=None,
        sampler_factory=None,
        timer_factory=None,
        coordinator_factory=None,
        worker_factory=None,
        parent=None,
    ):
        super().__init__(parent)
        if not isinstance(regions, ContextQuestionRegions) or not regions.is_valid():
            raise ValueError("invalid Context + Question regions")
        self.regions, self.mode = regions, AnalysisMode(mode)
        self.config_manager = config_manager or ConfigManager()
        repository = settings_repository or self.config_manager.settings_repository
        self.settings = repository.auto_watch_settings()
        self.local_ocr_session = local_ocr_session or LocalOCRSession()
        if context_ocr_cache is None and dispatcher is not None:
            context_ocr_cache = getattr(dispatcher, "context_ocr_cache", None)
        self.context_ocr_cache = context_ocr_cache or ContextOCRCache()

        config = self.config_manager.load(require_api_key=False)
        self._interface_language = normalize_language(
            getattr(config, "interface_language", DEFAULT_INTERFACE_LANGUAGE),
            default=DEFAULT_INTERFACE_LANGUAGE,
        )
        self.dispatcher = dispatcher or AnalysisDispatcher(
            settings=self.settings,
            config=config,
            local_ocr_session=self.local_ocr_session,
            context_ocr_cache=self.context_ocr_cache,
            worker_factory=worker_factory,
            session_id=regions.session_id,
            on_result=self._on_result,
            on_error=self._on_error,
            on_cancelled=self._on_cancelled,
            on_finished=self._on_finished,
            on_ocr=self._on_ocr,
            on_observe=self._on_observe,
        )
        if dispatcher is not None:
            for name, callback in (
                ("on_result", self._on_result),
                ("on_error", self._on_error),
                ("on_cancelled", self._on_cancelled),
                ("on_finished", self._on_finished),
                ("on_ocr", self._on_ocr),
                ("on_observe", self._on_observe),
            ):
                if hasattr(self.dispatcher, name):
                    setattr(self.dispatcher, name, callback)

        self.bridge = AutoWatchDispatcherBridge(self.dispatcher, self.mode)
        self.sampler_factory = sampler_factory or (
            lambda selected_regions, settings: ContextQuestionSampler(
                selected_regions, settings=settings
            )
        )
        self.timer_factory = timer_factory
        self.coordinator_factory = coordinator_factory or (
            lambda settings, callback: PairCoordinator(
                settings=settings, analysis_callback=callback
            )
        )
        self.overlay = overlay
        self.mini = mini
        self.timer = self.sampler = self.coordinator = None
        self.latest_images: ContextQuestionImages | None = None
        self._stopped = True
        self._faulted = False
        self._stop_emitted = False
        self._stop_wait_timer = None
        self._cleanup_started = False

    @property
    def pair_coordinator(self):
        return self.coordinator

    @property
    def context_question_regions(self):
        return self.regions

    def start(self) -> bool:
        if not self.regions.is_valid():
            self._fault(tr("watch.error_screen_changed", self._interface_language))
            return False
        self._stopped = False
        self._faulted = False
        self._stop_emitted = False
        self._cleanup_started = False
        self.sampler = self.sampler_factory(self.regions, self.settings)
        self.coordinator = self.coordinator_factory(self.settings, self._on_coordinator_event)
        self.timer = self.sampler.create_timer(self.tick) if self.timer_factory is None else self.timer_factory()
        if self.timer_factory is not None:
            self.timer.setInterval(self.settings.poll_interval_ms)
            self.timer.timeout.connect(self.tick)

        if self.overlay is None:
            self.overlay = ContextQuestionWatchOverlay(
                self.regions.screen,
                self.regions.context.logical_roi,
                self.regions.question.logical_roi,
            )
        elif hasattr(self.overlay, "set_regions"):
            # A pre-Start preview is handed to the session; make the
            # ownership transfer also guarantee the formal pair composition.
            self.overlay.set_regions(
                self.regions.screen,
                (
                    self.regions.context.logical_roi,
                    self.regions.question.logical_roi,
                ),
            )
        self.mini = self.mini or WatchMiniController(
            interface_language=self._interface_language
        )
        self.mini.set_mode(self.mode)
        if hasattr(self.mini, "set_region_mode"):
            self.mini.set_region_mode("Context + Question")
        global_rois = (
            self.regions.context.global_roi,
            self.regions.question.global_roi,
        )
        if hasattr(self.mini, "show_for_regions"):
            self.mini.show_for_regions(self.regions.screen, global_rois)
        else:
            self.mini.show_for(self.regions.screen, global_rois[0])
        self.mini.analyze_now_requested.connect(self.analyze_now)
        self.mini.pause_requested.connect(self.pause)
        self.mini.resume_requested.connect(self.resume)
        self.mini.stop_requested.connect(self.stop)
        if hasattr(self.overlay, "begin"):
            self.overlay.begin()
        self.coordinator.start()
        self.timer.start()
        self._emit_monitor()
        return True

    def tick(self) -> None:
        if self._stopped or self._faulted:
            return
        if not self.regions.is_valid():
            self._fault(tr("watch.error_screen_changed", self._interface_language))
            return
        try:
            images = self.sampler.sample()
            if not isinstance(images, ContextQuestionImages):
                raise RuntimeError(
                    tr("watch.error_empty_pair_capture", self._interface_language)
                )
            self.latest_images = images
            event = self.coordinator.tick(images)
            self._emit_monitor()
            if event is not None:
                self._on_coordinator_event(event)
        except Exception as exc:
            self._fault(str(exc))

    def _on_coordinator_event(self, event: PairSnapshot) -> None:
        if self._stopped:
            return
        request = self.bridge.submit_pair_event(
            event,
            mode=self.mode,
            session_id=self.regions.session_id,
        )
        if request is not None:
            self.analysis_requested.emit(request)

    def analyze_now(self) -> None:
        if self._stopped or self._faulted or self.latest_images is None:
            return
        try:
            event = self.coordinator.analyze_now(images=self.latest_images)
        except TypeError:
            # Keep injected deterministic coordinators that expose the
            # zero-argument Phase 1 helper usable in session tests/tools.
            event = self.coordinator.analyze_now()
        if event is not None:
            self._on_coordinator_event(event)
            self._emit_monitor()

    def pause(self) -> None:
        if self._stopped:
            return
        self.timer.stop()
        self.coordinator.pause()
        self.dispatcher.pause()
        self._emit_monitor()

    def resume(self) -> None:
        if self._stopped:
            return
        self.coordinator.resume()
        self.dispatcher.resume()
        self.timer.start()
        self._emit_monitor()

    def stop(self) -> None:
        # A capture fault pauses polling but deliberately leaves Stop usable.
        if self._stop_emitted:
            return
        if self._cleanup_started:
            self._finish_stop_if_ready()
            return
        self._cleanup_started = True
        self._stopped = True
        if self.timer is not None:
            self.timer.stop()
        if self.coordinator is not None:
            self.coordinator.stop()
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        if self.mini is not None:
            if hasattr(self.mini, "close_from_session"):
                self.mini.close_from_session()
            else:
                self.mini.close()
            self.mini = None
        self.dispatcher.stop()
        self.context_ocr_cache.clear()
        self.latest_images = None
        if getattr(self.dispatcher, "active_request", None) is None:
            self._finish_stop()
        else:
            if self._stop_wait_timer is None:
                self._stop_wait_timer = QTimer(self)
                self._stop_wait_timer.setInterval(10)
                self._stop_wait_timer.timeout.connect(self._finish_stop_if_ready)
            self._stop_wait_timer.start()

    shutdown = stop

    def _finish_stop(self) -> None:
        if self._stop_emitted:
            return
        if self._stop_wait_timer is not None:
            self._stop_wait_timer.stop()
            self._stop_wait_timer.deleteLater()
            self._stop_wait_timer = None
        self.regions = None
        self._stop_emitted = True
        self.session_stopped.emit()

    def _finish_stop_if_ready(self) -> None:
        if getattr(self.dispatcher, "active_request", None) is None:
            self._finish_stop()

    def _fault(self, message: str) -> None:
        if self._faulted or self._stop_emitted:
            return
        self._faulted = True
        if self.timer is not None:
            self.timer.stop()
        if self.coordinator is not None:
            self.coordinator.pause()
        if self.overlay is not None:
            self.overlay.show_error(message)
        if self.mini is not None:
            self.mini.set_monitor_state(MonitorState.PAUSED)
            self.mini.set_analysis_state("Error")
        self.monitor_state_changed.emit(
            {
                "state": MonitorState.PAUSED,
                "error": message,
                "mode": self.mode,
                "region_mode": "Context + Question",
            }
        )

    def _emit_monitor(self) -> None:
        state = self.coordinator.state if self.coordinator else MonitorState.ARMING
        generation = self._coordinator_generation()
        payload = {
            "state": state,
            "generation": generation,
            "context_revision": getattr(self.coordinator, "context_revision", 0) if self.coordinator else 0,
            "question_revision": getattr(self.coordinator, "question_revision", 0) if self.coordinator else 0,
            "mode": self.mode,
            "region_mode": "Context + Question",
        }
        self.monitor_state_changed.emit(payload)
        if self.overlay is not None:
            self.overlay.set_status(state, generation=generation)
        if self.mini is not None:
            self.mini.set_monitor_state(state)
            self.mini.set_generation(generation)

    def _coordinator_generation(self) -> int:
        if self.coordinator is None:
            return 0
        return int(getattr(self.coordinator, "pair_generation", getattr(self.coordinator, "generation", 0)))

    def _on_observe(self, kind, payload) -> None:
        if self._stopped:
            return
        value = dict(payload or {})
        value.update(kind=kind, mode=self.mode, region_mode="Context + Question")
        self.analysis_state_changed.emit(value)
        if self.mini is not None:
            self.mini.set_analysis_state(kind)
        if kind == "started":
            self.analysis_started.emit(value)

    def _on_result(self, request, result) -> None:
        if not self._stopped:
            self.analysis_result.emit(
                {
                    "request": request,
                    "result": result,
                    "mode": self.mode,
                    "region_mode": "Context + Question",
                    "generation": request.generation,
                }
            )

    def _on_error(self, request, message) -> None:
        if not self._stopped:
            self.analysis_error.emit(
                {
                    "request": request,
                    "error": message,
                    "mode": self.mode,
                    "region_mode": "Context + Question",
                    "generation": request.generation,
                }
            )

    def _on_ocr(self, request, stage, text) -> None:
        if not self._stopped:
            self.analysis_ocr_ready.emit(
                {
                    "request": request,
                    "stage": stage,
                    "text": text,
                    "mode": self.mode,
                    "region_mode": "Context + Question",
                    "generation": request.generation,
                }
            )

    def _on_cancelled(self, request) -> None:
        if not self._stopped:
            self.analysis_cancelled.emit(
                {
                    "request": request,
                    "mode": self.mode,
                    "region_mode": "Context + Question",
                    "generation": request.generation,
                }
            )

    def _on_finished(self, request) -> None:
        if self._stopped:
            self._finish_stop_if_ready()
            return
        self.analysis_finished.emit(
            {
                "request": request,
                "mode": self.mode,
                "region_mode": "Context + Question",
                "generation": request.generation,
            }
        )


ContextQuestionWatchSession = ContextQuestionAutoWatchSession

__all__ = ["ContextQuestionAutoWatchSession", "ContextQuestionWatchSession"]
