"""Platform capabilities for OCR components."""

from __future__ import annotations

from app.local_ocr.platform import current_spec


def is_local_ocr_supported() -> bool:
    """Return whether the bundled Local OCR component is supported."""

    return current_spec().supported
