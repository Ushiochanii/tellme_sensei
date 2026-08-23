"""Stable OCR result types shared by every provider."""

from __future__ import annotations

from dataclasses import dataclass


class OCRError(RuntimeError):
    """A user-facing OCR error."""


class OCRCancelled(OCRError):
    """Raised when an OCR provider stops because cancellation was requested."""


@dataclass(frozen=True)
class OCRLine:
    """One recognized text line and its optional confidence/position."""

    text: str
    confidence: float | None = None
    top: float = 0.0
    left: float = 0.0


@dataclass(frozen=True)
class OCRResult:
    """Normalized OCR output passed to the LLM service."""

    text: str
    lines: tuple[OCRLine, ...]
