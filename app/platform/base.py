"""Platform service interfaces used by the cross-platform application layer."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class GlobalHotkeyManager(QObject):
    """Abstract global-hotkey service exposed to the Qt application layer."""

    triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    @property
    def registered(self) -> bool:
        """Whether the platform currently owns the configured hotkey."""
        raise NotImplementedError

    def register(self) -> bool:
        """Register the hotkey, returning false when unavailable."""
        raise NotImplementedError

    def unregister(self) -> None:
        """Release the hotkey and any platform event hooks."""
        raise NotImplementedError

    @property
    def shortcut(self) -> str:
        """Return the canonical configured shortcut string."""
        raise NotImplementedError

    def rebind(self, shortcut: str) -> bool:
        """Atomically replace the configured shortcut when supported."""
        raise NotImplementedError
