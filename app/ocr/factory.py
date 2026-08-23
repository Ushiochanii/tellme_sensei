"""Construction point for OCR providers."""

from __future__ import annotations

from app.config import AppConfig, ConfigError
from app.ocr.base import OCRProvider
from app.ocr.providers.local_worker import LocalOCRProvider


def create_ocr_provider(config: AppConfig) -> OCRProvider:
    """Create the current default OCR provider.

    The Core process delegates local recognition to the separately installed
    component. Future provider selection can be introduced here without
    coupling callers to a concrete implementation.
    """

    if config.ocr_provider == "local":
        return LocalOCRProvider(language=config.ocr_language)
    if config.ocr_provider == "google_vision":
        from app.ocr.providers.google_vision import GoogleVisionOCRProvider

        return GoogleVisionOCRProvider(
            api_key=config.google_vision_api_key,
            language=config.ocr_language,
            timeout=config.online_ocr_timeout,
        )
    raise ConfigError(f"Unsupported OCR provider: {config.ocr_provider}")


def create_local_ocr_provider(
    config: AppConfig,
    executable: str | None = None,
    timeout: float = 60.0,
) -> OCRProvider:
    """Construct the external provider for controlled integration testing."""

    return LocalOCRProvider(
        language=config.ocr_language,
        executable=executable,
        timeout=timeout,
    )
