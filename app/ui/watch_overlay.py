"""Click-through, image-free border for an Auto Watch ROI."""
from __future__ import annotations
import sys
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget
from app.auto_watch.models import MonitorState
if sys.platform == "darwin":
    from app.platform.macos.window import configure_macos_overlay_window
else:
    configure_macos_overlay_window = None


def outside_roi_segments(roi: QRect, bounds: QRect, thickness: int = 3) -> tuple[QRect, ...]:
    """Return tight, non-overlapping border strips outside ``roi``.

    The strips are clipped to the overlay's screen-local bounds.  Clipping an
    off-screen strip to an edge can never move it back over the ROI because
    each strip starts strictly outside the ROI.
    """
    if roi.isEmpty() or bounds.isEmpty() or thickness < 1:
        return ()
    candidates = (
        QRect(roi.left(), roi.top() - thickness, roi.width(), thickness),
        QRect(roi.left(), roi.bottom() + 1, roi.width(), thickness),
        QRect(roi.left() - thickness, roi.top(), thickness, roi.height()),
        QRect(roi.right() + 1, roi.top(), thickness, roi.height()),
    )
    result = []
    for candidate in candidates:
        clipped = candidate.intersected(bounds)
        if not clipped.isEmpty() and not clipped.intersects(roi):
            result.append(clipped)
    return tuple(result)


class WatchOverlay(QWidget):
    COLORS = {MonitorState.WATCHING: QColor("#32bd72"), MonitorState.ARMING: QColor("#e5ad3d"),
              MonitorState.CHANGING: QColor("#e5ad3d"), MonitorState.PAUSED: QColor("#9299a6"),
              MonitorState.STOPPED: QColor("#9299a6")}
    def __init__(self, screen, roi: QRect, parent=None):
        super().__init__(parent); self.screen = screen; self.roi = QRect(roi); self.state = MonitorState.STOPPED
        self.error = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating); self.setFocusPolicy(Qt.NoFocus)
        self.setGeometry(screen.geometry())
    def begin(self):
        if (sys.platform == "darwin" and configure_macos_overlay_window is not None
                and QGuiApplication.platformName() != "offscreen"):
            configure_macos_overlay_window(self, ignores_mouse_events=True)
        self.show(); self.raise_()
    def set_status(self, state, *, generation=None, analysis_state=None, error=None):
        self.state = state; self.generation = generation; self.analysis_state = analysis_state; self.error = error; self.update()
    def show_error(self, message): self.error = str(message); self.state = MonitorState.PAUSED; self.update()
    def close(self):
        if self.isVisible(): self.hide()
        return super().close()
    def paintEvent(self, _event):
        painter = QPainter(self)
        color = QColor("#e58d8d") if self.error else self.COLORS.get(self.state, QColor("#9299a6"))
        bounds = QRect(0, 0, self.width(), self.height())
        for segment in outside_roi_segments(self.roi, bounds):
            painter.fillRect(segment, color)


__all__ = ["WatchOverlay", "outside_roi_segments"]
