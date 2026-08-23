from pathlib import Path

from app.config import ConfigManager
from app.local_ocr.component_manager import LocalOCRComponentManager
from app.settings.repository import SettingsRepository
from app.ui.main_window import MainWindow
from app.ui.settings_window import SettingsWindow


class _SecretStore:
    def get_api_key(self) -> str:
        return ""

    def set_api_key(self, value: str) -> None:
        pass

    def delete_api_key(self) -> None:
        pass


class _Thread:
    def __init__(self, running: bool = True) -> None:
        self.running = running

    def isRunning(self) -> bool:
        return self.running


class _Worker:
    def __init__(self) -> None:
        self.cancel_count = 0

    def request_cancel(self) -> None:
        self.cancel_count += 1


def _settings(tmp_path: Path) -> SettingsWindow:
    config = ConfigManager(
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=_SecretStore(),
    )
    return SettingsWindow(
        config_manager=config,
        component_manager=LocalOCRComponentManager(tmp_path / "runtime"),
    )


def test_shutdown_waits_for_local_ocr_download(qt_app, tmp_path: Path) -> None:
    window = _settings(tmp_path)
    download_thread = _Thread()
    download_worker = _Worker()
    window._download_thread = download_thread
    window._download_worker = download_worker
    ready: list[bool] = []
    window.shutdown_ready.connect(lambda: ready.append(True))

    window.request_shutdown()

    assert download_worker.cancel_count == 1
    assert window.has_running_background_operations()
    assert ready == []
    download_thread.running = False
    window._on_local_ocr_download_finished()
    assert ready == [True]
    window.deleteLater()


def test_shutdown_waits_for_both_settings_operations(qt_app, tmp_path: Path) -> None:
    window = _settings(tmp_path)
    connection_thread = _Thread()
    download_thread = _Thread()
    connection_worker = _Worker()
    download_worker = _Worker()
    window._connection_thread = connection_thread
    window._connection_worker = connection_worker
    window._download_thread = download_thread
    window._download_worker = download_worker
    ready: list[bool] = []
    window.shutdown_ready.connect(lambda: ready.append(True))

    window.request_shutdown()
    assert connection_worker.cancel_count == 1
    assert download_worker.cancel_count == 1
    assert ready == []

    connection_thread.running = False
    window._on_connection_finished()
    assert ready == []
    download_thread.running = False
    window._on_local_ocr_download_finished()
    assert ready == [True]
    window.deleteLater()


def test_close_settings_cancels_download(qt_app, tmp_path: Path) -> None:
    window = _settings(tmp_path)
    thread = _Thread()
    worker = _Worker()
    window._download_thread = thread
    window._download_worker = worker

    window.close()

    assert worker.cancel_count == 1
    window.deleteLater()


def test_main_window_waits_for_any_settings_operation(qt_app) -> None:
    class SettingsInProgress:
        def has_running_background_operations(self) -> bool:
            return True

    window = MainWindow(tray_mode=True)
    window._settings_window = SettingsInProgress()
    window._shutting_down = True
    ready: list[bool] = []
    window.shutdown_ready.connect(lambda: ready.append(True))

    window._maybe_emit_shutdown_ready()
    assert ready == []
    window._settings_window = None
    window._emit_shutdown_ready()
    assert ready == [True]
    window.shutdown()
