"""Click-through, image-free border for an Auto Watch ROI."""
from __future__ import annotations
import sys
from collections.abc import Iterable
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget
from app.auto_watch.models import ContextQuestionRegions, MonitorState
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


class ContextQuestionWatchOverlay(WatchOverlay):
    """One transparent fullscreen overlay that marks two watched ROIs."""

    CONTEXT_COLOR = QColor("#5da9e9")
    QUESTION_COLOR = QColor("#9b7bea")

    def __init__(self, screen_or_regions, context_roi: QRect | None = None,
                 question_roi: QRect | None = None, parent=None):
        if isinstance(screen_or_regions, ContextQuestionRegions):
            regions = screen_or_regions
            screen = regions.screen
            context_roi = regions.context.logical_roi
            question_roi = regions.question.logical_roi
        else:
            screen = screen_or_regions
            if question_roi is None and not isinstance(context_roi, QRect):
                try:
                    pair = tuple(context_roi)
                except TypeError as exc:
                    raise TypeError("ContextQuestionWatchOverlay requires two QRect ROIs") from exc
                if len(pair) != 2:
                    raise ValueError("ContextQuestionWatchOverlay requires two QRect ROIs")
                context_roi, question_roi = pair
        if not isinstance(context_roi, QRect) or context_roi.isEmpty():
            raise ValueError("Context ROI must be a non-empty QRect")
        if not isinstance(question_roi, QRect) or question_roi.isEmpty():
            raise ValueError("Question ROI must be a non-empty QRect")
        super().__init__(screen, context_roi, parent)
        self.context_roi = QRect(context_roi)
        self.question_roi = QRect(question_roi)
        self.rois = (self.context_roi, self.question_roi)

    def paintEvent(self, _event):  # noqa: N802 - Qt API name
        painter = QPainter(self)
        bounds = QRect(0, 0, self.width(), self.height())
        colors = (self.CONTEXT_COLOR, self.QUESTION_COLOR)
        for roi, color in zip(self.rois, colors):
            draw_color = QColor("#e58d8d") if self.error else color
            for segment in _outside_all_rois_segments(roi, self.rois, bounds):
                painter.fillRect(segment, draw_color)
            self._draw_label(
                painter,
                roi,
                "CONTEXT" if roi is self.context_roi else "QUESTION",
                draw_color,
                bounds,
                self.rois,
            )

    @staticmethod
    def _draw_label(painter: QPainter, roi: QRect, label: str, color: QColor, bounds: QRect,
                    rois: Iterable[QRect]) -> None:
        """Draw a label only in a strip that is outside both monitored ROIs."""
        label_height = 18
        label_width = max(70, len(label) * 9 + 14)
        candidates = (
            QRect(roi.left(), roi.top() - label_height - 4, label_width, label_height),
            QRect(roi.left(), roi.bottom() + 5, label_width, label_height),
            QRect(roi.left() - label_width - 5, roi.top(), label_width, label_height),
            QRect(roi.right() + 5, roi.top(), label_width, label_height),
        )
        for candidate in candidates:
            candidate = candidate.intersected(bounds)
            if candidate.isEmpty() or candidate.width() < label_width or candidate.height() < label_height:
                continue
            if any(candidate.intersects(other) for other in rois):
                continue
            painter.setPen(color)
            painter.drawText(candidate, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            return


def _outside_all_rois_segments(roi: QRect, rois: Iterable[QRect], bounds: QRect) -> tuple[QRect, ...]:
    """Keep a border strip out of every monitored pixel in pair mode."""
    segments = []
    other_rois = tuple(other for other in rois if other != roi)
    for segment in outside_roi_segments(roi, bounds):
        if not any(segment.intersects(other) for other in other_rois):
            segments.append(segment)
    return tuple(segments)


DualWatchOverlay = ContextQuestionWatchOverlay


__all__ = [
    "ContextQuestionWatchOverlay",
    "DualWatchOverlay",
    "WatchOverlay",
    "outside_roi_segments",
]
