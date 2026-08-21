from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.ui.application_controller import ApplicationController
from app.ui.main_window import MainWindow


class FakeApp(QObject):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.quit_count = 0

    def quit(self) -> None:
        self.events.append("quit")
        self.quit_count += 1


class FakeTray(QObject):
    capture_requested = Signal()
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.hide_count = 0

    def hide(self) -> None:
        self.events.append("tray_hide")
        self.hide_count += 1


class FakeHotkey(QObject):
    triggered = Signal()

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.unregister_count = 0

    def unregister(self) -> None:
        self.events.append("unregister")
        self.unregister_count += 1


class FakeWindow(QObject):
    shutdown_ready = Signal()

    def __init__(self, events: list[str], immediate: bool) -> None:
        super().__init__()
        self.events = events
        self.immediate = immediate
        self.request_shutdown_count = 0
        self.shutdown_count = 0

    def start_capture(self) -> None:
        pass

    def show_launcher(self) -> None:
        pass

    def hide(self) -> None:
        pass

    def show(self) -> None:
        pass

    def request_shutdown(self) -> None:
        self.events.append("request_shutdown")
        self.request_shutdown_count += 1
        if self.immediate:
            self.shutdown_ready.emit()

    def shutdown(self) -> None:
        self.shutdown_count += 1


def test_no_worker_shutdown_quits_immediately(qt_app) -> None:
    events: list[str] = []
    app = FakeApp(events)
    window = FakeWindow(events, immediate=True)
    controller = ApplicationController(app, window, FakeTray(events), FakeHotkey(events))

    controller.request_exit()

    assert app.quit_count == 1
    assert events == ["unregister", "request_shutdown", "tray_hide", "quit"]


def test_active_worker_shutdown_waits_for_shutdown_ready(qt_app) -> None:
    events: list[str] = []
    app = FakeApp(events)
    window = FakeWindow(events, immediate=False)
    tray = FakeTray(events)
    hotkey = FakeHotkey(events)
    controller = ApplicationController(app, window, tray, hotkey)

    controller.request_exit()
    assert app.quit_count == 0
    assert tray.hide_count == 0
    assert hotkey.unregister_count == 1

    window.shutdown_ready.emit()
    assert app.quit_count == 1
    assert tray.hide_count == 1


def test_finished_worker_quits_exactly_once_and_repeated_exit_is_safe(qt_app) -> None:
    events: list[str] = []
    app = FakeApp(events)
    window = FakeWindow(events, immediate=False)
    tray = FakeTray(events)
    hotkey = FakeHotkey(events)
    controller = ApplicationController(app, window, tray, hotkey)

    controller.request_exit()
    controller.request_exit()
    window.shutdown_ready.emit()
    window.shutdown_ready.emit()
    controller.request_exit()

    assert app.quit_count == 1
    assert hotkey.unregister_count == 1
    assert tray.hide_count == 1


def test_main_window_request_shutdown_is_signal_driven(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    ready: list[bool] = []
    window.shutdown_ready.connect(lambda: ready.append(True))

    window.request_shutdown()
    window.request_shutdown()

    assert ready == [True]
    assert window._shutting_down is True
    window.shutdown()


def test_main_window_active_thread_delays_shutdown_ready(qt_app) -> None:
    class FakeThread:
        def isRunning(self) -> bool:
            return True

    class FakeWorker:
        def __init__(self) -> None:
            self.cancel_count = 0

        def request_cancel(self) -> None:
            self.cancel_count += 1

    window = MainWindow(tray_mode=True)
    worker = FakeWorker()
    window.processing_thread = FakeThread()
    window.processing_worker = worker
    window._active_job_id = "shutdown-job"
    ready: list[bool] = []
    window.shutdown_ready.connect(lambda: ready.append(True))

    window.request_shutdown()

    assert ready == []
    assert worker.cancel_count == 1

    window._on_thread_finished("shutdown-job")
    assert ready == [True]
    window.shutdown()
