from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer

from app.config import ConfigManager
from app.settings.repository import SettingsRepository
from app.ui.settings_window import SettingsWindow
from app.update_service import ReleaseAsset, UpdateCheckResult, UpdateError
from app.version import __version__


class FakeUpdateService:
    def __init__(
        self,
        result: UpdateCheckResult | None = None,
        *,
        check_error: str | None = None,
    ) -> None:
        self.result = result or UpdateCheckResult(
            current_version=__version__,
            latest_version="0.8.2",
            update_available=True,
            asset=ReleaseAsset(
                "TellMeSensei-Setup-0.8.2.exe",
                "https://example.invalid/TellMeSensei-Setup-0.8.2.exe",
            ),
        )
        self.check_error = check_error
        self.check_threads: list[int] = []
        self.download_threads: list[int] = []
        self.downloaded_assets: list[ReleaseAsset] = []

    def check_for_update(self, current_version: str, cancel_event) -> UpdateCheckResult:
        self.check_threads.append(threading.get_ident())
        assert current_version == __version__
        if cancel_event.is_set():
            raise RuntimeError("cancelled before fake check")
        if self.check_error is not None:
            raise UpdateError(self.check_error)
        return self.result

    def download_and_launch(self, asset: ReleaseAsset, cancel_event) -> Path:
        self.download_threads.append(threading.get_ident())
        if cancel_event.is_set():
            raise RuntimeError("cancelled before fake download")
        self.downloaded_assets.append(asset)
        return Path("downloaded-update") / asset.name


class SlowUpdateService(FakeUpdateService):
    def check_for_update(self, current_version: str, cancel_event) -> UpdateCheckResult:
        self.check_threads.append(threading.get_ident())
        assert current_version == __version__
        deadline = time.monotonic() + 1.0
        while not cancel_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        from app.update_service import UpdateCancelled

        raise UpdateCancelled("Update cancelled")


def _manager(tmp_path) -> ConfigManager:
    return ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
    )


def _wait_until(qt_app, predicate, timeout_ms: int = 2000) -> None:
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    qt_app.processEvents()
    assert predicate()


def test_updates_page_checks_and_launches_new_release_off_gui_thread(
    qt_app, tmp_path
) -> None:
    main_thread = threading.get_ident()
    service = FakeUpdateService()
    window = SettingsWindow(
        _manager(tmp_path),
        update_service=service,
        local_ocr_supported=False,
    )

    assert [button.text() for button in window._navigation_buttons][-3:] == [
        "Updates",
        "Debug",
        "Language",
    ]
    assert window.current_version_label.text() == __version__
    assert window.latest_version_label.text() == "Not checked"
    assert window.update_button.isEnabled() is False

    window._navigation_buttons[6].click()
    assert window.page_stack.currentIndex() == 6
    window.check_update_button.click()
    _wait_until(qt_app, lambda: not window.is_update_check_running())

    assert window.latest_version_label.text() == "0.8.2"
    assert window.update_button.isEnabled() is True
    assert window.update_button.text() == "Update to 0.8.2"
    assert service.check_threads and service.check_threads[0] != main_thread

    window.update_button.click()
    _wait_until(qt_app, lambda: not window.is_update_download_running())

    assert service.downloaded_assets == [service.result.asset]
    assert service.download_threads and service.download_threads[0] != main_thread
    assert "package opened" in window.update_status_label.text().lower()
    assert window.update_button.isEnabled() is False
    window.deleteLater()
    qt_app.processEvents()


def test_updates_page_reports_up_to_date(qt_app, tmp_path) -> None:
    service = FakeUpdateService(
        UpdateCheckResult(
            current_version=__version__,
            latest_version=__version__,
            update_available=False,
            asset=ReleaseAsset(
                f"TellMeSensei-Setup-{__version__}.exe",
                "https://example.invalid/current.exe",
            ),
        )
    )
    window = SettingsWindow(
        _manager(tmp_path),
        update_service=service,
        local_ocr_supported=False,
    )

    window.check_for_updates()
    _wait_until(qt_app, lambda: not window.is_update_check_running())

    assert window.latest_version_label.text() == __version__
    assert "up to date" in window.update_status_label.text().lower()
    assert window.update_button.isEnabled() is False
    window.deleteLater()
    qt_app.processEvents()


def test_updates_page_surfaces_check_failure(qt_app, tmp_path) -> None:
    service = FakeUpdateService(check_error="GitHub is unavailable")
    window = SettingsWindow(
        _manager(tmp_path),
        update_service=service,
        local_ocr_supported=False,
    )

    window.check_for_updates()
    _wait_until(qt_app, lambda: not window.is_update_check_running())

    assert window.latest_version_label.text() == "Unavailable"
    assert window.update_status_label.text() == (
        "Unable to complete the update operation: GitHub is unavailable"
    )
    assert window.check_update_button.isEnabled() is True
    window.deleteLater()
    qt_app.processEvents()


def test_closing_settings_cancels_update_check(qt_app, tmp_path) -> None:
    service = SlowUpdateService()
    window = SettingsWindow(
        _manager(tmp_path),
        update_service=service,
        local_ocr_supported=False,
    )

    window.check_for_updates()
    _wait_until(qt_app, window.is_update_check_running)
    window.close()
    _wait_until(qt_app, lambda: not window.is_update_check_running())

    assert window.isHidden()
    window.deleteLater()
    qt_app.processEvents()
