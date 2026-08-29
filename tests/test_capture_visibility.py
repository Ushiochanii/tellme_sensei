from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from app.capture import overlay as overlay_module


class _FakePixmap:
    def toImage(self) -> QImage:
        image = QImage(80, 60, QImage.Format.Format_RGBA8888)
        image.fill(0xFFFFFFFF)
        return image


class _FakeScreen:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def geometry(self) -> QRect:
        return QRect(0, 0, 80, 60)

    def grabWindow(self, window_id: int) -> _FakePixmap:  # noqa: N802 - Qt API name
        assert window_id == 0
        self.events.append("grab")
        return _FakePixmap()


def _install_fake_screen(monkeypatch, events: list[str]) -> None:
    fake_screen = _FakeScreen(events)

    class FakeGuiApplication:
        @staticmethod
        def screenAt(_position):  # noqa: N802 - Qt API name
            return fake_screen

        @staticmethod
        def primaryScreen():  # noqa: N802 - Qt API name
            return fake_screen

    monkeypatch.setattr(overlay_module, "QGuiApplication", FakeGuiApplication)


def test_windows_capture_waits_150ms_before_screen_grab(qt_app, monkeypatch) -> None:
    events: list[str] = []
    _install_fake_screen(monkeypatch, events)
    monkeypatch.setattr(overlay_module.sys, "platform", "win32")

    overlay = overlay_module.CaptureOverlay()
    overlay.begin()

    assert events == []
    assert overlay._begin_timer.isActive()
    assert overlay._begin_timer.interval() == 150

    overlay._begin_timer.stop()
    overlay._capture_screen_and_show()
    assert events == ["grab"]
    overlay.close()
    qt_app.processEvents()


def test_direct_capture_keeps_launcher_hidden_after_capture_callback(qt_app, monkeypatch) -> None:
    events: list[str] = []
    _install_fake_screen(monkeypatch, events)
    monkeypatch.setattr(overlay_module.sys, "platform", "win32")

    launcher = QWidget()
    launcher.setObjectName("mainController")
    launcher.show()
    qt_app.processEvents()
    launcher.hide()
    qt_app.processEvents()

    overlay = overlay_module.CaptureOverlay()
    overlay.begin()
    overlay._begin_timer.stop()
    assert launcher in overlay._capture_hidden_launchers

    overlay.captured.connect(lambda _image: launcher.show())
    image = QImage(40, 30, QImage.Format.Format_RGBA8888)
    image.fill(0xFFFFFFFF)
    overlay._completed = True
    overlay._finish_capture(image)
    qt_app.processEvents()

    assert not launcher.isVisible()
    launcher.close()
    qt_app.processEvents()


def test_cancel_does_not_rehide_launcher(qt_app, monkeypatch) -> None:
    events: list[str] = []
    _install_fake_screen(monkeypatch, events)
    monkeypatch.setattr(overlay_module.sys, "platform", "win32")

    launcher = QWidget()
    launcher.setObjectName("mainController")
    launcher.hide()
    overlay = overlay_module.CaptureOverlay()
    overlay.begin()
    overlay._begin_timer.stop()
    overlay.cancelled.connect(launcher.show)

    overlay._cancel()
    qt_app.processEvents()

    assert launcher.isVisible()
    launcher.close()
    qt_app.processEvents()


def test_normal_answer_close_restores_floating_launcher(qt_app) -> None:
    from app.ui.main_window import MainWindow

    window = MainWindow(tray_mode=False)
    window.hide()
    window._show_or_create_answer()
    answer = window._answer_window
    assert answer is not None
    answer.show()
    qt_app.processEvents()

    assert not window.isVisible()
    answer.close()
    qt_app.processEvents()

    assert window.isVisible()
    window.close()
    qt_app.processEvents()
