"""Small Qt/Python thread context helper used by GUI diagnostics."""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread


def current_thread_info() -> str:
    """Return stable, non-sensitive identifiers for the current execution thread."""

    qt_thread = QThread.currentThread()
    name = qt_thread.objectName() or "<unnamed>"
    return f"python_id={threading.get_ident()} qt_object={id(qt_thread)} qt_name={name}"
