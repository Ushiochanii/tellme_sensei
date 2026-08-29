from PySide6.QtCore import QRect, Qt

from app.auto_watch.models import MonitorState
from app.analysis import AnalysisMode
from app.ui.watch_mini_controller import WatchMiniController
from app.ui.watch_overlay import ContextQuestionWatchOverlay


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
