"""Small Cocoa bridge for windows that must appear over macOS Spaces."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import c_bool, c_char_p, c_size_t, c_void_p

from PySide6.QtCore import QCoreApplication, QThread

logger = logging.getLogger(__name__)

NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES = 1 << 0
NS_WINDOW_COLLECTION_BEHAVIOR_MOVE_TO_ACTIVE_SPACE = 1 << 1
NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_PRIMARY = 1 << 7
NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY = 1 << 8
NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_NONE = 1 << 9
NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_ALLOWS_TILING = 1 << 11
NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_DISALLOWS_TILING = 1 << 12
NS_WINDOW_STYLE_MASK_NONACTIVATING_PANEL = 1 << 7
_OVERLAY_BEHAVIOR = (
    NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES
    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
)
_INCOMPATIBLE_OVERLAY_BEHAVIORS = (
    NS_WINDOW_COLLECTION_BEHAVIOR_MOVE_TO_ACTIVE_SPACE
    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_PRIMARY
    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_NONE
    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_ALLOWS_TILING
    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_DISALLOWS_TILING
)

_ObjCMsgSendID = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p)
_ObjCMsgSendNSUInteger = ctypes.CFUNCTYPE(c_size_t, c_void_p, c_void_p)
_ObjCMsgSendSetNSUInteger = ctypes.CFUNCTYPE(
    None,
    c_void_p,
    c_void_p,
    c_size_t,
)
_ObjCMsgSendSetBool = ctypes.CFUNCTYPE(
    None,
    c_void_p,
    c_void_p,
    c_bool,
)


def _overlay_collection_behavior(current: int) -> int:
    """Replace mutually exclusive Space/full-screen choices safely."""

    return (current & ~_INCOMPATIBLE_OVERLAY_BEHAVIORS) | _OVERLAY_BEHAVIOR


def _overlay_style_mask(current: int) -> int:
    """Preserve Qt's style bits while making the panel non-activating."""

    return current | NS_WINDOW_STYLE_MASK_NONACTIVATING_PANEL


class _CocoaWindowBridge:
    """Call only the Objective-C runtime methods needed for one overlay."""

    def __init__(self) -> None:
        self._objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        self._objc.sel_registerName.argtypes = [c_char_p]
        self._objc.sel_registerName.restype = c_void_p
        msg_send = self._objc.objc_msgSend
        self._send_id = ctypes.cast(msg_send, _ObjCMsgSendID)
        self._send_uint = ctypes.cast(msg_send, _ObjCMsgSendNSUInteger)
        self._send_set_uint = ctypes.cast(msg_send, _ObjCMsgSendSetNSUInteger)
        self._send_set_bool = ctypes.cast(msg_send, _ObjCMsgSendSetBool)

    def _selector(self, name: bytes) -> c_void_p:
        selector = self._objc.sel_registerName(name)
        if not selector:
            raise RuntimeError(f"Cocoa selector unavailable: {name!r}")
        return c_void_p(selector)

    def _window_for_widget(self, widget) -> c_void_p | None:
        view_pointer = int(widget.winId())
        if view_pointer <= 0:
            return None
        window_pointer = self._send_id(
            c_void_p(view_pointer),
            self._selector(b"window"),
        )
        if not window_pointer:
            return None
        return c_void_p(window_pointer)

    def _assert_gui_thread(self) -> bool:
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() != app.thread():
            logger.warning("macOS overlay window operation must run on the GUI thread")
            return False
        return True

    def configure_overlay(self, widget, *, ignores_mouse_events=False) -> bool:
        if not self._assert_gui_thread():
            return False

        window = self._window_for_widget(widget)
        if window is None:
            return False
        behavior = self._send_uint(window, self._selector(b"collectionBehavior"))
        self._send_set_uint(
            window,
            self._selector(b"setCollectionBehavior:"),
            _overlay_collection_behavior(behavior),
        )
        style_mask = self._send_uint(window, self._selector(b"styleMask"))
        self._send_set_uint(
            window,
            self._selector(b"setStyleMask:"),
            _overlay_style_mask(style_mask),
        )
        self._send_set_bool(
            window,
            self._selector(b"setHidesOnDeactivate:"),
            False,
        )
        if ignores_mouse_events:
            self._send_set_bool(
                window,
                self._selector(b"setIgnoresMouseEvents:"),
                True,
            )
        return True


def configure_macos_overlay_window(
    widget, *, ignores_mouse_events=False, bridge=None
) -> bool:
    """Make a Qt overlay join the current Space and full-screen Space."""

    if sys.platform != "darwin":
        return False
    try:
        active_bridge = bridge or _CocoaWindowBridge()
        if ignores_mouse_events:
            return active_bridge.configure_overlay(
                widget, ignores_mouse_events=True
            )
        return active_bridge.configure_overlay(widget)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, OverflowError) as exc:
        logger.warning("unable to configure macOS overlay window: %s", exc)
        return False


__all__ = [
    "NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES",
    "NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY",
    "NS_WINDOW_STYLE_MASK_NONACTIVATING_PANEL",
    "configure_macos_overlay_window",
]
