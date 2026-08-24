from pathlib import Path

from app.config import ConfigManager
from app.platform import ocr as ocr_platform
from app.settings.repository import SettingsRepository
from app.ui import settings_window as settings_window_module
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

    def is_installed(self) -> bool:
        return True

    def verify_installation(self) -> bool:
        return True

    def smoke_test(self) -> bool:
        return True


def test_local_ocr_capability_only_supports_windows(monkeypatch) -> None:
    monkeypatch.setattr(ocr_platform.sys, "platform", "darwin")
    assert not ocr_platform.is_local_ocr_supported()

    monkeypatch.setattr(ocr_platform.sys, "platform", "win32")
    assert ocr_platform.is_local_ocr_supported()


def test_macos_settings_hide_windows_local_ocr_controls(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings_window_module, "is_local_ocr_supported", lambda: False)
    config = ConfigManager(
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=_SecretStore(),
    )
    window = SettingsWindow(config, component_manager=_ComponentManager())

    assert window.online_mode_radio.isChecked()
    assert not window.local_mode_radio.isEnabled()
    assert not window.local_ocr_unsupported_label.isHidden()
    assert window.download_ocr_button.isHidden()
    assert window.verify_ocr_button.isHidden()
    assert window.remove_ocr_button.isHidden()

    window.download_local_ocr()
    assert "not installed/supported" in window.status_label.text()
    assert window._download_thread is None
    window.close()
