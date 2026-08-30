"""Runtime configuration assembled from environment, settings, and secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from app.platform.hotkey import (
    DEFAULT_CONTEXT_WATCH_SHORTCUT,
    DEFAULT_SHORTCUT,
    DEFAULT_VISION_SHORTCUT,
    DEFAULT_WATCH_SHORTCUT,
    HotkeySpec,
    HotkeySpecError,
    validate_unique_shortcuts,
)
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
    global_shortcut: str = DEFAULT_SHORTCUT
    vision_global_shortcut: str = DEFAULT_VISION_SHORTCUT
    watch_global_shortcut: str = DEFAULT_WATCH_SHORTCUT
    context_watch_global_shortcut: str = DEFAULT_CONTEXT_WATCH_SHORTCUT
    ocr_provider: str = "local"
    google_vision_api_key: str = field(default="", repr=False)
    online_ocr_timeout: float = 15.0


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

    def has_explicit_google_vision_api_key(self) -> bool:
        return bool(os.environ.get("GOOGLE_VISION_API_KEY", "").strip())

    def has_explicit_ocr_provider(self) -> bool:
        """Return whether OCR_PROVIDER is set in the real OS environment."""

        return bool(os.environ.get("OCR_PROVIDER", "").strip())

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

        try:
            online_ocr_timeout = float(
                self._os_value("ONLINE_OCR_TIMEOUT")
                or saved_settings.get(
                    "online_ocr_timeout",
                    self._file_value(dotenv_config, "ONLINE_OCR_TIMEOUT") or 15,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ConfigError("ONLINE_OCR_TIMEOUT must be a positive number") from exc
        if online_ocr_timeout <= 0 or online_ocr_timeout > 15:
            raise ConfigError("ONLINE_OCR_TIMEOUT must be between 0 and 15 seconds")

        google_vision_api_key = self._os_value("GOOGLE_VISION_API_KEY")
        if google_vision_api_key is None:
            google_vision_api_key = self._stored_google_vision_key()
        if not google_vision_api_key:
            google_vision_api_key = self._file_value(dotenv_config, "GOOGLE_VISION_API_KEY") or ""

        ocr_provider = (
            self._os_value("OCR_PROVIDER")
            or saved_settings.get(
                "ocr_provider",
                self._file_value(dotenv_config, "OCR_PROVIDER") or "local",
            )
        ).strip().lower()
        if ocr_provider not in {"local", "google_vision"}:
            raise ConfigError(f"Unsupported OCR provider: {ocr_provider}")

        shortcuts = self._normalized_shortcuts(
            (
                self._os_value("GLOBAL_SHORTCUT")
                or saved_settings.get(
                    "global_shortcut",
                    self._file_value(dotenv_config, "GLOBAL_SHORTCUT") or DEFAULT_SHORTCUT,
                ),
                self._os_value("VISION_GLOBAL_SHORTCUT")
                or saved_settings.get(
                    "vision_global_shortcut",
                    self._file_value(dotenv_config, "VISION_GLOBAL_SHORTCUT")
                    or DEFAULT_VISION_SHORTCUT,
                ),
                self._os_value("WATCH_GLOBAL_SHORTCUT")
                or saved_settings.get(
                    "watch_global_shortcut",
                    self._file_value(dotenv_config, "WATCH_GLOBAL_SHORTCUT")
                    or DEFAULT_WATCH_SHORTCUT,
                ),
                self._os_value("CONTEXT_WATCH_GLOBAL_SHORTCUT")
                or saved_settings.get(
                    "context_watch_global_shortcut",
                    self._file_value(dotenv_config, "CONTEXT_WATCH_GLOBAL_SHORTCUT")
                    or DEFAULT_CONTEXT_WATCH_SHORTCUT,
                ),
            )
        )

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
            global_shortcut=shortcuts[0],
            vision_global_shortcut=shortcuts[1],
            watch_global_shortcut=shortcuts[2],
            context_watch_global_shortcut=shortcuts[3],
            ocr_provider=ocr_provider,
            google_vision_api_key=google_vision_api_key,
            online_ocr_timeout=online_ocr_timeout,
        )

    def _stored_google_vision_key(self) -> str:
        getter = getattr(self.secret_store, "get_google_vision_api_key", None)
        if callable(getter):
            value = getter()
        else:
            generic = getattr(self.secret_store, "get_secret", None)
            value = generic("google-vision-api-key") if callable(generic) else ""
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _normalized_shortcut(value: str, default: str = DEFAULT_SHORTCUT) -> str:
        try:
            return HotkeySpec.parse(value).canonical
        except (HotkeySpecError, TypeError):
            return default

    @classmethod
    def _normalized_shortcuts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize startup values while keeping every native registration unique."""

        defaults = (
            DEFAULT_SHORTCUT,
            DEFAULT_VISION_SHORTCUT,
            DEFAULT_WATCH_SHORTCUT,
            DEFAULT_CONTEXT_WATCH_SHORTCUT,
        )
        normalized: list[str] = []
        for value, default in zip(values, defaults, strict=True):
            candidate = cls._normalized_shortcut(value, default=default)
            if candidate in normalized:
                candidate = next(fallback for fallback in defaults if fallback not in normalized)
            normalized.append(candidate)
        return tuple(normalized)

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

    def save_settings(
        self,
        api_key: str | None,
        model: str,
        request_timeout: float,
        global_shortcut: str | None = None,
        *,
        vision_global_shortcut: str | None = None,
        watch_global_shortcut: str | None = None,
        context_watch_global_shortcut: str | None = None,
        ocr_provider: str | None = None,
        google_vision_api_key: str | None = None,
        online_ocr_timeout: float | None = None,
    ) -> None:
        """Save settings; a None secret value leaves that stored secret unchanged."""

        if api_key is not None:
            if api_key.strip():
                self.secret_store.set_api_key(api_key)
            else:
                self.secret_store.delete_api_key()
        settings = {"model": model, "request_timeout": request_timeout}
        current_config = self.load(require_api_key=False)
        requested_shortcuts = (
            self._normalized_shortcut(
                global_shortcut,
                default=current_config.global_shortcut,
            ) if global_shortcut is not None else current_config.global_shortcut,
            self._normalized_shortcut(
                vision_global_shortcut,
                default=current_config.vision_global_shortcut,
            ) if vision_global_shortcut is not None else current_config.vision_global_shortcut,
            self._normalized_shortcut(
                watch_global_shortcut,
                default=current_config.watch_global_shortcut,
            ) if watch_global_shortcut is not None else current_config.watch_global_shortcut,
            self._normalized_shortcut(
                context_watch_global_shortcut,
                default=current_config.context_watch_global_shortcut,
            ) if context_watch_global_shortcut is not None else current_config.context_watch_global_shortcut,
        )
        try:
            validate_unique_shortcuts(requested_shortcuts)
        except HotkeySpecError as exc:
            raise ConfigError("快捷键不能重复") from exc
        if global_shortcut is not None:
            settings["global_shortcut"] = requested_shortcuts[0]
        if vision_global_shortcut is not None:
            settings["vision_global_shortcut"] = requested_shortcuts[1]
        if watch_global_shortcut is not None:
            settings["watch_global_shortcut"] = requested_shortcuts[2]
        if context_watch_global_shortcut is not None:
            settings["context_watch_global_shortcut"] = requested_shortcuts[3]
        if ocr_provider is not None:
            normalized_provider = ocr_provider.strip().lower()
            if normalized_provider not in {"local", "google_vision"}:
                raise ConfigError(f"Unsupported OCR provider: {ocr_provider}")
            settings["ocr_provider"] = normalized_provider
        if online_ocr_timeout is not None:
            if online_ocr_timeout <= 0 or online_ocr_timeout > 15:
                raise ConfigError("ONLINE_OCR_TIMEOUT must be between 0 and 15 seconds")
            settings["online_ocr_timeout"] = float(online_ocr_timeout)
        if google_vision_api_key is not None:
            if google_vision_api_key.strip():
                setter = getattr(self.secret_store, "set_google_vision_api_key", None)
                if callable(setter):
                    setter(google_vision_api_key)
                else:
                    generic_setter = getattr(self.secret_store, "set_secret", None)
                    if callable(generic_setter):
                        generic_setter("google-vision-api-key", google_vision_api_key)
            else:
                deleter = getattr(self.secret_store, "delete_google_vision_api_key", None)
                if callable(deleter):
                    deleter()
                else:
                    generic_deleter = getattr(self.secret_store, "delete_secret", None)
                    if callable(generic_deleter):
                        generic_deleter("google-vision-api-key")
        self.settings_repository.update(settings)
