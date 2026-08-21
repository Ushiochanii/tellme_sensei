"""Persistence for non-sensitive user settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QStandardPaths

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
        for key in ("base_url", "ocr_language"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                settings[key] = value.strip()
        return settings

    def save(self, settings: Mapping[str, Any]) -> None:
        """Persist only the allow-listed non-sensitive settings."""

        model = str(settings.get("model", DEFAULT_MODEL)).strip()
        if not model:
            raise ValueError("model 不能为空")
        try:
            request_timeout = float(settings.get("request_timeout", DEFAULT_REQUEST_TIMEOUT))
        except (TypeError, ValueError) as exc:
            raise ValueError("request_timeout 必须是正数") from exc
        if request_timeout <= 0:
            raise ValueError("request_timeout 必须是正数")

        payload = {"model": model, "request_timeout": request_timeout}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("settings saved")
