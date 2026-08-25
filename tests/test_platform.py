from __future__ import annotations

import inspect

from app.platform.base import GlobalHotkeyManager
from app.platform.factory import create_global_hotkey_manager
from app.platform.hotkey import TEXT_HOTKEY_ID, VISION_HOTKEY_ID, HotkeySpec, HotkeySpecError
from app.platform.macos.hotkey import MacOSGlobalHotkey
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
    manager = create_global_hotkey_manager(qt_app, platform_name="linux")

    assert isinstance(manager, UnsupportedGlobalHotkey)
    assert isinstance(manager, GlobalHotkeyManager)
    assert manager.register() is False
    assert manager.registered is False
    manager.unregister()


class _FakeMacHotkeyBackend:
    def __init__(
        self,
        results: list[object | None] | None = None,
        unregister_result: bool = True,
    ) -> None:
        self.results = list(results or [object()])
        self.unregister_result = unregister_result
        self.calls: list[tuple[int, int, int]] = []
        self.unregister_calls: list[object] = []
        self.callback = None

    def register(self, key_code, modifiers, hotkey_id, callback):
        self.calls.append((key_code, modifiers, hotkey_id))
        self.callback = callback
        return self.results.pop(0) if self.results else object()

    def unregister(self, handle) -> bool:
        self.unregister_calls.append(handle)
        return self.unregister_result


def test_factory_selects_macos_implementation(qt_app) -> None:
    manager = create_global_hotkey_manager(qt_app, platform_name="darwin")

    assert isinstance(manager, MacOSGlobalHotkey)
    assert isinstance(manager, GlobalHotkeyManager)
    manager.unregister()


def test_macos_hotkey_register_success_and_trigger(qt_app) -> None:
    backend = _FakeMacHotkeyBackend()
    manager = MacOSGlobalHotkey(qt_app, backend=backend)
    triggered: list[bool] = []
    manager.triggered.connect(lambda: triggered.append(True))

    assert manager.register() is True
    assert manager.registered is True
    assert manager.shortcut == "Ctrl+Shift+Q"
    assert backend.calls[0][0] == 12
    assert backend.calls[0][1] == (1 << 12) | (1 << 9)
    backend.callback(backend.calls[0][2])
    assert triggered == [True]

    manager.unregister()
    assert manager.registered is False
    assert len(backend.unregister_calls) == 1


def test_macos_hotkey_rebind_success(qt_app) -> None:
    backend = _FakeMacHotkeyBackend()
    manager = MacOSGlobalHotkey(qt_app, backend=backend)

    assert manager.register() is True
    assert manager.rebind("Ctrl+Alt+A") is True
    assert manager.shortcut == "Ctrl+Alt+A"
    assert manager.registered is True
    assert [call[2] for call in backend.calls] == [0x5341, 0x5341]
    manager.unregister()


def test_macos_hotkey_rebind_failure_restores_previous_shortcut(qt_app) -> None:
    backend = _FakeMacHotkeyBackend([object(), None, object()])
    manager = MacOSGlobalHotkey(qt_app, backend=backend)

    assert manager.register() is True
    assert manager.rebind("Ctrl+Alt+A") is False
    assert manager.shortcut == "Ctrl+Shift+Q"
    assert manager.registered is True
    assert len(backend.calls) == 3
    manager.unregister()


def test_macos_hotkey_registration_conflict_is_predictable(qt_app) -> None:
    manager = MacOSGlobalHotkey(qt_app, backend=_FakeMacHotkeyBackend([None]))

    assert manager.register() is False
    assert manager.registered is False


def test_macos_hotkey_supported_keys_use_carbon_virtual_key_codes(qt_app) -> None:
    expected = {
        "Ctrl+Shift+Q": (12, (1 << 12) | (1 << 9)),
        "Ctrl+Shift+A": (0, (1 << 12) | (1 << 9)),
        "Ctrl+Shift+W": (13, (1 << 12) | (1 << 9)),
        "Ctrl+Alt+A": (0, (1 << 12) | (1 << 11)),
        "Ctrl+Shift+1": (18, (1 << 12) | (1 << 9)),
        "Ctrl+Shift+F2": (120, (1 << 12) | (1 << 9)),
    }

    for shortcut, registration in expected.items():
        backend = _FakeMacHotkeyBackend()
        manager = MacOSGlobalHotkey(qt_app, shortcut=shortcut, backend=backend)
        assert manager.register() is True
        assert backend.calls[0][:2] == registration
        manager.unregister()


def test_macos_hotkey_rebind_keeps_old_registration_when_unregistration_fails(qt_app) -> None:
    backend = _FakeMacHotkeyBackend(unregister_result=False)
    manager = MacOSGlobalHotkey(qt_app, backend=backend)

    assert manager.register() is True
    assert manager.rebind("Ctrl+Alt+A") is False
    assert manager.shortcut == "Ctrl+Shift+Q"
    assert manager.registered is True
    assert len(backend.calls) == 1
    manager.unregister()


def test_macos_hotkey_rejects_empty_native_registration_handle(qt_app) -> None:
    from ctypes import c_void_p

    manager = MacOSGlobalHotkey(qt_app, backend=_FakeMacHotkeyBackend([c_void_p()]))

    assert manager.register() is False
    assert manager.registered is False


def test_factory_does_not_import_windows_backend_at_module_import() -> None:
    import app.platform.factory as factory_module

    assert not hasattr(factory_module, "WindowsGlobalHotkey")
    assert "from app.platform.windows.hotkey import WindowsGlobalHotkey" in inspect.getsource(factory_module)


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


def test_windows_two_hotkeys_use_distinct_ids_and_filter_events(qt_app) -> None:
    calls: list[tuple] = []

    def register(hwnd, hotkey_id, modifiers, key) -> int:
        calls.append(("register", hotkey_id, modifiers, key))
        return 1

    def unregister(hwnd, hotkey_id) -> int:
        calls.append(("unregister", hotkey_id))
        return 1

    text = WindowsGlobalHotkey(
        qt_app,
        register,
        unregister,
        hotkey_id=TEXT_HOTKEY_ID,
    )
    vision = WindowsGlobalHotkey(
        qt_app,
        register,
        unregister,
        shortcut="Ctrl+Shift+W",
        hotkey_id=VISION_HOTKEY_ID,
    )
    text_events: list[bool] = []
    vision_events: list[bool] = []
    text.triggered.connect(lambda: text_events.append(True))
    vision.triggered.connect(lambda: vision_events.append(True))

    assert text.register() is True
    assert vision.register() is True
    assert [call[1] for call in calls[:2]] == [TEXT_HOTKEY_ID, VISION_HOTKEY_ID]
    assert text.handle_hotkey(TEXT_HOTKEY_ID) is True
    assert text.handle_hotkey(VISION_HOTKEY_ID) is False
    assert vision.handle_hotkey(VISION_HOTKEY_ID) is True
    assert vision.handle_hotkey(TEXT_HOTKEY_ID) is False
    assert text_events == [True]
    assert vision_events == [True]
    text.unregister()
    vision.unregister()
    assert calls[-2:] == [("unregister", TEXT_HOTKEY_ID), ("unregister", VISION_HOTKEY_ID)]


def test_macos_two_hotkeys_pass_distinct_ids_to_carbon_backend(qt_app) -> None:
    text_backend = _FakeMacHotkeyBackend()
    vision_backend = _FakeMacHotkeyBackend()
    text = MacOSGlobalHotkey(qt_app, backend=text_backend, hotkey_id=TEXT_HOTKEY_ID)
    vision = MacOSGlobalHotkey(
        qt_app,
        shortcut="Ctrl+Shift+W",
        backend=vision_backend,
        hotkey_id=VISION_HOTKEY_ID,
    )

    assert text.register() is True
    assert vision.register() is True
    assert text_backend.calls[0][2] == TEXT_HOTKEY_ID
    assert vision_backend.calls[0][2] == VISION_HOTKEY_ID
    text_events: list[bool] = []
    vision_events: list[bool] = []
    text.triggered.connect(lambda: text_events.append(True))
    vision.triggered.connect(lambda: vision_events.append(True))
    text_backend.callback(VISION_HOTKEY_ID)
    vision_backend.callback(TEXT_HOTKEY_ID)
    text_backend.callback(TEXT_HOTKEY_ID)
    vision_backend.callback(VISION_HOTKEY_ID)
    assert text_events == [True]
    assert vision_events == [True]
    text.unregister()
    vision.unregister()
