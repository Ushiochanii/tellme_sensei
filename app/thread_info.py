"""Small Qt/Python thread context helper used by GUI diagnostics."""

from __future__ import annotations

import threading

try:
    from PySide6.QtCore import QThread
except ImportError:  # Standalone workers do not require the Qt runtime.
    QThread = None  # type: ignore[assignment,misc]


def current_thread_info() -> str:
    """Return stable, non-sensitive identifiers for the current execution thread."""

    if QThread is None:
        return f"python_id={threading.get_ident()} qt_object=<unavailable> qt_name=<python-only>"

    qt_thread = QThread.currentThread()
    name = qt_thread.objectName() or "<unnamed>"
    return f"python_id={threading.get_ident()} qt_object={id(qt_thread)} qt_name={name}"
