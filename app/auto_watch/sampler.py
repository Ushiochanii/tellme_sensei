from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from typing import Callable

from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QImage, QPixmap, QScreen

from .models import AutoWatchSettings


@dataclass(frozen=True)
class ScreenSampler:
    screen: QScreen
    logical_roi: QRect
    timer_factory: Callable[[], QTimer] = QTimer
    settings: AutoWatchSettings = AutoWatchSettings()

    def __post_init__(self) -> None:
        # Keep the Phase 1 third positional ``timer_factory`` slot usable while
        # allowing the natural ``ScreenSampler(screen, roi, settings)`` form.
        if isinstance(self.timer_factory, AutoWatchSettings):
            object.__setattr__(self, "settings", self.timer_factory)
            object.__setattr__(self, "timer_factory", QTimer)
        if self.logical_roi.isEmpty():
            raise ValueError("logical ROI must be non-empty")
        geometry = self.screen.geometry()
        if geometry.width() <= 0 or geometry.height() <= 0:
            raise ValueError("screen geometry must have positive width and height")

    def physical_roi(self) -> QRect:
        _shot, physical = self._capture_and_clip()
        return QRect(physical)

    def sample(self) -> QImage:
        shot, physical = self._capture_and_clip()
        return shot.copy(physical)

    def _capture_and_clip(self) -> tuple[QImage, QRect]:
        """Capture once, map the logical ROI, and apply the same clipping everywhere."""
        shot = self._grab_image()
        geometry = self.screen.geometry()
        if geometry.width() <= 0 or geometry.height() <= 0:
            raise RuntimeError("screen geometry must have positive width and height")
        sx, sy = shot.width() / geometry.width(), shot.height() / geometry.height()
        left = floor(self.logical_roi.x() * sx)
        top = floor(self.logical_roi.y() * sy)
        right = ceil((self.logical_roi.x() + self.logical_roi.width()) * sx)
        bottom = ceil((self.logical_roi.y() + self.logical_roi.height()) * sy)
        physical = QRect(left, top, right - left, bottom - top)
        physical = physical.intersected(QRect(0, 0, shot.width(), shot.height()))
        if physical.isEmpty():
            raise RuntimeError("logical ROI maps outside the captured screen")
        return shot, physical

    def _grab_image(self) -> QImage:
        """Normalize QScreen's QPixmap result and test doubles returning QImage."""
        captured = self.screen.grabWindow(0)
        if isinstance(captured, QPixmap):
            image = captured.toImage()
        elif isinstance(captured, QImage):
            image = captured
        else:
            raise TypeError("screen.grabWindow(0) must return QPixmap or QImage")
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            raise RuntimeError("screen capture returned an empty image")
        return image

    def create_timer(self, callback: Callable[[], None], interval_ms: int | None = None) -> QTimer:
        timer = self.timer_factory()
        timer.setInterval(self.settings.poll_interval_ms if interval_ms is None else interval_ms)
        timer.timeout.connect(callback)
        return timer
