"""Central platform selection for services used by the application."""

from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QObject

from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import DEFAULT_SHORTCUT, TEXT_HOTKEY_ID
from app.platform.unsupported import UnsupportedGlobalHotkey


def create_global_hotkey_manager(
    parent: QObject | None = None,
    *,
    platform_name: str | None = None,
    register_func: Callable | None = None,
    unregister_func: Callable | None = None,
    shortcut: str = DEFAULT_SHORTCUT,
    hotkey_id: int = TEXT_HOTKEY_ID,
) -> GlobalHotkeyManager:
    """Create the platform hotkey service used by the Qt controller."""

    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        from app.platform.windows.hotkey import WindowsGlobalHotkey

        return WindowsGlobalHotkey(
            parent,
            register_func,
            unregister_func,
            shortcut=shortcut,
            hotkey_id=hotkey_id,
        )
    if platform_name == "darwin":
        from app.platform.macos.hotkey import MacOSGlobalHotkey

        return MacOSGlobalHotkey(parent, shortcut=shortcut, hotkey_id=hotkey_id)
    return UnsupportedGlobalHotkey(
        parent,
        platform_name=platform_name,
        shortcut=shortcut,
        hotkey_id=hotkey_id,
    )
