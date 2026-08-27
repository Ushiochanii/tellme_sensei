"""Pure, Phase 1 screen-change detection primitives."""

from .coordinator import AutoWatchCoordinator
from .detector import compare_frames, preprocess_qimage
from .debug_overlay import DebugOverlay, event_label, format_ratio, state_label
from .models import DetectorConfig, DetectorFrame, DetectorMetrics, MonitorState, WatchEvent
from .sampler import ScreenSampler
from .stability import StabilityTracker

__all__ = ["AutoWatchCoordinator", "DebugOverlay", "DetectorConfig", "DetectorFrame",
           "DetectorMetrics", "MonitorState", "ScreenSampler", "StabilityTracker",
           "WatchEvent", "compare_frames", "event_label", "format_ratio",
           "preprocess_qimage", "state_label"]
