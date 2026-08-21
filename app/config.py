"""Application configuration for the Phase 1-3 command-line pipeline."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when application configuration is invalid or incomplete."""


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings shared by services."""

    api_key: str
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    request_timeout: float = 60.0
    ocr_language: str = "japan"


class ConfigManager:
    """Load environment variables and optional JSON settings in one place."""

    def __init__(
        self,
        project_root: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.config_path = config_path or self.project_root / "config.json"

    def load(self, require_api_key: bool = True) -> AppConfig:
        """Return application settings without ever logging the API key."""

        load_dotenv(self.project_root / ".env", override=False)
        file_config = self._read_json_config()

        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if require_api_key and not api_key:
            raise ConfigError(
                "未配置 DeepSeek API Key。请复制 .env.example 为 .env，"
                "并填写 DEEPSEEK_API_KEY。"
            )

        return AppConfig(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", str(file_config.get("model", "deepseek-chat"))),
            base_url=os.getenv(
                "DEEPSEEK_BASE_URL",
                str(file_config.get("base_url", "https://api.deepseek.com")),
            ),
            request_timeout=float(
                os.getenv("DEEPSEEK_TIMEOUT", str(file_config.get("request_timeout", 60)))
            ),
            ocr_language=os.getenv(
                "OCR_LANGUAGE", str(file_config.get("ocr_language", "japan"))
            ),
        )

    def _read_json_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"无法读取配置文件 {self.config_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("config.json 必须是 JSON 对象。")
        return data
