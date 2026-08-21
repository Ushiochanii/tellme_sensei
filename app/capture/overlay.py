"""Single-monitor, DPI-aware screen selection overlay."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class CaptureOverlay(QWidget):
    """Capture a rectangular area from the monitor under the current cursor."""

    captured = Signal(QImage)
    cancelled = Signal()

    def __init__(self, debug_path: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.debug_path = debug_path
        self._screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if self._screen is None:
            raise RuntimeError("没有可用的显示器。")
        self._screen_geometry = self._screen.geometry()
        self._screen_image = self._screen.grabWindow(0).toImage()
        self._drag_start: QPoint | None = None
        self._selection = QRect()
        self._completed = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(self._screen_geometry)

    @property
    def selection(self) -> QRect:
        """Current selection in overlay-local logical coordinates."""

        return QRect(self._selection)

    def begin(self) -> None:
        """Show the overlay after the screen image has been captured."""

        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(self.rect(), self._screen_image)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 145))

        if not self._selection.isNull():
            source_rect = self._source_rect(self._selection)
            painter.drawImage(self._selection, self._screen_image, source_rect)
            pen = QPen(QColor(55, 160, 255), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._selection)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._selection = QRect(self._drag_start, self._drag_start)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._drag_start is None:
            return
        current = event.position().toPoint()
        self._selection = QRect(self._drag_start, current).normalized().intersected(self.rect())
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.button() != Qt.MouseButton.LeftButton or self._drag_start is None:
            return
        self._drag_start = None
        if self._selection.width() < 20 or self._selection.height() < 20:
            self._cancel()
            return
        self._completed = True
        image = self._screen_image.copy(self._source_rect(self._selection))
        image.setDevicePixelRatio(1.0)
        if self.debug_path is not None:
            self.debug_path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(self.debug_path)):
                logger.warning("无法保存调试截图: %s", self.debug_path)
            else:
                logger.info("调试截图已保存: %s", self.debug_path)
        self.captured.emit(image)
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if not self._completed and self._drag_start is not None:
            self._drag_start = None
        super().closeEvent(event)

    def _cancel(self) -> None:
        if self._completed:
            return
        self._drag_start = None
        self._selection = QRect()
        self.cancelled.emit()
        self.close()

    def _source_rect(self, selection: QRect) -> QRect:
        """Map logical overlay coordinates to physical screenshot pixels."""

        if self.width() <= 0 or self.height() <= 0:
            return QRect()
        scale_x = self._screen_image.width() / self.width()
        scale_y = self._screen_image.height() / self.height()
        left = max(0, int(selection.left() * scale_x))
        top = max(0, int(selection.top() * scale_y))
        right = min(self._screen_image.width(), int((selection.right() + 1) * scale_x))
        bottom = min(self._screen_image.height(), int((selection.bottom() + 1) * scale_y))
        return QRect(left, top, max(1, right - left), max(1, bottom - top))
