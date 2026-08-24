from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from app.platform import screen_permissions
from app.state import AppState
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow


class _FakeFunction:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.argtypes = None
        self.restype = None

    def __call__(self) -> bool:
        return self.result


class _FakeCoreGraphics:
    def __init__(self, *, preflight: bool, request: bool) -> None:
        self.CGPreflightScreenCaptureAccess = _FakeFunction(preflight)
        self.CGRequestScreenCaptureAccess = _FakeFunction(request)


def _darwin(monkeypatch) -> None:
    monkeypatch.setattr(screen_permissions, "sys", SimpleNamespace(platform="darwin"))


def test_screen_permission_preflight_true(monkeypatch) -> None:
    _darwin(monkeypatch)
    library = _FakeCoreGraphics(preflight=True, request=False)
    monkeypatch.setattr(screen_permissions, "_load_core_graphics", lambda: library)

    assert screen_permissions.has_screen_recording_permission() is True


def test_screen_permission_preflight_false(monkeypatch) -> None:
    _darwin(monkeypatch)
    library = _FakeCoreGraphics(preflight=False, request=False)
    monkeypatch.setattr(screen_permissions, "_load_core_graphics", lambda: library)

    assert screen_permissions.has_screen_recording_permission() is False


def test_screen_permission_request_true(monkeypatch, qt_app) -> None:
    _darwin(monkeypatch)
    library = _FakeCoreGraphics(preflight=False, request=True)
    monkeypatch.setattr(screen_permissions, "_load_core_graphics", lambda: library)

    assert screen_permissions.request_screen_recording_permission() is True


def test_screen_permission_request_false(monkeypatch, qt_app) -> None:
    _darwin(monkeypatch)
    library = _FakeCoreGraphics(preflight=False, request=False)
    monkeypatch.setattr(screen_permissions, "_load_core_graphics", lambda: library)

    assert screen_permissions.request_screen_recording_permission() is False


def test_screen_permission_core_graphics_failure_is_safe(monkeypatch, qt_app) -> None:
    _darwin(monkeypatch)

    def fail_load():
        raise OSError("CoreGraphics unavailable")

    monkeypatch.setattr(screen_permissions, "_load_core_graphics", fail_load)

    assert screen_permissions.has_screen_recording_permission() is False
    assert screen_permissions.request_screen_recording_permission() is False


def test_non_macos_screen_permission_is_available(monkeypatch) -> None:
    monkeypatch.setattr(screen_permissions, "sys", SimpleNamespace(platform="win32"))

    assert screen_permissions.has_screen_recording_permission() is True
    assert screen_permissions.request_screen_recording_permission() is True


class _FakeOverlay(QObject):
    captured = Signal(object)
    cancelled = Signal()

    def __init__(self, **_kwargs) -> None:
        super().__init__()
        self.begin_calls = 0

    def begin(self) -> None:
        self.begin_calls += 1


def test_main_window_permission_available_starts_capture(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(main_window_module, "CaptureOverlay", _FakeOverlay)
    monkeypatch.setattr(main_window_module.screen_permissions, "has_screen_recording_permission", lambda: True)

    window = MainWindow(tray_mode=True)

    assert window.start_capture() is True
    assert isinstance(window._overlay, _FakeOverlay)
    assert window._overlay.begin_calls == 1
    assert window.state is AppState.CAPTURING
    window._on_capture_cancelled()
    window.shutdown()


def test_main_window_permission_denial_stays_idle_and_does_not_retry_request(qt_app, monkeypatch) -> None:
    calls = {"preflight": 0, "request": 0, "messages": 0}

    def preflight() -> bool:
        calls["preflight"] += 1
        return False

    def request() -> bool:
        calls["request"] += 1
        return False

    monkeypatch.setattr(main_window_module.screen_permissions, "has_screen_recording_permission", preflight)
    monkeypatch.setattr(main_window_module.screen_permissions, "request_screen_recording_permission", request)
    monkeypatch.setattr(
        MainWindow,
        "_show_screen_recording_permission_error",
        lambda _self: calls.__setitem__("messages", calls["messages"] + 1),
    )

    window = MainWindow(tray_mode=True)

    assert window.start_capture() is False
    assert window.state is AppState.IDLE
    assert window._busy is False
    assert window._overlay is None
    assert calls == {"preflight": 2, "request": 1, "messages": 1}

    assert window.start_capture() is False
    assert window.state is AppState.IDLE
    assert window._busy is False
    assert calls == {"preflight": 3, "request": 1, "messages": 2}
    window.shutdown()


def test_main_window_permission_exception_stays_idle(qt_app, monkeypatch) -> None:
    messages: list[bool] = []
    monkeypatch.setattr(
        main_window_module.screen_permissions,
        "has_screen_recording_permission",
        lambda: (_ for _ in ()).throw(RuntimeError("permission failure")),
    )
    monkeypatch.setattr(MainWindow, "_show_screen_recording_permission_error", lambda _self: messages.append(True))

    window = MainWindow(tray_mode=True)

    assert window.start_capture() is False
    assert window.state is AppState.IDLE
    assert window._busy is False
    assert window._overlay is None
    assert messages == [True]
    window.shutdown()
