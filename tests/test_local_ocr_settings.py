from pathlib import Path

from app.config import ConfigManager
from app.settings.repository import SettingsRepository
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

    def is_installed(self) -> bool:
        return self.installed

    def verify_installation(self) -> bool:
        return self.installed

    def smoke_test(self) -> bool:
        return self.installed

    def remove(self) -> bool:
        self.installed = False
        return True


def _window(tmp_path: Path, manager: _ComponentManager) -> SettingsWindow:
    config = ConfigManager(
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=_SecretStore(),
    )
    return SettingsWindow(config_manager=config, component_manager=manager)


def test_settings_shows_local_ocr_not_installed(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path, _ComponentManager(False))
    assert window.local_ocr_status_label.text() == "Not installed"
    assert not window.download_ocr_button.isHidden()
    assert not window.remove_ocr_button.isEnabled()
    window.close()


def test_settings_shows_installed_local_ocr(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path, _ComponentManager(True))
    assert "Installed" in window.local_ocr_status_label.text()
    assert window.download_ocr_button.isHidden()
    assert window.remove_ocr_button.isEnabled()
    window.close()
