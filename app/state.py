"""Application states used to suppress duplicate capture requests."""

from __future__ import annotations

from enum import Enum, auto


class AppState(Enum):
    IDLE = auto()
    CAPTURING = auto()
    OCR_PROCESSING = auto()
    AI_PROCESSING = auto()
    ERROR = auto()
