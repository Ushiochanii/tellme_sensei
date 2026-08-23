"""OCR contracts and provider implementations."""

from app.ocr.base import OCRProvider
from app.ocr.factory import create_ocr_provider
from app.ocr.types import OCRError, OCRLine, OCRResult
from app.ocr.utils import normalize_ocr_text

__all__ = [
    "OCRError",
    "OCRLine",
    "OCRProvider",
    "OCRResult",
    "create_ocr_provider",
    "normalize_ocr_text",
]
