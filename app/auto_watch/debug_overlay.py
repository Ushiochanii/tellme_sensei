"""Small, image-free ROI overlay for the Phase 1 auto-watch demo."""

from __future__ import annotations

from dataclasses import dataclass
import sys

from PySide6.QtCore import QRect, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .models import MonitorState, WatchEvent

if sys.platform == "darwin":
    from app.platform.macos.window import configure_macos_overlay_window
else:
    configure_macos_overlay_window = None


STATE_LABELS: dict[MonitorState, str] = {
    MonitorState.ARMING: "正在建立基准",
    MonitorState.WATCHING: "正在监控",
    MonitorState.CHANGING: "检测到变化，等待稳定",
    MonitorState.PAUSED: "已暂停",
    MonitorState.STOPPED: "已停止",
}

EVENT_LABELS: dict[WatchEvent, str] = {
    WatchEvent.INITIAL_STABLE_FRAME: "初始画面已稳定",
    WatchEvent.NEW_STABLE_FRAME: "检测到新的稳定画面",
}


def state_label(state: MonitorState) -> str:
    """Return the compact Chinese label shown on the ROI."""

    return STATE_LABELS[state]


def event_label(event: WatchEvent | None) -> str | None:
    """Return the short human-readable event message, if there is one."""

    return EVENT_LABELS.get(event) if event is not None else None


def format_ratio(ratio: float | None) -> str:
    """Format a ratio for terminal output without exposing raw decimals."""

    return "—" if ratio is None else f"{ratio:.1%}"


def overlay_bounds(screen_geometry: QRect, roi: QRect, label_size: QSize) -> QRect:
    """Return the smallest screen-global rect containing the ROI and label."""

    if screen_geometry.isEmpty() or roi.isEmpty():
        return QRect()
    screen_local = QRect(0, 0, screen_geometry.width(), screen_geometry.height())
    roi_local = roi.intersected(screen_local)
    if roi_local.isEmpty():
        return QRect()
    margin = 8
    label_width = max(0, label_size.width())
    label_height = max(0, label_size.height())
    label_x = max(0, min(roi_local.left(), screen_local.width() - label_width))
    above_y = roi_local.top() - label_height - margin
    label_y = above_y if above_y >= 0 else roi_local.bottom() + margin
    label_rect = QRect(label_x, label_y, label_width, label_height)
    content = roi_local.united(label_rect)
    return content.translated(screen_geometry.left(), screen_geometry.top())


@dataclass(frozen=True)
class OverlayPresentation:
    """Pure presentation data, kept separate from Qt painting."""

    state: MonitorState
    event: WatchEvent | None = None
    generation: int | None = None

    @property
    def text(self) -> str:
        message = event_label(self.event)
        text = f"{state_label(self.state)} · {message}" if message else state_label(self.state)
        return f"{text} · G{self.generation}" if self.generation is not None else text


class DebugOverlay(QWidget):
    """Always-on-top, click-through ROI border that never captures screen pixels."""

    _FEEDBACK_MS = 1_200
    _MARGIN = 8

    def __init__(self, screen, roi: QRect, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if roi.isEmpty():
            raise ValueError("debug overlay ROI must be non-empty")
        geometry = screen.geometry()
        if geometry.isEmpty():
            raise ValueError("debug overlay screen geometry must be non-empty")

        self.screen = screen
        self.roi = QRect(roi)
        self._presentation = OverlayPresentation(MonitorState.STOPPED)
        self._label_size = self._measure_label()
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._clear_event)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._set_content_geometry(geometry)

    @property
    def presentation(self) -> OverlayPresentation:
        return self._presentation

    @property
    def status_text(self) -> str:
        return self._presentation.text

    def begin(self) -> None:
        """Show the border without activating or retaining a screen image."""

        if (
            sys.platform == "darwin"
            and configure_macos_overlay_window is not None
            and QGuiApplication.platformName() != "offscreen"
        ):
            configure_macos_overlay_window(self, ignores_mouse_events=True)
        self.show()
        self.raise_()

    def set_status(self, state: MonitorState, event: WatchEvent | None = None, generation: int | None = None) -> None:
        """Update the border and optionally show a short success acknowledgement."""

        # Keep the success acknowledgement visible across the next few polling
        # ticks; the coordinator only emits an event on the accepting tick.
        if event is None and self._feedback_timer.isActive() and self._presentation.event is not None:
            event = self._presentation.event
        self._presentation = OverlayPresentation(state, event, generation)
        self._label_size = self._measure_label()
        self._set_content_geometry(self.screen.geometry())
        if event is not None:
            self._feedback_timer.start(self._FEEDBACK_MS)
        else:
            self._feedback_timer.stop()
        self.update()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self._feedback_timer.stop()
        super().closeEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        roi = self._roi_local.intersected(self.rect())
        if roi.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = self._border_color()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 220), 7))
        painter.drawRect(roi.adjusted(3, 3, -3, -3))
        painter.setPen(QPen(color, 4))
        painter.drawRect(roi.adjusted(3, 3, -3, -3))
        self._paint_label(painter, roi, color)

    def _paint_label(self, painter: QPainter, roi: QRect, color: QColor) -> None:
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        metrics = QFontMetrics(font)
        text = self.status_text
        label_width = metrics.horizontalAdvance(text) + 20
        label_height = metrics.height() + 10
        x = max(0, min(roi.left(), self.width() - label_width))
        above_y = roi.top() - label_height - self._MARGIN
        y = above_y if above_y >= 0 else min(self.height() - label_height, roi.bottom() + self._MARGIN)
        label_rect = QRect(x, max(0, y), label_width, label_height)
        painter.setBrush(QColor(20, 24, 32, 235))
        painter.setPen(QPen(color, 2))
        painter.drawRoundedRect(label_rect, 5, 5)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _border_color(self) -> QColor:
        if self._presentation.event is not None:
            return QColor(60, 220, 130)
        return {
            MonitorState.ARMING: QColor(255, 190, 45),
            MonitorState.WATCHING: QColor(45, 205, 255),
            MonitorState.CHANGING: QColor(255, 100, 70),
            MonitorState.PAUSED: QColor(180, 180, 190),
            MonitorState.STOPPED: QColor(140, 140, 150),
        }[self._presentation.state]

    def _clear_event(self) -> None:
        self._presentation = OverlayPresentation(self._presentation.state, generation=self._presentation.generation)
        self._label_size = self._measure_label()
        self._set_content_geometry(self.screen.geometry())
        self.update()

    def _measure_label(self) -> QSize:
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        metrics = QFontMetrics(font)
        return QSize(metrics.horizontalAdvance(self.status_text) + 20, metrics.height() + 10)

    def _set_content_geometry(self, screen_geometry: QRect) -> None:
        bounds = overlay_bounds(screen_geometry, self.roi, self._label_size)
        if bounds.isEmpty():
            raise ValueError("debug overlay ROI must intersect screen geometry")
        self.setGeometry(bounds)
        self._roi_local = self.roi.translated(
            screen_geometry.left() - bounds.left(),
            screen_geometry.top() - bounds.top(),
        )


__all__ = [
    "DebugOverlay",
    "EVENT_LABELS",
    "OverlayPresentation",
    "STATE_LABELS",
    "event_label",
    "format_ratio",
    "overlay_bounds",
    "state_label",
]
