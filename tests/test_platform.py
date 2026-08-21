from __future__ import annotations

import inspect

from app.platform.base import GlobalHotkeyManager
from app.platform.factory import create_global_hotkey_manager
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
