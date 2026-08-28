"""Pure auto-watch detection and Phase 2 control primitives."""

from .coordinator import AutoWatchCoordinator
from .dispatcher import AnalysisDispatcher, AutoWatchDispatcherBridge
from .detector import compare_frames, preprocess_qimage
from .debug_overlay import DebugOverlay, event_label, format_ratio, state_label
from .models import (AnalysisRequest, AnalysisState, AutoWatchSettings, ContextQuestionRegions,
                     ContextQuestionSnapshot, DetectorConfig, DetectorFrame, DetectorMetrics,
                     MonitorState, PairMonitorState, PairSnapshot, WatchEvent, WatchRegion,
                     WatchRegionRole)
from .pair_coordinator import PairCoordinator
from .pair_sampler import ContextQuestionImages, ContextQuestionSampler
from .sampler import ScreenSampler
from .stability import StabilityTracker

__all__ = ["AutoWatchCoordinator", "AnalysisDispatcher", "AutoWatchDispatcherBridge", "AutoWatchSettings",
           "ContextQuestionImages", "ContextQuestionRegions", "ContextQuestionSampler", "ContextQuestionSnapshot",
           "DebugOverlay", "DetectorConfig", "DetectorFrame", "DetectorMetrics", "MonitorState",
           "PairCoordinator", "PairMonitorState", "PairSnapshot", "ScreenSampler", "StabilityTracker",
           "AnalysisRequest", "AnalysisState", "WatchEvent", "WatchRegion", "WatchRegionRole",
           "compare_frames", "event_label", "format_ratio", "preprocess_qimage", "state_label"]
