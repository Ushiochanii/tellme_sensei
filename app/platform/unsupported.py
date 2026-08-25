"""Fallback platform services for unsupported operating systems."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject

from app.platform.base import GlobalHotkeyManager

logger = logging.getLogger(__name__)


class UnsupportedGlobalHotkey(GlobalHotkeyManager):
    """Safe fallback when a platform hotkey implementation is unavailable."""

    def __init__(
        self,
        parent: QObject | None = None,
        platform_name: str = "unknown",
        shortcut: str = "Ctrl+Shift+Q",
        hotkey_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.platform_name = platform_name
        self._shortcut = shortcut
        self.hotkey_id = hotkey_id

    @property
    def registered(self) -> bool:
        return False

    @property
    def shortcut(self) -> str:
        return self._shortcut

    def register(self) -> bool:
        logger.warning("global hotkey unsupported on platform: %s", self.platform_name)
        return False

    def rebind(self, shortcut: str) -> bool:
        logger.warning("global hotkey unsupported on platform: %s", self.platform_name)
        return False

    def unregister(self) -> None:
        logger.info("global hotkey unregistered")
