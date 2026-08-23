from __future__ import annotations

import threading
import time

from app.config import AppConfig
from app.ui.main_window import MainWindow


class _Config:
    def __init__(self, provider: str = "local") -> None:
        self.provider = provider

    def load(self, require_api_key: bool = True) -> AppConfig:
        return AppConfig(api_key="", ocr_provider=self.provider)


class _ComponentManager:
    version = "1.0.0"

    def __init__(self, installed: bool) -> None:
        self.installed = installed

    def is_installed(self) -> bool:
        return self.installed


class _Session:
    capability_unsupported = False

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.prepare_calls = 0
        self.stop_calls = 0
        self.running = False
        self.busy = False

    def is_running(self) -> bool:
        return self.running

    def is_busy(self) -> bool:
        return self.busy

    def is_preparing(self) -> bool:
        return self.busy

    def prepare(self, cancel_event: threading.Event | None = None) -> None:
        self.prepare_calls += 1
        self.busy = True
        if self.delay:
            time.sleep(self.delay)
        if cancel_event is not None and cancel_event.is_set():
            return
        self.running = True
        self.busy = False

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False
        self.busy = False

    def reset_capability(self) -> None:
        self.capability_unsupported = False


def _finish(qt_app, window: MainWindow) -> None:
    for _ in range(100):
        qt_app.processEvents()
        if window._prewarm_thread is None:
            return
        time.sleep(0.01)
        qt_app.processEvents()


def test_local_installed_schedules_one_prewarm(qt_app) -> None:
    session = _Session(delay=0.05)
    window = MainWindow(
        tray_mode=True,
        config_manager=_Config("local"),
        local_ocr_session=session,
        component_manager=_ComponentManager(True),
    )

    window.request_local_ocr_prewarm()
    window.request_local_ocr_prewarm()
    _finish(qt_app, window)

    assert session.prepare_calls == 1
    assert session.running is True
    window.shutdown()


def test_prewarm_is_skipped_without_component_or_for_online(qt_app) -> None:
    for provider, installed in (("local", False), ("google_vision", True)):
        session = _Session()
        window = MainWindow(
            tray_mode=True,
            config_manager=_Config(provider),
            local_ocr_session=session,
            component_manager=_ComponentManager(installed),
        )
        window.request_local_ocr_prewarm()
        qt_app.processEvents()
        assert session.prepare_calls == 0
        window.shutdown()


def test_online_save_cancels_prewarm_and_stops_session(qt_app) -> None:
    config = _Config("local")
    session = _Session(delay=0.2)
    window = MainWindow(
        tray_mode=True,
        config_manager=config,
        local_ocr_session=session,
        component_manager=_ComponentManager(True),
    )
    window.request_local_ocr_prewarm()
    config.provider = "google_vision"
    window._on_settings_saved()
    _finish(qt_app, window)

    assert session.stop_calls >= 1
    _finish(qt_app, window)
    window.shutdown()
