import numpy as np
import pytest
import os
import subprocess
import sys
from pathlib import Path
from PySide6.QtGui import QImage

from app.auto_watch.debug_overlay import event_label, format_ratio, state_label
from app.auto_watch.models import DetectorConfig, MonitorState, WatchEvent
from app.analysis import AnalysisMode
from app.auto_watch import AnalysisDispatcher, AnalysisState, AutoWatchDispatcherBridge, AutoWatchSettings
from tests.test_auto_watch_dispatcher import FakeScheduler, FakeWorker
from app.auto_watch.coordinator import AutoWatchCoordinator
from tools.auto_watch_detector_demo import (
    FakeAnalysisCollector,
    WatchReporter,
    build_parser,
    make_interrupt_handler,
    safe_close,
    run_ocr_preflight,
    start_watch,
    stop_watch,
    tick,
)


class FakeSampler:
    def __init__(self, image): self.image = image
    def sample(self): return self.image.copy()


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


def test_start_watch_explicitly_presents_initial_generation_zero():
    class Overlay:
        def __init__(self): self.calls = []
        def set_status(self, *args, **kwargs): self.calls.append((args, kwargs))
    overlay = Overlay()
    start_watch(FakeTimer(), AutoWatchCoordinator(), overlay)
    assert overlay.calls == [((MonitorState.ARMING,), {"generation": 0})]


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


def test_demo_settings_cli_and_fake_collector_are_shared_and_once_per_generation():
    args = build_parser().parse_args(["--poll-interval-ms", "80", "--stable-samples", "5"])
    assert (args.poll_interval_ms, args.stable_samples) == (80, 5)
    output = []; collector = FakeAnalysisCollector(output.append)
    c = AutoWatchCoordinator(settings=__import__('app.auto_watch', fromlist=['AutoWatchSettings']).AutoWatchSettings(
        poll_interval_ms=args.poll_interval_ms, stable_samples_required=args.stable_samples),
        analysis_callback=collector)
    c.start(); c.tick(np.zeros((2, 2), dtype=np.uint8)); c.analyze_now(); c.analyze_now()
    assert [generation for _, generation in collector.events] == [1, 2]


def test_real_local_preflight_prepares_shared_session_and_reports_ready():
    class Session:
        def __init__(self): self.prepare_calls = 0
        def prepare(self): self.prepare_calls += 1

    output = []
    session = Session()
    config = type("Config", (), {"ocr_provider": "local"})()

    assert run_ocr_preflight(config, session, output.append) is True
    assert session.prepare_calls == 1
    assert output == [
        "real OCR preflight passed: persistent worker ready; same session reused "
        "for subsequent generations."
    ]


@pytest.mark.parametrize(
    ("message", "diagnosis"),
    [
        ("找不到本地 OCR 组件", "component_missing"),
        ("Local OCR persistent worker failed to start.", "worker_start_failed"),
        ("Local OCR persistent worker startup timed out.", "model_load_timeout"),
    ],
)
def test_real_local_preflight_reports_classified_failure_and_is_retryable(message, diagnosis):
    class Session:
        def prepare(self): raise RuntimeError(message)

    output = []
    config = type("Config", (), {"ocr_provider": "local"})()

    assert run_ocr_preflight(config, Session(), output.append) is False
    assert output == [f"real OCR preflight failed diagnosis={diagnosis}: {message}"]


@pytest.mark.parametrize("mode", [AnalysisMode.TEXT, AnalysisMode.VISION])
def test_tick_bridge_submits_full_resolution_once_per_stable_generation(mode):
    settings = AutoWatchSettings(stable_samples_required=1)
    source = QImage(640, 360, QImage.Format.Format_RGBA8888); source.fill(0)
    sampler = FakeSampler(source)
    coordinator = AutoWatchCoordinator(settings=settings); coordinator.start()
    workers = []
    dispatcher = AnalysisDispatcher(worker_factory=lambda request: (workers.append(FakeWorker(request)) or workers[-1]))
    bridge = AutoWatchDispatcherBridge(dispatcher, mode)
    tick(sampler, coordinator, settings.detector_config, bridge=bridge)
    event = tick(sampler, coordinator, settings.detector_config, bridge=bridge)
    assert event is not None and len(workers) == 1
    assert workers[0].request.generation == event.generation
    assert workers[0].request.image.size() == source.size()
    assert bridge.submit_event(event, source) is None


def test_analyze_now_uses_same_delay_and_stop_cancels_delayed_request():
    scheduler = FakeScheduler(); settings = AutoWatchSettings(stable_samples_required=1, analysis_delay_ms=25)
    source = QImage(500, 300, QImage.Format.Format_RGBA8888); source.fill(0)
    sampler = FakeSampler(source); coordinator = AutoWatchCoordinator(settings=settings); coordinator.start()
    workers = []
    dispatcher = AnalysisDispatcher(settings=settings, scheduler=scheduler,
                                    worker_factory=lambda request: (workers.append(FakeWorker(request)) or workers[-1]))
    bridge = AutoWatchDispatcherBridge(dispatcher)
    tick(sampler, coordinator, settings.detector_config, bridge=bridge)
    event = tick(sampler, coordinator, settings.detector_config, bridge=bridge)
    assert event is not None and not workers
    manual = coordinator.analyze_now()
    request = bridge.submit_event(manual, source)
    assert request is not None and not workers and len(scheduler.jobs) == 2
    dispatcher.stop(); scheduler.fire(1)
    assert not workers and dispatcher.state is AnalysisState.IDLE


def test_dispatcher_demo_nonzero_delay_event_loop_finishes():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy(); env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run([sys.executable, str(root / "tools/auto_watch_dispatcher_demo.py"),
                             "--mode", "vision", "--delay-ms", "5"], cwd=root,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert "active generation=1 mode=vision" in result.stdout
    assert "finished generation=1 state=IDLE" in result.stdout
