from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage

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
    analysis_error = Signal(object)
    analysis_cancelled = Signal(object)
    analysis_finished = Signal(object)
    session_stopped = Signal()

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.start_count = 0
        self.stop_count = 0

    def start(self):
        self.start_count += 1
        return True

    def stop(self):
        self.stop_count += 1
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

    window._auto_watch_selection_overlay = _Selection(screen, question_roi)
    assert window._on_auto_watch_capture(QImage()) is True
    assert isinstance(window._auto_watch_regions, ContextQuestionRegions)
    assert window._auto_watch_session is None
    assert window.auto_watch_start_button.isEnabled()

    window.auto_watch_start_button.click()
    assert isinstance(window._auto_watch_session, _FakeWatchSession)
    assert window._auto_watch_active is True
    assert window._auto_watch_session.start_count == 1
    window._auto_watch_session.stop()
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
