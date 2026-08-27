from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import math

import numpy as np


class MonitorState(Enum):
    STOPPED = auto()
    ARMING = auto()
    WATCHING = auto()
    CHANGING = auto()
    PAUSED = auto()


class WatchEvent(Enum):
    INITIAL_STABLE_FRAME = auto()
    NEW_STABLE_FRAME = auto()


@dataclass(frozen=True)
class DetectorConfig:
    max_side: int = 96
    poll_interval_ms: int = 250
    pixel_delta_threshold: int = 15
    novelty_ratio: float = 0.06
    stability_ratio: float = 0.015
    stable_samples_required: int = 3

    def __post_init__(self) -> None:
        if self.max_side < 1:
            raise ValueError("max_side must be positive")
        if self.poll_interval_ms < 1:
            raise ValueError("poll_interval_ms must be positive")
        if not 1 <= self.pixel_delta_threshold <= 255:
            raise ValueError("pixel_delta_threshold must be between 1 and 255")
        for name, value in (("novelty_ratio", self.novelty_ratio), ("stability_ratio", self.stability_ratio)):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be a finite ratio between 0 and 1")
        if self.stable_samples_required < 1:
            raise ValueError("stable_samples_required must be positive")


@dataclass(frozen=True)
class DetectorFrame:
    pixels: np.ndarray

    def __post_init__(self) -> None:
        array = np.asarray(self.pixels, dtype=np.uint8)
        if array.ndim != 2 or 0 in array.shape:
            raise ValueError("detector frame must be a non-empty 2-D grayscale array")
        array = np.ascontiguousarray(array).copy()
        array.setflags(write=False)
        object.__setattr__(self, "pixels", array)


@dataclass(frozen=True)
class DetectorMetrics:
    change_ratio: float
    changed_bbox_ratio: float | None = None
