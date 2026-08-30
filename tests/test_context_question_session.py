from types import SimpleNamespace

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QColor, QImage

from app.analysis import AnalysisMode
from app.auto_watch.models import (
    AutoWatchSettings,
    ContextQuestionRegions,
    PairSnapshot,
    WatchRegion,
    MonitorState,
)
from app.auto_watch.pair_sampler import ContextQuestionImages
from app.ui.context_question_auto_watch_session import ContextQuestionAutoWatchSession


class _Repo:
    def __init__(self):
        self.settings = AutoWatchSettings(poll_interval_ms=25)

    def auto_watch_settings(self):
        return self.settings


class _Config:
    def __init__(self, repository):
        self.settings_repository = repository

    def load(self):
        return object()


class _Timer(QObject):
    timeout = Signal()

    def __init__(self):
        super().__init__()
        self.active = False
        self.start_count = 0
        self.stop_count = 0

    def setInterval(self, _value):
        pass

    def start(self):
        self.active = True
        self.start_count += 1

    def stop(self):
        self.active = False
        self.stop_count += 1


class _Sampler:
    def __init__(self, timer, images):
        self.timer = timer
        self.images = images

    def create_timer(self, _callback):
        return self.timer

    def sample(self):
        return self.images


class _PairCoordinator:
    def __init__(self, callback, snapshot):
        self.callback = callback
        self.snapshot = snapshot
        self.state = MonitorState.ARMING
        self.pair_generation = 0
        self.context_revision = 0
        self.question_revision = 0
        self.pause_count = 0
        self.resume_count = 0
        self.stop_count = 0

    def start(self):
        self.state = MonitorState.ARMING

    def tick(self, _images):
        self.state = MonitorState.WATCHING
        self.pair_generation = self.snapshot.generation
        self.context_revision = self.snapshot.context_revision
        self.question_revision = self.snapshot.question_revision
        return self.snapshot

    def analyze_now(self, images=None):
        assert images is not None
        self.snapshot = PairSnapshot(
            self.snapshot.generation + 1,
            self.snapshot.context_revision,
            self.snapshot.question_revision,
            images.context,
            images.question,
        )
        self.pair_generation = self.snapshot.generation
        return self.snapshot

    def pause(self):
        self.pause_count += 1
        self.state = MonitorState.PAUSED

    def resume(self):
        self.resume_count += 1
        self.state = MonitorState.ARMING

    def stop(self):
        self.stop_count += 1
        self.state = MonitorState.STOPPED


class _Dispatcher:
    def __init__(self):
        self.session_id = "dispatcher-session"
        self.active_request = None
        self.submissions = []
        self.pause_count = 0
        self.resume_count = 0
        self.stop_count = 0
        self.on_result = self.on_error = self.on_cancelled = self.on_finished = self.on_ocr = self.on_observe = None

    def submit_context_question(self, context_image, question_image, mode, **kwargs):
        request = SimpleNamespace(
            context_image=context_image,
            question_image=question_image,
            mode=AnalysisMode(mode),
            generation=kwargs["generation"],
            session_id=kwargs["session_id"],
            request_id=f"pair-{kwargs['generation']}",
        )
        self.submissions.append(request)
        self.active_request = request
        return request

    def pause(self):
        self.pause_count += 1

    def resume(self):
        self.resume_count += 1

    def stop(self):
        self.stop_count += 1
        self.active_request = None


class _Overlay:
    def __init__(self):
        self.begin_count = 0
        self.close_count = 0
        self.errors = []
        self.regions = None

    def begin(self):
        self.begin_count += 1

    def set_regions(self, screen, rois):
        self.regions = (screen, tuple(rois))

    def close(self):
        self.close_count += 1

    def set_status(self, *_args, **_kwargs):
        pass

    def show_error(self, message):
        self.errors.append(message)


class _Mini(QObject):
    analyze_now_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.close_count = 0
        self.mode = None
        self.region_mode = None
        self.shown_rois = None

    def set_mode(self, mode):
        self.mode = mode

    def set_region_mode(self, mode):
        self.region_mode = mode

    def show_for_regions(self, _screen, rois):
        self.shown_rois = tuple(rois)

    def set_monitor_state(self, _state):
        pass

    def set_generation(self, _generation):
        pass

    def set_analysis_state(self, _state):
        pass

    def close_from_session(self):
        self.close_count += 1


def _images(context_color, question_color):
    context = QImage(30, 20, QImage.Format.Format_RGBA8888)
    context.fill(QColor(context_color))
    question = QImage(40, 24, QImage.Format.Format_RGBA8888)
    question.fill(QColor(question_color))
    return ContextQuestionImages(context, question)


def test_context_question_session_routes_pair_lifecycle_and_controls(qt_app):
    screen = qt_app.primaryScreen()
    context = WatchRegion.create(screen, QRect(10, 10, 80, 60), "pair-session")
    question = WatchRegion.create(screen, QRect(200, 120, 90, 70), "pair-session")
    regions = ContextQuestionRegions.create(context, question)
    images = _images("red", "blue")
    snapshot = PairSnapshot(1, 1, 1, images.context, images.question)
    timer = _Timer()
    sampler = _Sampler(timer, images)
    coordinator = _PairCoordinator(None, snapshot)
    dispatcher = _Dispatcher()
    overlay = _Overlay()
    mini = _Mini()
    session = ContextQuestionAutoWatchSession(
        regions,
        AnalysisMode.TEXT,
        config_manager=_Config(_Repo()),
        dispatcher=dispatcher,
        overlay=overlay,
        mini=mini,
        sampler_factory=lambda _regions, _settings: sampler,
        coordinator_factory=lambda _settings, callback: _PairCoordinator(callback, snapshot),
    )
    requested = []
    session.analysis_requested.connect(requested.append)

    assert session.start() is True
    assert mini.mode is AnalysisMode.TEXT
    assert mini.region_mode == "Context + Question"
    assert mini.shown_rois == (context.global_roi, question.global_roi)
    session.tick()
    assert len(requested) == 1
    assert dispatcher.submissions[0].generation == 1
    assert dispatcher.submissions[0].context_image.size() == images.context.size()
    assert dispatcher.submissions[0].question_image.size() == images.question.size()
    assert overlay.regions == (screen, (context.logical_roi, question.logical_roi))

    ocr_events = []
    session.analysis_ocr_ready.connect(ocr_events.append)
    dispatcher.on_ocr(dispatcher.submissions[0], "context", "context text")
    assert ocr_events[0]["generation"] == 1
    assert ocr_events[0]["stage"] == "context"
    assert ocr_events[0]["text"] == "context text"

    mini.pause_requested.emit()
    assert not timer.active and dispatcher.pause_count == 1
    mini.resume_requested.emit()
    assert timer.active and dispatcher.resume_count == 1
    mini.analyze_now_requested.emit()
    assert len(dispatcher.submissions) == 2
    assert dispatcher.submissions[-1].generation == 2

    dispatcher.active_request = None
    mini.stop_requested.emit()
    assert session.regions is None
    assert overlay.close_count == 1 and mini.close_count == 1
    assert dispatcher.stop_count == 1
