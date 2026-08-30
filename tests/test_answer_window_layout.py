from __future__ import annotations

from app.ui.answer_window import AnswerWindow


def test_context_question_layout_prioritizes_answer(qt_app) -> None:
    window = AnswerWindow()
    body_layout = window.context_ocr_card.parentWidget().layout()

    assert body_layout.stretch(body_layout.indexOf(window.answer_card)) == 5
    assert body_layout.stretch(body_layout.indexOf(window.context_ocr_card)) == 3
    assert body_layout.stretch(body_layout.indexOf(window.question_ocr_card)) == 2

    # Single-region OCR keeps its compact cap, while the pair sections are free
    # to participate in the 5:3:2 vertical layout as the window is resized.
    assert window.ocr_edit.maximumHeight() == 145
    assert window.context_ocr_edit.maximumHeight() > 145
    assert window.question_ocr_edit.maximumHeight() > 145

    window.deleteLater()
    qt_app.processEvents()
