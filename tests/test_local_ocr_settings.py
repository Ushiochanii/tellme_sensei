from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from app.config import ConfigManager
from app.settings.repository import SettingsRepository
import app.ui.settings_window as settings_window_module
from app.ui.settings_window import SettingsWindow


class _SecretStore:
    def get_api_key(self) -> str:
        return ""

    def set_api_key(self, value: str) -> None:
        pass

    def delete_api_key(self) -> None:
        pass


class _ComponentManager:
    version = "1.0.0"

    def __init__(self, installed: bool = False) -> None:
        self.installed = installed
        self.remove_calls = 0
        self.remove_error: Exception | None = None

    def is_installed(self) -> bool:
        return self.installed

    def verify_installation(self) -> bool:
        return self.installed

    def smoke_test(self) -> bool:
        return self.installed

    def remove(self) -> bool:
        self.remove_calls += 1
        if self.remove_error is not None:
            raise self.remove_error
        self.installed = False
        return True


class _PreparingSession:
    def __init__(self) -> None:
        self.stop_calls = 0

    def is_preparing(self) -> bool:
        return True

    def is_busy(self) -> bool:
        return True

    def stop(self) -> None:
        self.stop_calls += 1

    def reset_capability(self) -> None:
        pass


def _window(
    tmp_path: Path,
    manager: _ComponentManager,
    session: _PreparingSession | None = None,
    manifest_url: str | None = "https://example.test/manifest.json",
) -> SettingsWindow:
    if manifest_url is not None:
        (tmp_path / ".env").write_text(
            f"LOCAL_OCR_MANIFEST_URL={manifest_url}\n", encoding="utf-8"
        )
    config = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=_SecretStore(),
    )
    return SettingsWindow(
        config_manager=config,
        component_manager=manager,
        local_ocr_session=session,
    )


def test_settings_shows_local_ocr_not_installed(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path, _ComponentManager(False))
    assert window.local_ocr_status_label.text() == "Not installed"
    assert not window.download_ocr_button.isHidden()
    assert not window.remove_ocr_button.isEnabled()
    window.close()


def test_settings_shows_supported_but_unconfigured_distribution(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        settings_window_module, "manifest_url_available", lambda _root=None: False
    )
    window = _window(tmp_path, _ComponentManager(False), manifest_url=None)

    assert window.online_mode_radio.isChecked()
    assert not window.local_mode_radio.isEnabled()
    assert not window.local_ocr_unsupported_label.isHidden()
    assert "supported on this Mac" in window.local_ocr_unsupported_label.text()
    assert window.download_ocr_button.isHidden()

    window.download_local_ocr()

    assert "supported on this Mac" in window.status_label.text()
    assert window._download_thread is None
    window.close()


def test_settings_shows_installed_local_ocr(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path, _ComponentManager(True))
    assert "Installed" in window.local_ocr_status_label.text()
    assert window.download_ocr_button.isHidden()
    assert window.remove_ocr_button.isEnabled()
    window.close()


def test_remove_local_ocr_yes_updates_state(qt_app, tmp_path: Path, monkeypatch) -> None:
    manager = _ComponentManager(True)
    window = _window(tmp_path, manager)
    monkeypatch.setattr(
        settings_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window.remove_local_ocr()

    assert manager.remove_calls == 1
    assert not manager.is_installed()
    assert window.local_ocr_status_label.text() == "Not installed"
    assert not window.remove_ocr_button.isEnabled()
    assert not window.download_ocr_button.isHidden()
    window.close()


def test_remove_local_ocr_no_keeps_state(qt_app, tmp_path: Path, monkeypatch) -> None:
    manager = _ComponentManager(True)
    window = _window(tmp_path, manager)
    monkeypatch.setattr(
        settings_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    window.remove_local_ocr()

    assert manager.remove_calls == 0
    assert manager.is_installed()
    assert "Installed" in window.local_ocr_status_label.text()
    assert window.remove_ocr_button.isEnabled()
    window.close()


def test_remove_local_ocr_error_is_visible(qt_app, tmp_path: Path, monkeypatch) -> None:
    manager = _ComponentManager(True)
    manager.remove_error = OSError("permission denied")
    window = _window(tmp_path, manager)
    monkeypatch.setattr(
        settings_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window.remove_local_ocr()

    assert manager.remove_calls == 1
    assert "Failed to remove Local OCR" in window.local_ocr_status_label.text()
    assert "permission denied" in window.local_ocr_status_label.text()
    window.close()


def test_download_is_rejected_during_local_ocr_prepare(qt_app, tmp_path: Path) -> None:
    manager = _ComponentManager(False)
    session = _PreparingSession()
    window = _window(tmp_path, manager, session)

    window.download_local_ocr()

    assert "Local OCR is preparing" in window.status_label.text()
    assert session.stop_calls == 0
    assert manager.remove_calls == 0
    assert window._download_thread is None
    window.close()


def test_remove_is_rejected_during_local_ocr_prepare(qt_app, tmp_path: Path) -> None:
    manager = _ComponentManager(True)
    session = _PreparingSession()
    window = _window(tmp_path, manager, session)

    window.remove_local_ocr()

    assert "Local OCR is preparing" in window.local_ocr_status_label.text()
    assert manager.remove_calls == 0
    assert session.stop_calls == 0
    assert manager.is_installed()
    window.close()
