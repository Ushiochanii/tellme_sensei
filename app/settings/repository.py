"""Persistence for non-sensitive user settings."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QStandardPaths

from app.analysis import AnalysisMode
from app.localization import (
    DEFAULT_ANSWER_LANGUAGE,
    DEFAULT_INTERFACE_LANGUAGE,
    SUPPORTED_LANGUAGES,
    normalize_language,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_REQUEST_TIMEOUT = 60.0


class SettingsRepository:
    """Read and write the small, non-sensitive settings JSON document."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else self.default_path()

    @staticmethod
    def default_path() -> Path:
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        if not base:
            raise RuntimeError("无法确定应用配置目录")
        return Path(base) / "tellme-sensei" / "settings.json"

    def load(self) -> dict[str, Any]:
        """Load supported values; malformed or unavailable files fall back safely."""

        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("settings load failed; using defaults: %s", type(exc).__name__)
            return {}
        if not isinstance(raw, dict):
            logger.warning("settings file is not a JSON object; using defaults")
            return {}

        settings: dict[str, Any] = {}
        model = raw.get("model")
        if isinstance(model, str) and model.strip():
            settings["model"] = model.strip()
        timeout = raw.get("request_timeout")
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
            settings["request_timeout"] = float(timeout)
        for key in (
            "base_url",
            "deepseek_base_url",
            "qwen_base_url",
            "zai_base_url",
            "ocr_language",
        ):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                settings[key] = value.strip()
        for key in (
            "text_ai_provider",
            "text_ai_model",
            "vision_ai_provider",
            "vision_ai_model",
        ):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                settings[key] = value.strip()
        for key in ("interface_language", "answer_language"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip() in SUPPORTED_LANGUAGES:
                settings[key] = value.strip()
        provider = raw.get("ocr_provider")
        if isinstance(provider, str) and provider.strip():
            settings["ocr_provider"] = provider.strip().lower()
        online_timeout = raw.get("online_ocr_timeout")
        if isinstance(online_timeout, (int, float)) and not isinstance(online_timeout, bool) and online_timeout > 0:
            settings["online_ocr_timeout"] = float(online_timeout)
        shortcut = raw.get("global_shortcut")
        if isinstance(shortcut, str) and shortcut.strip():
            settings["global_shortcut"] = shortcut.strip()
        for key in (
            "vision_global_shortcut",
            "watch_global_shortcut",
            "context_watch_global_shortcut",
        ):
            shortcut = raw.get(key)
            if isinstance(shortcut, str) and shortcut.strip():
                settings[key] = shortcut.strip()
        analysis_mode = raw.get("auto_watch_analysis_mode")
        if isinstance(analysis_mode, str) and analysis_mode.strip().lower() in {
            mode.value for mode in AnalysisMode
        }:
            settings["auto_watch_analysis_mode"] = analysis_mode.strip().lower()
        geometry = self._normalize_geometry(raw.get("answer_window_geometry"))
        if geometry is not None:
            settings["answer_window_geometry"] = geometry
        settings.update(self._load_auto_watch(raw))
        return settings

    def interface_language(self) -> str:
        """Return the persisted interface language or the upgrade default."""

        return normalize_language(
            self.load().get("interface_language"),
            default=DEFAULT_INTERFACE_LANGUAGE,
        )

    def answer_language(self) -> str:
        """Return the persisted answer language or the upgrade default."""

        return normalize_language(
            self.load().get("answer_language"),
            default=DEFAULT_ANSWER_LANGUAGE,
        )

    def auto_watch_analysis_mode(self) -> AnalysisMode:
        """Return the persisted Auto Watch mode, defaulting safely to Text."""

        value = self.load().get("auto_watch_analysis_mode")
        try:
            return AnalysisMode(value)
        except (TypeError, ValueError):
            return AnalysisMode.TEXT

    @staticmethod
    def _load_auto_watch(raw: Mapping[str, Any]) -> dict[str, Any]:
        """Load valid Auto Watch fields independently, falling back per field."""
        from app.auto_watch.models import AutoWatchSettings

        values: dict[str, Any] = {}
        for key in (
            "poll_interval_ms", "pixel_delta_threshold", "novelty_ratio",
            "stability_ratio", "stable_samples_required", "analysis_delay_ms",
        ):
            if key not in raw:
                continue
            candidate = dict(values)
            candidate[key] = raw[key]
            try:
                AutoWatchSettings(**candidate)
            except (TypeError, ValueError):
                continue
            values[key] = raw[key]
        return values

    def auto_watch_settings(self) -> AutoWatchSettings:
        """Return immutable Auto Watch settings assembled from persisted values."""
        from app.auto_watch.models import AutoWatchSettings

        saved = self.load()
        values = {
            key: saved[key]
            for key in (
                "poll_interval_ms", "pixel_delta_threshold", "novelty_ratio",
                "stability_ratio", "stable_samples_required", "analysis_delay_ms",
            ) if key in saved
        }
        return AutoWatchSettings(**values)

    def save(self, settings: Mapping[str, Any]) -> None:
        """Backward-compatible alias for an allow-listed partial update."""

        self.update(settings)

    def update(self, settings: Mapping[str, Any]) -> None:
        """Merge supported values without deleting unrelated saved settings."""

        payload = self.load()
        if "model" in settings:
            model = str(settings["model"]).strip()
            if not model:
                raise ValueError("model 不能为空")
            payload["model"] = model
        if "request_timeout" in settings:
            try:
                request_timeout = float(settings["request_timeout"])
            except (TypeError, ValueError) as exc:
                raise ValueError("request_timeout 必须是正数") from exc
            if request_timeout <= 0:
                raise ValueError("request_timeout 必须是正数")
            payload["request_timeout"] = request_timeout
        for key in (
            "base_url",
            "deepseek_base_url",
            "qwen_base_url",
            "zai_base_url",
            "ocr_language",
        ):
            if key not in settings:
                continue
            value = settings[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} 不能为空")
            payload[key] = value.strip()
        for key in (
            "text_ai_provider",
            "text_ai_model",
            "vision_ai_provider",
            "vision_ai_model",
        ):
            if key not in settings:
                continue
            value = settings[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} 不能为空")
            payload[key] = value.strip()
        if "global_shortcut" in settings:
            shortcut = str(settings["global_shortcut"]).strip()
            if not shortcut:
                raise ValueError("global_shortcut 不能为空")
            payload["global_shortcut"] = shortcut
        if "vision_global_shortcut" in settings:
            shortcut = str(settings["vision_global_shortcut"]).strip()
            if not shortcut:
                raise ValueError("vision_global_shortcut 不能为空")
            payload["vision_global_shortcut"] = shortcut
        for key in ("watch_global_shortcut", "context_watch_global_shortcut"):
            if key not in settings:
                continue
            shortcut = str(settings[key]).strip()
            if not shortcut:
                raise ValueError(f"{key} 不能为空")
            payload[key] = shortcut
        for key, default in (
            ("interface_language", DEFAULT_INTERFACE_LANGUAGE),
            ("answer_language", DEFAULT_ANSWER_LANGUAGE),
        ):
            if key not in settings:
                continue
            candidate = settings[key]
            if not isinstance(candidate, str) or candidate.strip() not in SUPPORTED_LANGUAGES:
                raise ValueError(f"{key} must be one of: {', '.join(SUPPORTED_LANGUAGES)}")
            payload[key] = normalize_language(candidate, default=default)
        if "auto_watch_analysis_mode" in settings:
            candidate = settings["auto_watch_analysis_mode"]
            if isinstance(candidate, AnalysisMode):
                candidate = candidate.value
            if not isinstance(candidate, str):
                raise ValueError("auto_watch_analysis_mode must be 'text' or 'vision'")
            candidate = candidate.strip().lower()
            if candidate not in {mode.value for mode in AnalysisMode}:
                raise ValueError("auto_watch_analysis_mode must be 'text' or 'vision'")
            payload["auto_watch_analysis_mode"] = candidate
        if "ocr_provider" in settings:
            provider = str(settings["ocr_provider"]).strip().lower()
            if provider not in {"local", "google_vision"}:
                raise ValueError("unsupported ocr_provider")
            payload["ocr_provider"] = provider
        if "online_ocr_timeout" in settings:
            try:
                online_timeout = float(settings["online_ocr_timeout"])
            except (TypeError, ValueError) as exc:
                raise ValueError("online_ocr_timeout must be a number") from exc
            if online_timeout <= 0 or online_timeout > 15:
                raise ValueError("online_ocr_timeout must be between 0 and 15 seconds")
            payload["online_ocr_timeout"] = online_timeout
        if "answer_window_geometry" in settings:
            geometry = self._normalize_geometry(settings["answer_window_geometry"])
            if geometry is None:
                raise ValueError("answer_window_geometry 无效")
            payload["answer_window_geometry"] = geometry
        auto_values = {
            key: settings[key]
            for key in (
                "poll_interval_ms", "pixel_delta_threshold", "novelty_ratio",
                "stability_ratio", "stable_samples_required", "analysis_delay_ms",
            ) if key in settings
        }
        if auto_values:
            from app.auto_watch.models import AutoWatchSettings

            current = self.auto_watch_settings()
            merged = {
                "poll_interval_ms": current.poll_interval_ms,
                "pixel_delta_threshold": current.pixel_delta_threshold,
                "novelty_ratio": current.novelty_ratio,
                "stability_ratio": current.stability_ratio,
                "stable_samples_required": current.stable_samples_required,
                "analysis_delay_ms": current.analysis_delay_ms,
            }
            merged.update(auto_values)
            try:
                validated = AutoWatchSettings(**merged)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid Auto Watch setting") from exc
            for key in auto_values:
                payload[key] = getattr(validated, key)

        self._atomic_write(payload)
        logger.info("settings saved")

    @staticmethod
    def _normalize_geometry(value: Any) -> dict[str, int] | None:
        if not isinstance(value, Mapping):
            return None
        result: dict[str, int] = {}
        for key in ("x", "y", "width", "height"):
            item = value.get(key)
            if not isinstance(item, int) or isinstance(item, bool):
                return None
            result[key] = item
        if result["width"] <= 0 or result["height"] <= 0:
            return None
        return result

    def _atomic_write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as temporary:
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
