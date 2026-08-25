"""Carbon RegisterEventHotKey implementation for macOS."""

from __future__ import annotations

import ctypes
import logging
from ctypes import POINTER, byref, c_int32, c_uint32, c_void_p
from typing import Callable

from PySide6.QtCore import QObject

from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import DEFAULT_SHORTCUT, TEXT_HOTKEY_ID, HotkeySpec, HotkeySpecError

logger = logging.getLogger(__name__)

CARBON_FRAMEWORK = "/System/Library/Frameworks/Carbon.framework/Carbon"
NO_ERR = 0

# Carbon Event Manager constants from HIToolbox/Events.h.
K_EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
K_EVENT_HOT_KEY_PRESSED = 5
K_EVENT_PARAM_DIRECT_OBJECT = int.from_bytes(b"----", "big")
TYPE_EVENT_HOT_KEY_ID = int.from_bytes(b"hkid", "big")
CONTROL_KEY = 1 << 12
OPTION_KEY = 1 << 11
SHIFT_KEY = 1 << 9

_KEY_CODES = {
    "A": 0,
    "B": 11,
    "C": 8,
    "D": 2,
    "E": 14,
    "F": 3,
    "G": 5,
    "H": 4,
    "I": 34,
    "J": 38,
    "K": 40,
    "L": 37,
    "M": 46,
    "N": 45,
    "O": 31,
    "P": 35,
    "Q": 12,
    "R": 15,
    "S": 1,
    "T": 17,
    "U": 32,
    "V": 9,
    "W": 13,
    "X": 7,
    "Y": 16,
    "Z": 6,
    "0": 29,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "5": 23,
    "6": 22,
    "7": 26,
    "8": 28,
    "9": 25,
    "F1": 122,
    "F2": 120,
    "F3": 99,
    "F4": 118,
    "F5": 96,
    "F6": 97,
    "F7": 98,
    "F8": 100,
    "F9": 101,
    "F10": 109,
    "F11": 103,
    "F12": 111,
}
_MODIFIER_BITS = {"Ctrl": CONTROL_KEY, "Alt": OPTION_KEY, "Shift": SHIFT_KEY}
HOTKEY_SIGNATURE = int.from_bytes(b"TMSH", "big")
# Backward-compatible name for the original Text Mode registration ID.
HOTKEY_ID = TEXT_HOTKEY_ID


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("event_class", c_uint32), ("event_kind", c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", c_uint32), ("id", c_uint32)]


_EventHandler = ctypes.CFUNCTYPE(c_int32, c_void_p, c_void_p, c_void_p)


class _CarbonHotkeyBackend:
    """Small ctypes wrapper around Carbon's application hotkey API."""

    def __init__(self) -> None:
        self._carbon = ctypes.CDLL(CARBON_FRAMEWORK)
        self._configure_functions()
        self._callback: Callable[[int], None] | None = None
        self._native_callback = _EventHandler(self._handle_event)
        self._handler_ref = c_void_p()

    def _configure_functions(self) -> None:
        carbon = self._carbon
        carbon.GetApplicationEventTarget.restype = c_void_p
        carbon.InstallEventHandler.argtypes = [
            c_void_p,
            _EventHandler,
            c_uint32,
            POINTER(_EventTypeSpec),
            c_void_p,
            POINTER(c_void_p),
        ]
        carbon.InstallEventHandler.restype = c_int32
        carbon.RemoveEventHandler.argtypes = [c_void_p]
        carbon.RemoveEventHandler.restype = c_int32
        carbon.RegisterEventHotKey.argtypes = [
            c_uint32,
            c_uint32,
            _EventHotKeyID,
            c_void_p,
            c_uint32,
            POINTER(c_void_p),
        ]
        carbon.RegisterEventHotKey.restype = c_int32
        carbon.UnregisterEventHotKey.argtypes = [c_void_p]
        carbon.UnregisterEventHotKey.restype = c_int32
        carbon.GetEventParameter.argtypes = [
            c_void_p,
            c_uint32,
            c_uint32,
            c_void_p,
            c_uint32,
            c_void_p,
            c_void_p,
        ]
        carbon.GetEventParameter.restype = c_int32

    def register(
        self,
        key_code: int,
        modifiers: int,
        hotkey_id: int,
        callback: Callable[[int], None],
    ) -> c_void_p | None:
        self._callback = callback
        event_type = _EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOT_KEY_PRESSED)
        target = self._carbon.GetApplicationEventTarget()
        status = self._carbon.InstallEventHandler(
            target,
            self._native_callback,
            1,
            byref(event_type),
            None,
            byref(self._handler_ref),
        )
        if status != NO_ERR:
            logger.error("macOS hotkey event handler installation failed: %s", status)
            self._callback = None
            return None

        native_ref = c_void_p()
        hotkey = _EventHotKeyID(HOTKEY_SIGNATURE, hotkey_id)
        status = self._carbon.RegisterEventHotKey(
            key_code,
            modifiers,
            hotkey,
            target,
            0,
            byref(native_ref),
        )
        logger.debug(
            "macOS RegisterEventHotKey key_code=%s modifiers=%s id=%s status=%s ref=%s",
            key_code,
            modifiers,
            hotkey_id,
            status,
            native_ref.value,
        )
        if status != NO_ERR:
            logger.warning("macOS hotkey registration failed: status=%s", status)
            self._remove_handler()
            return None
        if not native_ref.value:
            logger.error("macOS hotkey registration returned no EventHotKeyRef")
            self._remove_handler()
            return None
        logger.debug(
            "macOS hotkey registration active id=%s ref=%s",
            hotkey_id,
            native_ref.value,
        )
        return native_ref

    def unregister(self, native_ref: c_void_p) -> bool:
        status = self._carbon.UnregisterEventHotKey(native_ref)
        logger.debug("macOS UnregisterEventHotKey status=%s", status)
        if status != NO_ERR:
            logger.warning("macOS hotkey unregister failed: status=%s", status)
            return False
        self._remove_handler()
        return True

    def _remove_handler(self) -> None:
        if self._handler_ref.value:
            self._carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = c_void_p()
        self._callback = None

    def _handle_event(self, _next_handler, event, _user_data) -> int:
        logger.debug("macOS Carbon hotkey callback entered event=%s", event)
        hotkey = _EventHotKeyID()
        status = self._carbon.GetEventParameter(
            event,
            K_EVENT_PARAM_DIRECT_OBJECT,
            TYPE_EVENT_HOT_KEY_ID,
            None,
            ctypes.sizeof(hotkey),
            None,
            byref(hotkey),
        )
        logger.debug(
            "macOS Carbon hotkey event parameter status=%s signature=%s id=%s expected_signature=%s",
            status,
            hotkey.signature,
            hotkey.id,
            HOTKEY_SIGNATURE,
        )
        if status != NO_ERR:
            logger.debug("macOS Carbon hotkey callback ignored: parameter read failed")
            return NO_ERR
        if hotkey.signature != HOTKEY_SIGNATURE:
            logger.debug("macOS Carbon hotkey callback ignored: signature mismatch")
            return NO_ERR
        if self._callback is None:
            logger.debug("macOS Carbon hotkey callback ignored: callback is not active")
            return NO_ERR
        try:
            self._callback(hotkey.id)
        except Exception:
            logger.exception("macOS hotkey callback failed")
        return NO_ERR


class MacOSGlobalHotkey(GlobalHotkeyManager):
    """Register one simple global shortcut through Carbon."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        shortcut: str = DEFAULT_SHORTCUT,
        hotkey_id: int = TEXT_HOTKEY_ID,
        backend: object | None = None,
    ) -> None:
        super().__init__(parent)
        try:
            self._spec = HotkeySpec.parse(shortcut)
        except HotkeySpecError:
            logger.warning("invalid shortcut %r; falling back to %s", shortcut, DEFAULT_SHORTCUT)
            self._spec = HotkeySpec.parse(DEFAULT_SHORTCUT)
        self._backend = backend
        self.hotkey_id = hotkey_id
        self._native_handle: c_void_p | object | None = None
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    @property
    def shortcut(self) -> str:
        return self._spec.canonical

    def register(self) -> bool:
        if self._registered:
            return True
        try:
            backend = self._backend_instance()
            key_code = _KEY_CODES[self._spec.key]
            modifiers = self._modifier_mask(self._spec)
            logger.debug(
                "macOS hotkey register requested shortcut=%s key_code=%s modifiers=%s id=%s",
                self.shortcut,
                key_code,
                modifiers,
                self.hotkey_id,
            )
            handle = backend.register(
                key_code,
                modifiers,
                self.hotkey_id,
                self._on_native_hotkey,
            )
        except (OSError, RuntimeError, KeyError) as exc:
            logger.warning("macOS global hotkey registration unavailable: %s", type(exc).__name__)
            return False
        if handle is None or (isinstance(handle, c_void_p) and not handle.value):
            logger.warning("macOS global hotkey registration failed: %s", self.shortcut)
            return False
        self._native_handle = handle
        self._registered = True
        return True

    def unregister(self) -> None:
        if not self._release_native_registration():
            logger.warning("macOS global hotkey remains registered after unregister failure")

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
        if was_registered and not self._release_native_registration():
            logger.error("macOS global hotkey rebind could not release the old registration")
            return False
        self._spec = new_spec
        if self.register():
            return True

        self._spec = old_spec
        if was_registered and not self.register():
            logger.error("macOS global hotkey rollback failed: %s", old_spec.canonical)
        return False

    def _release_native_registration(self) -> bool:
        if not self._registered or self._native_handle is None:
            self._native_handle = None
            self._registered = False
            return True
        try:
            result = self._backend_instance().unregister(self._native_handle)
        except (OSError, RuntimeError) as exc:
            logger.warning("macOS global hotkey unregister failed: %s", type(exc).__name__)
            return False
        if result is False:
            return False
        self._native_handle = None
        self._registered = False
        return True

    def _backend_instance(self):
        if self._backend is None:
            self._backend = _CarbonHotkeyBackend()
        return self._backend

    @staticmethod
    def _modifier_mask(spec: HotkeySpec) -> int:
        return sum(_MODIFIER_BITS[modifier] for modifier in spec.modifiers)

    def _on_native_hotkey(self, hotkey_id: int) -> None:
        if not self._registered:
            logger.debug("macOS hotkey callback ignored: manager is not registered")
            return
        if hotkey_id != self.hotkey_id:
            logger.debug(
                "macOS hotkey callback ignored: id=%s expected_id=%s",
                hotkey_id,
                self.hotkey_id,
            )
            return
        logger.info("macOS global hotkey triggered id=%s", hotkey_id)
        self.triggered.emit()


__all__ = ["MacOSGlobalHotkey"]
