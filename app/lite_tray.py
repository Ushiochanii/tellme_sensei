"""Small menu-bar controller used only by TellMeSensei Lite."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class VisionLiteTray(QObject):
    """Expose the four Lite menu actions without Full-app tray behavior."""

    capture_requested = Signal()
    show_controller_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None, tray_icon=None) -> None:
        super().__init__(parent)
        self.tray = tray_icon or QSystemTrayIcon(self._create_icon(), self)
        self.menu = QMenu()
        self.menu.addAction("Capture", self.capture_requested.emit)
        self.menu.addAction("Show Controller", self.show_controller_requested.emit)
        self.menu.addAction("Settings...", self.settings_requested.emit)
        self.menu.addSeparator()
        self.menu.addAction("Quit", self.quit_requested.emit)
        self.tray.setContextMenu(self.menu)

    @staticmethod
    def _create_icon() -> QIcon:
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#2f4057"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pixmap.rect(), 0x84, "V")
        painter.end()
        return QIcon(pixmap)

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()
