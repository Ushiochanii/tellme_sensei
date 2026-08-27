from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from .detector import compare_frames
from .models import DetectorConfig, DetectorFrame, MonitorState, WatchEvent
from .stability import StabilityTracker


@dataclass(frozen=True)
class CoordinatorEvent:
    kind: WatchEvent
    generation: int
    frame: DetectorFrame


class AutoWatchCoordinator:
    """Synchronous state machine; it owns no Qt, screen, timer, or GUI objects."""
    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()
        self.state = MonitorState.STOPPED
        self.baseline: DetectorFrame | None = None
        self.previous: DetectorFrame | None = None
        self.generation = 0
        self._stability = StabilityTracker(self.config.stability_ratio, self.config.stable_samples_required)

    def start(self) -> None:
        self.stop()
        self.state = MonitorState.ARMING

    def tick(self, frame: DetectorFrame | np.ndarray) -> CoordinatorEvent | None:
        current = frame if isinstance(frame, DetectorFrame) else DetectorFrame(frame)
        if self.state in (MonitorState.STOPPED, MonitorState.PAUSED):
            return None
        if self.previous is None:
            self.previous = current
            return None
        stability = compare_frames(current, self.previous, self.config.pixel_delta_threshold).change_ratio
        self.previous = current
        if self.state is MonitorState.ARMING:
            if self._stability.update(stability):
                self._stability.reset()
                if self.baseline is None:
                    self.baseline = current
                    self.generation = 1
                    self.state = MonitorState.WATCHING
                    return CoordinatorEvent(WatchEvent.INITIAL_STABLE_FRAME, self.generation, current)
                novelty = compare_frames(current, self.baseline, self.config.pixel_delta_threshold).change_ratio
                if novelty >= self.config.novelty_ratio:
                    self.baseline = current
                    self.generation += 1
                    self.state = MonitorState.WATCHING
                    return CoordinatorEvent(WatchEvent.NEW_STABLE_FRAME, self.generation, current)
                self.state = MonitorState.WATCHING
            return None
        if self.state is MonitorState.WATCHING:
            novelty = compare_frames(current, self.baseline, self.config.pixel_delta_threshold).change_ratio
            if novelty >= self.config.novelty_ratio:
                self.state = MonitorState.CHANGING
                self._stability.reset()
            return None
        if self.state is MonitorState.CHANGING:
            if self._stability.update(stability):
                novelty = compare_frames(current, self.baseline, self.config.pixel_delta_threshold).change_ratio
                self._stability.reset()
                if novelty >= self.config.novelty_ratio:
                    self.baseline = current
                    self.generation += 1
                    self.state = MonitorState.WATCHING
                    return CoordinatorEvent(WatchEvent.NEW_STABLE_FRAME, self.generation, current)
                self.state = MonitorState.WATCHING
            return None
        return None

    def pause(self) -> None:
        if self.state is not MonitorState.STOPPED:
            self.state = MonitorState.PAUSED
            self._stability.reset()

    def resume(self) -> None:
        if self.state is MonitorState.PAUSED:
            self.state = MonitorState.ARMING
            self.previous = None
            self._stability.reset()

    def stop(self) -> None:
        self.state = MonitorState.STOPPED
        self.baseline = self.previous = None
        self.generation = 0
        self._stability.reset()
