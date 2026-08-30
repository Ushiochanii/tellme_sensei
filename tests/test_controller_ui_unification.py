from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QSizePolicy, QPushButton

from app.auto_watch.models import WatchRegion
from app.ui.main_window import MainWindow


def test_controller_exposes_four_cards_in_visual_tab_order(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window.show()
    qt_app.processEvents()

    cards = [
        window.text_mode_button,
        window.vision_mode_button,
        window.watch_mode_button,
        window.context_watch_mode_button,
    ]
    assert [card.objectName() for card in cards] == [
        "textModeButton",
        "visionModeButton",
        "watchModeButton",
        "contextWatchModeButton",
    ]
    assert [card.accessibleName() for card in cards] == [
        "Text / OCR",
        "Vision",
        "Watch",
        "Context Watch",
    ]
    assert [card.text().splitlines()[0] for card in cards] == [
        "Text / OCR",
        "Vision",
        "Watch",
        "Context Watch",
    ]
    assert window.findChildren(QPushButton, "autoWatchButton") == []
    assert cards[0].geometry().y() == cards[1].geometry().y()
    assert cards[2].geometry().y() > cards[0].geometry().y()
    assert cards[0].geometry().width() == cards[1].geometry().width()
    assert cards[0].geometry().width() == cards[2].geometry().width()
    assert cards[0].nextInFocusChain() is cards[1]
    assert cards[1].nextInFocusChain() is cards[2]
    assert cards[2].nextInFocusChain() is cards[3]

    window.close()
    qt_app.processEvents()


def test_watch_cards_route_directly_to_the_matching_setup(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    calls: list[str] = []

    def record(region_mode: str = "single") -> bool:
        calls.append(region_mode)
        return True

    window.enter_auto_watch_setup = record
    window.watch_mode_button.click()
    window.context_watch_mode_button.click()

    assert calls == ["single", "context_question"]
    window.close()
    qt_app.processEvents()


def test_watch_setup_hides_region_mode_and_reentry_resets_selection(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window.show()
    qt_app.processEvents()

    window.context_watch_mode_button.click()
    assert window._auto_watch_region_mode == "context_question"
    assert window.auto_watch_setup.isVisible()
    assert window.auto_watch_text_radio.isVisible()
    assert window.auto_watch_vision_radio.isVisible()
    assert not window.auto_watch_single_region_radio.isVisible()
    assert not window.auto_watch_context_question_radio.isVisible()
    assert window.auto_watch_select_button.text() == "Select Context"

    screen = qt_app.primaryScreen()
    context = WatchRegion.create(screen, QRect(10, 10, 80, 60), "ui-session")
    question = WatchRegion.create(screen, QRect(120, 10, 80, 60), "ui-session")
    window._auto_watch_context_region = context
    window._auto_watch_question_region = question

    window.auto_watch_back_button.click()
    window.watch_mode_button.click()

    assert window._auto_watch_region_mode == "single"
    assert window._auto_watch_context_region is None
    assert window._auto_watch_question_region is None
    assert window.auto_watch_select_button.text() == "Select Region"
    assert not window.auto_watch_start_button.isVisible()

    window.close()
    qt_app.processEvents()


def test_controller_status_strip_is_compact_and_non_focusable(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window.show()
    qt_app.processEvents()

    assert window.status_label.property("fluentRole") == "statusBar"
    assert window.status_label.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert 34 <= window.status_label.height() <= 40
    assert window.status_label.maximumHeight() <= 40

    window.close()
    qt_app.processEvents()
