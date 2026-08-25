from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.platform.windows_hotkey import GlobalHotkeyManager
from app.state import AppState
from app.ui.application_controller import ApplicationController
from app.ui.main_window import MainWindow
from app.ui.tray import SystemTrayController
from app.ui.answer_window import AnswerWindow


class FakeTrayIcon(QObject):
    activated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.context_menu = None
        self.visible = False

    def setContextMenu(self, menu) -> None:  # noqa: N802 - Qt API shape
        self.context_menu = menu

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


class FakeWindow(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.capture_count = 0
        self.settings_count = 0
        self.shutdown_count = 0
        self.visible = False

    def start_capture(self) -> None:
        self.capture_count += 1

    def show_launcher(self) -> None:
        self.settings_count += 1

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def shutdown(self) -> None:
        self.shutdown_count += 1


class FakeHotkey(QObject):
    triggered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.register_count = 0
        self.unregister_count = 0

    def register(self) -> bool:
        self.register_count += 1
        return True

    def unregister(self) -> None:
        self.unregister_count += 1


def test_tray_initialization_and_capture_action_routing(qt_app) -> None:
    fake_tray = FakeTrayIcon()
    tray = SystemTrayController(tray_icon=fake_tray)
    labels = [action.text() for action in tray.menu.actions() if not action.isSeparator()]
    assert labels == ["学习助手", "截图识别（文字题）", "截图分析（图形题）", "设置", "退出"]
    received: list[bool] = []
    tray.capture_requested.connect(lambda: received.append(True))
    tray.trigger_capture()
    fake_tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
    assert received == [True, True]


def test_tray_exposes_distinct_text_and_vision_actions(qt_app) -> None:
    tray = SystemTrayController(tray_icon=FakeTrayIcon())
    text: list[bool] = []
    vision: list[bool] = []
    tray.text_capture_requested.connect(lambda: text.append(True))
    tray.vision_capture_requested.connect(lambda: vision.append(True))

    tray.trigger_text_capture()
    tray.trigger_vision_capture()

    assert text == [True]
    assert vision == [True]


def test_global_hotkey_register_event_route_and_unregister(qt_app) -> None:
    calls: list[tuple] = []

    def register(hwnd, hotkey_id, modifiers, key) -> int:
        calls.append((hwnd, hotkey_id, modifiers, key))
        return 1

    def unregister(hwnd, hotkey_id) -> int:
        calls.append((hwnd, hotkey_id))
        return 1

    manager = GlobalHotkeyManager(qt_app, register, unregister)
    received: list[bool] = []
    manager.triggered.connect(lambda: received.append(True))
    assert manager.register() is True
    assert manager.registered is True
    assert manager.handle_hotkey(manager.hotkey_id) is True
    assert manager.handle_hotkey(manager.hotkey_id + 1) is False
    manager.unregister()
    assert received == [True]
    assert len(calls) == 2
    assert manager.registered is False


def test_failed_hotkey_registration_does_not_disable_tray(qt_app) -> None:
    manager = GlobalHotkeyManager(qt_app, lambda *_args: 0, lambda *_args: 1)
    tray = SystemTrayController(tray_icon=FakeTrayIcon())
    received: list[bool] = []
    tray.capture_requested.connect(lambda: received.append(True))
    assert manager.register() is False
    tray.trigger_capture()
    assert received == [True]


def test_application_controller_routes_and_cleans_up(qt_app) -> None:
    fake_window = FakeWindow()
    fake_tray = SystemTrayController(tray_icon=FakeTrayIcon())
    fake_hotkey = FakeHotkey()
    controller = ApplicationController(qt_app, fake_window, fake_tray, fake_hotkey)
    controller.start(show_window=False)
    fake_tray.trigger_capture()
    fake_tray.trigger_settings()
    fake_hotkey.triggered.emit()
    assert fake_window.capture_count == 2
    assert fake_window.settings_count == 1
    assert fake_hotkey.register_count == 1
    controller.cleanup()
    controller.cleanup()
    assert fake_window.shutdown_count == 1
    assert fake_hotkey.unregister_count == 1
    assert fake_tray.tray.visible is False


def test_application_controller_routes_two_hotkeys_and_shutdown(qt_app) -> None:
    class DualWindow(FakeWindow):
        def __init__(self) -> None:
            super().__init__()
            self.text_count = 0
            self.vision_count = 0

        def start_text_capture(self) -> None:
            self.text_count += 1

        def start_vision_capture(self) -> None:
            self.vision_count += 1

    window = DualWindow()
    tray = SystemTrayController(tray_icon=FakeTrayIcon())
    text_hotkey = FakeHotkey()
    vision_hotkey = FakeHotkey()
    controller = ApplicationController(qt_app, window, tray, text_hotkey, vision_hotkey)
    controller.start()

    tray.trigger_text_capture()
    tray.trigger_vision_capture()
    text_hotkey.triggered.emit()
    vision_hotkey.triggered.emit()

    assert window.text_count == 2
    assert window.vision_count == 2
    assert text_hotkey.register_count == 1
    assert vision_hotkey.register_count == 1
    controller.cleanup()
    assert text_hotkey.unregister_count == 1
    assert vision_hotkey.unregister_count == 1


def test_busy_state_prevents_second_capture(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window.state = AppState.CAPTURING
    window._busy = True
    assert window.start_capture() is False
    assert window._overlay is None
    window.shutdown()


def test_cancel_capture_restores_idle(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window.state = AppState.CAPTURING
    window._busy = True
    window._on_capture_cancelled()
    assert window.state is AppState.IDLE
    assert window._busy is False
    assert window.capture_button.isEnabled()
    window.shutdown()


def test_answer_window_close_does_not_quit_application(qt_app) -> None:
    qt_app.setQuitOnLastWindowClosed(False)
    answer = AnswerWindow()
    answer.show()
    answer.close()
    qt_app.processEvents()
    assert not qt_app.closingDown()


def test_worker_error_cleanup_restores_idle(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window._busy = True
    window.state = AppState.OCR_PROCESSING

    window._on_error("OCR failed")
    assert window.state is AppState.ERROR

    window._on_thread_finished()
    assert window.state is AppState.IDLE
    assert window._busy is False
    window.shutdown()
