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
        self._quit_called = False

        self.tray.capture_requested.connect(self.window.start_capture)
        self.tray.settings_requested.connect(self.window.show_launcher)
        self.hotkey.triggered.connect(self.window.start_capture)
        self.tray.exit_requested.connect(self.request_exit)
        if hasattr(self.window, "shutdown_ready"):
            self.window.shutdown_ready.connect(self._on_shutdown_ready)

    def start(self, show_window: bool = False) -> None:
        self.tray.show()
        self.hotkey.register()
        if show_window:
            self.window.show()
        else:
            self.window.hide()

    def request_exit(self) -> None:
        """Begin shutdown; QApplication.quit waits for shutdown_ready."""

        if self._shutting_down:
            return
        self._shutting_down = True
        self.hotkey.unregister()
        request_shutdown = getattr(self.window, "request_shutdown", None)
        if callable(request_shutdown):
            request_shutdown()
        else:
            self.window.shutdown()

    def _on_shutdown_ready(self) -> None:
        if self._quit_called:
            return
        self._quit_called = True
        self.tray.hide()
        logger.info("application exiting")
        self.app.quit()

    def cleanup(self) -> None:
        """Final idempotent cleanup for QApplication.aboutToQuit."""

        if self._quit_called:
            return
        self._shutting_down = True
        if not hasattr(self.window, "shutdown_ready"):
            self.window.shutdown()
        self.hotkey.unregister()
        self.tray.hide()
        self._quit_called = True
