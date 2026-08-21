from __future__ import annotations

from dataclasses import dataclass
import threading
import time

import pytest
from PySide6.QtCore import QEventLoop, QPoint, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.capture.overlay import CaptureOverlay
from app.config import AppConfig
from app.state import AppState
from app.services.deepseek_service import DeepSeekError, DeepSeekService
from app.services.ocr_service import OCRLine, OCRResult, OCRService
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.ui.answer_window import AnswerWindow
from app.workers.processing_worker import ProcessingWorker


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    return app


def test_qimage_is_supported_by_ocr_service(qt_app) -> None:
    image = QImage(32, 24, QImage.Format.Format_RGBA8888)
    image.fill(0xFFFFFFFF)
    array = OCRService._prepare_image(image)
    assert array.shape == (24, 32, 3)


def test_processing_worker_emits_result_without_touching_widgets(qt_app) -> None:
    @dataclass
    class FakeOCR:
        def recognize(self, _image) -> OCRResult:
            return OCRResult("题目文本", (OCRLine("题目文本"),))

    @dataclass
    class FakeAI:
        received: str = ""

        def analyze(self, text: str) -> str:
            self.received = text
            return "【答案】测试答案"

    ai = FakeAI()
    worker = ProcessingWorker(object(), FakeOCR(), ai)
    events: list[str] = []
    results: list[object] = []
    worker.ocr_started.connect(lambda: events.append("ocr_started"))
    worker.ocr_finished.connect(lambda text: events.append(f"ocr_finished:{text}"))
    worker.ai_started.connect(lambda: events.append("ai_started"))
    worker.result_ready.connect(results.append)
    worker.finished.connect(lambda: events.append("finished"))
    worker.run()

    assert ai.received == "题目文本"
    assert results[0].answer == "【答案】测试答案"
    assert events == ["ocr_started", "ocr_finished:题目文本", "ai_started", "finished"]


def test_answer_window_copy_and_retry(qt_app) -> None:
    window = AnswerWindow()
    window.set_ocr_text("题目")
    window.set_result("【答案】复制测试")
    window.copy_button.click()
    assert QApplication.clipboard().text() == "【答案】复制测试"
    assert window.retry_button.isEnabled()
    window.close()
    qt_app.processEvents()


def test_answer_window_error_replaces_processing_placeholder(qt_app) -> None:
    window = AnswerWindow()
    window.set_ocr_text("题目")
    window.set_result("旧答案")
    window.show_error("DeepSeek API Key 无效（401）")

    answer_text = window.answer_edit.toPlainText()
    assert "AI 解析失败" in answer_text
    assert "401" in answer_text
    assert "旧答案" not in answer_text
    assert window.copy_button.isEnabled() is False
    assert window.retry_button.isEnabled() is True
    window.close()
    qt_app.processEvents()


def test_answer_window_cancelled_replaces_processing_placeholder(qt_app) -> None:
    window = AnswerWindow()
    window.set_result("旧答案")
    window.show_cancelled()

    assert "已取消" in window.answer_edit.toPlainText()
    assert "旧答案" not in window.answer_edit.toPlainText()
    assert window.copy_button.isEnabled() is False
    assert window.stop_button.isVisible() is False
    window.close()
    qt_app.processEvents()


def test_answer_window_ai_processing_clears_previous_answer(qt_app) -> None:
    window = AnswerWindow()
    window.set_result("旧答案")
    window.set_ai_processing()

    assert window.answer_edit.toPlainText() == ""
    assert window._answer_text == ""
    assert window.copy_button.isEnabled() is False
    window.close()
    qt_app.processEvents()


def test_capture_overlay_rejects_small_selection(qt_app) -> None:
    overlay = CaptureOverlay()
    overlay._selection.setWidth(19)
    overlay._selection.setHeight(20)
    assert overlay._selection.width() < 20
    overlay.close()
    qt_app.processEvents()


def test_capture_overlay_emits_selected_image(qt_app) -> None:
    overlay = CaptureOverlay()
    captured: list[QImage] = []

    def on_captured(image: QImage) -> None:
        assert overlay.isVisible() is False
        captured.append(image)

    overlay.captured.connect(on_captured)
    overlay.show()
    qt_app.processEvents()
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(overlay, QPoint(90, 70), delay=10)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(90, 70))
    qt_app.processEvents()
    assert len(captured) == 1
    assert not captured[0].isNull()


def test_retry_worker_skips_ocr(qt_app) -> None:
    @dataclass
    class OCRMustNotRun:
        def recognize(self, _image):
            raise AssertionError("retry must not call OCR")

    @dataclass
    class FakeAI:
        def analyze(self, text: str) -> str:
            return f"重试：{text}"

    worker = ProcessingWorker(None, OCRMustNotRun(), FakeAI(), ocr_text="已有 OCR")
    results: list[object] = []
    worker.result_ready.connect(results.append)
    worker.run()
    assert results[0].answer == "重试：已有 OCR"


def test_worker_keeps_ocr_text_when_ai_key_is_missing(qt_app) -> None:
    @dataclass
    class FakeOCR:
        def recognize(self, _image) -> OCRResult:
            return OCRResult("保留的 OCR", (OCRLine("保留的 OCR"),))

    worker = ProcessingWorker(
        object(), FakeOCR(), DeepSeekService(AppConfig(api_key=""))
    )
    ocr_texts: list[str] = []
    errors: list[str] = []
    worker.ocr_finished.connect(ocr_texts.append)
    worker.error_occurred.connect(errors.append)
    worker.run()
    assert ocr_texts == ["保留的 OCR"]
    assert errors and "API Key" in errors[0]


def test_main_window_runs_worker_through_real_qthread(qt_app, monkeypatch) -> None:
    main_thread_id = threading.get_ident()
    called_thread_ids: list[int] = []

    class FakeOCR:
        def __init__(self, language: str) -> None:
            self.language = language

        def recognize(self, _image) -> OCRResult:
            called_thread_ids.append(threading.get_ident())
            time.sleep(0.03)
            return OCRResult("真实 QThread OCR", (OCRLine("真实 QThread OCR"),))

    class FakeAI:
        def __init__(self, config) -> None:
            self.config = config

        def analyze(self, text: str) -> str:
            time.sleep(0.03)
            return f"【答案】{text}"

    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "load",
        lambda _self, require_api_key=True: AppConfig(api_key="test"),
    )
    monkeypatch.setattr(main_window_module, "OCRService", FakeOCR)
    monkeypatch.setattr(main_window_module, "DeepSeekService", FakeAI)

    window = MainWindow()
    window._show_or_create_answer()
    thread_finished: list[bool] = []
    loop = QEventLoop()
    window.processing_finished.connect(lambda: thread_finished.append(True))
    window.processing_finished.connect(loop.quit)
    window._launch_worker(QImage(32, 24, QImage.Format.Format_RGBA8888), None)
    assert window.processing_thread is not None
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    qt_app.processEvents()

    assert thread_finished == [True]
    assert called_thread_ids and called_thread_ids[0] != main_thread_id
    assert window._last_ocr_text == "真实 QThread OCR"
    assert window._answer_window is not None
    assert "真实 QThread OCR" in window._answer_window.answer_edit.toPlainText()
    assert window.state is AppState.IDLE
    assert window._busy is False
    window._answer_window.close()
    window.close()
    qt_app.processEvents()


def test_main_window_ai_error_renders_terminal_answer_state(qt_app, monkeypatch) -> None:
    class FakeOCR:
        def __init__(self, language: str) -> None:
            self.language = language

        def recognize(self, _image) -> OCRResult:
            return OCRResult("OCR 题目", (OCRLine("OCR 题目"),))

    class FakeAI:
        def __init__(self, config) -> None:
            self.config = config

        def analyze(self, text: str) -> str:
            raise DeepSeekError("DeepSeek API Key 无效（401）")

    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "load",
        lambda _self, require_api_key=True: AppConfig(api_key="test"),
    )
    monkeypatch.setattr(main_window_module, "OCRService", FakeOCR)
    monkeypatch.setattr(main_window_module, "DeepSeekService", FakeAI)

    window = MainWindow(tray_mode=True)
    window._show_or_create_answer()
    loop = QEventLoop()
    window.processing_finished.connect(loop.quit)
    window._launch_worker(QImage(32, 24, QImage.Format.Format_RGBA8888), None)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    qt_app.processEvents()

    assert window.state is AppState.IDLE
    assert window._answer_window is not None
    assert "401" in window._answer_window.status_label.text()
    assert "AI 解析失败" in window._answer_window.answer_edit.toPlainText()
    assert window._answer_window.copy_button.isEnabled() is False
    window._answer_window.close()
    window.close()
    qt_app.processEvents()
