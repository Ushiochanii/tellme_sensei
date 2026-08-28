"""One-capture sampler for the Context + Question Auto Watch core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QImage

from .models import AutoWatchSettings, ContextQuestionRegions
from .sampler import _normalize_capture, _physical_roi_for_image


@dataclass(frozen=True)
class ContextQuestionImages:
    """Detached full-resolution crops produced from one screen capture."""

    context: QImage
    question: QImage

    def __post_init__(self) -> None:
        for name in ("context", "question"):
            image = getattr(self, name)
            if not isinstance(image, QImage) or image.isNull() or image.width() <= 0 or image.height() <= 0:
                raise ValueError(f"{name} image must be non-empty")
            object.__setattr__(self, name, image.copy())


class ContextQuestionSampler:
    """Capture one display image and crop the two selected regions from it."""

    def __init__(self, regions: ContextQuestionRegions, timer_factory: Callable[[], QTimer] = QTimer,
                 settings: AutoWatchSettings = AutoWatchSettings()) -> None:
        # Match ScreenSampler's convenient ``(regions, settings)`` form.
        if isinstance(timer_factory, AutoWatchSettings):
            settings = timer_factory
            timer_factory = QTimer
        if not isinstance(regions, ContextQuestionRegions):
            raise ValueError("ContextQuestionSampler requires ContextQuestionRegions")
        geometry = QRect(regions.screen.geometry())
        if geometry.width() <= 0 or geometry.height() <= 0:
            raise ValueError("screen geometry must have positive width and height")
        self.regions = regions
        self.timer_factory = timer_factory
        self.settings = settings

    @property
    def screen(self):
        return self.regions.screen

    def sample(self) -> ContextQuestionImages:
        geometry = QRect(self.screen.geometry())
        if geometry != self.regions.screen_geometry:
            raise RuntimeError("screen geometry changed after Context and Question selection")
        current_dpr = float(self.screen.devicePixelRatio()) if hasattr(self.screen, "devicePixelRatio") else 1.0
        if abs(current_dpr - self.regions.device_pixel_ratio) > 1e-6:
            raise RuntimeError("screen device pixel ratio changed after Context and Question selection")

        # Both crops intentionally come from this single capture per polling tick.
        shot = _normalize_capture(self.screen.grabWindow(0))
        context_roi = _physical_roi_for_image(self.regions.context.logical_roi, geometry, shot)
        question_roi = _physical_roi_for_image(self.regions.question.logical_roi, geometry, shot)
        return ContextQuestionImages(shot.copy(context_roi), shot.copy(question_roi))

    def create_timer(self, callback, interval_ms: int | None = None) -> QTimer:
        timer = self.timer_factory()
        timer.setInterval(self.settings.poll_interval_ms if interval_ms is None else interval_ms)
        timer.timeout.connect(callback)
        return timer


__all__ = ["ContextQuestionImages", "ContextQuestionSampler"]
