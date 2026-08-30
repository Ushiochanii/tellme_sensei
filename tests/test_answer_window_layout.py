from __future__ import annotations

from PySide6.QtCore import QRect

from app.analysis import AnalysisMode
from app.ui.answer_window import AnswerWindow


class _FakeScreen:
    def availableGeometry(self) -> QRect:  # noqa: N802 - Qt API name
        return QRect(0, 0, 1400, 1000)


def _assert_edit_fills_card(card, label, edit) -> None:
    layout = card.layout()
    margins = layout.contentsMargins()

    assert edit.y() <= label.geometry().bottom() + layout.spacing() + 2
    assert edit.geometry().bottom() >= card.height() - margins.bottom() - 2


def test_context_question_layout_prioritizes_usable_text_space(qt_app) -> None:
    window = AnswerWindow()
    window.setGeometry(0, 0, 560, 640)
    window.begin_auto_watch(
        AnalysisMode.TEXT,
        generation=1,
        roi_hint=QRect(700, 100, 200, 150),
        screen=_FakeScreen(),
        region_mode="context_question",
    )
    qt_app.processEvents()

    # Entering Context Watch must preserve the usable window size instead of
    # shrinking to the widgets' content hints.
    assert window.height() == 640

    for height in (640, 800):
        window.resize(560, height)
        qt_app.processEvents()

        assert window.answer_edit.height() > window.context_ocr_edit.height()
        assert window.context_ocr_edit.height() > window.question_ocr_edit.height()
        assert window.question_ocr_edit.height() >= 52
        assert window.question_ocr_section_label.isVisible()

        # Answer keeps its stronger color, but all three section titles use
        # the same typography contract.
        assert window.answer_section_label.font().pointSizeF() == window.context_ocr_section_label.font().pointSizeF()
        assert window.answer_section_label.font().weight() == window.context_ocr_section_label.font().weight()
        assert window.question_ocr_section_label.font().pointSizeF() == window.context_ocr_section_label.font().pointSizeF()
        assert window.question_ocr_section_label.font().weight() == window.context_ocr_section_label.font().weight()

        _assert_edit_fills_card(
            window.context_ocr_card,
            window.context_ocr_section_label,
            window.context_ocr_edit,
        )
        _assert_edit_fills_card(
            window.question_ocr_card,
            window.question_ocr_section_label,
            window.question_ocr_edit,
        )
        _assert_edit_fills_card(
            window.answer_card,
            window.answer_section_label,
            window.answer_edit,
        )

    # Single-region OCR remains intentionally compact.
    assert window.ocr_edit.maximumHeight() == 145

    window.deleteLater()
    qt_app.processEvents()
