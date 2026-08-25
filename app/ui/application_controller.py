"""Application-level routing and shutdown lifecycle for tray mode."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer

from app.platform.base import GlobalHotkeyManager

logger = logging.getLogger(__name__)


class ApplicationController(QObject):
    """Connect tray/hotkey signals and own the shutdown sequence."""

    def __init__(
        self,
        app,
        window,
        tray,
        hotkey: GlobalHotkeyManager,
        vision_hotkey: GlobalHotkeyManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or app)
        self.app = app
        self.window = window
        self.tray = tray
        self.hotkey = hotkey
        self.text_hotkey = hotkey
        self.vision_hotkey = vision_hotkey
        self._shutting_down = False
        self._quit_called = False

        text_capture = getattr(self.window, "start_text_capture", self.window.start_capture)
        vision_capture = getattr(self.window, "start_vision_capture", None)
        if hasattr(self.tray, "text_capture_requested"):
            self.tray.text_capture_requested.connect(text_capture)
        else:
            self.tray.capture_requested.connect(text_capture)
        if vision_capture is not None and hasattr(self.tray, "vision_capture_requested"):
            self.tray.vision_capture_requested.connect(vision_capture)
        settings_handler = getattr(self.window, "show_settings", None)
        if not callable(settings_handler):
            settings_handler = self.window.show_launcher
        self.tray.settings_requested.connect(settings_handler)
        self.text_hotkey.triggered.connect(text_capture)
        if self.vision_hotkey is not None and vision_capture is not None:
            self.vision_hotkey.triggered.connect(vision_capture)
        self.tray.exit_requested.connect(self.request_exit)
        if hasattr(self.window, "shutdown_ready"):
            self.window.shutdown_ready.connect(self._on_shutdown_ready)

    def start(self, show_window: bool = False) -> None:
        self.tray.show()
        if not self.text_hotkey.register():
            logger.warning("Text Mode global hotkey registration failed; open Settings to change it")
        if self.vision_hotkey is not None and not self.vision_hotkey.register():
            logger.warning("Vision Mode global hotkey registration failed; open Settings to change it")
        if show_window:
            self.window.show()
        else:
            self.window.hide()
        prewarm = getattr(self.window, "request_local_ocr_prewarm", None)
        if callable(prewarm):
            QTimer.singleShot(0, prewarm)

    def request_exit(self) -> None:
        """Begin shutdown; QApplication.quit waits for shutdown_ready."""

        if self._shutting_down:
            return
        self._shutting_down = True
        self.text_hotkey.unregister()
        if self.vision_hotkey is not None:
            self.vision_hotkey.unregister()
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
        self.text_hotkey.unregister()
        if self.vision_hotkey is not None:
            self.vision_hotkey.unregister()
        self.tray.hide()
        self._quit_called = True
