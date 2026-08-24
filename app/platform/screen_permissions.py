"""Cross-platform screen capture permission checks."""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QCoreApplication, QThread

logger = logging.getLogger(__name__)

_CORE_GRAPHICS_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"


def _load_core_graphics():
    """Load the public CoreGraphics framework used by macOS screen capture."""

    library = ctypes.CDLL(_CORE_GRAPHICS_PATH)
    for name in ("CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess"):
        function = getattr(library, name)
        function.argtypes = []
        function.restype = ctypes.c_bool
    return library


def _is_gui_thread() -> bool:
    application = QCoreApplication.instance()
    return application is not None and QThread.currentThread() == application.thread()


def has_screen_recording_permission() -> bool:
    """Return whether the current platform allows screen capture."""

    if sys.platform != "darwin":
        return True
    try:
        return bool(_load_core_graphics().CGPreflightScreenCaptureAccess())
    except Exception:
        logger.exception("unable to check macOS screen capture permission")
        return False


def request_screen_recording_permission() -> bool:
    """Ask macOS to present its public Screen Recording permission prompt."""

    if sys.platform != "darwin":
        return True
    if not _is_gui_thread():
        logger.warning("macOS screen capture permission request must run on the GUI thread")
        return False
    try:
        return bool(_load_core_graphics().CGRequestScreenCaptureAccess())
    except Exception:
        logger.exception("unable to request macOS screen capture permission")
        return False
