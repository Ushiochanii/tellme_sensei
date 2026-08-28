from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from app.analysis import AnalysisMode
from app.auto_watch.coordinator import CoordinatorEvent
from app.auto_watch.models import AutoWatchSettings, DetectorFrame, MonitorState, WatchEvent
from app.ui.auto_watch_session import WatchRegion
from app.ui import watch_mini_controller as watch_mini_controller_module
from app.ui.watch_mini_controller import WatchMiniController, place_mini_controller
from app.ui.watch_overlay import WatchOverlay, outside_roi_segments


class _Repo:
    def __init__(self):
        self.calls = 0
        self.settings = AutoWatchSettings(poll_interval_ms=25, analysis_delay_ms=0)
    def auto_watch_settings(self):
        self.calls += 1
        return self.settings


class _Config:
    def __init__(self, repo):
        self.settings_repository = repo
        self.calls = 0
    def load(self, require_api_key=False):
        self.calls += 1
        return object()


class _Timer(QObject):
    timeout = Signal()
    def __init__(self):
        super().__init__(); self.start_count = 0; self.stop_count = 0; self.active = False
    def setInterval(self, _value): pass
    def start(self): self.start_count += 1; self.active = True
    def stop(self): self.stop_count += 1; self.active = False


class _Sampler:
    def __init__(self, timer, image=None, error=None):
        self.timer = timer; self.image = image; self.error = error
    def create_timer(self, _callback): return self.timer
    def sample(self):
        if self.error: raise self.error
        return self.image.copy()


class _Coordinator:
    def __init__(self, callback, event):
        self.callback = callback; self.event = event; self.state = MonitorState.ARMING
        self.generation = 0; self.frames = []; self.pause_count = 0; self.resume_count = 0; self.stop_count = 0
    def start(self): self.state = MonitorState.ARMING
    def tick(self, frame):
        assert isinstance(frame, DetectorFrame); self.frames.append(frame)
        self.generation = self.event.generation
        self.state = MonitorState.WATCHING
        return self.event
    def analyze_now(self):
        self.generation += 1
        self.event = CoordinatorEvent(WatchEvent.NEW_STABLE_FRAME, self.generation, self.event.frame)
        return self.event
    def pause(self): self.pause_count += 1; self.state = MonitorState.PAUSED
    def resume(self): self.resume_count += 1; self.state = MonitorState.ARMING
    def stop(self): self.stop_count += 1; self.state = MonitorState.STOPPED


class _Request:
    def __init__(self, generation, mode, image, session_id):
        self.generation = generation; self.mode = mode; self.image = image
        self.session_id = session_id; self.request_id = f"request-{generation}"


class _Dispatcher:
    def __init__(self):
        self.session_id = "session"; self.active_request = None; self.submissions = []
        self.pause_count = self.resume_count = self.stop_count = 0
        self.on_result = self.on_error = self.on_cancelled = self.on_finished = self.on_observe = None
    def submit(self, image, mode, *, session_id=None, generation=None, **_kwargs):
        request = _Request(generation, AnalysisMode(mode), image, session_id or self.session_id)
        self.submissions.append(request); self.active_request = request
        # Tests control completion explicitly, like a real worker.
        return request
    def pause(self): self.pause_count += 1
    def resume(self): self.resume_count += 1
    def stop(self): self.stop_count += 1


class _Overlay:
    def __init__(self): self.close_count = 0; self.errors = []
    def begin(self): pass
    def close(self): self.close_count += 1
    def set_status(self, *_args, **_kwargs): pass
    def show_error(self, message): self.errors.append(message)


class _Mini(QObject):
    analyze_now_requested = Signal(); pause_requested = Signal(); resume_requested = Signal(); stop_requested = Signal()
    def __init__(self):
        super().__init__(); self.close_count = 0; self.states = []; self.generations = []
    def set_mode(self, _mode): pass
    def show_for(self, *_args): pass
    def set_monitor_state(self, state): self.states.append(state)
    def set_generation(self, generation): self.generations.append(generation)
    def set_analysis_state(self, _state): pass
    def close_from_session(self): self.close_count += 1


def _session(qt_app, mode=AnalysisMode.TEXT, *, active=False, sampler_error=None):
    from app.ui.auto_watch_session import AutoWatchSession
    screen = qt_app.primaryScreen()
    region = WatchRegion.create(screen, QRect(2, 3, 40, 30), f"session-{mode.value}")
    repo = _Repo(); config = _Config(repo); timer = _Timer()
    image = QImage(40, 30, QImage.Format.Format_RGBA8888); image.fill(0xFF112233)
    sampler = _Sampler(timer, image, sampler_error)
    event = CoordinatorEvent(WatchEvent.INITIAL_STABLE_FRAME, 1, DetectorFrame(__import__("numpy").zeros((2, 2), dtype="uint8")))
    coordinator = _Coordinator(None, event)
    dispatcher = _Dispatcher(); overlay = _Overlay(); mini = _Mini()
    if active: dispatcher.active_request = _Request(1, mode, image, region.session_id)
    session = AutoWatchSession(region, mode, config_manager=config, settings_repository=repo,
                               dispatcher=dispatcher, overlay=overlay, mini=mini,
                               sampler_factory=lambda *_args, **_kwargs: sampler,
                               coordinator_factory=lambda _settings, callback: coordinator)
    return session, repo, config, timer, sampler, coordinator, dispatcher, overlay, mini, image


def test_watch_region_uses_screen_local_roi_and_global_coordinates(qt_app: QApplication):
    screen = qt_app.primaryScreen()
    if screen is None:
        return
    geometry = screen.geometry()
    roi = QRect(2, 3, 40, 30)
    region = WatchRegion.create(screen, roi, "session-1")
    assert region.logical_roi == roi
    assert region.global_roi == roi.translated(geometry.topLeft())
    assert region.screen_geometry == geometry
    assert region.session_id == "session-1"


def test_watch_region_invalidates_geometry_or_dpr_snapshot_changes(qt_app: QApplication):
    screen = qt_app.primaryScreen()
    if screen is None:
        return
    region = WatchRegion.create(screen, QRect(2, 3, 40, 30), "snapshot")
    assert region.is_valid()
    from dataclasses import replace
    assert not replace(region, screen=object()).is_valid()
    assert not replace(region, screen_geometry=region.screen_geometry.adjusted(0, 0, 1, 0)).is_valid()
    assert not replace(region, device_pixel_ratio=region.device_pixel_ratio + 0.25).is_valid()


def test_watch_overlay_is_input_transparent_and_does_not_store_image(qt_app):
    screen = qt_app.primaryScreen()
    if screen is None:
        return
    overlay = WatchOverlay(screen, QRect(2, 3, 40, 30))
    overlay.set_status(MonitorState.WATCHING, generation=2)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert not hasattr(overlay, "_screen_image")
    assert overlay.state is MonitorState.WATCHING
    overlay.close()


def test_mini_controller_placement_and_controls(qt_app):
    roi = QRect(-900, 100, 200, 100)
    available = QRect(-1000, 0, 1200, 800)
    placed = place_mini_controller(roi, available, WatchMiniController().sizeHint())
    assert available.contains(placed)
    mini = WatchMiniController()
    events = []
    mini.analyze_now_requested.connect(lambda: events.append("analyze"))
    mini.stop_requested.connect(lambda: events.append("stop"))
    mini.analyze_button.click(); mini.stop_button.click()
    assert events == ["analyze", "stop"]
    mini.adjustSize()
    assert mini.objectName() == "watchMiniController"
    assert mini.surface.objectName() == "watchMiniSurface"
    assert mini.size() == mini.surface.size()
    assert mini.testAttribute(Qt.WA_TranslucentBackground)
    mini.set_monitor_state(MonitorState.WATCHING)
    assert mini.status_label.text() == "Watching"
    mini.set_analysis_state("accepted")
    assert mini.analysis_label.text() == "Waiting to analyze"
    mini.set_analysis_state("started")
    assert mini.analysis_label.text() == "Analyzing…"
    mini.set_analysis_state("finished")
    assert mini.analysis_label.text() == "Last analysis completed"
    mini.set_analysis_state("cancelled")
    assert mini.analysis_label.text() == "Analysis cancelled"
    mini.set_analysis_state("error")
    assert mini.analysis_label.text() == "Analysis failed"
    mini.close_from_session()


def test_mini_controller_keeps_tool_window_visible_on_macos_when_deactivated(qt_app, monkeypatch):
    monkeypatch.setattr(watch_mini_controller_module.sys, "platform", "darwin")
    mini = WatchMiniController()
    assert mini.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    mini.close()
    qt_app.processEvents()


def test_mini_pause_button_switches_between_pause_and_resume(qt_app):
    mini = WatchMiniController()
    events = []
    mini.pause_requested.connect(lambda: events.append("pause"))
    mini.resume_requested.connect(lambda: events.append("resume"))
    mini.set_monitor_state(MonitorState.WATCHING)
    mini.pause_button.click()
    mini.set_monitor_state(MonitorState.PAUSED)
    mini.pause_button.click()
    assert events == ["pause", "resume"]
    mini.close_from_session()


def test_mini_fallback_chooses_smallest_intersection(qt_app):
    roi = QRect(0, 0, 100, 100)
    available = QRect(0, 0, 100, 100)
    placed = place_mini_controller(roi, available, QRect(0, 0, 80, 80).size())
    assert available.contains(placed)


def test_mini_clamps_candidates_before_choosing_zero_overlap():
    available = QRect(0, 0, 300, 300)
    roi = QRect(100, 100, 100, 100)
    placed = place_mini_controller(roi, available, QSize(250, 100))
    assert placed == QRect(50, 200, 250, 100)
    assert not placed.intersects(roi)


def test_overlay_segments_are_outside_roi_and_clipped_at_screen_edges():
    bounds = QRect(0, 0, 300, 200)
    roi = QRect(0, 40, 100, 100)
    segments = outside_roi_segments(roi, bounds, thickness=3)
    assert segments
    assert all(bounds.contains(segment) for segment in segments)
    assert all(not segment.intersects(roi) for segment in segments)
    assert all(segment.left() >= 0 and segment.top() >= 0 for segment in segments)
    assert not any(segment.left() < 0 for segment in segments)


def test_session_snapshots_settings_and_routes_full_resolution_text_and_vision(qt_app):
    for mode in (AnalysisMode.TEXT, AnalysisMode.VISION):
        session, repo, config, timer, sampler, coordinator, dispatcher, overlay, mini, image = _session(qt_app, mode)
        requested = []
        session.analysis_requested.connect(requested.append)
        original = repo.settings
        session.start(); session.tick()
        repo.settings = AutoWatchSettings(poll_interval_ms=999)
        assert repo.calls == 1
        assert config.calls == 1
        assert session.settings is original
        assert coordinator.frames and coordinator.frames[0].pixels.ndim == 2
        assert coordinator.frames[0].pixels.dtype.name == "uint8"
        assert dispatcher.submissions[-1].image.size() == image.size()
        assert dispatcher.submissions[-1].mode is mode
        assert requested[-1].image.size() == image.size()
        dispatcher.active_request = None
        session.stop()


def test_session_pause_resume_analyze_now_and_mini_actions(qt_app):
    session, repo, config, timer, sampler, coordinator, dispatcher, overlay, mini, image = _session(qt_app)
    session.start(); session.tick()
    submissions = len(dispatcher.submissions)
    mini.pause_requested.emit()
    assert not timer.active and dispatcher.pause_count == 1 and dispatcher.stop_count == 0
    mini.resume_requested.emit()
    assert timer.active and coordinator.state is MonitorState.ARMING and dispatcher.resume_count == 1
    mini.analyze_now_requested.emit()
    assert len(dispatcher.submissions) == submissions + 1
    dispatcher.active_request = None
    mini.stop_requested.emit()
    assert not timer.active and overlay.close_count == 1 and mini.close_count == 1
    assert dispatcher.stop_count == 1 and session.region is None


def test_session_stop_waits_for_active_dispatcher_and_is_idempotent(qt_app):
    session, repo, config, timer, sampler, coordinator, dispatcher, overlay, mini, image = _session(qt_app, active=True)
    session.start(); stopped = QSignalSpy(session.session_stopped)
    session.stop(); session.shutdown()
    assert stopped.count() == 0 and session.region is not None
    dispatcher.active_request = None
    assert stopped.wait(1000)
    assert stopped.count() == 1 and session.region is None
    session.stop(); session.shutdown()
    assert stopped.count() == 1 and dispatcher.stop_count == 1


def test_session_fault_pauses_once_and_late_callbacks_are_ignored(qt_app):
    session, repo, config, timer, sampler, coordinator, dispatcher, overlay, mini, image = _session(qt_app, sampler_error=RuntimeError("capture failed"))
    states = []; results = []; errors = []; cancelled = []; finished = []
    session.monitor_state_changed.connect(states.append); session.analysis_result.connect(results.append)
    session.analysis_error.connect(errors.append); session.analysis_cancelled.connect(cancelled.append); session.analysis_finished.connect(finished.append)
    session.start(); session.tick(); session.tick()
    assert not timer.active and len(overlay.errors) == 1
    assert len(states) == 2 and states[-1]["state"] is MonitorState.PAUSED
    session.stop()
    request = _Request(1, AnalysisMode.TEXT, image, "session-text")
    session._on_result(request, object()); session._on_error(request, "late"); session._on_cancelled(request); session._on_finished(request)
    assert results == errors == cancelled == finished == []


def test_session_dpr_fault_stops_polling_once_and_stop_remains_available(qt_app):
    session, repo, config, timer, sampler, coordinator, dispatcher, overlay, mini, image = _session(qt_app)
    from dataclasses import replace
    states = []
    session.monitor_state_changed.connect(states.append)
    session.start()
    session.region = replace(session.region, device_pixel_ratio=session.region.device_pixel_ratio + 0.25)
    session.tick(); session.tick()
    assert not timer.active and len(overlay.errors) == 1
    assert "配置已改变" in overlay.errors[0]
    assert len(states) == 2 and states[-1]["state"] is MonitorState.PAUSED
    dispatcher.active_request = None
    session.stop()
    assert session.region is None and dispatcher.stop_count == 1
