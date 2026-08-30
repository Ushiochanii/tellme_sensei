"""Single-monitor, DPI-aware screen selection overlay."""

from __future__ import annotations

import logging
from pathlib import Path
import sys

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app.localization import DEFAULT_INTERFACE_LANGUAGE, normalize_language, tr

if sys.platform == "darwin":
    from app.platform.macos.window import configure_macos_overlay_window
else:
    configure_macos_overlay_window = None

logger = logging.getLogger(__name__)

_WINDOWS_CAPTURE_SETTLE_MS = 150


class CaptureOverlay(QWidget):
    """Capture a rectangular area from the monitor under the current cursor."""

    captured = Signal(QImage)
    cancelled = Signal()

    def __init__(
        self,
        debug_path: Path | None = None,
        parent: QWidget | None = None,
        interface_language: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.debug_path = debug_path
        self._interface_language = normalize_language(
            interface_language, default=DEFAULT_INTERFACE_LANGUAGE
        )
        self._screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if self._screen is None:
            raise RuntimeError(tr("capture.no_screen", self._interface_language))
        self._screen_geometry = self._screen.geometry()
        self._screen_image = (
            QImage() if sys.platform == "win32" else self._screen.grabWindow(0).toImage()
        )
        self._drag_start: QPoint | None = None
        self._selection = QRect()
        self._completed = False
        self._capture_hidden_launchers: tuple[QWidget, ...] = ()
        self._begin_timer = QTimer(self)
        self._begin_timer.setSingleShot(True)
        self._begin_timer.timeout.connect(self._capture_screen_and_show)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        if sys.platform == "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(self._screen_geometry)

    @property
    def selection(self) -> QRect:
        """Current selection in overlay-local logical coordinates."""

        return QRect(self._selection)

    @property
    def screen(self):
        """The selected monitor, exposed read-only for auto-watch tooling."""
        return self._screen

    @property
    def selection_metadata(self) -> tuple[object, QRect]:
        """Return the monitor and logical ROI without exposing mutable internals."""
        return self._screen, QRect(self._selection)

    def begin(self) -> None:
        """Show the overlay, delaying only the Windows screen grab."""

        # Direct capture hides the floating launcher before creating this overlay.
        # Remember that state so the synchronous capture callback cannot bring the
        # launcher back while the AnswerWindow is still open. Auto Watch selection
        # leaves the launcher visible, so it is intentionally not included here.
        self._capture_hidden_launchers = tuple(
            widget
            for widget in QApplication.topLevelWidgets()
            if widget.objectName() == "mainController" and not widget.isVisible()
        )
        if sys.platform == "win32":
            self._begin_timer.start(_WINDOWS_CAPTURE_SETTLE_MS)
            return
        if sys.platform == "darwin":
            if configure_macos_overlay_window is not None:
                configure_macos_overlay_window(self)
            self.show()
            return
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _capture_screen_and_show(self) -> None:
        """Grab one settled Windows desktop frame, then expose the selection UI."""

        self._screen_image = self._screen.grabWindow(0).toImage()
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
        self._finish_capture(image)

    def _finish_capture(self, image: QImage) -> None:
        """Deliver the image while preserving direct-capture launcher visibility."""

        self.hide()
        self.captured.emit(image)
        for launcher in self._capture_hidden_launchers:
            if launcher.isVisible():
                launcher.hide()
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
