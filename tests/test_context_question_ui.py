from types import SimpleNamespace

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage

from app.analysis import AnalysisMode
from app.auto_watch.models import ContextQuestionRegions, WatchRegion
from app.config import ConfigManager
from app.settings.repository import SettingsRepository
from app.ui import main_window as main_window_module
from app.ui.main_window import AutoWatchSelectionPhase, MainWindow


class _FakeOverlay(QObject):
    captured = Signal(object)
    cancelled = Signal()
    instances: list["_FakeOverlay"] = []
    next_metadata = None
    constructor_error: Exception | None = None
    begin_error: Exception | None = None
    metadata_error: Exception | None = None

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        if type(self).constructor_error is not None:
            raise type(self).constructor_error
        if type(self).next_metadata is None:
            raise AssertionError("test must provide selection metadata")
        self._selection_metadata = (
            type(self).next_metadata[0],
            QRect(type(self).next_metadata[1]),
        )
        self.begin_count = 0
        self.close_count = 0
        self._visible = False
        type(self).instances.append(self)

    def begin(self) -> None:
        self.begin_count += 1
        if type(self).begin_error is not None:
            raise type(self).begin_error
        self._visible = True

    @property
    def selection_metadata(self):
        if type(self).metadata_error is not None:
            raise type(self).metadata_error
        return self._selection_metadata

    def close(self) -> None:
        self.close_count += 1
        self._visible = False

    def isVisible(self) -> bool:
        return self._visible


class _FakeWatchSession(QObject):
    analysis_requested = Signal(object)
    analysis_started = Signal(object)
    analysis_result = Signal(object)
    analysis_ocr_ready = Signal(object)
    analysis_error = Signal(object)
    analysis_cancelled = Signal(object)
    analysis_finished = Signal(object)
    session_stopped = Signal()
    instances: list["_FakeWatchSession"] = []
    start_error: Exception | None = None
    start_result = True

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.start_count = 0
        self.stop_count = 0
        self.shutdown_count = 0
        type(self).instances.append(self)

    def start(self):
        self.start_count += 1
        if type(self).start_error is not None:
            raise type(self).start_error
        return type(self).start_result

    def stop(self):
        self.stop_count += 1
        self.session_stopped.emit()

    def shutdown(self):
        self.shutdown_count += 1
        self.stop()


def _reset_fakes() -> None:
    _FakeOverlay.instances.clear()
    _FakeOverlay.next_metadata = None
    _FakeOverlay.constructor_error = None
    _FakeOverlay.begin_error = None
    _FakeOverlay.metadata_error = None
    _FakeWatchSession.instances.clear()
    _FakeWatchSession.start_error = None
    _FakeWatchSession.start_result = True


def _prepare(monkeypatch, screen, roi):
    _reset_fakes()
    monkeypatch.setattr(main_window_module, "CaptureOverlay", _FakeOverlay)
    monkeypatch.setattr(
        main_window_module.screen_permissions,
        "has_screen_recording_permission",
        lambda: True,
    )
    _FakeOverlay.next_metadata = (screen, roi)


def _close(window, qt_app) -> None:
    window.close()
    qt_app.processEvents()


def test_watch_entry_creates_overlay_and_starts_session_after_valid_capture(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    monkeypatch.setattr(main_window_module, "AutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    window.show()

    assert window.start_watch() is True
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.SELECTING_SINGLE
    assert len(_FakeOverlay.instances) == 1
    overlay = _FakeOverlay.instances[0]
    assert overlay.begin_count == 1
    assert window._auto_watch_session is None

    overlay.captured.emit(QImage())
    assert len(_FakeWatchSession.instances) == 1
    session = _FakeWatchSession.instances[0]
    assert session.args[1] is AnalysisMode.TEXT
    assert session.start_count == 1
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.ACTIVE
    assert window._auto_watch_active is True
    assert overlay.close_count == 1
    session.stop()
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    _close(window, qt_app)


def test_context_entry_advances_to_question_and_starts_without_confirmation(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    context_roi = QRect(10, 10, 80, 60)
    question_roi = QRect(220, 120, 90, 70)
    _prepare(monkeypatch, screen, context_roi)
    monkeypatch.setattr(main_window_module, "ContextQuestionAutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    window.show()

    assert window.start_context_watch() is True
    context_overlay = _FakeOverlay.instances[0]
    _FakeOverlay.next_metadata = (screen, question_roi)
    context_overlay.captured.emit(QImage())

    assert len(_FakeOverlay.instances) == 2
    question_overlay = _FakeOverlay.instances[1]
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.SELECTING_QUESTION
    assert isinstance(window._auto_watch_context_region, WatchRegion)
    assert window._auto_watch_session is None
    question_overlay.captured.emit(QImage())

    assert len(_FakeWatchSession.instances) == 1
    session = _FakeWatchSession.instances[0]
    assert isinstance(session.args[0], ContextQuestionRegions)
    assert session.args[1] is AnalysisMode.TEXT
    assert session.start_count == 1
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.ACTIVE
    assert window._auto_watch_context_region is None
    assert window._auto_watch_question_region is None
    session.stop()
    _close(window, qt_app)


def test_mode_is_snapshotted_before_question_selection(qt_app, monkeypatch, tmp_path):
    screen = qt_app.primaryScreen()
    repo = SettingsRepository(tmp_path / "settings.json")
    repo.update({"auto_watch_analysis_mode": AnalysisMode.VISION})
    manager = ConfigManager(settings_repository=repo)
    context_roi = QRect(10, 10, 80, 60)
    question_roi = QRect(220, 120, 90, 70)
    _prepare(monkeypatch, screen, context_roi)
    monkeypatch.setattr(main_window_module, "ContextQuestionAutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True, config_manager=manager)
    assert window.start_context_watch() is True
    assert window._auto_watch_workflow_mode is AnalysisMode.VISION
    repo.update({"auto_watch_analysis_mode": AnalysisMode.TEXT})
    _FakeOverlay.next_metadata = (screen, question_roi)
    _FakeOverlay.instances[0].captured.emit(QImage())
    _FakeOverlay.instances[1].captured.emit(QImage())
    assert _FakeWatchSession.instances[0].args[1] is AnalysisMode.VISION
    repo.update({"auto_watch_analysis_mode": AnalysisMode.TEXT})
    assert _FakeWatchSession.instances[0].args[1] is AnalysisMode.VISION
    _FakeWatchSession.instances[0].stop()
    _close(window, qt_app)


def test_context_different_screen_reopens_question_and_cancel_clears_context(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    other_screen = object()
    context_roi = QRect(10, 10, 80, 60)
    question_roi = QRect(220, 120, 90, 70)
    _prepare(monkeypatch, screen, context_roi)
    monkeypatch.setattr(main_window_module, "ContextQuestionAutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    assert window.start_context_watch() is True
    _FakeOverlay.next_metadata = (screen, question_roi)
    _FakeOverlay.instances[0].captured.emit(QImage())
    question_overlay = _FakeOverlay.instances[1]

    question_overlay._selection_metadata = (other_screen, QRect(question_roi))
    question_overlay.captured.emit(QImage())
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.SELECTING_QUESTION
    assert window._auto_watch_context_region is not None
    assert window._auto_watch_session is None
    assert len(_FakeOverlay.instances) == 3
    assert "same display" in window.status_label.text()
    retry_overlay = _FakeOverlay.instances[2]
    retry_overlay.cancelled.emit()
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_selection_overlay is None
    assert window._auto_watch_context_region is None
    _close(window, qt_app)


def test_cancel_and_late_callback_cannot_commit_after_reentry(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    monkeypatch.setattr(main_window_module, "AutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    assert window.start_watch() is True
    old_overlay = _FakeOverlay.instances[0]
    old_generation = window._auto_watch_selection_generation
    old_overlay.cancelled.emit()
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_selection_overlay is None
    _FakeOverlay.next_metadata = (screen, QRect(20, 20, 80, 60))
    assert window.start_watch() is True
    new_overlay = _FakeOverlay.instances[1]
    assert window._on_auto_watch_capture(QImage(), old_overlay, old_generation) is False
    assert window._auto_watch_selection_overlay is new_overlay
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.SELECTING_SINGLE
    assert not _FakeWatchSession.instances
    new_overlay.cancelled.emit()
    _close(window, qt_app)


def test_invalid_first_selection_aborts_without_pending_region(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 0, 60))
    monkeypatch.setattr(main_window_module, "AutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    assert window.start_watch() is True
    _FakeOverlay.instances[0].captured.emit(QImage())
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_selection_overlay is None
    assert window._auto_watch_region is None
    assert not _FakeWatchSession.instances
    _close(window, qt_app)


def test_selection_metadata_failure_closes_current_overlay_before_abort(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    _FakeOverlay.metadata_error = RuntimeError("metadata failed")
    monkeypatch.setattr(main_window_module, "AutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    assert window.start_watch() is True
    overlay = _FakeOverlay.instances[0]
    overlay.captured.emit(QImage())
    assert overlay.close_count == 1
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_selection_overlay is None
    assert window._auto_watch_context_region is None
    assert window._auto_watch_question_region is None
    assert window._auto_watch_regions is None
    assert window._auto_watch_workflow_mode is None
    assert window._auto_watch_session is None
    _close(window, qt_app)


def test_overlay_constructor_and_begin_failures_abort_cleanly(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    window = MainWindow(tray_mode=True)
    _FakeOverlay.constructor_error = RuntimeError("constructor failed")
    assert window.start_watch() is False
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_selection_overlay is None
    assert window._auto_watch_workflow_mode is None

    _reset_fakes()
    _FakeOverlay.next_metadata = (screen, QRect(10, 10, 80, 60))
    _FakeOverlay.begin_error = RuntimeError("begin failed")
    assert window.start_watch() is False
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_selection_overlay is None
    assert _FakeOverlay.instances[0].close_count == 1
    _close(window, qt_app)


def test_session_start_failure_cleans_session_and_returns_idle(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    _FakeWatchSession.start_error = RuntimeError("start failed")
    monkeypatch.setattr(main_window_module, "AutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    assert window.start_watch() is True
    _FakeOverlay.instances[0].captured.emit(QImage())
    session = _FakeWatchSession.instances[0]
    assert session.shutdown_count == 1
    assert session.stop_count == 1
    assert window._auto_watch_session is None
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_workflow_mode is None
    _close(window, qt_app)


def test_false_session_start_and_busy_entry_are_clean_noops(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    _FakeWatchSession.start_result = False
    monkeypatch.setattr(main_window_module, "AutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    assert window.start_watch() is True
    first_overlay = _FakeOverlay.instances[0]
    assert window.start_context_watch() is False
    assert len(_FakeOverlay.instances) == 1
    first_overlay.captured.emit(QImage())
    assert len(_FakeWatchSession.instances) == 1
    assert _FakeWatchSession.instances[0].shutdown_count == 1
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    window._busy = True
    assert window.start_watch() is False
    assert len(_FakeOverlay.instances) == 1
    _close(window, qt_app)


def test_session_constructor_failure_returns_to_idle(qt_app, monkeypatch):
    class FailingSession(QObject):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            raise RuntimeError("constructor failed")

    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    monkeypatch.setattr(main_window_module, "AutoWatchSession", FailingSession)
    window = MainWindow(tray_mode=True)
    assert window.start_watch() is True
    _FakeOverlay.instances[0].captured.emit(QImage())
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_session is None
    assert window._auto_watch_workflow_mode is None
    _close(window, qt_app)


def test_shutdown_during_selection_closes_overlay_without_session_wait(qt_app, monkeypatch):
    screen = qt_app.primaryScreen()
    _prepare(monkeypatch, screen, QRect(10, 10, 80, 60))
    window = MainWindow(tray_mode=True)
    shutdown_ready = []
    window.shutdown_ready.connect(lambda: shutdown_ready.append(True))
    assert window.start_watch() is True
    overlay = _FakeOverlay.instances[0]
    window.request_shutdown()
    assert overlay.close_count == 1
    assert window._auto_watch_selection_phase is AutoWatchSelectionPhase.IDLE
    assert window._auto_watch_selection_overlay is None
    assert window._auto_watch_workflow_mode is None
    assert window._auto_watch_context_region is None
    assert window._auto_watch_question_region is None
    assert window._auto_watch_session is None
    assert shutdown_ready == [True]
    window.close()
    qt_app.processEvents()


def test_context_question_ocr_events_are_generation_guarded_in_main_window(qt_app, monkeypatch):
    monkeypatch.setattr(main_window_module, "ContextQuestionAutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    screen = qt_app.primaryScreen()
    context = WatchRegion.create(screen, QRect(10, 10, 80, 60), "ocr-session")
    question = WatchRegion.create(screen, QRect(220, 120, 90, 70), "ocr-session")
    regions = ContextQuestionRegions.create(context, question)
    session = _FakeWatchSession()
    window._auto_watch_session = session
    window._auto_watch_session_id = regions.session_id
    window._auto_watch_active = True
    window._auto_watch_generation = 0
    window._auto_watch_regions = regions
    window._connect_auto_watch_signals(session, regions)
    request_one = SimpleNamespace(generation=1, mode=AnalysisMode.TEXT, session_id=regions.session_id)
    request_two = SimpleNamespace(generation=2, mode=AnalysisMode.TEXT, session_id=regions.session_id)

    session.analysis_requested.emit(request_one)
    session.analysis_ocr_ready.emit({
        "request": request_one,
        "stage": "context",
        "text": "context one",
        "mode": AnalysisMode.TEXT,
        "generation": 1,
    })
    answer = window._answer_window
    assert answer is not None
    assert answer.context_ocr_edit.toPlainText() == "context one"
    assert answer.answer_edit.toPlainText() == ""

    session.analysis_requested.emit(request_two)
    session.analysis_ocr_ready.emit({
        "request": request_one,
        "stage": "question",
        "text": "stale question",
        "mode": AnalysisMode.TEXT,
        "generation": 1,
    })
    assert answer.question_ocr_edit.toPlainText() == ""

    session.analysis_ocr_ready.emit({
        "request": request_two,
        "stage": "question",
        "text": "question two",
        "mode": AnalysisMode.TEXT,
        "generation": 2,
    })
    assert answer.question_ocr_edit.toPlainText() == "question two"
    assert answer.answer_edit.toPlainText() == ""
    window._auto_watch_session = None
    window._auto_watch_active = False
    answer.close()
    _close(window, qt_app)
