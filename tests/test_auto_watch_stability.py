from app.auto_watch.stability import StabilityTracker


def test_stability_counts_and_resets():
    tracker = StabilityTracker(0.015, 3)
    assert [tracker.update(x) for x in (0.01, 0.0, 0.005)] == [False, False, True]
    assert tracker.stable_count == 3
    assert tracker.update(0.02) is False and tracker.stable_count == 0
    tracker.reset(); assert tracker.stable_count == 0
