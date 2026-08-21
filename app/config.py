"""Runtime configuration assembled from environment, settings, and secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from app.settings.repository import SettingsRepository
from app.settings.secret_store import SecretStore


class ConfigError(RuntimeError):
    """Raised when application configuration is invalid or incomplete."""


@dataclass(frozen=True)
class AppConfig:
    """Immutable runtime settings shared by services and one processing job."""

    api_key: str = field(repr=False)
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    request_timeout: float = 60.0
    ocr_language: str = "japan"


class ConfigManager:
    """Compose environment variables, saved settings, and the OS secret store."""

    def __init__(
        self,
        project_root: Path | None = None,
        config_path: Path | None = None,
        settings_repository: SettingsRepository | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.settings_repository = settings_repository or SettingsRepository(config_path)
        self.secret_store = secret_store or SecretStore()

    def has_explicit_api_key(self) -> bool:
        """Return whether a real OS environment variable overrides stored settings."""

        return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())

    def load(self, require_api_key: bool = True) -> AppConfig:
        """Return one immutable runtime configuration without logging secrets."""

        dotenv_config = self._read_dotenv_values()
        saved_settings = self.settings_repository.load()

        api_key = self._os_value("DEEPSEEK_API_KEY")
        if api_key is None:
            api_key = self.secret_store.get_api_key()
        if not api_key:
            api_key = self._file_value(dotenv_config, "DEEPSEEK_API_KEY") or ""
        if require_api_key and not api_key:
            raise ConfigError(
                "未配置 DeepSeek API Key。请在设置中保存，或在 .env 中填写 DEEPSEEK_API_KEY。"
            )

        try:
            request_timeout = float(
                self._os_value("DEEPSEEK_TIMEOUT")
                or saved_settings.get(
                    "request_timeout",
                    self._file_value(dotenv_config, "DEEPSEEK_TIMEOUT") or 60,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ConfigError("DEEPSEEK_TIMEOUT 必须是正数") from exc
        if request_timeout <= 0:
            raise ConfigError("DEEPSEEK_TIMEOUT 必须是正数")

        return AppConfig(
            api_key=api_key,
            model=(
                self._os_value("DEEPSEEK_MODEL")
                or saved_settings.get(
                    "model",
                    self._file_value(dotenv_config, "DEEPSEEK_MODEL") or "deepseek-chat",
                )
            ),
            base_url=(
                self._os_value("DEEPSEEK_BASE_URL")
                or saved_settings.get(
                    "base_url",
                    self._file_value(dotenv_config, "DEEPSEEK_BASE_URL")
                    or "https://api.deepseek.com",
                )
            ),
            request_timeout=request_timeout,
            ocr_language=(
                self._os_value("OCR_LANGUAGE")
                or saved_settings.get(
                    "ocr_language",
                    self._file_value(dotenv_config, "OCR_LANGUAGE") or "japan",
                )
            ),
        )

    def _read_dotenv_values(self) -> dict[str, str]:
        try:
            values = dotenv_values(self.project_root / ".env")
        except OSError:
            return {}
        return {
            key: value.strip()
            for key, value in values.items()
            if isinstance(value, str) and value.strip()
        }

    @staticmethod
    def _os_value(name: str) -> str | None:
        value = os.environ.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _file_value(values: dict[str, str], name: str) -> str | None:
        value = values.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    def save_settings(self, api_key: str, model: str, request_timeout: float) -> None:
        """Save API key and normal settings through their dedicated stores."""

        if api_key.strip():
            self.secret_store.set_api_key(api_key)
        else:
            self.secret_store.delete_api_key()
        self.settings_repository.save(
            {"model": model, "request_timeout": request_timeout}
        )
