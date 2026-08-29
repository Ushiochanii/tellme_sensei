from types import SimpleNamespace

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage

from app.analysis import AnalysisMode
from app.auto_watch.models import ContextQuestionRegions, WatchRegion
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow


class _Selection:
    def __init__(self, screen, roi):
        self.selection_metadata = (screen, QRect(roi))


class _FakeWatchSession(QObject):
    analysis_requested = Signal(object)
    analysis_started = Signal(object)
    analysis_result = Signal(object)
    analysis_ocr_ready = Signal(object)
    analysis_error = Signal(object)
    analysis_cancelled = Signal(object)
    analysis_finished = Signal(object)
    session_stopped = Signal()

    def __init__(self, *_args, **kwargs):
        super().__init__()
        self.start_count = 0
        self.stop_count = 0
        self.overlay = kwargs.get("overlay")

    def start(self):
        self.start_count += 1
        if self.overlay is not None:
            self.overlay.begin()
        return True

    def stop(self):
        self.stop_count += 1
        if self.overlay is not None:
            self.overlay.close()
        self.session_stopped.emit()


def test_context_question_setup_requires_same_display_and_explicit_start(qt_app, monkeypatch):
    monkeypatch.setattr(main_window_module, "ContextQuestionAutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    window.show()
    assert window.enter_auto_watch_setup()
    window.auto_watch_context_question_radio.click()

    screen = qt_app.primaryScreen()
    context_roi = QRect(10, 10, 80, 60)
    question_roi = QRect(220, 120, 90, 70)
    window._auto_watch_selection_overlay = _Selection(screen, context_roi)
    assert window._on_auto_watch_capture(QImage()) is True
    assert isinstance(window._auto_watch_context_region, WatchRegion)
    assert window._auto_watch_question_region is None
    assert not window.auto_watch_start_button.isEnabled()

    # A different QScreen object is rejected before it can replace Context.
    window._auto_watch_selection_overlay = _Selection(object(), question_roi)
    assert window._on_auto_watch_capture(QImage()) is False
    assert "same display" in window.auto_watch_setup_status.text()
    assert window._auto_watch_context_region is not None
    assert window._auto_watch_question_region is None
    preview = window._auto_watch_selection_preview
    assert preview is not None and preview.isVisible()

    window._auto_watch_selection_overlay = _Selection(screen, question_roi)
    assert window._on_auto_watch_capture(QImage()) is True
    assert isinstance(window._auto_watch_regions, ContextQuestionRegions)
    assert window._auto_watch_session is None
    assert window.auto_watch_start_button.isEnabled()

    window.auto_watch_start_button.click()
    session = window._auto_watch_session
    assert isinstance(session, _FakeWatchSession)
    assert session.overlay is preview
    assert window._auto_watch_selection_preview is None
    assert window._auto_watch_active is True
    assert session.start_count == 1
    session.stop()
    assert not preview.isVisible()
    assert window._auto_watch_selection_preview is None
    window.close()
    qt_app.processEvents()


def test_single_region_selection_still_starts_the_existing_session(qt_app, monkeypatch):
    monkeypatch.setattr(main_window_module, "AutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    window.show()
    window.enter_auto_watch_setup()
    screen = qt_app.primaryScreen()
    window._auto_watch_selection_overlay = _Selection(screen, QRect(10, 10, 80, 60))

    assert window._on_auto_watch_capture(QImage()) is True
    assert isinstance(window._auto_watch_session, _FakeWatchSession)
    assert window._auto_watch_regions is None
    assert isinstance(window._auto_watch_region, WatchRegion)
    assert window._auto_watch_active is True
    window._auto_watch_session.stop()
    window.close()
    qt_app.processEvents()


def test_context_question_preview_updates_reuses_one_overlay_and_cleans_up(qt_app):
    window = MainWindow(tray_mode=True)
    window.show()
    assert window.enter_auto_watch_setup()
    window.auto_watch_context_question_radio.click()
    screen = qt_app.primaryScreen()
    context_roi = QRect(10, 10, 80, 60)
    question_roi = QRect(220, 120, 90, 70)

    assert window._on_context_question_capture(screen, context_roi, "context")
    preview = window._auto_watch_selection_preview
    assert preview is not None and preview.isVisible()
    assert preview.rois == (context_roi,)

    assert window._on_context_question_capture(screen, question_roi, "question")
    assert window._auto_watch_selection_preview is preview
    assert preview.rois == (context_roi, question_roi)
    assert window.auto_watch_reselect_context_button.isVisible()
    assert window.auto_watch_reselect_question_button.isVisible()

    preview.hide()
    window._on_auto_watch_selection_cancelled()
    assert window._auto_watch_selection_preview is preview
    assert preview.isVisible()

    window.auto_watch_single_region_radio.click()
    assert window._auto_watch_selection_preview is None
    assert not preview.isVisible()
    window.close()
    qt_app.processEvents()


def test_context_question_ocr_events_are_generation_guarded_in_main_window(qt_app, monkeypatch):
    monkeypatch.setattr(main_window_module, "ContextQuestionAutoWatchSession", _FakeWatchSession)
    window = MainWindow(tray_mode=True)
    window.show()
    assert window.enter_auto_watch_setup()
    window.auto_watch_context_question_radio.click()
    screen = qt_app.primaryScreen()
    context = WatchRegion.create(screen, QRect(10, 10, 80, 60), "ocr-session")
    question = WatchRegion.create(screen, QRect(220, 120, 90, 70), "ocr-session")
    regions = ContextQuestionRegions.create(context, question)
    window._auto_watch_session = _FakeWatchSession()
    window._auto_watch_session_id = regions.session_id
    window._auto_watch_active = True
    window._auto_watch_generation = 0
    window._auto_watch_regions = regions
    window._connect_auto_watch_signals(window._auto_watch_session, regions)
    request_one = SimpleNamespace(generation=1, mode=AnalysisMode.TEXT, session_id=regions.session_id)
    request_two = SimpleNamespace(generation=2, mode=AnalysisMode.TEXT, session_id=regions.session_id)

    window._auto_watch_session.analysis_requested.emit(request_one)
    window._auto_watch_session.analysis_ocr_ready.emit({
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

    window._auto_watch_session.analysis_requested.emit(request_two)
    window._auto_watch_session.analysis_ocr_ready.emit({
        "request": request_one,
        "stage": "question",
        "text": "stale question",
        "mode": AnalysisMode.TEXT,
        "generation": 1,
    })
    assert answer.question_ocr_edit.toPlainText() == ""

    window._auto_watch_session.analysis_ocr_ready.emit({
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
    window.close()
    qt_app.processEvents()
