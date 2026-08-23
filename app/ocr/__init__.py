"""OCR contracts and provider implementations."""

from app.ocr.base import OCRProvider
from app.ocr.types import OCRError, OCRLine, OCRResult
from app.ocr.utils import normalize_ocr_text

__all__ = [
    "OCRError",
    "OCRLine",
    "OCRProvider",
    "OCRResult",
    "create_ocr_provider",
    "create_local_ocr_provider",
    "normalize_ocr_text",
]


def __getattr__(name: str):
    """Load factory helpers lazily so the standalone worker stays headless."""

    if name == "create_ocr_provider":
        from app.ocr.factory import create_ocr_provider

        return create_ocr_provider
    if name == "create_local_ocr_provider":
        from app.ocr.factory import create_local_ocr_provider

        return create_local_ocr_provider
    raise AttributeError(name)
