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
    """One transparent overlay for a Context/Question preview or watch pair."""

    CONTEXT_COLOR = QColor("#5da9e9")
    QUESTION_COLOR = QColor("#9b7bea")

    def __init__(self, screen_or_regions, context_roi: QRect | None = None,
                 question_roi: QRect | None = None, parent=None):
        screen, rois = self._parse_regions(screen_or_regions, context_roi, question_roi)
        super().__init__(screen, rois[0], parent)
        self.set_regions(screen, rois)

    @staticmethod
    def _parse_regions(screen_or_regions, context_roi, question_roi):
        if isinstance(screen_or_regions, ContextQuestionRegions):
            regions = screen_or_regions
            return regions.screen, (
                QRect(regions.context.logical_roi),
                QRect(regions.question.logical_roi),
            )

        screen = screen_or_regions
        if question_roi is None and not isinstance(context_roi, QRect):
            try:
                rois = tuple(context_roi)
            except TypeError as exc:
                raise TypeError("ContextQuestionWatchOverlay requires one or two QRect ROIs") from exc
        elif question_roi is None:
            rois = (context_roi,)
        else:
            rois = (context_roi, question_roi)
        if not 1 <= len(rois) <= 2:
            raise ValueError("ContextQuestionWatchOverlay requires one or two QRect ROIs")
        if any(not isinstance(roi, QRect) or roi.isEmpty() for roi in rois):
            raise ValueError("Context and Question ROIs must be non-empty QRects")
        return screen, tuple(QRect(roi) for roi in rois)

    def set_regions(self, screen_or_regions, context_roi=None, question_roi=None) -> None:
        """Replace preview/watch ROIs without creating another overlay window."""

        screen, rois = self._parse_regions(screen_or_regions, context_roi, question_roi)
        if screen is None:
            raise ValueError("ContextQuestionWatchOverlay requires a screen")
        self.screen = screen
        self.rois = tuple(QRect(roi) for roi in rois)
        self.roi = QRect(self.rois[0])  # Keep the base overlay compatibility field.
        self.context_roi = self.rois[0]
        self.question_roi = self.rois[1] if len(self.rois) == 2 else None
        self.setGeometry(screen.geometry())
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt API name
        painter = QPainter(self)
        bounds = QRect(0, 0, self.width(), self.height())
        colors = (self.CONTEXT_COLOR, self.QUESTION_COLOR)
        labels = ("CONTEXT", "QUESTION")
        for index, (roi, color, label) in enumerate(zip(self.rois, colors, labels)):
            draw_color = QColor("#e58d8d") if self.error else color
            for segment in _outside_all_rois_segments(
                roi, self.rois, bounds, index=index
            ):
                painter.fillRect(segment, draw_color)

        # Labels are also part of the one shared composition.  Avoiding the
        # other label rectangles prevents a close pair from hiding one label.
        occupied_labels: list[QRect] = []
        for index, (roi, color, label) in enumerate(zip(self.rois, colors, labels)):
            draw_color = QColor("#e58d8d") if self.error else color
            self._draw_label(
                painter,
                roi,
                label,
                draw_color,
                bounds,
                self.rois,
                occupied_labels,
            )

    @staticmethod
    def _draw_label(painter: QPainter, roi: QRect, label: str, color: QColor, bounds: QRect,
                    rois: Iterable[QRect], occupied: list[QRect] | None = None) -> None:
        """Draw a role label in a free strip outside all monitored pixels."""
        label_height = 18
        label_width = max(70, len(label) * 9 + 14)
        candidates = (
            QRect(roi.left(), roi.top() - label_height - 4, label_width, label_height),
            QRect(roi.left(), roi.bottom() + 5, label_width, label_height),
            QRect(roi.left() - label_width - 5, roi.top(), label_width, label_height),
            QRect(roi.right() + 5, roi.top(), label_width, label_height),
        )
        if occupied is None:
            occupied = []
        for candidate in candidates:
            candidate = candidate.intersected(bounds)
            if candidate.isEmpty() or candidate.width() < label_width or candidate.height() < label_height:
                continue
            if any(candidate.intersects(other) for other in rois):
                continue
            if any(candidate.intersects(other) for other in occupied):
                continue
            painter.setPen(color)
            painter.drawText(candidate, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            occupied.append(candidate)
            return


def _subtract_rect(rect: QRect, occluder: QRect) -> tuple[QRect, ...]:
    """Subtract one monitored rectangle while retaining safe border fragments."""

    intersection = rect.intersected(occluder)
    if intersection.isEmpty():
        return (rect,)

    pieces: list[QRect] = []
    if intersection.top() > rect.top():
        pieces.append(QRect(rect.left(), rect.top(), rect.width(), intersection.top() - rect.top()))
    if intersection.bottom() < rect.bottom():
        pieces.append(
            QRect(rect.left(), intersection.bottom() + 1, rect.width(), rect.bottom() - intersection.bottom())
        )
    if intersection.left() > rect.left():
        pieces.append(QRect(rect.left(), intersection.top(), intersection.left() - rect.left(), intersection.height()))
    if intersection.right() < rect.right():
        pieces.append(
            QRect(intersection.right() + 1, intersection.top(), rect.right() - intersection.right(), intersection.height())
        )
    return tuple(piece for piece in pieces if not piece.isEmpty())


def _outside_all_rois_segments(
    roi: QRect,
    rois: Iterable[QRect],
    bounds: QRect,
    *,
    index: int | None = None,
) -> tuple[QRect, ...]:
    """Keep border strips outside every monitored ROI, without dropping fragments."""

    all_rois = tuple(rois)
    if index is None:
        index = next((i for i, other in enumerate(all_rois) if other == roi), None)
    other_rois = tuple(other for i, other in enumerate(all_rois) if i != index)
    segments: list[QRect] = []
    for segment in outside_roi_segments(roi, bounds):
        fragments = (segment,)
        for other in other_rois:
            fragments = tuple(
                fragment
                for piece in fragments
                for fragment in _subtract_rect(piece, other)
            )
        segments.extend(
            fragment
            for fragment in fragments
            if not fragment.isEmpty()
            and not any(fragment.intersects(other) for other in other_rois)
        )
    return tuple(segments)


DualWatchOverlay = ContextQuestionWatchOverlay


__all__ = [
    "ContextQuestionWatchOverlay",
    "DualWatchOverlay",
    "WatchOverlay",
    "outside_roi_segments",
]
