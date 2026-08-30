"""Session-owned Auto Watch lifecycle and screen ROI model."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from app.analysis import AnalysisMode
from app.auto_watch.coordinator import AutoWatchCoordinator, CoordinatorEvent
from app.auto_watch.context_ocr_cache import ContextOCRCache
from app.auto_watch.detector import preprocess_qimage
from app.auto_watch.dispatcher import AnalysisDispatcher, AutoWatchDispatcherBridge
from app.auto_watch.models import MonitorState, WatchRegion
from app.auto_watch.sampler import ScreenSampler
from app.config import ConfigManager
from app.localization import DEFAULT_INTERFACE_LANGUAGE, normalize_language, tr
from app.ocr.local_session import LocalOCRSession
from .watch_overlay import WatchOverlay
from .watch_mini_controller import WatchMiniController

logger = logging.getLogger(__name__)


class AutoWatchSession(QObject):
    analysis_requested = Signal(object)
    analysis_started = Signal(object)
    analysis_result = Signal(object)
    analysis_error = Signal(object)
    analysis_cancelled = Signal(object)
    analysis_finished = Signal(object)
    monitor_state_changed = Signal(object)
    analysis_state_changed = Signal(object)
    session_stopped = Signal()

    def __init__(self, region: WatchRegion, mode: AnalysisMode, *, config_manager=None,
                 settings_repository=None, local_ocr_session=None, dispatcher=None,
                 context_ocr_cache=None,
                 overlay=None, mini=None, sampler_factory=None, timer_factory=None,
                 coordinator_factory=None, worker_factory=None, parent=None):
        super().__init__(parent)
        if not isinstance(region, WatchRegion) or not region.is_valid():
            raise ValueError("invalid watch region")
        self.region, self.mode = region, AnalysisMode(mode)
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
        self._dispatcher_injected = dispatcher is not None
        self.dispatcher = dispatcher or AnalysisDispatcher(
            settings=self.settings, config=config, local_ocr_session=self.local_ocr_session,
            context_ocr_cache=self.context_ocr_cache,
            worker_factory=worker_factory, session_id=region.session_id,
            on_result=self._on_result, on_error=self._on_error,
            on_cancelled=self._on_cancelled, on_finished=self._on_finished,
            on_observe=self._on_observe)
        if dispatcher is not None:
            for name, callback in (("on_result", self._on_result), ("on_error", self._on_error),
                                   ("on_cancelled", self._on_cancelled), ("on_finished", self._on_finished),
                                   ("on_observe", self._on_observe)):
                if hasattr(self.dispatcher, name): setattr(self.dispatcher, name, callback)
        self.bridge = AutoWatchDispatcherBridge(self.dispatcher, self.mode)
        self.sampler_factory = sampler_factory or (lambda screen, roi, settings: ScreenSampler(screen, roi, settings=settings))
        self.timer_factory = timer_factory
        self.coordinator_factory = coordinator_factory or (lambda settings, callback: AutoWatchCoordinator(settings=settings, analysis_callback=callback))
        self.overlay = overlay
        self.mini = mini
        self.timer = self.sampler = self.coordinator = None
        self.latest_image: QImage | None = None
        self._stopped = True
        self._faulted = False
        self._stop_emitted = False
        self._stop_wait_timer = None
        self._cleanup_started = False

    def start(self) -> bool:
        if not self.region.is_valid():
            self._fault(tr("watch.error_screen_changed", self._interface_language))
            return False
        self._stopped = False; self._faulted = False; self._stop_emitted = False; self._cleanup_started = False
        self.sampler = self.sampler_factory(self.region.screen, self.region.logical_roi, self.settings)
        self.coordinator = self.coordinator_factory(self.settings, self._on_coordinator_event)
        self.timer = self.sampler.create_timer(self.tick) if self.timer_factory is None else self.timer_factory()
        if self.timer_factory is not None:
            self.timer.setInterval(self.settings.poll_interval_ms); self.timer.timeout.connect(self.tick)
        self.overlay = self.overlay or WatchOverlay(self.region.screen, self.region.logical_roi)
        self.mini = self.mini or WatchMiniController(
            interface_language=self._interface_language
        )
        self.mini.set_mode(self.mode); self.mini.show_for(self.region.screen, self.region.global_roi)
        self.mini.analyze_now_requested.connect(self.analyze_now)
        self.mini.pause_requested.connect(self.pause)
        self.mini.resume_requested.connect(self.resume)
        self.mini.stop_requested.connect(self.stop)
        if hasattr(self.overlay, "begin"): self.overlay.begin()
        self.coordinator.start(); self.timer.start()
        self._emit_monitor()
        return True

    def tick(self) -> None:
        if self._stopped or self._faulted: return
        if not self.region.is_valid():
            self._fault(tr("watch.error_screen_changed", self._interface_language)); return
        try:
            image = self.sampler.sample()
            if image.isNull() or image.width() <= 0 or image.height() <= 0:
                raise RuntimeError(
                    tr("watch.error_empty_capture", self._interface_language)
                )
            self.latest_image = image.copy()
            event = self.coordinator.tick(preprocess_qimage(self.latest_image, self.settings.max_side))
            self._emit_monitor()
            if event is not None: self._on_coordinator_event(event)
        except Exception as exc:
            self._fault(str(exc))

    def _on_coordinator_event(self, event: CoordinatorEvent) -> None:
        if self._stopped or self.latest_image is None: return
        request = self.bridge.submit_event(event, self.latest_image.copy(), mode=self.mode, session_id=self.region.session_id)
        if request is not None: self.analysis_requested.emit(request)

    def analyze_now(self) -> None:
        if not self._stopped and not self._faulted and self.latest_image is not None:
            event = self.coordinator.analyze_now()
            if event is not None: self._on_coordinator_event(event)

    def pause(self) -> None:
        if self._stopped: return
        self.timer.stop(); self.coordinator.pause(); self.dispatcher.pause(); self._emit_monitor()

    def resume(self) -> None:
        if self._stopped: return
        self.coordinator.resume(); self.dispatcher.resume(); self.timer.start(); self._emit_monitor()

    def stop(self) -> None:
        # Stop is deliberately a full cleanup operation even after a capture
        # fault (fault only pauses polling so the mini Stop remains usable).
        if self._stop_emitted: return
        if self._cleanup_started:
            self._finish_stop_if_ready()
            return
        self._cleanup_started = True
        self._stopped = True
        if self.timer is not None: self.timer.stop()
        if self.coordinator is not None: self.coordinator.stop()
        if self.overlay is not None: self.overlay.close(); self.overlay = None
        if self.mini is not None:
            if hasattr(self.mini, "close_from_session"): self.mini.close_from_session()
            else: self.mini.close()
            self.mini = None
        self.dispatcher.stop(); self.context_ocr_cache.clear(); self.latest_image = None
        if self.dispatcher.active_request is None:
            self.region = None; self._finish_stop()
        else:
            if self._stop_wait_timer is None:
                self._stop_wait_timer = QTimer(self); self._stop_wait_timer.setInterval(10)
                self._stop_wait_timer.timeout.connect(self._finish_stop_if_ready)
            self._stop_wait_timer.start()

    shutdown = stop

    def _finish_stop(self):
        if self._stop_emitted: return
        if self._stop_wait_timer is not None:
            self._stop_wait_timer.stop(); self._stop_wait_timer.deleteLater(); self._stop_wait_timer = None
        self.region = None
        self._stop_emitted = True; self.session_stopped.emit()

    def _finish_stop_if_ready(self):
        if self.dispatcher.active_request is None: self._finish_stop()

    def _fault(self, message):
        if self._faulted or self._stop_emitted: return
        self._faulted = True
        if self.timer is not None: self.timer.stop()
        if self.coordinator is not None: self.coordinator.pause()
        if self.overlay is not None: self.overlay.show_error(message)
        if self.mini is not None:
            self.mini.set_monitor_state(MonitorState.PAUSED)
            self.mini.set_analysis_state("Error")
        self.monitor_state_changed.emit({"state": MonitorState.PAUSED, "error": message, "mode": self.mode})

    def _emit_monitor(self):
        state = self.coordinator.state if self.coordinator else MonitorState.ARMING
        payload = {"state": state, "generation": self.coordinator.generation if self.coordinator else 0, "mode": self.mode}
        self.monitor_state_changed.emit(payload)
        if self.overlay is not None: self.overlay.set_status(state, generation=payload["generation"])
        if self.mini is not None:
            self.mini.set_monitor_state(state); self.mini.set_generation(payload["generation"])

    def _on_observe(self, kind, payload):
        if self._stopped: return
        value = dict(payload or {}); value.update(kind=kind, mode=self.mode)
        self.analysis_state_changed.emit(value)
        if self.mini is not None: self.mini.set_analysis_state(kind)
        signal = {"started": self.analysis_started}.get(kind)
        if signal is not None: signal.emit(value)

    def _on_result(self, request, result):
        if not self._stopped: self.analysis_result.emit({"request": request, "result": result, "mode": self.mode, "generation": request.generation})
    def _on_error(self, request, message):
        if not self._stopped: self.analysis_error.emit({"request": request, "error": message, "mode": self.mode, "generation": request.generation})
    def _on_cancelled(self, request):
        if not self._stopped: self.analysis_cancelled.emit({"request": request, "mode": self.mode, "generation": request.generation})
    def _on_finished(self, request):
        if self._stopped:
            self._finish_stop_if_ready()
            return
        self.analysis_finished.emit({"request": request, "mode": self.mode, "generation": request.generation})
