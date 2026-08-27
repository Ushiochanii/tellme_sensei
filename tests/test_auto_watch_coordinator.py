import numpy as np
from app.auto_watch.coordinator import AutoWatchCoordinator
import pytest
from app.auto_watch.models import AutoWatchSettings, DetectorConfig, DetectorFrame, MonitorState, WatchEvent


def frames(value): return np.full((10, 10), value, dtype=np.uint8)


def test_dual_reference_and_pause_resume():
    c = AutoWatchCoordinator(DetectorConfig(stable_samples_required=2, novelty_ratio=.2))
    c.start(); assert c.state is MonitorState.ARMING
    assert c.tick(frames(10)) is None
    assert c.tick(frames(10)) is None
    event = c.tick(frames(10)); assert event.kind is WatchEvent.INITIAL_STABLE_FRAME
    assert c.tick(frames(10)) is None
    c.tick(frames(200)); assert c.state is MonitorState.CHANGING
    c.pause(); assert c.tick(frames(30)) is None
    c.resume(); assert c.state is MonitorState.ARMING
    c.stop(); assert c.baseline is None and c.previous is None and c.generation == 0


def test_new_frame_only_after_stability():
    c = AutoWatchCoordinator(DetectorConfig(stable_samples_required=2, novelty_ratio=.2))
    c.start(); [c.tick(frames(10)) for _ in range(4)]
    c.tick(frames(200)); assert c.tick(frames(100)) is None
    assert c.tick(frames(200)) is None
    assert c.tick(frames(200)) is None
    assert c.tick(frames(200)).kind is WatchEvent.NEW_STABLE_FRAME
    assert c.tick(frames(200)) is None


def test_partial_loading_and_final_q2_only_accept_final_stable_frame():
    c = AutoWatchCoordinator(DetectorConfig(stable_samples_required=2, novelty_ratio=.2))
    c.start(); [c.tick(frames(10)) for _ in range(2)]
    assert c.tick(frames(10)).kind is WatchEvent.INITIAL_STABLE_FRAME
    # A changing loading/reflow sequence never reaches the stable counter.
    for value in (80, 120, 160, 200):
        assert c.tick(frames(value)) is None
        assert c.state is MonitorState.CHANGING
    assert c.tick(frames(200)) is None
    assert c.tick(frames(200)).kind is WatchEvent.NEW_STABLE_FRAME


def test_continuous_scrolling_does_not_accept():
    c = AutoWatchCoordinator(DetectorConfig(stable_samples_required=3, novelty_ratio=.2))
    c.start(); [c.tick(frames(10)) for _ in range(4)]
    for value in range(40, 240, 20):
        assert c.tick(frames(value)) is None
    assert c.state is MonitorState.CHANGING


def test_temporary_popup_returning_to_baseline_is_ignored():
    c = AutoWatchCoordinator(DetectorConfig(stable_samples_required=2, novelty_ratio=.2))
    c.start(); [c.tick(frames(10)) for _ in range(2)]
    assert c.tick(frames(10)).kind is WatchEvent.INITIAL_STABLE_FRAME
    c.tick(frames(220)); assert c.state is MonitorState.CHANGING
    assert c.tick(frames(10)) is None
    assert c.tick(frames(10)) is None
    assert c.tick(frames(10)) is None
    assert c.state is MonitorState.WATCHING


def test_resume_same_baseline_does_not_emit_duplicate_initial_event():
    c = AutoWatchCoordinator(DetectorConfig(stable_samples_required=2))
    c.start(); [c.tick(frames(10)) for _ in range(2)]
    assert c.tick(frames(10)).kind is WatchEvent.INITIAL_STABLE_FRAME
    c.pause(); c.resume()
    assert [c.tick(frames(10)) for _ in range(3)] == [None, None, None]
    assert c.state is MonitorState.WATCHING


def test_resume_changed_baseline_emits_new_after_final_stability():
    c = AutoWatchCoordinator(DetectorConfig(stable_samples_required=2, novelty_ratio=.2))
    c.start(); [c.tick(frames(10)) for _ in range(2)]
    assert c.tick(frames(10)).kind is WatchEvent.INITIAL_STABLE_FRAME
    c.pause(); c.resume()
    assert c.tick(frames(200)) is None  # initializes previous after resume
    assert c.tick(frames(200)) is None
    event = c.tick(frames(200))
    assert event is not None and event.kind is WatchEvent.NEW_STABLE_FRAME


def test_lifecycle_calls_are_idempotent_and_stop_clears_everything():
    c = AutoWatchCoordinator(); c.start(); c.start()
    assert c.state is MonitorState.ARMING
    c.pause(); c.pause(); assert c.state is MonitorState.PAUSED
    c.resume(); c.resume(); assert c.state is MonitorState.ARMING
    c.stop(); c.stop()
    assert (c.state, c.baseline, c.previous, c.generation) == (MonitorState.STOPPED, None, None, 0)


def test_analyze_now_boundaries_consistency_and_callback_errors():
    seen = []
    def bad(event):
        seen.append(event); raise RuntimeError("demo callback failure")
    c = AutoWatchCoordinator(analysis_callback=bad)
    assert c.analyze_now() is None
    c.start(); frame = np.full((3, 3), 7, dtype=np.uint8); c.tick(frame)
    first = c.analyze_now(); assert first.kind is WatchEvent.INITIAL_STABLE_FRAME
    assert first.generation == 1 and c.baseline is c.previous
    second = c.analyze_now(); assert second.kind is WatchEvent.NEW_STABLE_FRAME
    assert [e.generation for e in seen] == [1, 2] and len(c.callback_errors) == 2
    assert c.tick(frame) is None
    c.pause(); assert c.analyze_now() is None
    c.stop(); assert c.analyze_now() is None


def test_falsey_explicit_callback_is_still_used():
    seen = []
    class FalseyCallback:
        def __bool__(self): return False
        def __call__(self, event): seen.append(event.generation)
    fallback = lambda _event: seen.append("fallback")
    c = AutoWatchCoordinator(analysis_callback=fallback)
    c.start(); c.tick(frames(1))
    c.analyze_now(FalseyCallback())
    assert seen == [1]


def test_settings_defaults_ranges_freezing_and_safe_frame_copy():
    settings = AutoWatchSettings(); assert settings.poll_interval_ms == 250
    assert settings.estimated_stability_ms == 750
    with pytest.raises((ValueError, TypeError)): AutoWatchSettings(poll_interval_ms=True)
    with pytest.raises(ValueError): AutoWatchSettings(analysis_delay_ms=-1)
    with pytest.raises(ValueError): DetectorConfig(max_side=0)
    with pytest.raises(ValueError): DetectorConfig(stable_samples_required=1.5)
    with pytest.raises((AttributeError, TypeError)): settings.poll_interval_ms = 1
    source = np.zeros((2, 2), dtype=np.uint8); frame = DetectorFrame(source); source[0, 0] = 99
    assert frame.pixels[0, 0] == 0 and not frame.pixels.flags.writeable
