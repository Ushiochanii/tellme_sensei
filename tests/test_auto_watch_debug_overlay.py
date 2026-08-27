from PySide6.QtCore import QRect, QSize, Qt

from app.auto_watch.debug_overlay import DebugOverlay, overlay_bounds
from app.auto_watch.models import MonitorState, WatchEvent


class GeometryOnlyScreen:
    def __init__(self, geometry=QRect(0, 0, 480, 320)):
        self._geometry = QRect(geometry)

    def geometry(self):
        return QRect(self._geometry)

    def grabWindow(self, _):
        raise AssertionError("debug overlay must not capture or save screenshots")


def test_debug_overlay_is_click_through_topmost_and_keeps_roi(qt_app):
    overlay = DebugOverlay(GeometryOnlyScreen(), QRect(30, 40, 200, 120))
    assert overlay.roi == QRect(30, 40, 200, 120)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.focusPolicy() is Qt.FocusPolicy.NoFocus
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


def test_overlay_bounds_maps_local_roi_to_nonzero_screen_origin():
    screen = QRect(100, 50, 800, 600)
    roi = QRect(20, 30, 200, 120)

    assert overlay_bounds(screen, roi, QSize(180, 30)) == QRect(120, 80, 200, 157)
    assert overlay_bounds(screen, QRect(20, 200, 200, 120), QSize(180, 30)) == QRect(
        120, 212, 200, 158
    )


def test_debug_overlay_uses_small_nonzero_origin_geometry_and_local_roi(qt_app):
    screen_geometry = QRect(100, 50, 800, 600)
    roi = QRect(20, 200, 200, 120)
    overlay = DebugOverlay(GeometryOnlyScreen(screen_geometry), roi)

    geometry = overlay.geometry()
    assert geometry == overlay_bounds(screen_geometry, roi, overlay._label_size)
    assert geometry != screen_geometry
    assert geometry.width() * geometry.height() < screen_geometry.width() * screen_geometry.height() / 4

    global_roi_top_left = screen_geometry.topLeft() + roi.topLeft()
    assert geometry.contains(global_roi_top_left)
    assert overlay._roi_local.topLeft() == global_roi_top_left - geometry.topLeft()
    assert overlay._roi_local == roi.translated(
        screen_geometry.left() - geometry.left(),
        screen_geometry.top() - geometry.top(),
    )

    overlay.set_status(MonitorState.CHANGING)
    assert overlay.geometry() == overlay_bounds(
        screen_geometry, roi, overlay._label_size
    )
    overlay.close()
    qt_app.processEvents()
