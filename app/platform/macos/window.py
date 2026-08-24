"""Small Cocoa bridge for windows that must appear over macOS Spaces."""

from __future__ import annotations

import ctypes
import logging
from ctypes import c_char_p, c_size_t, c_void_p

logger = logging.getLogger(__name__)

NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES = 1 << 0
NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY = 1 << 8
_OVERLAY_BEHAVIOR = (
    NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES
    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
)


class _CocoaWindowBridge:
    """Call only the Objective-C runtime methods needed for one overlay."""

    def __init__(self) -> None:
        self._objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        self._objc.sel_registerName.argtypes = [c_char_p]
        self._objc.sel_registerName.restype = c_void_p
        self._msg_send = self._objc.objc_msgSend

    def _selector(self, name: bytes) -> c_void_p:
        selector = self._objc.sel_registerName(name)
        if not selector:
            raise RuntimeError(f"Cocoa selector unavailable: {name!r}")
        return c_void_p(selector)

    def _send(self, result_type, argument_types, receiver, selector, *arguments):
        function_type = ctypes.CFUNCTYPE(
            result_type,
            c_void_p,
            c_void_p,
            *argument_types,
        )
        function = function_type(self._msg_send)
        return function(receiver, selector, *arguments)

    def configure_overlay(self, widget) -> bool:
        view_pointer = int(widget.winId())
        if not view_pointer:
            return False
        view = c_void_p(view_pointer)
        window = self._send(
            c_void_p,
            [],
            view,
            self._selector(b"window"),
        )
        if not window:
            return False
        behavior = self._send(
            c_size_t,
            [],
            window,
            self._selector(b"collectionBehavior"),
        )
        self._send(
            None,
            [c_size_t],
            window,
            self._selector(b"setCollectionBehavior:"),
            c_size_t(behavior | _OVERLAY_BEHAVIOR),
        )
        return True


def configure_macos_overlay_window(widget, *, bridge=None) -> bool:
    """Make a Qt overlay join the current Space and full-screen Space."""

    try:
        return (bridge or _CocoaWindowBridge()).configure_overlay(widget)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("unable to configure macOS overlay window: %s", exc)
        return False


__all__ = [
    "NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES",
    "NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY",
    "configure_macos_overlay_window",
]
