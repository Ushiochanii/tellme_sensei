from __future__ import annotations

from app.capture import overlay as overlay_module
from app.platform.macos.window import (
    NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES,
    NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY,
    configure_macos_overlay_window,
)


class _FakeWidget:
    def winId(self) -> int:
        return 123


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


def test_macos_overlay_uses_space_and_fullscreen_collection_behaviors() -> None:
    assert NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES == 1
    assert NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY == 1 << 8


def test_macos_overlay_begin_does_not_activate_the_application(monkeypatch) -> None:
    overlay = _FakeOverlay()
    configure_calls = []
    monkeypatch.setattr(overlay_module.sys, "platform", "darwin")
    monkeypatch.setattr(overlay_module, "configure_macos_overlay_window", configure_calls.append)

    overlay_module.CaptureOverlay.begin(overlay)

    assert overlay.show_calls == 1
    assert configure_calls == [overlay, overlay]
    assert overlay.raise_calls == 0
    assert overlay.activate_calls == 0
