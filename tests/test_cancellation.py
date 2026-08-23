from __future__ import annotations

from dataclasses import dataclass
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QEventLoop, QObject, QTimer, Signal, Qt
from PySide6.QtGui import QKeyEvent, QImage

from app.config import AppConfig
from app.pipeline import PipelineResult
from app.services.deepseek_service import DeepSeekCancelled, DeepSeekService
from app.services.ocr_service import OCRLine, OCRResult
from app.state import AppState
from app.ui import main_window as main_window_module
from app.ui.answer_window import AnswerWindow
from app.ui.main_window import MainWindow
from app.workers.processing_worker import ProcessingWorker


def _chunk(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
    )


class FakeStream:
    def __init__(self, chunks) -> None:
        self.chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.chunks)

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.stream


def test_deepseek_stream_assembles_complete_answer_and_closes_stream() -> None:
    stream = FakeStream([_chunk("第一段"), _chunk("第二段")])
    client = FakeClient(stream)
    service = DeepSeekService(AppConfig(api_key="test"), client=client)

    answer = service.analyze("题目")

    assert answer == "第一段第二段"
    assert client.kwargs["stream"] is True
    assert client.kwargs["timeout"] == 60.0
    assert stream.closed is True


def test_deepseek_stream_cancellation_closes_response() -> None:
    cancel_event = threading.Event()

    class CancellingStream(FakeStream):
        def __next__(self):
            chunk = super().__next__()
            cancel_event.set()
            return chunk

    stream = CancellingStream([_chunk("部分答案"), _chunk("不应消费")])
    service = DeepSeekService(AppConfig(api_key="test"), client=FakeClient(stream))

    with pytest.raises(DeepSeekCancelled):
        service.analyze("题目", cancel_event=cancel_event)
    assert stream.closed is True


def test_cancel_during_ocr_never_calls_ai(qt_app) -> None:
    cancel_event = threading.Event()
    ai_called: list[bool] = []

    @dataclass
    class FakeOCR:
        def recognize(self, _image) -> OCRResult:
            cancel_event.set()
            return OCRResult("OCR 文本", (OCRLine("OCR 文本"),))

    @dataclass
    class FakeAI:
        def analyze(self, _text: str, cancel_event=None) -> str:
            ai_called.append(True)
            return "不应调用"

    worker = ProcessingWorker(
        object(), FakeOCR(), FakeAI(), job_id="ocr-cancel", cancel_event=cancel_event
    )
    cancelled: list[str] = []
    errors: list[str] = []
    worker.cancelled.connect(cancelled.append)
    worker.error_occurred.connect(errors.append)
    worker.run()

    assert ai_called == []
    assert cancelled == ["ocr-cancel"]
    assert errors == []


def test_cancel_during_ai_emits_cancelled_not_error(qt_app) -> None:
    cancel_event = threading.Event()
    ai_called: list[str] = []

    @dataclass
    class FakeOCR:
        def recognize(self, _image) -> OCRResult:
            return OCRResult("OCR 文本", (OCRLine("OCR 文本"),))

    @dataclass
    class FakeAI:
        def analyze(self, text: str, cancel_event=None) -> str:
            ai_called.append(text)
            cancel_event.set()
            return "晚到的答案"

    worker = ProcessingWorker(
        object(), FakeOCR(), FakeAI(), job_id="ai-cancel", cancel_event=cancel_event
    )
    cancelled: list[str] = []
    errors: list[str] = []
    results: list[object] = []
    worker.cancelled.connect(cancelled.append)
    worker.error_occurred.connect(errors.append)
    worker.job_result_ready.connect(lambda _job_id, result: results.append(result))
    worker.run()

    assert ai_called == ["OCR 文本"]
    assert cancelled == ["ai-cancel"]
    assert errors == []
    assert results == []


def test_real_qthread_cancel_during_ai_restores_idle(qt_app, monkeypatch) -> None:
    @dataclass
    class FakeOCR:
        def __init__(self, language: str) -> None:
            self.language = language

        def recognize(self, _image) -> OCRResult:
            return OCRResult("QThread OCR", (OCRLine("QThread OCR"),))

    @dataclass
    class BlockingAI:
        def __init__(self, config) -> None:
            self.config = config

        def analyze(self, _text: str, cancel_event=None) -> str:
            while not cancel_event.wait(0.01):
                pass
            raise DeepSeekCancelled("cancelled by test")

    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "load",
        lambda _self, require_api_key=True: AppConfig(api_key="test"),
    )
    monkeypatch.setattr(
        main_window_module,
        "create_ocr_provider",
        lambda config: FakeOCR(config.ocr_language),
    )
    monkeypatch.setattr(main_window_module, "DeepSeekService", BlockingAI)

    window = MainWindow(tray_mode=True)
    window._show_or_create_answer()
    window._busy = True
    window.state = AppState.OCR_PROCESSING
    loop = QEventLoop()
    window.processing_finished.connect(loop.quit)
    window._launch_worker(QImage(32, 24, QImage.Format.Format_RGBA8888), None)
    QTimer.singleShot(100, window.cancel_processing)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    qt_app.processEvents()

    assert window.state is AppState.IDLE
    assert window._busy is False
    assert window._answer_window.status_label.text() == "状态：已取消"
    window.shutdown()


def test_repeated_worker_cancel_is_safe(qt_app) -> None:
    worker = ProcessingWorker(
        object(), object(), object(), job_id="repeat-cancel"
    )
    cancelled: list[str] = []
    worker.cancelled.connect(cancelled.append)
    worker.request_cancel()
    worker.request_cancel()
    worker.run()
    assert cancelled == ["repeat-cancel"]


def test_cancelled_job_restores_idle_and_preserves_ocr(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window._show_or_create_answer()
    window._active_job_id = "cancelled-job"
    window._busy = True
    window.state = AppState.CANCELLING
    window._last_ocr_text = "已识别题目"
    window._on_ocr_finished("cancelled-job", "已识别题目")
    window._on_cancelled("cancelled-job")
    window._on_thread_finished("cancelled-job")

    assert window.state is AppState.IDLE
    assert window._busy is False
    assert window._answer_window.ocr_edit.toPlainText() == "已识别题目"
    assert window._answer_window.status_label.text() == "状态：已取消"
    assert window._answer_window.retry_button.isEnabled()
    window.shutdown()


def test_stale_result_from_cancelled_job_is_ignored(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window._show_or_create_answer()
    window._active_job_id = "new-job"
    stale = PipelineResult(
        ocr=OCRResult("旧 OCR", (OCRLine("旧 OCR"),)),
        answer="旧答案",
    )

    window._on_result("old-job", stale)

    assert window._answer_window.answer_edit.toPlainText() == ""
    assert window._last_ocr_text == ""
    window.shutdown()


def test_new_capture_works_after_cancellation(qt_app, monkeypatch) -> None:
    class FakeOverlay(QObject):
        captured = Signal(QImage)
        cancelled = Signal()

        def __init__(self, debug_path=None) -> None:
            super().__init__()
            self.started = False

        def begin(self) -> None:
            self.started = True

        def close(self) -> None:
            pass

    monkeypatch.setattr(main_window_module, "CaptureOverlay", FakeOverlay)
    window = MainWindow(tray_mode=True)
    window._active_job_id = "old-job"
    window._busy = True
    window.state = AppState.CANCELLING
    window._on_cancelled("old-job")
    window._on_thread_finished("old-job")

    window._recapture_requested()

    assert window.state is AppState.CAPTURING
    assert window._overlay is not None
    assert window._overlay.started is True
    window._on_capture_cancelled()
    window.shutdown()


def test_answer_window_escape_requests_cancel_while_busy(qt_app) -> None:
    answer = AnswerWindow()
    answer.show()
    answer.show_processing()
    requests: list[bool] = []
    answer.stop_requested.connect(lambda: requests.append(True))

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    answer.keyPressEvent(event)

    assert requests == [True]
    answer.set_cancelling()
    assert answer.stop_button.isEnabled() is False
    answer.show_cancelled()
    assert answer.recapture_button.isVisible()
    answer.close()
    qt_app.processEvents()
