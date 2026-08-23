"""Construction point for OCR providers."""

from __future__ import annotations

from app.config import AppConfig
from app.ocr.base import OCRProvider
from app.ocr.providers.paddle import PaddleOCRProvider


def create_ocr_provider(config: AppConfig) -> OCRProvider:
    """Create the current default OCR provider.

    The provider is intentionally fixed to PaddleOCR in Phase 10A. Future
    provider selection can be introduced here without coupling callers to a
    concrete implementation.
    """

    return PaddleOCRProvider(language=config.ocr_language)
