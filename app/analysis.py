"""Explicit user-selected analysis modes."""

from __future__ import annotations

from enum import Enum


class AnalysisMode(str, Enum):
    """The two independent screenshot analysis pipelines."""

    TEXT = "text"
    VISION = "vision"
