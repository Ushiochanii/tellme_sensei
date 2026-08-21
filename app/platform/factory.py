"""Central platform selection for services used by the application."""

from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QObject

from app.platform.base import GlobalHotkeyManager
from app.platform.unsupported import UnsupportedGlobalHotkey
from app.platform.windows.hotkey import WindowsGlobalHotkey


def create_global_hotkey_manager(
    parent: QObject | None = None,
    *,
    platform_name: str | None = None,
    register_func: Callable | None = None,
    unregister_func: Callable | None = None,
) -> GlobalHotkeyManager:
    """Create the platform hotkey service used by the Qt controller."""

    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        return WindowsGlobalHotkey(parent, register_func, unregister_func)
    return UnsupportedGlobalHotkey(parent, platform_name=platform_name)
