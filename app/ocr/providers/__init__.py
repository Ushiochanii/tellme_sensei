"""Concrete OCR provider implementations."""

from app.ocr.providers.paddle import PaddleOCRProvider
from app.ocr.providers.local_worker import LocalOCRProvider

__all__ = ["LocalOCRProvider", "PaddleOCRProvider"]
