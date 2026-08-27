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
        for name, value in (("max_side", self.max_side), ("poll_interval_ms", self.poll_interval_ms),
                            ("pixel_delta_threshold", self.pixel_delta_threshold),
                            ("stable_samples_required", self.stable_samples_required)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
        for name, value in (("novelty_ratio", self.novelty_ratio), ("stability_ratio", self.stability_ratio)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be numeric")
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


@dataclass(frozen=True, init=False)
class AutoWatchSettings:
    """Immutable Phase 2 settings shared by the sampler, coordinator and demo.

    ``detector_config`` is accepted as a compatibility-friendly nested source;
    the direct detector keyword arguments are also accepted for CLI/test code.
    """

    poll_interval_ms: int
    detector_config: DetectorConfig
    analysis_delay_ms: int

    def __init__(self, poll_interval_ms: int | None = None,
                 detector_config: DetectorConfig | None = None,
                 analysis_delay_ms: int = 0, *, max_side: int | None = None,
                 pixel_delta_threshold: int | None = None,
                 novelty_ratio: float | None = None,
                 stability_ratio: float | None = None,
                 stable_samples_required: int | None = None) -> None:
        if detector_config is not None and not isinstance(detector_config, DetectorConfig):
            raise ValueError("detector_config must be a DetectorConfig")
        base = detector_config or DetectorConfig()
        if poll_interval_ms is not None and (not isinstance(poll_interval_ms, int) or isinstance(poll_interval_ms, bool)):
            raise ValueError("poll_interval_ms must be an integer")
        values = dict(max_side=base.max_side,
                      poll_interval_ms=base.poll_interval_ms if poll_interval_ms is None else poll_interval_ms,
                      pixel_delta_threshold=base.pixel_delta_threshold,
                      novelty_ratio=base.novelty_ratio,
                      stability_ratio=base.stability_ratio,
                      stable_samples_required=base.stable_samples_required)
        for name, value in (("max_side", max_side), ("pixel_delta_threshold", pixel_delta_threshold),
                            ("novelty_ratio", novelty_ratio), ("stability_ratio", stability_ratio),
                            ("stable_samples_required", stable_samples_required)):
            if value is not None:
                values[name] = value
        config = DetectorConfig(**values)
        if not isinstance(analysis_delay_ms, int) or isinstance(analysis_delay_ms, bool) or analysis_delay_ms < 0:
            raise ValueError("analysis_delay_ms must be a non-negative integer")
        object.__setattr__(self, "poll_interval_ms", config.poll_interval_ms)
        object.__setattr__(self, "detector_config", config)
        object.__setattr__(self, "analysis_delay_ms", analysis_delay_ms)

    @property
    def detector(self) -> DetectorConfig:
        return self.detector_config

    @property
    def max_side(self) -> int:
        return self.detector_config.max_side

    @property
    def pixel_delta_threshold(self) -> int:
        return self.detector_config.pixel_delta_threshold

    @property
    def novelty_ratio(self) -> float:
        return self.detector_config.novelty_ratio

    @property
    def stability_ratio(self) -> float:
        return self.detector_config.stability_ratio

    @property
    def stable_samples_required(self) -> int:
        return self.detector_config.stable_samples_required

    @property
    def estimated_stability_ms(self) -> int:
        return self.poll_interval_ms * self.stable_samples_required

    @property
    def expected_stability_ms(self) -> int:
        return self.estimated_stability_ms


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
