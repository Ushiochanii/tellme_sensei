"""Compatibility exports for the former OCRService import path."""

from app.ocr.providers.paddle import PaddleOCRProvider
from app.ocr.types import OCRError, OCRLine, OCRResult
from app.ocr.utils import normalize_ocr_text

OCRService = PaddleOCRProvider

__all__ = [
    "OCRError",
    "OCRLine",
    "OCRResult",
    "OCRService",
    "normalize_ocr_text",
]
