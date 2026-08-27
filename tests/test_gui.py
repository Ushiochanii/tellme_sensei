from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from pathlib import Path

import pytest
import numpy as np
from PySide6.QtCore import QEventLoop, QPoint, QRect, QTimer, Qt, QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.analysis import AnalysisMode
from app.auto_watch.coordinator import CoordinatorEvent
from app.auto_watch.models import DetectorFrame, MonitorState, WatchEvent
from app.capture.overlay import CaptureOverlay
from app.config import AppConfig
from app.pipeline import PipelineResult
from app.state import AppState
from app.services.deepseek_service import DeepSeekError, DeepSeekService
from app.services.ocr_service import OCRLine, OCRResult
from app.ocr.providers.local_worker import LocalOCRProvider
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow, _AutoWatchFakeHandle
from app.ui.answer_window import AnswerWindow
from app.workers.processing_worker import ProcessingWorker


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    return app


def test_qimage_is_supported_by_local_ocr_provider(qt_app) -> None:
    image = QImage(32, 24, QImage.Format.Format_RGBA8888)
    image.fill(0xFFFFFFFF)

    class FakeSession:
        def recognize(self, input_path: str | Path, cancel_event=None) -> OCRResult:
            path = Path(input_path)
            assert path.suffix == ".png"
            assert QImage(str(path)).isNull() is False
            return OCRResult("题目", (OCRLine("题目"),))

    result = LocalOCRProvider(session=FakeSession()).recognize(image)

    assert result.text == "题目"


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


def test_answer_window_mode_titles_and_ocr_visibility(qt_app) -> None:
    window = AnswerWindow()
    window.show()
    qt_app.processEvents()

    window.set_mode(AnalysisMode.TEXT)
    assert window.title_bar.title_label.text() == "Text / OCR Analysis"
    assert window.ocr_section_label.isVisible()
    assert window.ocr_edit.isVisible()

    window.set_mode(AnalysisMode.VISION)
    assert window.title_bar.title_label.text() == "Vision Analysis"
    assert window.ocr_section_label.isVisible() is False
    assert window.ocr_edit.isVisible() is False
    window.close()
    qt_app.processEvents()


def test_answer_window_processing_and_result_button_hierarchy(qt_app) -> None:
    window = AnswerWindow()
    window.show()
    qt_app.processEvents()
    window.show_processing()
    assert window.stop_button.isVisible()
    assert window.stop_button.isEnabled()
    assert window.retry_button.isEnabled() is False

    window.set_ocr_text("题目")
    window.set_result("答案")
    assert window.stop_button.isVisible() is False
    assert window.copy_button.isEnabled()
    assert window.retry_button.isEnabled()

    window.show_cancelled()
    assert window.recapture_button.isVisible()
    assert window.stop_button.isVisible() is False
    window.close()
    qt_app.processEvents()


def test_answer_window_action_signals_emit_once(qt_app) -> None:
    window = AnswerWindow()
    window.set_ocr_text("题目")
    window.set_result("答案")
    events: list[str] = []
    window.reanalyze_requested.connect(lambda: events.append("retry"))
    window.recapture_requested.connect(lambda: events.append("recapture"))
    window.stop_requested.connect(lambda: events.append("stop"))

    window.retry_button.click()
    window.recapture_button.click()
    window.show_processing()
    window.stop_button.click()
    assert events == ["retry", "recapture", "stop"]
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


def test_answer_window_auto_watch_text_preserves_previous_result_and_restores_controls(qt_app) -> None:
    window = AnswerWindow()
    screen = qt_app.primaryScreen()
    window.begin_auto_watch(AnalysisMode.TEXT, 1, QRect(100, 100, 60, 50), screen)
    assert window.retry_button.isVisible() is False
    assert window.retry_button.isEnabled() is False
    first = PipelineResult(OCRResult("Q1 text", (OCRLine("Q1 text"),)), "Q1 answer")
    window.show_auto_watch_result(1, first)
    assert window.ocr_card.isVisible()
    assert window.ocr_edit.toPlainText() == "Q1 text"
    assert window.answer_edit.toPlainText() == "Q1 answer"
    window.show_auto_watch_analyzing(2)
    assert window.answer_edit.toPlainText() == "Q1 answer"
    window.show_auto_watch_error(2, "temporary error")
    assert window.answer_edit.toPlainText() == "Q1 answer"
    window.show_auto_watch_cancelled(2)
    assert "cancelled" in window.status_label.text().lower()
    window.show_auto_watch_result(1, PipelineResult(OCRResult("stale", ()), "stale"))
    assert window.answer_edit.toPlainText() == "Q1 answer"
    window.end_auto_watch()
    assert not window.stop_button.isVisible()
    assert not window.recapture_button.isVisible()
    assert window.retry_button.isVisible()
    assert window.retry_button.isEnabled()
    window.close(); qt_app.processEvents()


def test_answer_window_auto_watch_vision_hides_ocr_and_does_not_persist_temporary_geometry(qt_app) -> None:
    class Repository:
        def __init__(self): self.updates = 0
        def load(self): return {}
        def update(self, _values): self.updates += 1

    repository = Repository()
    window = AnswerWindow(settings_repository=repository)
    window.begin_auto_watch(AnalysisMode.VISION, 1, QRect(20, 20, 60, 50), qt_app.primaryScreen())
    window.show_auto_watch_result(1, "Vision answer")
    assert not window.ocr_card.isVisible()
    assert window.answer_edit.toPlainText() == "Vision answer"
    window.close(); qt_app.processEvents()
    assert repository.updates == 0


def test_capture_overlay_rejects_small_selection(qt_app) -> None:
    overlay = CaptureOverlay()
    overlay._selection.setWidth(19)
    overlay._selection.setHeight(20)
    assert overlay._selection.width() < 20
    overlay.close()
    qt_app.processEvents()


def test_capture_overlay_emits_selected_image(qt_app) -> None:
    overlay = CaptureOverlay()
    # Keep this unit test independent from Screen Recording/display capture
    # availability on the host running pytest.
    overlay._screen_image = QImage(200, 120, QImage.Format.Format_RGBA8888)
    overlay._screen_image.fill(0xFFFFFFFF)
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


def test_capture_overlay_exposes_read_only_watch_metadata(qt_app) -> None:
    overlay = CaptureOverlay()
    overlay._selection = QRect(1, 1, 30, 30)
    screen, selection = overlay.selection_metadata
    assert screen is overlay.screen
    selection.setX(selection.x() + 10)
    assert selection.x() != overlay.selection.x()


def test_main_window_auto_watch_setup_is_exclusive_and_back_restores(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    assert window.auto_watch_main_view.isVisible() is False
    window.show()
    qt_app.processEvents()
    assert window.auto_watch_main_view.isVisible()
    assert not window.auto_watch_setup.isVisible()
    window.enter_auto_watch_setup()
    assert not window.auto_watch_main_view.isVisible()
    assert window.auto_watch_setup.isVisible()
    assert window.start_text_capture() is False
    window.auto_watch_vision_radio.click()
    assert window.auto_watch_vision_radio.isChecked()
    window.auto_watch_back_button.click()
    assert window.auto_watch_main_view.isVisible()
    assert not window.auto_watch_setup.isVisible()
    window.close()
    qt_app.processEvents()


def test_main_window_auto_watch_selection_cancel_returns_to_setup(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window.show(); window.enter_auto_watch_setup()
    window._on_auto_watch_selection_cancelled()
    assert window._auto_watch_selection_overlay is None
    assert window.auto_watch_setup.isVisible()
    assert not window.auto_watch_main_view.isVisible()
    window.close()
    qt_app.processEvents()


def test_main_window_watch_start_failure_cleans_created_session(qt_app, monkeypatch) -> None:
    class FakeSession(QObject):
        session_stopped = Signal()
        last = None
        def __init__(self, *_args, **_kwargs):
            super().__init__(); self.stop_count = 0; FakeSession.last = self
        def start(self): raise RuntimeError("start failed")
        def stop(self): self.stop_count += 1

    class FakeSelection:
        selection_metadata = (qt_app.primaryScreen(), QRect(2, 3, 40, 30))

    monkeypatch.setattr(main_window_module, "AutoWatchSession", FakeSession)
    window = MainWindow(tray_mode=True)
    window.show(); window.enter_auto_watch_setup()
    window._auto_watch_selection_overlay = FakeSelection()
    assert window._on_auto_watch_capture(QImage()) is False
    assert FakeSession.last.stop_count == 1
    assert window._auto_watch_session is None
    assert window.auto_watch_setup.isVisible()
    assert not window.auto_watch_main_view.isVisible()
    window.close()
    qt_app.processEvents()


def test_main_window_watch_active_disables_manual_capture_and_stop_restores(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window.show(); window.enter_auto_watch_setup()
    window._auto_watch_active = True
    window._set_capture_controls_enabled(False)
    assert not window.text_mode_button.isEnabled()
    assert not window.vision_mode_button.isEnabled()
    assert window.start_text_capture() is False
    window._on_auto_watch_stopped()
    assert window.text_mode_button.isEnabled()
    assert window.vision_mode_button.isEnabled()
    assert window.auto_watch_main_view.isVisible()
    window.close()
    qt_app.processEvents()


def test_late_old_session_stop_cannot_clear_current_watch(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    current = QObject()
    old = QObject()
    window._auto_watch_session = current
    window._auto_watch_session_id = "current"
    window._auto_watch_active = True
    window._on_auto_watch_session_stopped(old, "old")
    assert window._auto_watch_session is current
    assert window._auto_watch_session_id == "current"
    assert window._auto_watch_active is True
    window.close(); qt_app.processEvents()


def test_answer_window_auto_watch_end_restores_geometry_before_normal_save(qt_app) -> None:
    class Repository:
        def __init__(self): self.updates = []
        def load(self): return {}
        def update(self, values): self.updates.append(values)

    repository = Repository()
    answer = AnswerWindow(settings_repository=repository)
    original = QRect(17, 23, 420, 500)
    answer.setGeometry(original)
    answer.begin_auto_watch(AnalysisMode.TEXT, 1, QRect(100, 100, 50, 50), qt_app.primaryScreen())
    answer.setGeometry(QRect(200, 180, 420, 500))
    answer.end_auto_watch()
    assert answer.geometry() == original
    assert answer._auto_watch_roi is None
    answer.close(); qt_app.processEvents()
    assert repository.updates
    assert repository.updates[-1]["answer_window_geometry"]["x"] == original.x()


def test_closing_answer_window_during_watch_does_not_show_main_window(qt_app) -> None:
    main = MainWindow(tray_mode=False)
    main.hide()
    main._auto_watch_active = True
    answer = AnswerWindow()
    main._answer_window = answer
    answer.closed.connect(main._on_answer_closed)
    answer.close(); qt_app.processEvents()
    assert not main.isVisible()
    assert main._auto_watch_active is True
    main.close(); qt_app.processEvents()


def test_fake_handle_emits_result_and_finished_once_and_is_cancel_idempotent(qt_app) -> None:
    class Request:
        generation = 7
        mode = AnalysisMode.VISION

    handle = _AutoWatchFakeHandle(Request())
    results = []; finished = []; cancelled = []
    handle.result_ready.connect(results.append)
    handle.finished.connect(lambda: finished.append(True))
    handle.cancelled.connect(lambda: cancelled.append(True))
    handle.request_cancel()
    handle.request_cancel()
    handle.start()
    assert results == []
    assert cancelled == [True]
    assert finished == [True]

    second = _AutoWatchFakeHandle(Request())
    second_results = []; second_finished = []
    second.result_ready.connect(second_results.append)
    second.finished.connect(lambda: second_finished.append(True))
    second.start(); second.start(); qt_app.processEvents(); second.request_cancel()
    assert second_results == ["Fake Vision answer"]
    assert second_finished == [True]


def test_fake_main_window_watch_dispatches_result_and_keeps_watching(qt_app) -> None:
    class FakeSelection:
        selection_metadata = (qt_app.primaryScreen(), QRect(2, 3, 40, 30))

    window = MainWindow(tray_mode=True, auto_watch_fake=True)
    window.show(); window.enter_auto_watch_setup()
    window._auto_watch_selection_overlay = FakeSelection()
    assert window._on_auto_watch_capture(QImage()) is True
    session = window._auto_watch_session
    assert session is not None
    image = QImage(40, 30, QImage.Format.Format_RGBA8888)
    image.fill(0xFF112233)
    session.latest_image = image
    session.coordinator.state = MonitorState.WATCHING
    session.coordinator.generation = 1
    results = []; finished = []
    session.analysis_result.connect(results.append)
    session.analysis_finished.connect(finished.append)
    event = CoordinatorEvent(WatchEvent.INITIAL_STABLE_FRAME, 1, DetectorFrame(np.zeros((2, 2), dtype=np.uint8)))
    session._on_coordinator_event(event)
    qt_app.processEvents()
    assert results and isinstance(results[0]["result"], PipelineResult)
    assert results[0]["result"].ocr.text == "Fake OCR question"
    assert results[0]["result"].answer == "Fake OCR answer"
    assert window._answer_window is not None
    assert window._answer_window.ocr_edit.toPlainText() == "Fake OCR question"
    assert window._answer_window.answer_edit.toPlainText() == "Fake OCR answer"
    assert finished and finished[0]["generation"] == 1
    assert session.coordinator.state is MonitorState.WATCHING
    assert session._stopped is False
    answer = window._answer_window
    answer.close()
    qt_app.processEvents()
    assert window._answer_window is None
    assert window._auto_watch_session is session
    assert session._stopped is False
    session.stop()
    window.close(); qt_app.processEvents()


def test_fake_main_window_vision_result_updates_answer_window_without_ocr(qt_app) -> None:
    class FakeSelection:
        selection_metadata = (qt_app.primaryScreen(), QRect(2, 3, 40, 30))

    window = MainWindow(tray_mode=True, auto_watch_fake=True)
    window.show(); window.enter_auto_watch_setup()
    window.auto_watch_vision_radio.click()
    window._auto_watch_selection_overlay = FakeSelection()
    assert window._on_auto_watch_capture(QImage()) is True
    session = window._auto_watch_session
    assert session is not None
    image = QImage(40, 30, QImage.Format.Format_RGBA8888)
    image.fill(0xFF112233)
    session.latest_image = image
    session.coordinator.state = MonitorState.WATCHING
    session.coordinator.generation = 1
    event = CoordinatorEvent(WatchEvent.INITIAL_STABLE_FRAME, 1, DetectorFrame(np.zeros((2, 2), dtype=np.uint8)))
    session._on_coordinator_event(event)
    qt_app.processEvents()

    answer = window._answer_window
    assert answer is not None
    assert not answer.ocr_card.isVisible()
    assert answer.answer_edit.toPlainText() == "Fake Vision answer"
    assert session._stopped is False
    session.stop()
    window.close(); qt_app.processEvents()


def test_old_text_and_vision_callbacks_cannot_create_or_modify_answer_window(qt_app) -> None:
    class FakeSession(QObject):
        analysis_requested = Signal(object)
        analysis_started = Signal(object)
        analysis_result = Signal(object)
        analysis_error = Signal(object)
        analysis_cancelled = Signal(object)
        analysis_finished = Signal(object)
        session_stopped = Signal()

    class Region:
        def __init__(self, session_id):
            self.session_id = session_id

    class Request:
        def __init__(self, mode, session_id):
            self.generation = 1
            self.mode = mode
            self.session_id = session_id

    window = MainWindow(tray_mode=True)
    current = QObject()
    window._auto_watch_session = current
    window._auto_watch_session_id = "current-session"
    window._auto_watch_active = True
    window._auto_watch_generation = 1
    answer = AnswerWindow()
    answer.set_result("Current answer")
    window._answer_window = answer

    old_sessions = []
    for mode in (AnalysisMode.TEXT, AnalysisMode.VISION):
        old = FakeSession()
        old_sessions.append(old)
        old_id = f"old-{mode.value}"
        window._connect_auto_watch_signals(old, Region(old_id))
        request = Request(mode, old_id)
        result = (
            PipelineResult(OCRResult("stale OCR", (OCRLine("stale OCR"),)), "stale answer")
            if mode is AnalysisMode.TEXT else "stale vision answer"
        )
        old.analysis_result.emit({"request": request, "result": result, "mode": mode, "generation": 1})
        old.analysis_error.emit({"request": request, "error": "stale error", "mode": mode, "generation": 1})
        old.analysis_cancelled.emit({"request": request, "mode": mode, "generation": 1})
        old.analysis_finished.emit({"request": request, "mode": mode, "generation": 1})
        old.session_stopped.emit()

    assert window._auto_watch_session is current
    assert window._auto_watch_session_id == "current-session"
    assert window._auto_watch_active is True
    assert answer._auto_watch_active is False
    assert answer.answer_edit.toPlainText() == "Current answer"
    assert answer.ocr_edit.toPlainText() == ""
    window._auto_watch_session = None
    window._auto_watch_active = False
    answer.close(); window.close(); qt_app.processEvents()


def test_non_tray_watch_hides_main_window_and_stop_restores_it(qt_app) -> None:
    class FakeSelection:
        selection_metadata = (qt_app.primaryScreen(), QRect(2, 3, 40, 30))

    window = MainWindow(tray_mode=False, auto_watch_fake=True)
    window.show(); qt_app.processEvents()
    window.enter_auto_watch_setup()
    window._auto_watch_selection_overlay = FakeSelection()
    assert window._on_auto_watch_capture(QImage()) is True
    assert not window.isVisible()
    session = window._auto_watch_session
    assert session is not None
    image = QImage(40, 30, QImage.Format.Format_RGBA8888)
    image.fill(0xFF112233)
    session.latest_image = image
    session.coordinator.state = MonitorState.WATCHING
    session.coordinator.generation = 1
    session._on_coordinator_event(
        CoordinatorEvent(WatchEvent.INITIAL_STABLE_FRAME, 1, DetectorFrame(np.zeros((2, 2), dtype=np.uint8)))
    )
    qt_app.processEvents()
    answer = window._answer_window
    assert answer is not None
    assert answer.answer_edit.toPlainText() == "Fake OCR answer"
    session.stop()
    qt_app.processEvents()
    assert window.isVisible()
    assert window.auto_watch_main_view.isVisible()
    assert window.text_mode_button.isEnabled()
    assert window.vision_mode_button.isEnabled()
    assert not answer._auto_watch_active
    assert not answer.stop_button.isVisible()
    assert not answer.recapture_button.isVisible()
    assert answer.retry_button.isVisible()
    assert answer.retry_button.isEnabled()
    answer.show_processing()
    assert answer.stop_button.isVisible()
    assert answer.stop_button.isEnabled()
    assert answer.retry_button.isVisible()
    assert answer.retry_button.isEnabled() is False
    window.close(); qt_app.processEvents()


def test_tray_watch_stop_does_not_force_show_hidden_controller(qt_app) -> None:
    class FakeSelection:
        selection_metadata = (qt_app.primaryScreen(), QRect(2, 3, 40, 30))

    window = MainWindow(tray_mode=True, auto_watch_fake=True)
    window.hide(); window.enter_auto_watch_setup()
    window._auto_watch_selection_overlay = FakeSelection()
    assert window._on_auto_watch_capture(QImage()) is True
    session = window._auto_watch_session
    assert session is not None
    session.stop(); qt_app.processEvents()
    assert not window.isVisible()
    window.close(); qt_app.processEvents()


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
    monkeypatch.setattr(
        main_window_module,
        "create_ocr_provider",
        lambda config: FakeOCR(config.ocr_language),
    )
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
    monkeypatch.setattr(
        main_window_module,
        "create_ocr_provider",
        lambda config: FakeOCR(config.ocr_language),
    )
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
    assert window._answer_window.status_label.text() == "!  Analysis failed"
    assert "AI 解析失败" in window._answer_window.answer_edit.toPlainText()
    assert window._answer_window.copy_button.isEnabled() is False
    window._answer_window.close()
    window.close()
    qt_app.processEvents()
