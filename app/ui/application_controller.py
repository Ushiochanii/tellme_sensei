"""Application-level routing and shutdown lifecycle for tray mode."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject

logger = logging.getLogger(__name__)


class ApplicationController(QObject):
    """Connect tray/hotkey signals and own the shutdown sequence."""

    def __init__(self, app, window, tray, hotkey, parent: QObject | None = None) -> None:
        super().__init__(parent or app)
        self.app = app
        self.window = window
        self.tray = tray
        self.hotkey = hotkey
        self._shutting_down = False

        self.tray.capture_requested.connect(self.window.start_capture)
        self.tray.settings_requested.connect(self.window.show_launcher)
        self.hotkey.triggered.connect(self.window.start_capture)
        self.tray.exit_requested.connect(self.request_exit)

    def start(self, show_window: bool = False) -> None:
        self.tray.show()
        self.hotkey.register()
        if show_window:
            self.window.show()
        else:
            self.window.hide()

    def request_exit(self) -> None:
        self.cleanup()
        self.app.quit()

    def cleanup(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.window.shutdown()
        self.hotkey.unregister()
        self.tray.hide()
        logger.info("application exiting")
