from __future__ import annotations

import os

from app.config import ConfigManager
from app.settings.repository import SettingsRepository
from app.settings.secret_store import SecretStore


class _Secrets:
    def __init__(self, deepseek: str = "", google: str = "") -> None:
        self.deepseek = deepseek
        self.google = google

    def get_api_key(self) -> str:
        return self.deepseek

    def get_google_vision_api_key(self) -> str:
        return self.google


class _Keyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str):
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def _manager(tmp_path, secrets: _Secrets) -> ConfigManager:
    return ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=secrets,
    )


def _clear_env(monkeypatch) -> None:
    for name in (
        "DEEPSEEK_API_KEY",
        "GOOGLE_VISION_API_KEY",
        "OCR_PROVIDER",
        "ONLINE_OCR_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_google_key_precedence_is_environment_then_secret_then_dotenv(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    (tmp_path / ".env").write_text("GOOGLE_VISION_API_KEY=dotenv-google\n", encoding="utf-8")
    assert _manager(tmp_path, _Secrets(google="stored-google")).load(False).google_vision_api_key == "stored-google"

    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "environment-google")
    assert _manager(tmp_path, _Secrets(google="stored-google")).load(False).google_vision_api_key == "environment-google"

    monkeypatch.delenv("GOOGLE_VISION_API_KEY")
    assert _manager(tmp_path, _Secrets()).load(False).google_vision_api_key == "dotenv-google"


def test_provider_precedence_and_default(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    (tmp_path / ".env").write_text("OCR_PROVIDER=google_vision\n", encoding="utf-8")
    assert _manager(tmp_path, _Secrets()).load(False).ocr_provider == "google_vision"

    SettingsRepository(tmp_path / "settings.json").update({"ocr_provider": "local"})
    assert _manager(tmp_path, _Secrets()).load(False).ocr_provider == "local"

    monkeypatch.setenv("OCR_PROVIDER", "google_vision")
    assert _manager(tmp_path, _Secrets()).load(False).ocr_provider == "google_vision"


def test_online_timeout_precedence_and_dotenv_is_not_injected(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    (tmp_path / ".env").write_text("ONLINE_OCR_TIMEOUT=12\n", encoding="utf-8")
    assert "ONLINE_OCR_TIMEOUT" not in os.environ
    assert _manager(tmp_path, _Secrets()).load(False).online_ocr_timeout == 12.0
    assert "ONLINE_OCR_TIMEOUT" not in os.environ


def test_legacy_and_google_secret_accounts_are_separate() -> None:
    keyring = _Keyring()
    store = SecretStore(keyring_module=keyring)
    store.set_api_key("deepseek-key")
    store.set_google_vision_api_key("google-key")

    assert store.get_api_key() == "deepseek-key"
    assert store.get_google_vision_api_key() == "google-key"
    assert ("tellme-sensei", "default") in keyring.values
    assert ("tellme-sensei", "google-vision-api-key") in keyring.values


def test_google_key_is_not_in_app_config_repr() -> None:
    from app.config import AppConfig

    assert "google-secret" not in repr(
        AppConfig(api_key="deepseek", google_vision_api_key="google-secret")
    )
