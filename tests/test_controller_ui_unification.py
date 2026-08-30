from __future__ import annotations

from PySide6.QtWidgets import QSizePolicy, QPushButton

from app.ui.main_window import AutoWatchSelectionPhase, MainWindow


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
    assert [card.text().splitlines()[1] for card in cards] == [
        "Text extraction",
        "Visual analysis",
        "Single region",
        "Context + question",
    ]
    assert [card.accessibleDescription() for card in cards] == [
        "Text / OCR: Text extraction",
        "Vision: Visual analysis",
        "Watch: Single region",
        "Context Watch: Context + question",
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


def test_watch_cards_route_directly_to_the_canonical_entry_methods(qt_app, monkeypatch) -> None:
    window = MainWindow(tray_mode=True)
    calls: list[str] = []

    def record_watch(_checked: bool = False) -> bool:
        calls.append("watch")
        return True

    def record_context(_checked: bool = False) -> bool:
        calls.append("context")
        return True

    monkeypatch.setattr(MainWindow, "start_watch", record_watch)
    monkeypatch.setattr(MainWindow, "start_context_watch", record_context)
    # The card signal connections are made during construction, so use a fresh
    # window after replacing the public canonical entry methods.
    window.close()
    window = MainWindow(tray_mode=True)
    window.watch_mode_button.click()
    window.context_watch_mode_button.click()

    assert calls == ["watch", "context"]
    window.close()
    qt_app.processEvents()


def test_watch_hotkeys_use_the_same_selection_entry_methods(qt_app, monkeypatch) -> None:
    window = MainWindow(tray_mode=True)
    phases: list[AutoWatchSelectionPhase] = []

    def record(phase: AutoWatchSelectionPhase) -> bool:
        phases.append(phase)
        return True

    monkeypatch.setattr(window, "_begin_auto_watch_workflow", record)

    assert window.start_watch() is True
    assert window.start_context_watch() is True
    assert phases == [
        AutoWatchSelectionPhase.SELECTING_SINGLE,
        AutoWatchSelectionPhase.SELECTING_CONTEXT,
    ]

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
