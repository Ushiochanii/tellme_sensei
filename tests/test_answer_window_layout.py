from __future__ import annotations

from app.analysis import AnalysisMode
from app.ui.answer_window import AnswerWindow


def test_context_question_layout_prioritizes_rendered_answer_space(qt_app) -> None:
    window = AnswerWindow()
    window.begin_auto_watch(
        AnalysisMode.TEXT,
        generation=1,
        region_mode="context_question",
    )

    for height in (640, 800):
        window.resize(560, height)
        qt_app.processEvents()

        answer_height = window.answer_card.height()
        context_height = window.context_ocr_card.height()
        question_height = window.question_ocr_card.height()
        visible_pair_height = answer_height + context_height + question_height

        assert answer_height > context_height > question_height
        assert answer_height / visible_pair_height >= 0.45
        assert context_height / visible_pair_height >= 0.27
        assert question_height / visible_pair_height <= 0.24

    # The single-region OCR view remains intentionally compact.
    assert window.ocr_edit.maximumHeight() == 145

    window.deleteLater()
    qt_app.processEvents()
