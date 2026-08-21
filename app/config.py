"""Runtime configuration assembled from environment, settings, and secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

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

    def load(self, require_api_key: bool = True) -> AppConfig:
        """Return one immutable runtime configuration without logging secrets."""

        load_dotenv(self.project_root / ".env", override=False)
        saved_settings = self.settings_repository.load()

        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            api_key = self.secret_store.get_api_key()
        if require_api_key and not api_key:
            raise ConfigError(
                "未配置 DeepSeek API Key。请在设置中保存，或在 .env 中填写 DEEPSEEK_API_KEY。"
            )

        try:
            request_timeout = float(
                os.getenv(
                    "DEEPSEEK_TIMEOUT",
                    str(saved_settings.get("request_timeout", 60)),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ConfigError("DEEPSEEK_TIMEOUT 必须是正数") from exc
        if request_timeout <= 0:
            raise ConfigError("DEEPSEEK_TIMEOUT 必须是正数")

        return AppConfig(
            api_key=api_key,
            model=os.getenv(
                "DEEPSEEK_MODEL",
                str(saved_settings.get("model", "deepseek-chat")),
            ),
            base_url=os.getenv(
                "DEEPSEEK_BASE_URL",
                str(saved_settings.get("base_url", "https://api.deepseek.com")),
            ),
            request_timeout=request_timeout,
            ocr_language=os.getenv(
                "OCR_LANGUAGE",
                str(saved_settings.get("ocr_language", "japan")),
            ),
        )

    def save_settings(self, api_key: str, model: str, request_timeout: float) -> None:
        """Save API key and normal settings through their dedicated stores."""

        if api_key.strip():
            self.secret_store.set_api_key(api_key)
        else:
            self.secret_store.delete_api_key()
        self.settings_repository.save(
            {"model": model, "request_timeout": request_timeout}
        )
