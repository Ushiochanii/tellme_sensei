"""System tray menu and signal routing."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

logger = logging.getLogger(__name__)


class SystemTrayController(QObject):
    """Own the tray icon and expose GUI-safe actions as Qt signals."""

    capture_requested = Signal()
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QObject | None = None, tray_icon=None) -> None:
        super().__init__(parent)
        self.tray = tray_icon or QSystemTrayIcon(self._create_icon(), self)
        self.menu = QMenu()
        title = self.menu.addAction("学习助手")
        title.setEnabled(False)
        self.menu.addSeparator()
        capture = self.menu.addAction("截图识别")
        settings = self.menu.addAction("设置")
        self.menu.addSeparator()
        exit_action = self.menu.addAction("退出")
        capture.triggered.connect(self.trigger_capture)
        settings.triggered.connect(self.trigger_settings)
        exit_action.triggered.connect(self.trigger_exit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        logger.info("tray initialized")

    @staticmethod
    def _create_icon() -> QIcon:
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#2f4057"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pixmap.rect(), 0x84, "学")
        painter.end()
        return QIcon(pixmap)

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def trigger_capture(self) -> None:
        logger.info("tray capture triggered")
        self.capture_requested.emit()

    def trigger_settings(self) -> None:
        self.settings_requested.emit()

    def trigger_exit(self) -> None:
        self.exit_requested.emit()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.trigger_capture()
