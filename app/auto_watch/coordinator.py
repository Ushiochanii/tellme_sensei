from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import numpy as np

from .detector import compare_frames
from .models import AutoWatchSettings, DetectorConfig, DetectorFrame, MonitorState, WatchEvent
from .stability import StabilityTracker


@dataclass(frozen=True)
class CoordinatorEvent:
    kind: WatchEvent
    generation: int
    frame: DetectorFrame


class AutoWatchCoordinator:
    """Synchronous state machine; it owns no Qt, screen, timer, or GUI objects."""
    def __init__(self, config: DetectorConfig | None = None, *, settings: AutoWatchSettings | None = None,
                 analysis_callback: Callable[[CoordinatorEvent], None] | None = None) -> None:
        if config is not None and settings is not None:
            raise ValueError("provide config or settings, not both")
        self.settings = settings or AutoWatchSettings(detector_config=config or DetectorConfig())
        self.config = self.settings.detector_config
        self.state = MonitorState.STOPPED
        self.baseline: DetectorFrame | None = None
        self.previous: DetectorFrame | None = None
        self.generation = 0
        self._stability = StabilityTracker(self.config.stability_ratio, self.config.stable_samples_required)
        self._latest_frame: DetectorFrame | None = None
        self.analysis_callback = analysis_callback
        self.callback_errors: list[Exception] = []

    def start(self) -> None:
        if self.state is MonitorState.STOPPED:
            self.state = MonitorState.ARMING

    def tick(self, frame: DetectorFrame | np.ndarray) -> CoordinatorEvent | None:
        current = frame if isinstance(frame, DetectorFrame) else DetectorFrame(frame)
        if self.state in (MonitorState.STOPPED, MonitorState.PAUSED):
            return None
        self._latest_frame = current
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
                    return self._emit(CoordinatorEvent(WatchEvent.INITIAL_STABLE_FRAME, self.generation, current))
                novelty = compare_frames(current, self.baseline, self.config.pixel_delta_threshold).change_ratio
                if novelty >= self.config.novelty_ratio:
                    self.baseline = current
                    self.generation += 1
                    self.state = MonitorState.WATCHING
                    return self._emit(CoordinatorEvent(WatchEvent.NEW_STABLE_FRAME, self.generation, current))
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
                    return self._emit(CoordinatorEvent(WatchEvent.NEW_STABLE_FRAME, self.generation, current))
                self.state = MonitorState.WATCHING
            return None
        return None

    def pause(self) -> None:
        if self.state not in (MonitorState.STOPPED, MonitorState.PAUSED):
            self.state = MonitorState.PAUSED
            self._stability.reset()

    def resume(self) -> None:
        if self.state is MonitorState.PAUSED:
            self.state = MonitorState.ARMING
            self.previous = None
            self._latest_frame = None
            self._stability.reset()

    def stop(self) -> None:
        self.state = MonitorState.STOPPED
        self.baseline = self.previous = None
        self.generation = 0
        self._stability.reset()
        self._latest_frame = None

    def analyze_now(self, callback: Callable[[CoordinatorEvent], None] | None = None, *,
                   frame: DetectorFrame | np.ndarray | None = None) -> CoordinatorEvent | None:
        """Immediately accept the most recently sampled frame, if active.

        ``frame`` is keyword-only so existing callback callers remain compatible;
        the pair coordinator uses it to pass the current dual-region sample.
        """
        if self.state in (MonitorState.STOPPED, MonitorState.PAUSED):
            return None
        if frame is not None:
            self._latest_frame = frame if isinstance(frame, DetectorFrame) else DetectorFrame(frame)
        if self.state in (MonitorState.STOPPED, MonitorState.PAUSED) or self._latest_frame is None:
            return None
        kind = WatchEvent.INITIAL_STABLE_FRAME if self.generation == 0 else WatchEvent.NEW_STABLE_FRAME
        self.generation += 1
        self.baseline = self.previous = self._latest_frame
        self._stability.reset()
        self.state = MonitorState.WATCHING
        return self._emit(CoordinatorEvent(kind, self.generation, self._latest_frame), callback)

    def _emit(self, event: CoordinatorEvent, callback: Callable[[CoordinatorEvent], None] | None = None) -> CoordinatorEvent:
        target = callback if callback is not None else self.analysis_callback
        if target is not None:
            try:
                target(event)
            except Exception as exc:  # demo callbacks must never break monitoring
                self.callback_errors.append(exc)
        return event
