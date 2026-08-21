"""Backward-compatible import for the Windows hotkey service."""

from app.platform.windows.hotkey import WindowsGlobalHotkey

GlobalHotkeyManager = WindowsGlobalHotkey

__all__ = ["GlobalHotkeyManager", "WindowsGlobalHotkey"]
