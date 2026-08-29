from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from app.capture import overlay as overlay_module


def test_windows_capture_syncs_window_system_before_screen_grab(qt_app, monkeypatch) -> None:
    events: list[str] = []

    class FakePixmap:
        def toImage(self) -> QImage:
            image = QImage(80, 60, QImage.Format.Format_RGBA8888)
            image.fill(0xFFFFFFFF)
            return image

    class FakeScreen:
        def geometry(self) -> QRect:
            return QRect(0, 0, 80, 60)

        def grabWindow(self, window_id: int) -> FakePixmap:  # noqa: N802 - Qt API name
            assert window_id == 0
            events.append("grab")
            return FakePixmap()

    fake_screen = FakeScreen()

    class FakeGuiApplication:
        @staticmethod
        def screenAt(_position):  # noqa: N802 - Qt API name
            return fake_screen

        @staticmethod
        def primaryScreen():  # noqa: N802 - Qt API name
            return fake_screen

        @staticmethod
        def sync() -> None:
            events.append("sync")

    monkeypatch.setattr(overlay_module.sys, "platform", "win32")
    monkeypatch.setattr(overlay_module, "QGuiApplication", FakeGuiApplication)

    overlay = overlay_module.CaptureOverlay()

    assert events == ["sync", "grab"]
    overlay.close()
    qt_app.processEvents()
