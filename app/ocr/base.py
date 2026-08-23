"""Provider contract for OCR backends."""

from __future__ import annotations

from typing import Any, Protocol

from app.ocr.types import OCRResult


class OCRProvider(Protocol):
    """Minimal OCR interface consumed by the pipeline and worker."""

    def recognize(self, image: Any) -> OCRResult:
        """Recognize text from an image path or an in-memory image."""
