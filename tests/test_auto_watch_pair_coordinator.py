import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from app.auto_watch.models import DetectorConfig, MonitorState, PairMonitorState, PairSnapshot
from app.auto_watch.pair_coordinator import ContextQuestionImages, PairCoordinator


CONFIG = DetectorConfig(stable_samples_required=2, novelty_ratio=0.2)


def frame(value):
    return np.full((10, 10), value, dtype=np.uint8)


def pair_tick(coordinator, context_value, question_value):
    return coordinator.tick(frame(context_value), frame(question_value))


def started_coordinator():
    coordinator = PairCoordinator(CONFIG)
    coordinator.start()
    return coordinator


def establish_initial_pair(coordinator, context_value=10, question_value=10):
    assert pair_tick(coordinator, context_value, question_value) is None
    assert pair_tick(coordinator, context_value, question_value) is None
    snapshot = pair_tick(coordinator, context_value, question_value)
    assert snapshot is not None
    assert (snapshot.generation, snapshot.context_revision, snapshot.question_revision) == (1, 1, 1)
    return snapshot


def test_initial_pair_is_emitted_once_and_pair_state_projects_existing_vocabulary():
    coordinator = started_coordinator()
    snapshot = establish_initial_pair(coordinator)

    assert isinstance(snapshot, PairSnapshot)
    assert coordinator.state is PairMonitorState.WATCHING
    assert coordinator.state is MonitorState.WATCHING
    assert coordinator.pair_generation == 1
    assert pair_tick(coordinator, 10, 10) is None
    assert coordinator.pair_generation == 1


def test_question_only_change_reuses_context_revision_and_emits_once():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)

    assert pair_tick(coordinator, 10, 200) is None
    assert pair_tick(coordinator, 10, 200) is None
    snapshot = pair_tick(coordinator, 10, 200)

    assert snapshot is not None
    assert (snapshot.generation, snapshot.context_revision, snapshot.question_revision) == (2, 1, 2)
    assert pair_tick(coordinator, 10, 200) is None
    assert coordinator.pair_generation == 2


def test_context_only_change_reuses_question_revision_and_emits_once():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)

    assert pair_tick(coordinator, 200, 10) is None
    assert pair_tick(coordinator, 200, 10) is None
    snapshot = pair_tick(coordinator, 200, 10)

    assert snapshot is not None
    assert (snapshot.generation, snapshot.context_revision, snapshot.question_revision) == (2, 2, 1)
    assert pair_tick(coordinator, 200, 10) is None


def test_both_change_waits_for_question_stability_after_context_stabilizes():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)

    # The Question moves through a transient frame while Context has already
    # reached C2. The pair must not expose C2 + Q1 or any other mixed state.
    assert pair_tick(coordinator, 200, 200) is None
    assert pair_tick(coordinator, 200, 100) is None
    assert coordinator.state is PairMonitorState.CHANGING
    assert pair_tick(coordinator, 200, 100) is None
    assert coordinator.context_revision == 2
    assert coordinator.question_revision == 1
    assert pair_tick(coordinator, 200, 100) is not None
    assert (coordinator.pair_generation, coordinator.context_revision, coordinator.question_revision) == (2, 2, 2)


@pytest.mark.parametrize("changed_side", ["context", "question"])
def test_temporary_popup_returning_to_baseline_emits_no_pair(changed_side):
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)

    values = [(220, 10)] if changed_side == "context" else [(10, 220)]
    assert pair_tick(coordinator, *values[0]) is None
    for _ in range(3):
        assert pair_tick(coordinator, 10, 10) is None

    assert coordinator.pair_generation == 1
    assert coordinator.context_revision == coordinator.question_revision == 1
    assert coordinator.state is PairMonitorState.WATCHING


def test_continuous_instability_does_not_emit_pair():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)

    for value in range(40, 240, 20):
        assert pair_tick(coordinator, value, 10) is None
    assert coordinator.state is PairMonitorState.CHANGING
    assert coordinator.pair_generation == 1


def test_pause_unchanged_resume_does_not_duplicate_pair():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)
    coordinator.pause()
    assert coordinator.state is PairMonitorState.PAUSED
    assert pair_tick(coordinator, 10, 10) is None
    coordinator.resume()
    assert coordinator.state is PairMonitorState.ARMING

    for _ in range(3):
        assert pair_tick(coordinator, 10, 10) is None
    assert coordinator.state is PairMonitorState.WATCHING
    assert coordinator.pair_generation == 1


def test_pause_question_change_resume_emits_one_pair_after_stability():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)
    coordinator.pause()
    coordinator.resume()

    assert pair_tick(coordinator, 10, 200) is None
    assert pair_tick(coordinator, 10, 200) is None
    snapshot = pair_tick(coordinator, 10, 200)

    assert snapshot is not None
    assert (snapshot.generation, snapshot.context_revision, snapshot.question_revision) == (2, 1, 2)
    assert pair_tick(coordinator, 10, 200) is None


def test_analyze_now_accepts_current_pair_and_same_frames_do_not_auto_duplicate():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)
    assert pair_tick(coordinator, 200, 220) is None
    assert coordinator.state is PairMonitorState.CHANGING

    snapshot = coordinator.analyze_now()

    assert snapshot is not None
    assert (snapshot.generation, snapshot.context_revision, snapshot.question_revision) == (2, 2, 2)
    assert coordinator.state is PairMonitorState.WATCHING
    assert pair_tick(coordinator, 200, 220) is None
    assert coordinator.pair_generation == 2


def test_coordinator_accepts_sampler_images_and_explicit_analyze_now_images():
    coordinator = PairCoordinator(DetectorConfig(stable_samples_required=1))
    coordinator.start()
    context = QImage(20, 10, QImage.Format.Format_RGBA8888)
    question = QImage(30, 12, QImage.Format.Format_RGBA8888)
    context.fill(QColor("red"))
    question.fill(QColor("blue"))
    images = ContextQuestionImages(context, question)

    assert coordinator.tick(images) is None
    snapshot = coordinator.tick(images)
    assert snapshot is not None
    assert (snapshot.context_image.size(), snapshot.question_image.size()) == (context.size(), question.size())

    changed_context = QImage(24, 10, QImage.Format.Format_RGBA8888)
    changed_question = QImage(30, 12, QImage.Format.Format_RGBA8888)
    changed_context.fill(QColor("green"))
    changed_question.fill(QColor("yellow"))
    manual = coordinator.analyze_now(context_image=changed_context, question_image=changed_question)
    assert manual is not None
    assert manual.generation == 2
    assert manual.context_image.size() == changed_context.size()
    assert coordinator.tick(ContextQuestionImages(changed_context, changed_question)) is None


def test_pair_snapshot_and_callback_are_detached_and_callback_errors_do_not_break_watch():
    seen = []

    def callback(snapshot):
        seen.append(snapshot)
        raise RuntimeError("observer failed")

    coordinator = PairCoordinator(CONFIG, analysis_callback=callback)
    coordinator.start()
    snapshot = establish_initial_pair(coordinator)
    assert seen == [snapshot]
    assert len(coordinator.callback_errors) == 1

    # The fallback full-resolution images are owned by the snapshot and are
    # still valid after later detector frames are supplied.
    assert snapshot.context_image.width() == 10
    assert snapshot.question_image.height() == 10
    pair_tick(coordinator, 10, 10)
    assert snapshot.context_image.pixel(0, 0) == 0xFF0A0A0A


def test_pair_lifecycle_is_idempotent_and_stop_clears_revisions_and_generation():
    coordinator = started_coordinator()
    establish_initial_pair(coordinator)
    coordinator.pause()
    coordinator.pause()
    coordinator.resume()
    coordinator.resume()
    coordinator.stop()
    coordinator.stop()

    assert coordinator.state is PairMonitorState.STOPPED
    assert (coordinator.pair_generation, coordinator.context_revision, coordinator.question_revision) == (0, 0, 0)
    assert coordinator.last_snapshot is None
