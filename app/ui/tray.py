"""System tray menu and signal routing."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.ui.theme import tray_menu_stylesheet

logger = logging.getLogger(__name__)


class SystemTrayController(QObject):
    """Own the tray icon and expose GUI-safe actions as Qt signals."""

    text_capture_requested = Signal()
    vision_capture_requested = Signal()
    # Retain the old signal name for external callers and existing integrations.
    capture_requested = Signal()
    show_controller_requested = Signal()
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QObject | None = None, tray_icon=None) -> None:
        super().__init__(parent)
        self.tray = tray_icon or QSystemTrayIcon(self._create_icon(), self)
        self.menu = QMenu()
        self.menu.setObjectName("trayMenu")
        self.menu.setStyleSheet(tray_menu_stylesheet())
        title = self.menu.addAction("TellMeSensei")
        title.setEnabled(False)
        self.menu.addSeparator()
        text_capture = self.menu.addAction("Text / OCR Capture")
        vision_capture = self.menu.addAction("Vision Capture")
        show_controller = self.menu.addAction("Show Controller")
        self.menu.addSeparator()
        settings = self.menu.addAction("Settings")
        self.menu.addSeparator()
        exit_action = self.menu.addAction("Quit")
        text_capture.triggered.connect(self.trigger_text_capture)
        vision_capture.triggered.connect(self.trigger_vision_capture)
        show_controller.triggered.connect(self.trigger_show_controller)
        settings.triggered.connect(self.trigger_settings)
        exit_action.triggered.connect(self.trigger_exit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        logger.info("tray initialized")

    @staticmethod
    def _create_icon() -> QIcon:
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2f6fe4"))
        painter.drawRoundedRect(3, 3, 26, 26, 8, 8)
        painter.setPen(
            QPen(QColor("#ffffff"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawLine(9, 13, 9, 9)
        painter.drawLine(9, 9, 13, 9)
        painter.drawLine(19, 9, 23, 9)
        painter.drawLine(23, 9, 23, 13)
        painter.drawLine(9, 19, 9, 23)
        painter.drawLine(9, 23, 13, 23)
        painter.drawLine(19, 23, 23, 23)
        painter.drawLine(23, 23, 23, 19)
        painter.setBrush(QColor("#d8caff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(14, 14, 4, 4)
        painter.end()
        return QIcon(pixmap)

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def trigger_capture(self) -> None:
        """Backward-compatible alias for the Text Mode tray action."""

        self.trigger_text_capture()

    def trigger_text_capture(self) -> None:
        logger.info("tray text capture triggered")
        self.text_capture_requested.emit()
        self.capture_requested.emit()

    def trigger_vision_capture(self) -> None:
        logger.info("tray vision capture triggered")
        self.vision_capture_requested.emit()

    def trigger_show_controller(self) -> None:
        self.show_controller_requested.emit()

    def trigger_settings(self) -> None:
        self.settings_requested.emit()

    def trigger_exit(self) -> None:
        self.exit_requested.emit()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.trigger_capture()
