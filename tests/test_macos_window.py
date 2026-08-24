from __future__ import annotations

from app.capture import overlay as overlay_module
from app.platform.macos.window import (
    NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES,
    NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY,
    NS_WINDOW_COLLECTION_BEHAVIOR_MOVE_TO_ACTIVE_SPACE,
    NS_WINDOW_STYLE_MASK_NONACTIVATING_PANEL,
    _overlay_collection_behavior,
    _overlay_style_mask,
    configure_macos_overlay_window,
)
from app.platform.macos import window as window_module


class _FakeWidget:
    def winId(self) -> int:
        return 123


class _NullWidget:
    def winId(self) -> int:
        return 0


class _FakeBridge:
    def __init__(self) -> None:
        self.widgets = []

    def configure_overlay(self, widget) -> bool:
        self.widgets.append(widget)
        return True

class _FakeOverlay:
    def __init__(self) -> None:
        self.show_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0

    def show(self) -> None:
        self.show_calls += 1

    def raise_(self) -> None:
        self.raise_calls += 1

    def activateWindow(self) -> None:
        self.activate_calls += 1


def test_macos_overlay_bridge_configures_native_window() -> None:
    bridge = _FakeBridge()
    widget = _FakeWidget()

    assert configure_macos_overlay_window(widget, bridge=bridge) is True
    assert bridge.widgets == [widget]


def test_macos_overlay_non_darwin_is_noop(monkeypatch) -> None:
    bridge = _FakeBridge()
    monkeypatch.setattr(window_module.sys, "platform", "win32")

    assert configure_macos_overlay_window(_FakeWidget(), bridge=bridge) is False
    assert bridge.widgets == []


def test_macos_overlay_null_native_view_is_safe() -> None:
    bridge = object.__new__(window_module._CocoaWindowBridge)

    assert bridge.configure_overlay(_NullWidget()) is False


def test_macos_overlay_null_native_window_is_safe() -> None:
    bridge = object.__new__(window_module._CocoaWindowBridge)
    bridge._selector = lambda _name: None
    bridge._send_id = lambda _view, _selector: None

    assert bridge.configure_overlay(_FakeWidget()) is False


def test_macos_overlay_bridge_failure_is_safe() -> None:
    class FailingBridge:
        def configure_overlay(self, _widget) -> bool:
            raise RuntimeError("native bridge test failure")

    assert configure_macos_overlay_window(_FakeWidget(), bridge=FailingBridge()) is False


def test_macos_overlay_uses_space_and_fullscreen_collection_behaviors() -> None:
    assert NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES == 1
    assert NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY == 1 << 8


def test_macos_overlay_replaces_move_to_active_space_behavior() -> None:
    current = (
        NS_WINDOW_COLLECTION_BEHAVIOR_MOVE_TO_ACTIVE_SPACE
        | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
    )

    behavior = _overlay_collection_behavior(current)

    assert behavior & NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES
    assert behavior & NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
    assert not behavior & NS_WINDOW_COLLECTION_BEHAVIOR_MOVE_TO_ACTIVE_SPACE


def test_macos_overlay_preserves_style_bits_and_adds_nonactivating_panel() -> None:
    existing = 14

    style_mask = _overlay_style_mask(existing)

    assert style_mask & existing == existing
    assert style_mask & NS_WINDOW_STYLE_MASK_NONACTIVATING_PANEL


def test_macos_overlay_begin_configures_native_window_without_activation(monkeypatch) -> None:
    overlay = _FakeOverlay()
    configure_calls = []
    monkeypatch.setattr(overlay_module.sys, "platform", "darwin")
    monkeypatch.setattr(overlay_module, "configure_macos_overlay_window", configure_calls.append)

    overlay_module.CaptureOverlay.begin(overlay)

    assert overlay.show_calls == 1
    assert configure_calls == [overlay, overlay]
    assert overlay.raise_calls == 0
    assert overlay.activate_calls == 0
