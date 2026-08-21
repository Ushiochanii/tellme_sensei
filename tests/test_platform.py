from __future__ import annotations

import inspect

from app.platform.base import GlobalHotkeyManager
from app.platform.factory import create_global_hotkey_manager
from app.platform.hotkey import HotkeySpec, HotkeySpecError
from app.platform.unsupported import UnsupportedGlobalHotkey
from app.platform.windows import hotkey as windows_hotkey
from app.platform.windows.hotkey import WindowsGlobalHotkey
from app.ui import application_controller


def test_factory_selects_windows_implementation(qt_app) -> None:
    manager = create_global_hotkey_manager(
        qt_app,
        platform_name="win32",
        register_func=lambda *_args: 1,
        unregister_func=lambda *_args: 1,
    )

    assert isinstance(manager, WindowsGlobalHotkey)
    assert isinstance(manager, GlobalHotkeyManager)
    assert manager.register() is True
    manager.unregister()


def test_factory_returns_predictable_unsupported_platform(qt_app) -> None:
    manager = create_global_hotkey_manager(qt_app, platform_name="darwin")

    assert isinstance(manager, UnsupportedGlobalHotkey)
    assert isinstance(manager, GlobalHotkeyManager)
    assert manager.register() is False
    assert manager.registered is False
    manager.unregister()


def test_win32_integration_is_confined_to_platform_layer() -> None:
    source = inspect.getsource(application_controller)

    assert "windows_hotkey" not in source
    assert "RegisterHotKey" not in source
    assert "ctypes" not in source
    assert windows_hotkey.WM_HOTKEY == 0x0312


def test_hotkey_spec_normalizes_supported_shortcuts() -> None:
    assert HotkeySpec.parse("shift+ctrl+f2").canonical == "Ctrl+Shift+F2"
    assert HotkeySpec.parse("Alt+0").canonical == "Alt+0"


def test_hotkey_spec_rejects_unsupported_shortcuts() -> None:
    for shortcut in ("Q", "Ctrl+Win+Q", "Ctrl+Q+A", "Ctrl+Ctrl+Q"):
        try:
            HotkeySpec.parse(shortcut)
        except HotkeySpecError:
            continue
        raise AssertionError(f"shortcut should be rejected: {shortcut}")


def test_windows_rebind_success_releases_old_and_registers_new(qt_app) -> None:
    calls: list[tuple] = []

    def register(hwnd, hotkey_id, modifiers, key) -> int:
        calls.append(("register", modifiers, key))
        return 1

    def unregister(hwnd, hotkey_id) -> int:
        calls.append(("unregister", hotkey_id))
        return 1

    manager = WindowsGlobalHotkey(qt_app, register, unregister)
    assert manager.register() is True
    assert manager.rebind("Ctrl+Alt+A") is True
    assert manager.shortcut == "Ctrl+Alt+A"
    assert manager.registered is True
    assert [call[0] for call in calls] == ["register", "unregister", "register"]
    manager.unregister()


def test_windows_rebind_failure_restores_old_shortcut(qt_app) -> None:
    calls: list[tuple] = []

    def register(hwnd, hotkey_id, modifiers, key) -> int:
        calls.append(("register", key))
        return 0 if key == ord("A") else 1

    def unregister(hwnd, hotkey_id) -> int:
        calls.append(("unregister", hotkey_id))
        return 1

    manager = WindowsGlobalHotkey(qt_app, register, unregister)
    assert manager.register() is True
    assert manager.rebind("Ctrl+Alt+A") is False
    assert manager.shortcut == "Ctrl+Shift+Q"
    assert manager.registered is True
    assert calls[-1] == ("register", ord("Q"))
    manager.unregister()
