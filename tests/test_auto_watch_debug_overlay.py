from PySide6.QtCore import QRect, Qt

from app.auto_watch.debug_overlay import DebugOverlay
from app.auto_watch.models import MonitorState, WatchEvent


class GeometryOnlyScreen:
    def geometry(self):
        return QRect(0, 0, 480, 320)

    def grabWindow(self, _):
        raise AssertionError("debug overlay must not capture or save screenshots")


def test_debug_overlay_is_click_through_topmost_and_keeps_roi(qt_app):
    overlay = DebugOverlay(GeometryOnlyScreen(), QRect(30, 40, 200, 120))
    assert overlay.roi == QRect(30, 40, 200, 120)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    overlay.set_status(MonitorState.CHANGING)
    assert overlay.status_text == "检测到变化，等待稳定"
    overlay.begin()
    qt_app.processEvents()
    assert overlay.isVisible()
    overlay.close()
    qt_app.processEvents()
    assert not overlay.isVisible()


def test_debug_overlay_success_feedback_is_temporary_and_closes_cleanly(qt_app):
    overlay = DebugOverlay(GeometryOnlyScreen(), QRect(30, 40, 200, 120))
    overlay.set_status(MonitorState.WATCHING, WatchEvent.NEW_STABLE_FRAME)
    assert overlay.status_text == "正在监控 · 检测到新的稳定画面"
    assert overlay._feedback_timer.isActive()
    overlay.set_status(MonitorState.WATCHING)
    assert overlay.status_text == "正在监控 · 检测到新的稳定画面"
    overlay.close()
    qt_app.processEvents()
    assert not overlay._feedback_timer.isActive()
