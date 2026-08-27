import numpy as np
import pytest

from app.auto_watch.debug_overlay import event_label, format_ratio, state_label
from app.auto_watch.models import DetectorConfig, MonitorState, WatchEvent
from app.auto_watch.coordinator import AutoWatchCoordinator
from tools.auto_watch_detector_demo import (
    WatchReporter,
    build_parser,
    make_interrupt_handler,
    safe_close,
    start_watch,
    stop_watch,
)


class FakeTimer:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self): self.started += 1
    def stop(self): self.stopped += 1


class FakeLoop:
    def __init__(self): self.quit_calls = 0
    def quit(self): self.quit_calls += 1


class FakeApp(FakeLoop):
    pass


class FakeOverlay:
    def __init__(self): self.close_calls = 0
    def close(self): self.close_calls += 1


class DeletedQtOverlay:
    def close(self):
        raise RuntimeError("Internal C++ object (CaptureOverlay) already deleted.")


class BrokenOverlay:
    def close(self):
        raise RuntimeError("unexpected close failure")


def test_start_watch_starts_coordinator_before_timer():
    timer = FakeTimer()
    coordinator = AutoWatchCoordinator(DetectorConfig())
    start_watch(timer, coordinator)
    assert coordinator.state is MonitorState.ARMING
    assert timer.started == 1


def test_stop_watch_cleans_timer_and_coordinator():
    timer = FakeTimer()
    coordinator = AutoWatchCoordinator()
    debug_overlay = FakeOverlay()
    coordinator.start()
    coordinator.tick(np.zeros((2, 2), dtype=np.uint8))
    stop_watch(timer, coordinator, debug_overlay=debug_overlay)
    assert timer.stopped == 1
    assert coordinator.state is MonitorState.STOPPED
    assert coordinator.baseline is None and coordinator.previous is None
    assert debug_overlay.close_calls == 1


def test_interrupt_during_selection_cleans_all_runtime_objects():
    timer = FakeTimer()
    coordinator = AutoWatchCoordinator()
    coordinator.start()
    selection_loop = FakeLoop()
    app = FakeApp()
    overlay = FakeOverlay()
    interrupted = []
    handler = make_interrupt_handler(
        selection_loop, app, overlay, coordinator, [timer], interrupted
    )
    handler(2, None)
    assert interrupted == [True]
    assert timer.stopped == 1
    assert coordinator.state is MonitorState.STOPPED
    assert overlay.close_calls == 1
    assert selection_loop.quit_calls == 1
    assert app.quit_calls == 1


def test_deleted_qt_overlay_is_safe_in_handler_and_final_cleanup():
    timer = FakeTimer()
    coordinator = AutoWatchCoordinator()
    coordinator.start()
    selection_loop = FakeLoop()
    app = FakeApp()
    interrupted = []
    handler = make_interrupt_handler(
        selection_loop,
        app,
        DeletedQtOverlay(),
        coordinator,
        [timer],
        interrupted,
        [DeletedQtOverlay()],
    )

    handler(2, None)
    stop_watch(timer, coordinator, debug_overlay=DeletedQtOverlay())
    assert interrupted == [True]
    assert coordinator.state is MonitorState.STOPPED


def test_safe_close_does_not_hide_unexpected_runtime_errors():
    safe_close(DeletedQtOverlay())
    with pytest.raises(RuntimeError, match="unexpected close failure"):
        safe_close(BrokenOverlay())


def test_status_and_event_labels_are_compact_chinese():
    assert state_label(MonitorState.ARMING) == "正在建立基准"
    assert state_label(MonitorState.WATCHING) == "正在监控"
    assert state_label(MonitorState.CHANGING) == "检测到变化，等待稳定"
    assert state_label(MonitorState.PAUSED) == "已暂停"
    assert state_label(MonitorState.STOPPED) == "已停止"
    assert event_label(WatchEvent.INITIAL_STABLE_FRAME) == "初始画面已稳定"
    assert event_label(WatchEvent.NEW_STABLE_FRAME) == "检测到新的稳定画面"
    assert format_ratio(0.1234) == "12.3%"


def test_reporter_is_quiet_between_state_event_and_heartbeat():
    output = []
    now = [0.0]
    reporter = WatchReporter(
        heartbeat_seconds=10,
        clock=lambda: now[0],
        output=output.append,
    )
    metrics = {"capture": 1.0, "preprocess": 2.0, "compare": 3.0, "total": 6.0}
    reporter.tick(
        state=MonitorState.ARMING,
        event=None,
        novelty_ratio=None,
        frame_ratio=0.0,
        timings_ms=metrics,
    )
    now[0] = 1
    reporter.tick(
        state=MonitorState.ARMING,
        event=None,
        novelty_ratio=None,
        frame_ratio=0.0,
        timings_ms=metrics,
    )
    assert len(output) == 1
    now[0] = 2
    reporter.tick(
        state=MonitorState.WATCHING,
        event=WatchEvent.INITIAL_STABLE_FRAME,
        novelty_ratio=0.0,
        frame_ratio=0.0,
        timings_ms=metrics,
    )
    assert len(output) == 2
    assert "相对基准变化：0.0%" in output[-1]
    assert "帧间变化：0.0%" in output[-1]
    assert "事件：初始画面已稳定" in output[-1]


def test_verbose_parser_and_reporter_include_each_frame_timing():
    assert build_parser().parse_args(["--verbose"]).verbose is True
    output = []
    reporter = WatchReporter(verbose=True, output=output.append)
    reporter.tick(
        state=MonitorState.WATCHING,
        event=None,
        novelty_ratio=0.2,
        frame_ratio=0.03,
        timings_ms={"capture": 1.0, "preprocess": 2.0, "compare": 3.0, "total": 6.0},
    )
    reporter.tick(
        state=MonitorState.WATCHING,
        event=None,
        novelty_ratio=0.2,
        frame_ratio=0.03,
        timings_ms={"capture": 1.1, "preprocess": 2.1, "compare": 3.1, "total": 6.3},
    )
    assert len(output) == 2
    assert "timing capture=" in output[-1]
