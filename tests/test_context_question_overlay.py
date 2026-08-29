from PySide6.QtCore import QRect, Qt

from app.auto_watch.models import MonitorState
from app.analysis import AnalysisMode
from app.ui.watch_mini_controller import WatchMiniController
from app.ui.watch_overlay import ContextQuestionWatchOverlay, _outside_all_rois_segments


def test_pair_overlay_uses_one_input_transparent_window_for_two_rois(qt_app) -> None:
    screen = qt_app.primaryScreen()
    overlay = ContextQuestionWatchOverlay(
        screen,
        QRect(20, 20, 80, 60),
        QRect(300, 120, 90, 70),
    )
    overlay.set_status(MonitorState.WATCHING, generation=4)

    assert overlay.rois == (QRect(20, 20, 80, 60), QRect(300, 120, 90, 70))
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert not hasattr(overlay, "_screen_image")
    overlay.close()
    qt_app.processEvents()


def test_pair_mini_controller_labels_mode_and_pair_generation(qt_app) -> None:
    mini = WatchMiniController()
    mini.set_mode(AnalysisMode.TEXT)
    mini.set_region_mode("Context + Question")
    mini.set_generation(4)

    assert "Context + Question" in mini.mode_label.text()
    assert mini.region_mode == "Context + Question"
    assert mini.generation_label.text() == "Pair 4"
    mini.close_from_session()


def test_adjacent_pair_keeps_safe_fragments_for_both_colored_borders() -> None:
    context = QRect(20, 20, 140, 80)
    question = QRect(20, 100, 140, 80)
    bounds = QRect(0, 0, 240, 240)
    rois = (context, question)

    context_segments = _outside_all_rois_segments(context, rois, bounds, index=0)
    question_segments = _outside_all_rois_segments(question, rois, bounds, index=1)

    assert context_segments and question_segments
    assert all(not segment.intersects(context) and not segment.intersects(question)
               for segment in (*context_segments, *question_segments))
    # The shared boundary is intentionally omitted because it is monitored;
    # each role still retains its own outer safe border fragments.
    assert any(segment.top() < context.top() for segment in context_segments)
    assert any(segment.bottom() > question.bottom() for segment in question_segments)
