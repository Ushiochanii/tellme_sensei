from PySide6.QtCore import QRect

from app.analysis import AnalysisMode
from app.pipeline import ContextQuestionPipelineResult
from app.ocr.types import OCRLine, OCRResult
from app.ui.answer_window import AnswerWindow
from app.ui.answer_window_placement import place_answer_window_avoiding


def test_pair_placement_avoids_each_actual_roi_and_can_use_the_gap() -> None:
    context = QRect(0, 0, 80, 80)
    question = QRect(300, 0, 80, 80)
    placed = place_answer_window_avoiding(
        QRect(0, 0, 100, 80),
        (context, question),
        QRect(0, 0, 400, 200),
        12,
    )

    assert QRect(0, 0, 400, 200).contains(placed)
    assert not placed.intersects(context)
    assert not placed.intersects(question)
    assert placed.left() < question.left()


def test_answer_window_renders_structured_pair_ocr_and_tracks_two_rois(qt_app) -> None:
    window = AnswerWindow()
    context = QRect(20, 20, 80, 60)
    question = QRect(300, 100, 80, 60)
    window.begin_auto_watch(
        AnalysisMode.TEXT,
        1,
        screen=qt_app.primaryScreen(),
        avoid_rois=(context, question),
        region_mode="Context + Question",
    )
    context_ocr = OCRResult("common passage", (OCRLine("common passage"),))
    question_ocr = OCRResult("current question", (OCRLine("current question"),))
    window.show_auto_watch_result(
        1,
        ContextQuestionPipelineResult(
            context_ocr=context_ocr,
            question_ocr=question_ocr,
            answer="pair answer",
            context_revision=1,
            question_revision=1,
        ),
    )

    assert window._auto_watch_rois == (context, question)
    assert "[Context]\ncommon passage" in window.ocr_edit.toPlainText()
    assert "[Question]\ncurrent question" in window.ocr_edit.toPlainText()
    assert window.answer_edit.toPlainText() == "pair answer"
    window.end_auto_watch()
    window.close()
    qt_app.processEvents()


def test_pair_answer_window_publishes_ocr_sections_before_answer_and_restores_single_ui(qt_app) -> None:
    window = AnswerWindow()
    context = QRect(20, 20, 80, 60)
    question = QRect(300, 100, 80, 60)
    window.begin_auto_watch(
        AnalysisMode.TEXT,
        3,
        screen=qt_app.primaryScreen(),
        avoid_rois=(context, question),
        region_mode="Context + Question",
    )

    assert window.context_ocr_card.isVisible()
    assert window.question_ocr_card.isVisible()
    assert window.answer_card.isVisible()
    assert not window.ocr_card.isVisible()

    window.show_auto_watch_ocr(3, "context", "shared passage")
    assert window.context_ocr_edit.toPlainText() == "shared passage"
    assert window.question_ocr_edit.toPlainText() == ""
    assert window.answer_edit.toPlainText() == ""

    window.show_auto_watch_ocr(3, "question", "current question")
    assert window.question_ocr_edit.toPlainText() == "current question"
    assert window.answer_edit.toPlainText() == ""

    window.show_auto_watch_result(
        3,
        ContextQuestionPipelineResult(
            context_ocr=OCRResult("shared passage", (OCRLine("shared passage"),)),
            question_ocr=OCRResult("current question", (OCRLine("current question"),)),
            answer="final answer",
            context_revision=1,
            question_revision=1,
        ),
    )
    assert window.answer_edit.toPlainText() == "final answer"

    window.end_auto_watch()
    assert window.ocr_card.isVisible()
    assert not window.context_ocr_card.isVisible()
    assert not window.question_ocr_card.isVisible()
    window.close()
    qt_app.processEvents()


def test_pair_vision_keeps_all_ocr_sections_hidden(qt_app) -> None:
    window = AnswerWindow()
    window.begin_auto_watch(
        AnalysisMode.VISION,
        1,
        screen=qt_app.primaryScreen(),
        avoid_rois=(QRect(20, 20, 80, 60), QRect(300, 100, 80, 60)),
        region_mode="Context + Question",
    )

    assert not window.ocr_card.isVisible()
    assert not window.context_ocr_card.isVisible()
    assert not window.question_ocr_card.isVisible()
    window.close()
    qt_app.processEvents()
