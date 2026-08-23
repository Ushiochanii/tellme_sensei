"""Provider-independent OCR text utilities."""

from __future__ import annotations

from app.ocr.types import OCRLine


def normalize_ocr_text(lines: list[OCRLine]) -> str:
    """Keep recognized content while removing empty/meaningless whitespace."""

    meaningful = [line.text.strip() for line in lines if line.text.strip()]
    return "\n".join(meaningful)
