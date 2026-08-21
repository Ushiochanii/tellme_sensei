"""Windows RegisterHotKey implementation behind the platform interface."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject

from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import DEFAULT_SHORTCUT, HotkeySpec, HotkeySpecError

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
MOD_SHIFT = 0x0004
VK_Q = 0x51
HOTKEY_ID = 0x5341

_MODIFIER_BITS = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT}
_KEY_CODES = {
    **{letter: ord(letter) for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{str(number): 0x30 + number for number in range(10)},
    **{f"F{number}": 0x6F + number for number in range(1, 13)},
}


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


class WindowsGlobalHotkey(GlobalHotkeyManager, QAbstractNativeEventFilter):
    """Register a simple shortcut and route WM_HOTKEY into a Qt signal."""

    def __init__(
        self,
        parent: QObject | None = None,
        register_func: Callable[[object, int, int, int], int] | None = None,
        unregister_func: Callable[[object, int], int] | None = None,
        *,
        shortcut: str = DEFAULT_SHORTCUT,
    ) -> None:
        GlobalHotkeyManager.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self.hotkey_id = HOTKEY_ID
        try:
            self._spec = HotkeySpec.parse(shortcut)
        except HotkeySpecError:
            logger.warning("invalid shortcut %r; falling back to %s", shortcut, DEFAULT_SHORTCUT)
            self._spec = HotkeySpec.parse(DEFAULT_SHORTCUT)
        self.modifiers = 0
        self.virtual_key = 0
        self._apply_spec(self._spec)
        self._registered = False
        self._register_func = register_func
        self._unregister_func = unregister_func

        if self._register_func is None and sys.platform == "win32":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._register_func = user32.RegisterHotKey
            self._unregister_func = user32.UnregisterHotKey

    @property
    def registered(self) -> bool:
        return self._registered

    @property
    def shortcut(self) -> str:
        return self._spec.canonical

    def register(self) -> bool:
        if self._registered:
            return True
        logger.info("global hotkey registration requested")
        if self._register_func is None:
            logger.error("Global hotkey registration failed: %s", self.shortcut)
            return False
        try:
            result = self._register_func(None, self.hotkey_id, self.modifiers, self.virtual_key)
        except OSError:
            result = 0
        if not result:
            logger.error("Global hotkey registration failed: %s", self.shortcut)
            return False

        application = self._application()
        if application is not None:
            application.installNativeEventFilter(self)
        self._registered = True
        logger.info("global hotkey registered")
        return True

    def unregister(self) -> None:
        application = self._application()
        if application is not None:
            application.removeNativeEventFilter(self)
        if self._registered and self._unregister_func is not None:
            try:
                self._unregister_func(None, self.hotkey_id)
            except OSError:
                logger.exception("global hotkey unregister failed")
        self._registered = False
        logger.info("global hotkey unregistered")

    def rebind(self, shortcut: str) -> bool:
        try:
            new_spec = HotkeySpec.parse(shortcut)
        except HotkeySpecError:
            logger.warning("invalid global hotkey shortcut: %s", shortcut)
            return False

        if new_spec == self._spec and self._registered:
            return True

        old_spec = self._spec
        was_registered = self._registered
        if was_registered:
            self.unregister()
        self._spec = new_spec
        self._apply_spec(new_spec)
        if self.register():
            return True

        self._spec = old_spec
        self._apply_spec(old_spec)
        if was_registered and not self.register():
            logger.error("global hotkey rollback failed: %s", old_spec.canonical)
        return False

    def _apply_spec(self, spec: HotkeySpec) -> None:
        self.modifiers = sum(_MODIFIER_BITS[modifier] for modifier in spec.modifiers)
        self.virtual_key = _KEY_CODES[spec.key]

    def handle_hotkey(self, hotkey_id: int) -> bool:
        if hotkey_id != self.hotkey_id:
            return False
        logger.info("global hotkey triggered")
        self.triggered.emit()
        return True

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt API name
        if not self._registered:
            return False, 0
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG", "windows_generic_MSG"):
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            if msg.message == WM_HOTKEY and self.handle_hotkey(int(msg.wParam)):
                return True, 0
        except (TypeError, ValueError, OSError):
            logger.exception("failed to parse native hotkey event")
        return False, 0

    @staticmethod
    def _application():
        from PySide6.QtCore import QCoreApplication

        return QCoreApplication.instance()
