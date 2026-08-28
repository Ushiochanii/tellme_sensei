from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import math
import uuid
import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage, QScreen

from app.analysis import AnalysisMode


class MonitorState(Enum):
    STOPPED = auto()
    ARMING = auto()
    WATCHING = auto()
    CHANGING = auto()
    PAUSED = auto()


# Pair monitoring deliberately projects onto the existing compact vocabulary.
PairMonitorState = MonitorState


class WatchRegionRole(Enum):
    CONTEXT = "context"
    QUESTION = "question"


@dataclass(frozen=True)
class WatchRegion:
    """A screen-local ROI plus the display snapshot it was selected against."""

    logical_roi: QRect
    screen: QScreen
    screen_geometry: QRect
    device_pixel_ratio: float
    session_id: str

    @classmethod
    def create(cls, screen: QScreen, roi: QRect, session_id: str | None = None) -> "WatchRegion":
        if screen is None or not isinstance(roi, QRect) or roi.isEmpty():
            raise ValueError("watch ROI must be non-empty")
        geometry = QRect(screen.geometry())
        local = QRect(0, 0, geometry.width(), geometry.height())
        if geometry.isEmpty() or not local.contains(roi.topLeft()) or not local.contains(roi.bottomRight()):
            raise ValueError("watch ROI must be fully contained in one screen")
        dpr = float(screen.devicePixelRatio()) if hasattr(screen, "devicePixelRatio") else 1.0
        return cls(QRect(roi), screen, geometry, dpr, session_id or uuid.uuid4().hex)

    @property
    def global_roi(self) -> QRect:
        return self.logical_roi.translated(self.screen_geometry.topLeft())

    def is_valid(self) -> bool:
        screens = QGuiApplication.screens()
        if self.screen not in screens:
            return False
        if QRect(self.screen.geometry()) != self.screen_geometry:
            return False
        current_dpr = float(self.screen.devicePixelRatio()) if hasattr(self.screen, "devicePixelRatio") else 1.0
        return abs(current_dpr - self.device_pixel_ratio) <= 1e-6


@dataclass(frozen=True)
class ContextQuestionRegions:
    """Exactly one Context and one Question ROI from the same display/session."""

    context: WatchRegion
    question: WatchRegion
    session_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.context, WatchRegion) or not isinstance(self.question, WatchRegion):
            raise ValueError("Context and Question must both be WatchRegion instances")
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if self.context.screen is None or self.question.screen is None:
            raise ValueError("Context and Question must belong to a screen")
        if self.context.logical_roi.isEmpty() or self.question.logical_roi.isEmpty():
            raise ValueError("Context and Question ROIs must be non-empty")
        if self.context.session_id != self.question.session_id or self.context.session_id != self.session_id:
            raise ValueError("Context and Question must use the same session ID")
        same_screen = self.context.screen is self.question.screen
        if not same_screen:
            try:
                same_screen = bool(self.context.screen == self.question.screen)
            except Exception:
                same_screen = False
        if not same_screen:
            raise ValueError("Context and Question must be on the same screen")
        if self.context.screen_geometry != self.question.screen_geometry:
            raise ValueError("Context and Question must use the same screen geometry")
        if abs(self.context.device_pixel_ratio - self.question.device_pixel_ratio) > 1e-6:
            raise ValueError("Context and Question must use the same device pixel ratio")

    @classmethod
    def create(cls, context: WatchRegion, question: WatchRegion, session_id: str | None = None) -> "ContextQuestionRegions":
        return cls(context, question, session_id or context.session_id)

    @property
    def screen(self) -> QScreen:
        return self.context.screen

    @property
    def screen_geometry(self) -> QRect:
        return QRect(self.context.screen_geometry)

    @property
    def device_pixel_ratio(self) -> float:
        return self.context.device_pixel_ratio

    def is_valid(self) -> bool:
        """Return whether both selected regions still describe the same display snapshot."""

        return self.context.is_valid() and self.question.is_valid()


class WatchEvent(Enum):
    INITIAL_STABLE_FRAME = auto()
    NEW_STABLE_FRAME = auto()


class AnalysisState(Enum):
    IDLE = auto()
    RUNNING = auto()
    CANCELLING = auto()


@dataclass(frozen=True)
class AnalysisRequest:
    """Detached, full-resolution input handed to one analysis generation."""

    generation: int
    mode: AnalysisMode
    image: QImage
    source: str = "auto_watch"
    session_id: str = "auto-watch"
    request_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        if not isinstance(self.mode, AnalysisMode):
            raise ValueError("mode must be AnalysisMode.TEXT or AnalysisMode.VISION")
        if self.source != "auto_watch":
            raise ValueError("source must be auto_watch")
        for name in ("session_id", "request_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.image, QImage) or self.image.isNull():
            raise ValueError("analysis request requires a non-empty QImage")
        object.__setattr__(self, "image", self.image.copy())


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


@dataclass(frozen=True)
class PairSnapshot:
    """Detached full-resolution images for one accepted Context + Question pair."""

    generation: int
    context_revision: int
    question_revision: int
    context_image: QImage
    question_image: QImage

    def __post_init__(self) -> None:
        for name in ("generation", "context_revision", "question_revision"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("context_image", "question_image"):
            image = getattr(self, name)
            if not isinstance(image, QImage) or image.isNull() or image.width() <= 0 or image.height() <= 0:
                raise ValueError(f"{name} must be a non-empty QImage")
            object.__setattr__(self, name, image.copy())


# Keep the descriptive design-doc name available alongside the concise test/API name.
ContextQuestionSnapshot = PairSnapshot
