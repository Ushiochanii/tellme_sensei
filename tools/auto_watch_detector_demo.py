"""Manual, non-production screen detector demo (never stores image/text data)."""
from __future__ import annotations

import argparse
from collections.abc import Callable
import re
import signal
import sys
import time
from queue import Empty, Queue
from threading import Thread
from pathlib import Path

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auto_watch import (
    AutoWatchCoordinator,
    AutoWatchSettings,
    DebugOverlay,
    DetectorConfig,
    ScreenSampler,
    compare_frames,
    event_label,
    format_ratio,
    preprocess_qimage,
    state_label,
)
from app.auto_watch.models import MonitorState, WatchEvent
from app.capture.overlay import CaptureOverlay


_DELETED_QT_WRAPPER = re.compile(
    r"^Internal C\+\+ object \([^)]*\) already deleted\.?$"
)


def safe_close(qt_object) -> None:
    """Close a Qt wrapper idempotently, preserving every unrelated exception."""

    if qt_object is None:
        return
    try:
        qt_object.close()
    except RuntimeError as exc:
        if not _DELETED_QT_WRAPPER.fullmatch(str(exc).strip()):
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 1 auto-watch screen-change demo; never saves screenshots."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print per-frame ratios and timing details (default output is low-noise)",
    )
    parser.add_argument("--poll-interval-ms", type=int, default=250)
    parser.add_argument("--stable-samples", type=int, default=3)
    return parser


class FakeAnalysisCollector:
    """Demo-only analysis sink: records events, never sends frames to an AI."""
    def __init__(self, output: Callable[[str], None] = print) -> None:
        self.events: list[tuple[WatchEvent, int]] = []
        self._generations: set[int] = set()
        self.output = output

    def __call__(self, event) -> None:
        if event.generation in self._generations:
            return
        self._generations.add(event.generation)
        self.events.append((event.kind, event.generation))
        self.output(f"fake analysis: {event.kind.name} generation={event.generation}")


class CommandReader:
    """Background stdin reader; command execution remains on the Qt thread."""
    def __init__(self, input_stream=sys.stdin) -> None:
        self.commands: Queue[str] = Queue()
        self._thread = Thread(target=self._read, args=(input_stream,), daemon=True)
        self._thread.start()

    def _read(self, stream) -> None:
        for line in stream:
            self.commands.put(line.strip().lower())

    def drain(self) -> list[str]:
        result = []
        while True:
            try: result.append(self.commands.get_nowait())
            except Empty: return result


class WatchReporter:
    """Human-readable terminal reporter with quiet-by-default heartbeat output."""

    def __init__(
        self,
        *,
        verbose: bool = False,
        heartbeat_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        output: Callable[[str], None] = print,
    ) -> None:
        self.verbose = verbose
        self.heartbeat_seconds = heartbeat_seconds
        self._clock = clock
        self._output = output
        self._last_state: MonitorState | None = None
        self._last_output_at: float | None = None

    def selection_prompt(self) -> None:
        self._write("Auto-watch：拖动框选 ROI；Esc/右键取消；Ctrl-C 退出；不会保存截图。")

    def selected(self, roi) -> None:
        self._write(
            f"已选 ROI：{roi.width()}×{roi.height()}；操作：监控期间 Ctrl-C 退出，边框可见且鼠标点击穿透。"
        )

    def cancelled(self) -> None:
        self._write("Auto-watch 已取消：未开始采样。")

    def started(self, state: MonitorState) -> None:
        self._write(f"开始监控；状态：{state_label(state)}；generation=0。命令：Pause/Resume/Analyze Now/Stop/Quit")
        self._last_state = state
        self._last_output_at = self._clock()

    def tick(
        self,
        *,
        state: MonitorState,
        generation: int = 0,
        event: WatchEvent | None,
        novelty_ratio: float | None,
        frame_ratio: float | None,
        timings_ms: dict[str, float],
    ) -> None:
        now = self._clock()
        state_changed = state != self._last_state
        event_happened = event is not None
        heartbeat_due = (
            self._last_output_at is None
            or now - self._last_output_at >= self.heartbeat_seconds
        )
        if not (self.verbose or state_changed or event_happened or heartbeat_due):
            self._last_state = state
            return

        line = (
            f"状态：{state_label(state)}；相对基准变化：{format_ratio(novelty_ratio)}；"
            f"帧间变化：{format_ratio(frame_ratio)}；generation={generation}"
        )
        if event is not None:
            line += f"；事件：{event_label(event)}"
        if self.verbose:
            line += (
                f"；timing capture={timings_ms['capture']:.2f}ms"
                f" preprocess={timings_ms['preprocess']:.2f}ms"
                f" compare={timings_ms['compare']:.2f}ms"
                f" total={timings_ms['total']:.2f}ms"
            )
        self._write(line)
        self._last_state = state
        self._last_output_at = now

    def _write(self, message: str) -> None:
        self._output(message)

    def command_result(self, command: str, event=None) -> None:
        if event is None:
            self._write(f"命令 {command}：no-op（当前无可用采样或状态不允许）。")
        else:
            self._write(f"命令 {command}：{event_label(event.kind)}；generation={event.generation}")


def start_watch(timer, coordinator, debug_overlay=None) -> None:
    """Start the pure state machine before starting periodic sampling."""

    coordinator.start()
    if debug_overlay is not None:
        debug_overlay.set_status(coordinator.state, generation=coordinator.generation)
    timer.start()


def stop_watch(timer, coordinator, app=None, debug_overlay=None) -> None:
    if timer is not None:
        timer.stop()
    coordinator.stop()
    safe_close(debug_overlay)
    if app is not None:
        app.quit()


def make_interrupt_handler(
    selection_loop,
    app,
    overlay,
    coordinator,
    timer_ref,
    interrupted,
    debug_overlay_ref=None,
):
    """Build a main-thread SIGINT handler safe to use during either Qt loop."""

    def handle(_signum, _frame) -> None:
        interrupted.append(True)
        timer = timer_ref[0]
        if timer is not None:
            timer.stop()
        coordinator.stop()
        safe_close(overlay)
        if debug_overlay_ref is not None:
            safe_close(debug_overlay_ref[0])
        selection_loop.quit()
        app.quit()

    return handle


def main(
    app_factory: Callable[[list[str]], QApplication] = QApplication,
    overlay_factory: Callable[[], CaptureOverlay] = CaptureOverlay,
    debug_overlay_factory: Callable[[object, object], DebugOverlay] = DebugOverlay,
    argv: list[str] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    # Keep demo-only argparse flags away from Qt's argument parser.
    app = app_factory([sys.argv[0]])
    overlay = overlay_factory()
    settings = AutoWatchSettings(poll_interval_ms=args.poll_interval_ms,
                                 stable_samples_required=args.stable_samples)
    collector = FakeAnalysisCollector(output)
    coordinator = AutoWatchCoordinator(settings=settings, analysis_callback=collector)
    selected = []
    cancelled = []
    interrupted = []
    selection_loop = QEventLoop()
    timer_ref = [None]
    debug_overlay_ref = [None]
    reporter = WatchReporter(verbose=args.verbose, output=output)
    old_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(
        signal.SIGINT,
        make_interrupt_handler(
            selection_loop,
            app,
            overlay,
            coordinator,
            timer_ref,
            interrupted,
            debug_overlay_ref,
        ),
    )

    def on_captured(_image) -> None:
        selected.append(overlay.selection_metadata)
        selection_loop.quit()

    def on_cancelled() -> None:
        cancelled.append(True)
        selection_loop.quit()

    overlay.captured.connect(on_captured)
    overlay.cancelled.connect(on_cancelled)
    reporter.selection_prompt()
    try:
        overlay.begin()
        selection_loop.exec()
        if interrupted or cancelled or not selected:
            if cancelled:
                reporter.cancelled()
            return 0

        screen, roi = selected[0]
        reporter.selected(roi)
        sampler = ScreenSampler(screen, roi, settings=settings)
        config = settings.detector_config
        debug_overlay = debug_overlay_factory(screen, roi)
        debug_overlay_ref[0] = debug_overlay
        timer = sampler.create_timer(
            lambda: tick(sampler, coordinator, config, debug_overlay, reporter),
            config.poll_interval_ms,
        )
        timer_ref[0] = timer
        start_watch(timer, coordinator, debug_overlay)
        debug_overlay.begin()
        reporter.started(coordinator.state)
        command_reader = CommandReader()
        command_timer = __import__("PySide6.QtCore", fromlist=["QTimer"]).QTimer()
        stopped_by_command = [False]

        def handle_commands() -> None:
            for command in command_reader.drain():
                if command in {"pause", "p"}:
                    coordinator.pause()
                    timer.stop()
                elif command in {"resume", "r"}:
                    coordinator.resume()
                    if coordinator.state is MonitorState.ARMING:
                        timer.start()
                elif command in {"analyze now", "analyze", "a"}:
                    event = coordinator.analyze_now()
                    reporter.command_result(command, event)
                elif command in {"stop", "s", "quit", "exit", "q"}:
                    stopped_by_command[0] = True
                    command_timer.stop()
                    stop_watch(timer, coordinator, debug_overlay=debug_overlay)
                    app.quit()
                if not stopped_by_command[0]:
                    debug_overlay.set_status(coordinator.state, generation=coordinator.generation)

        command_timer.timeout.connect(handle_commands)
        command_timer.start(100)
        return app.exec()
    except KeyboardInterrupt:
        return 0
    finally:
        if 'command_timer' in locals():
            command_timer.stop()
        stop_watch(timer_ref[0], coordinator, app, debug_overlay_ref[0])
        safe_close(overlay)
        signal.signal(signal.SIGINT, old_sigint)


def tick(sampler, coordinator, config, debug_overlay=None, reporter=None):
    started = time.perf_counter()
    image = sampler.sample()
    capture_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    frame = preprocess_qimage(image, config.max_side)
    preprocess_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    baseline = coordinator.baseline
    previous = coordinator.previous
    event = coordinator.tick(frame)
    compare_ms = (time.perf_counter() - started) * 1000
    tick_ms = capture_ms + preprocess_ms + compare_ms
    novelty_metrics = (
        compare_frames(frame, baseline, config.pixel_delta_threshold)
        if baseline is not None
        else None
    )
    stability_metrics = (
        compare_frames(frame, previous, config.pixel_delta_threshold)
        if previous is not None
        else None
    )
    if debug_overlay is not None:
        debug_overlay.set_status(coordinator.state, event.kind if event is not None else None, coordinator.generation)
    if reporter is not None:
        reporter.tick(
            state=coordinator.state,
            generation=coordinator.generation,
            event=event.kind if event is not None else None,
            novelty_ratio=novelty_metrics.change_ratio if novelty_metrics else None,
            frame_ratio=stability_metrics.change_ratio if stability_metrics else None,
            timings_ms={
                "capture": capture_ms,
                "preprocess": preprocess_ms,
                "compare": compare_ms,
                "total": tick_ms,
            },
        )
    return event


if __name__ == "__main__":
    raise SystemExit(main())
