"""Runtime configuration assembled from environment, settings, and secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from app.ai.models import (
    AIBackendConfig,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_PROVIDER,
    DEFAULT_DEEPSEEK_TEXT_MODEL,
    DEFAULT_DEEPSEEK_VISION_MODEL,
    DEFAULT_REQUEST_TIMEOUT,
)
from app.ai.catalog import default_model, get_provider_descriptor
from app.localization import (
    DEFAULT_ANSWER_LANGUAGE,
    DEFAULT_INTERFACE_LANGUAGE,
    normalize_language,
)
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


DEFAULT_OCR_MODE = "local"
DEFAULT_LOCAL_OCR_ENGINE = "paddleocr"
DEFAULT_ONLINE_OCR_PROVIDER = "google_vision"


def _default_text_ai_config() -> AIBackendConfig:
    return AIBackendConfig(
        provider_id=DEFAULT_DEEPSEEK_PROVIDER,
        model_id=DEFAULT_DEEPSEEK_TEXT_MODEL,
        base_url=DEFAULT_DEEPSEEK_BASE_URL,
        request_timeout=DEFAULT_REQUEST_TIMEOUT,
    )


def _default_vision_ai_config() -> AIBackendConfig:
    return AIBackendConfig(
        provider_id=DEFAULT_DEEPSEEK_PROVIDER,
        model_id=DEFAULT_DEEPSEEK_VISION_MODEL,
        base_url=DEFAULT_DEEPSEEK_BASE_URL,
        request_timeout=DEFAULT_REQUEST_TIMEOUT,
    )


@dataclass(frozen=True)
class AppConfig:
    """Immutable runtime settings shared by services and one processing job."""

    text_ai: AIBackendConfig = field(default_factory=_default_text_ai_config)
    vision_ai: AIBackendConfig = field(default_factory=_default_vision_ai_config)
    ocr_language: str = "japan"
    global_shortcut: str = DEFAULT_SHORTCUT
    vision_global_shortcut: str = DEFAULT_VISION_SHORTCUT
    watch_global_shortcut: str = DEFAULT_WATCH_SHORTCUT
    context_watch_global_shortcut: str = DEFAULT_CONTEXT_WATCH_SHORTCUT
    ocr_mode: str = DEFAULT_OCR_MODE
    local_ocr_engine: str = DEFAULT_LOCAL_OCR_ENGINE
    online_ocr_provider: str = DEFAULT_ONLINE_OCR_PROVIDER
    google_vision_api_key: str = field(default="", repr=False)
    online_ocr_timeout: float = 15.0
    interface_language: str = DEFAULT_INTERFACE_LANGUAGE
    answer_language: str = DEFAULT_ANSWER_LANGUAGE


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

    def has_explicit_provider_api_key(self, provider_id: str) -> bool:
        """Return whether an OS environment variable overrides one provider key."""

        try:
            environment_name = get_provider_descriptor(provider_id).api_key_env
        except ValueError:
            return False
        return bool(self._os_value(environment_name))

    def get_provider_api_key(self, provider_id: str) -> str:
        """Resolve one provider key using the same precedence as ``load``."""

        dotenv_config = self._read_dotenv_values()
        return self._resolve_provider_api_key(provider_id, dotenv_config)

    def get_provider_base_url(self, provider_id: str) -> str:
        """Resolve one provider endpoint using the same precedence as ``load``."""

        return self._resolve_provider_base_url(
            provider_id,
            self._read_dotenv_values(),
            self.settings_repository.load(),
        )

    def has_explicit_provider_base_url(self, provider_id: str) -> bool:
        """Return whether an OS endpoint override is active for a provider."""

        try:
            get_provider_descriptor(provider_id)
        except ValueError:
            return False
        return bool(self._os_value(f"{str(provider_id).strip().upper()}_BASE_URL"))

    def has_explicit_google_vision_api_key(self) -> bool:
        return bool(os.environ.get("GOOGLE_VISION_API_KEY", "").strip())

    def has_explicit_ocr_mode(self) -> bool:
        """Return whether an OS environment variable controls OCR mode."""

        return bool(
            self._os_value("OCR_MODE") or self._os_value("OCR_PROVIDER")
        )

    def load(self) -> AppConfig:
        """Return one immutable runtime configuration without logging secrets."""

        dotenv_config = self._read_dotenv_values()
        saved_settings = self.settings_repository.load()

        try:
            request_timeout = float(
                self._os_value("AI_REQUEST_TIMEOUT")
                or self._os_value("DEEPSEEK_TIMEOUT")
                or saved_settings.get(
                    "request_timeout",
                    self._file_value(dotenv_config, "AI_REQUEST_TIMEOUT")
                    or self._file_value(dotenv_config, "DEEPSEEK_TIMEOUT")
                    or DEFAULT_REQUEST_TIMEOUT,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ConfigError("AI request timeout 必须是正数") from exc
        if request_timeout <= 0:
            raise ConfigError("AI request timeout 必须是正数")

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

        ocr_mode, local_ocr_engine, online_ocr_provider = self._resolve_ocr_configuration(
            dotenv_config,
            saved_settings,
        )

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

        text_provider = self._resolve_ai_selection(
            "TEXT_AI_PROVIDER",
            "text_ai_provider",
            dotenv_config,
            saved_settings,
            DEFAULT_DEEPSEEK_PROVIDER,
        )
        vision_provider = self._resolve_ai_selection(
            "VISION_AI_PROVIDER",
            "vision_ai_provider",
            dotenv_config,
            saved_settings,
            DEFAULT_DEEPSEEK_PROVIDER,
        )
        try:
            get_provider_descriptor(text_provider)
            get_provider_descriptor(vision_provider)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        text_model = self._resolve_model(
            text_provider,
            "text",
            dotenv_config,
            saved_settings,
        )
        vision_model = self._resolve_model(
            vision_provider,
            "vision",
            dotenv_config,
            saved_settings,
        )
        text_backend = self._backend_config(
            text_provider,
            text_model,
            dotenv_config,
            saved_settings,
            request_timeout,
        )
        vision_backend = self._backend_config(
            vision_provider,
            vision_model,
            dotenv_config,
            saved_settings,
            request_timeout,
        )
        return AppConfig(
            text_ai=text_backend,
            vision_ai=vision_backend,
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
            ocr_mode=ocr_mode,
            local_ocr_engine=local_ocr_engine,
            online_ocr_provider=online_ocr_provider,
            google_vision_api_key=google_vision_api_key,
            online_ocr_timeout=online_ocr_timeout,
            interface_language=self._language_setting(
                "interface_language",
                DEFAULT_INTERFACE_LANGUAGE,
                saved_settings,
            ),
            answer_language=self._language_setting(
                "answer_language",
                DEFAULT_ANSWER_LANGUAGE,
                saved_settings,
            ),
        )

    def _resolve_ocr_configuration(
        self,
        dotenv_config: dict[str, str],
        saved_settings: dict[str, object],
    ) -> tuple[str, str, str]:
        """Resolve normalized OCR selections while honoring legacy upgrades."""

        # OCR_MODE is the normalized override. OCR_PROVIDER remains an OS-level
        # compatibility override so existing installations keep their behavior.
        mode_value = self._os_value("OCR_MODE")
        if mode_value is None:
            legacy_os_provider = self._os_value("OCR_PROVIDER")
            if legacy_os_provider is not None:
                mode_value = self._mode_from_legacy_provider(legacy_os_provider)
        if mode_value is None:
            mode_value = saved_settings.get("ocr_mode")
        if mode_value is None and saved_settings.get("ocr_provider") is not None:
            mode_value = self._mode_from_legacy_provider(saved_settings["ocr_provider"])
        if mode_value is None:
            mode_value = self._file_value(dotenv_config, "OCR_MODE")
        if mode_value is None:
            legacy_file_provider = self._file_value(dotenv_config, "OCR_PROVIDER")
            if legacy_file_provider is not None:
                mode_value = self._mode_from_legacy_provider(legacy_file_provider)
        ocr_mode = str(mode_value or DEFAULT_OCR_MODE).strip().lower()
        if ocr_mode not in {"local", "online"}:
            raise ConfigError(f"Unsupported OCR mode: {ocr_mode}")

        local_ocr_engine = str(
            self._os_value("LOCAL_OCR_ENGINE")
            or saved_settings.get("local_ocr_engine")
            or self._file_value(dotenv_config, "LOCAL_OCR_ENGINE")
            or DEFAULT_LOCAL_OCR_ENGINE
        ).strip().lower()
        if local_ocr_engine != DEFAULT_LOCAL_OCR_ENGINE:
            raise ConfigError(f"Unsupported Local OCR engine: {local_ocr_engine}")

        online_ocr_provider = str(
            self._os_value("ONLINE_OCR_PROVIDER")
            or saved_settings.get("online_ocr_provider")
            or self._file_value(dotenv_config, "ONLINE_OCR_PROVIDER")
            or DEFAULT_ONLINE_OCR_PROVIDER
        ).strip().lower()
        if online_ocr_provider != DEFAULT_ONLINE_OCR_PROVIDER:
            raise ConfigError(
                f"Unsupported Online OCR provider: {online_ocr_provider}"
            )
        return ocr_mode, local_ocr_engine, online_ocr_provider

    @staticmethod
    def _mode_from_legacy_provider(value: object) -> str:
        normalized = str(value).strip().lower()
        if normalized == "local":
            return "local"
        if normalized == "google_vision":
            return "online"
        raise ConfigError(f"Unsupported OCR provider: {normalized}")

    def _resolve_model(
        self,
        provider_id: str,
        capability: str,
        dotenv_config: dict[str, str],
        saved_settings: dict[str, object],
    ) -> str:
        """Resolve capability-specific model settings and DeepSeek upgrades."""

        environment_name = (
            "TEXT_AI_MODEL" if capability == "text" else "VISION_AI_MODEL"
        )
        setting_name = (
            "text_ai_model" if capability == "text" else "vision_ai_model"
        )
        selected = (
            self._os_value(environment_name)
            or saved_settings.get(setting_name)
            or self._file_value(dotenv_config, environment_name)
        )
        if selected is None and provider_id == DEFAULT_DEEPSEEK_PROVIDER:
            if capability == "text":
                selected = (
                    self._os_value("DEEPSEEK_MODEL")
                    or saved_settings.get("model")
                    or self._file_value(dotenv_config, "DEEPSEEK_MODEL")
                )
        if selected is not None and str(selected).strip():
            return str(selected).strip()
        if provider_id == DEFAULT_DEEPSEEK_PROVIDER:
            return (
                DEFAULT_DEEPSEEK_TEXT_MODEL
                if capability == "text"
                else DEFAULT_DEEPSEEK_VISION_MODEL
            )
        return default_model(provider_id, capability)  # type: ignore[arg-type]

    def _backend_config(
        self,
        provider_id: str,
        model_id: str,
        dotenv_config: dict[str, str],
        saved_settings: dict[str, object],
        request_timeout: float,
    ) -> AIBackendConfig:
        return AIBackendConfig(
            provider_id=provider_id,
            model_id=model_id,
            api_key=self._resolve_provider_api_key(provider_id, dotenv_config),
            base_url=self._resolve_provider_base_url(
                provider_id,
                dotenv_config,
                saved_settings,
            ),
            request_timeout=request_timeout,
        )

    def _resolve_provider_api_key(
        self,
        provider_id: str,
        dotenv_config: dict[str, str],
    ) -> str:
        descriptor = get_provider_descriptor(provider_id)
        value = self._os_value(descriptor.api_key_env)
        if value is None:
            getter = getattr(self.secret_store, "get_provider_api_key", None)
            if callable(getter):
                value = getter(provider_id)
            elif provider_id == DEFAULT_DEEPSEEK_PROVIDER:
                legacy_getter = getattr(self.secret_store, "get_api_key", None)
                value = legacy_getter() if callable(legacy_getter) else ""
                if not value:
                    generic = getattr(self.secret_store, "get_secret", None)
                    value = (
                        generic(descriptor.secret_account_name)
                        if callable(generic)
                        else ""
                    )
            else:
                generic = getattr(self.secret_store, "get_secret", None)
                value = (
                    generic(descriptor.secret_account_name)
                    if callable(generic)
                    else ""
                )
        if not value:
            value = self._file_value(dotenv_config, descriptor.api_key_env) or ""
        return value.strip() if isinstance(value, str) else ""

    def _resolve_provider_base_url(
        self,
        provider_id: str,
        dotenv_config: dict[str, str],
        saved_settings: dict[str, object],
    ) -> str:
        descriptor = get_provider_descriptor(provider_id)
        normalized_provider_id = descriptor.provider_id
        endpoint_key = f"{normalized_provider_id}_base_url"
        value = self._os_value(f"{normalized_provider_id.upper()}_BASE_URL")
        if value is None:
            value = saved_settings.get(endpoint_key)
        if value is None and normalized_provider_id == DEFAULT_DEEPSEEK_PROVIDER:
            value = saved_settings.get("base_url")
        if value is None:
            value = self._file_value(
                dotenv_config,
                f"{normalized_provider_id.upper()}_BASE_URL",
            )
        if value is None and normalized_provider_id == DEFAULT_DEEPSEEK_PROVIDER:
            value = self._file_value(dotenv_config, "DEEPSEEK_BASE_URL")
        return str(value).strip() if value and str(value).strip() else descriptor.default_base_url

    def _resolve_ai_selection(
        self,
        environment_name: str,
        setting_name: str,
        dotenv_config: dict[str, str],
        saved_settings: dict[str, object],
        default: str,
        *,
        lowercase: bool = True,
    ) -> str:
        value = (
            self._os_value(environment_name)
            or saved_settings.get(setting_name)
            or self._file_value(dotenv_config, environment_name)
            or default
        )
        normalized = str(value).strip()
        if lowercase:
            normalized = normalized.lower()
        return normalized or default

    def _language_setting(
        self,
        key: str,
        default: str,
        saved_settings: dict[str, object],
    ) -> str:
        getter = getattr(self.settings_repository, key, None)
        if callable(getter):
            return normalize_language(getter(), default=default)
        return normalize_language(saved_settings.get(key), default=default)

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
        *,
        text_ai_provider: str,
        text_ai_model: str,
        vision_ai_provider: str,
        vision_ai_model: str,
        request_timeout: float,
        global_shortcut: str | None = None,
        provider_api_keys: Mapping[str, str | None] | None = None,
        provider_base_urls: Mapping[str, str | None] | None = None,
        vision_global_shortcut: str | None = None,
        watch_global_shortcut: str | None = None,
        context_watch_global_shortcut: str | None = None,
        ocr_mode: str | None = None,
        local_ocr_engine: str | None = None,
        online_ocr_provider: str | None = None,
        google_vision_api_key: str | None = None,
        online_ocr_timeout: float | None = None,
        interface_language: str | None = None,
        answer_language: str | None = None,
    ) -> None:
        """Persist independent AI selections plus shared provider credentials."""

        try:
            get_provider_descriptor(text_ai_provider)
            get_provider_descriptor(vision_ai_provider)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        settings: dict[str, object] = {
            "text_ai_provider": str(text_ai_provider).strip().lower(),
            "text_ai_model": str(text_ai_model).strip(),
            "vision_ai_provider": str(vision_ai_provider).strip().lower(),
            "vision_ai_model": str(vision_ai_model).strip(),
        }
        for key in ("text_ai_model", "vision_ai_model"):
            if not isinstance(settings[key], str) or not settings[key]:
                raise ConfigError(f"{key} 不能为空")
        try:
            timeout_value = float(request_timeout)
        except (TypeError, ValueError) as exc:
            raise ConfigError("AI request timeout 必须是正数") from exc
        if timeout_value <= 0:
            raise ConfigError("AI request timeout 必须是正数")
        settings["request_timeout"] = timeout_value

        if provider_base_urls:
            for provider_id, endpoint in provider_base_urls.items():
                try:
                    get_provider_descriptor(provider_id)
                except ValueError as exc:
                    raise ConfigError(str(exc)) from exc
                if endpoint is None:
                    continue
                if not isinstance(endpoint, str) or not endpoint.strip():
                    raise ConfigError(f"{provider_id}_base_url 不能为空")
                settings[f"{str(provider_id).strip().lower()}_base_url"] = endpoint.strip()
        if provider_api_keys:
            for provider_id, key in provider_api_keys.items():
                try:
                    get_provider_descriptor(provider_id)
                except ValueError as exc:
                    raise ConfigError(str(exc)) from exc
                if key is None:
                    continue
                self._save_provider_api_key(provider_id, key)
        current_config = self.load()
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
        if ocr_mode is not None:
            normalized_mode = ocr_mode.strip().lower()
            if normalized_mode not in {"local", "online"}:
                raise ConfigError(f"Unsupported OCR mode: {ocr_mode}")
            settings["ocr_mode"] = normalized_mode
        if local_ocr_engine is not None:
            normalized_engine = local_ocr_engine.strip().lower()
            if normalized_engine != DEFAULT_LOCAL_OCR_ENGINE:
                raise ConfigError(f"Unsupported Local OCR engine: {local_ocr_engine}")
            settings["local_ocr_engine"] = normalized_engine
        if online_ocr_provider is not None:
            normalized_online_provider = online_ocr_provider.strip().lower()
            if normalized_online_provider != DEFAULT_ONLINE_OCR_PROVIDER:
                raise ConfigError(
                    f"Unsupported Online OCR provider: {online_ocr_provider}"
                )
            settings["online_ocr_provider"] = normalized_online_provider
        if online_ocr_timeout is not None:
            if online_ocr_timeout <= 0 or online_ocr_timeout > 15:
                raise ConfigError("ONLINE_OCR_TIMEOUT must be between 0 and 15 seconds")
            settings["online_ocr_timeout"] = float(online_ocr_timeout)
        if interface_language is not None:
            if not isinstance(interface_language, str):
                raise ConfigError("Unsupported interface language")
            normalized_interface_language = normalize_language(
                interface_language,
                default=DEFAULT_INTERFACE_LANGUAGE,
            )
            if normalized_interface_language != interface_language.strip():
                raise ConfigError("Unsupported interface language")
            settings["interface_language"] = normalized_interface_language
        if answer_language is not None:
            if not isinstance(answer_language, str):
                raise ConfigError("Unsupported answer language")
            normalized_answer_language = normalize_language(
                answer_language,
                default=DEFAULT_ANSWER_LANGUAGE,
            )
            if normalized_answer_language != answer_language.strip():
                raise ConfigError("Unsupported answer language")
            settings["answer_language"] = normalized_answer_language
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

    def save_ai_settings(self, **kwargs: object) -> None:
        """Named entry point for callers saving the independent AI cards."""

        self.save_settings(**kwargs)

    def _save_provider_api_key(self, provider_id: str, value: str) -> None:
        normalized = str(provider_id).strip().lower()
        if not isinstance(value, str):
            raise ConfigError(f"{normalized} API Key must be a string")
        if value.strip():
            setter = getattr(self.secret_store, "set_provider_api_key", None)
            if callable(setter):
                setter(normalized, value)
                return
            if normalized == DEFAULT_DEEPSEEK_PROVIDER:
                legacy = getattr(self.secret_store, "set_api_key", None)
                if callable(legacy):
                    legacy(value)
                    return
            generic = getattr(self.secret_store, "set_secret", None)
            if callable(generic):
                generic(get_provider_descriptor(normalized).secret_account_name, value)
                return
            raise ConfigError(f"Unable to save {normalized} API Key")

        deleter = getattr(self.secret_store, "delete_provider_api_key", None)
        if callable(deleter):
            deleter(normalized)
            return
        if normalized == DEFAULT_DEEPSEEK_PROVIDER:
            legacy = getattr(self.secret_store, "delete_api_key", None)
            if callable(legacy):
                legacy()
                return
        generic = getattr(self.secret_store, "delete_secret", None)
        if callable(generic):
            generic(get_provider_descriptor(normalized).secret_account_name)
            return
        raise ConfigError(f"Unable to delete {normalized} API Key")
