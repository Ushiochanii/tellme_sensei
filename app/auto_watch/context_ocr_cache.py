"""Session-scoped cache for Context OCR results."""

from __future__ import annotations

from app.ocr.types import OCRResult


class ContextOCRCache:
    """Keep the most recent completed Context OCR result for one session.

    The monitor already assigns a monotonically increasing revision whenever
    the Context changes.  That revision is the complete cache key; the cache
    intentionally does not inspect or fingerprint image pixels.
    """

    def __init__(self) -> None:
        self._cached_context_revision: int | None = None
        self._cached_context_ocr_result: OCRResult | None = None
        self._clear_generation = 0

    @property
    def clear_generation(self) -> int:
        """Return the generation in which the current cache was created."""

        return self._clear_generation

    @property
    def cached_context_revision(self) -> int | None:
        return self._cached_context_revision

    @property
    def cached_context_ocr_result(self) -> OCRResult | None:
        return self._cached_context_ocr_result

    def get(self, context_revision: int) -> OCRResult | None:
        """Return the result only when it belongs to ``context_revision``."""

        self._validate_revision(context_revision)
        if context_revision != self._cached_context_revision:
            return None
        return self._cached_context_ocr_result

    def put(self, context_revision: int, result: OCRResult, *, clear_generation: int | None = None) -> None:
        """Store one completed OCR result under its Context revision."""

        self._validate_revision(context_revision)
        if not isinstance(result, OCRResult):
            raise TypeError("Context OCR cache requires an OCRResult")
        if clear_generation is not None and clear_generation != self._clear_generation:
            return
        self._cached_context_revision = context_revision
        self._cached_context_ocr_result = result

    def clear(self) -> None:
        """Drop all cached data at the end of a session."""

        self._clear_generation += 1
        self._cached_context_revision = None
        self._cached_context_ocr_result = None

    @staticmethod
    def _validate_revision(context_revision: int) -> None:
        if not isinstance(context_revision, int) or isinstance(context_revision, bool) or context_revision <= 0:
            raise ValueError("context_revision must be a positive integer")


__all__ = ["ContextOCRCache"]
