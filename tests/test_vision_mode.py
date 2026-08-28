from __future__ import annotations

import base64
import json
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from app.analysis import AnalysisMode
from app.config import AppConfig
from app.services.deepseek_service import (
    DeepSeekCancelled,
    DeepSeekError,
    DeepSeekService,
    VISION_MODEL,
)
from app.state import AppState
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.workers.vision_processing_worker import VisionProcessingWorker


def _image() -> QImage:
    image = QImage(8, 6, QImage.Format.Format_RGBA8888)
    image.fill(0xFFFFFFFF)
    return image


def _chunk(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
    )


def _reasoning_chunk(text: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, reasoning_content=text),
                finish_reason=None,
            )
        ]
    )


def _finish_chunk(reason: str = "stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None),
                finish_reason=reason,
            )
        ]
    )


class _Stream:
    def __init__(self, chunks) -> None:
        self.chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.chunks)

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, stream: _Stream) -> None:
        self.stream = stream
        self.kwargs = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.stream


def test_vision_request_uses_fixed_model_and_png_data_url() -> None:
    stream = _Stream([_chunk("第一段"), _chunk("第二段")])
    client = _Client(stream)
    service = DeepSeekService(AppConfig(api_key="test"), client=client)
    image_bytes = VisionProcessingWorker.encode_png(_image())

    assert service.analyze_image(image_bytes) == "第一段第二段"
    assert client.kwargs["model"] == VISION_MODEL
    assert client.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    content = client.kwargs["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    data_url = content[1]["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(data_url.split(",", 1)[1])
    assert decoded == image_bytes
    assert "下面是 OCR 识别到的题目" not in json.dumps(client.kwargs, ensure_ascii=False)
    assert stream.closed is True


def test_text_request_does_not_enable_vision_thinking_override() -> None:
    stream = _Stream([_chunk("文字答案"), _finish_chunk()])
    client = _Client(stream)
    service = DeepSeekService(AppConfig(api_key="test"), client=client)

    assert service.analyze("题目文字") == "文字答案"
    assert "extra_body" not in client.kwargs


def test_vision_reasoning_without_final_content_is_empty_answer_error() -> None:
    stream = _Stream([_reasoning_chunk("内部推理，不是最终答案"), _finish_chunk()])
    service = DeepSeekService(AppConfig(api_key="test"), client=_Client(stream))

    with pytest.raises(DeepSeekError, match="空答案"):
        service.analyze_image(VisionProcessingWorker.encode_png(_image()))


def test_vision_request_cancellation_and_empty_response() -> None:
    cancel_event = threading.Event()

    class CancellingStream(_Stream):
        def __next__(self):
            chunk = super().__next__()
            cancel_event.set()
            return chunk

    service = DeepSeekService(
        AppConfig(api_key="test"),
        client=_Client(CancellingStream([_chunk("部分答案")])),
    )
    with pytest.raises(DeepSeekCancelled):
        service.analyze_image(
            VisionProcessingWorker.encode_png(_image()),
            cancel_event=cancel_event,
        )

    empty = DeepSeekService(
        AppConfig(api_key="test"),
        client=_Client(_Stream([])),
    )
    with pytest.raises(DeepSeekError, match="空答案"):
        empty.analyze_image(VisionProcessingWorker.encode_png(_image()))


def test_vision_worker_analyzes_image_without_ocr_provider() -> None:
    received: list[bytes] = []

    class FakeVision:
        def analyze_image(self, image_bytes: bytes, cancel_event=None) -> str:
            received.append(image_bytes)
            return "【答案】图形答案"

    worker = VisionProcessingWorker(_image(), FakeVision(), "vision-job")
    events: list[str] = []
    answers: list[str] = []
    worker.job_ai_started.connect(lambda _job_id: events.append("ai"))
    worker.job_result_ready.connect(lambda _job_id, answer: answers.append(answer))
    worker.finished.connect(lambda: events.append("finished"))
    worker.run()

    assert received and received[0].startswith(b"\x89PNG")
    assert answers == ["【答案】图形答案"]
    assert events == ["ai", "finished"]


def test_vision_worker_cancellation_is_structured() -> None:
    cancelled: list[str] = []

    class CancelledVision:
        def analyze_image(self, _image_bytes: bytes, cancel_event=None) -> str:
            raise DeepSeekCancelled("cancelled")

    worker = VisionProcessingWorker(_image(), CancelledVision(), "vision-cancel")
    worker.cancelled.connect(cancelled.append)
    worker.run()

    assert cancelled == ["vision-cancel"]


def test_main_window_vision_capture_skips_ocr(monkeypatch, qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window._capture_mode = AnalysisMode.VISION
    launched: list[QImage] = []
    monkeypatch.setattr(window, "_launch_vision_worker", launched.append)
    monkeypatch.setattr(
        main_window_module,
        "create_ocr_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Vision must not create OCR")),
    )

    window._on_capture(_image())

    assert window._active_mode is AnalysisMode.VISION
    assert len(launched) == 1
    assert window._answer_window is not None
    assert window._answer_window.ocr_edit.isVisible() is False
    window._busy = False
    window.state = AppState.IDLE
    window.shutdown()
    qt_app.processEvents()


def test_vision_reanalyze_and_recapture_preserve_mode(monkeypatch, qt_app) -> None:
    window = MainWindow(tray_mode=True)
    image = _image()
    window._active_mode = AnalysisMode.VISION
    window._last_vision_image = image
    window._show_or_create_answer()
    window._answer_window.set_mode(AnalysisMode.VISION)
    calls: list[QImage] = []
    monkeypatch.setattr(window, "_launch_vision_worker", calls.append)

    window._retry_analysis()
    assert len(calls) == 1
    assert calls[0].size() == image.size()

    window._busy = False
    window.state = AppState.IDLE
    requested: list[bool] = []
    monkeypatch.setattr(window, "start_vision_capture", lambda: requested.append(True) or True)
    window._recapture_requested()
    assert requested == [True]
    window.shutdown()
    qt_app.processEvents()


def test_main_window_mode_buttons_route_physical_capture(qt_app, monkeypatch) -> None:
    window = MainWindow(tray_mode=True)
    calls: list[AnalysisMode] = []
    monkeypatch.setattr(window, "start_text_capture", lambda: calls.append(AnalysisMode.TEXT) or True)
    monkeypatch.setattr(window, "start_vision_capture", lambda: calls.append(AnalysisMode.VISION) or True)

    window.vision_mode_button.click()
    assert calls == [AnalysisMode.VISION]

    window.text_mode_button.click()
    assert calls == [AnalysisMode.VISION, AnalysisMode.TEXT]
    window.close()
    qt_app.processEvents()


def test_main_window_controller_has_glass_mode_controls(qt_app) -> None:
    window = MainWindow(tray_mode=True)

    assert window.text_mode_button.text().startswith("Text / OCR")
    assert window.vision_mode_button.text().startswith("Vision")
    assert window.settings_button.toolTip() == "Settings"
    assert window.status_label.text() == "●  Ready"
    assert window.width() == 340
    assert window.height() == 330
    window.close()
    qt_app.processEvents()


def test_main_window_displays_configured_shortcuts(qt_app) -> None:
    config = AppConfig(
        api_key="test",
        global_shortcut="Ctrl+Alt+T",
        vision_global_shortcut="Ctrl+Alt+V",
    )
    manager = SimpleNamespace(load=lambda require_api_key=False: config)
    window = MainWindow(
        tray_mode=True,
        config_manager=manager,
        hotkey_manager=SimpleNamespace(shortcut="Ctrl+Alt+T"),
        vision_hotkey_manager=SimpleNamespace(shortcut="Ctrl+Alt+V"),
    )

    assert "Ctrl+Alt+T" in window.text_mode_button.text()
    assert "Ctrl+Alt+V" in window.vision_mode_button.text()
    window.close()
    qt_app.processEvents()


def test_main_window_shortcut_labels_refresh_after_settings_save(qt_app) -> None:
    config_values = {"text": "Ctrl+Shift+A", "vision": "Ctrl+Shift+S"}
    config = AppConfig(
        api_key="test",
        global_shortcut=config_values["text"],
        vision_global_shortcut=config_values["vision"],
    )
    manager = SimpleNamespace(load=lambda require_api_key=False: config)
    text_hotkey = SimpleNamespace(shortcut="Ctrl+Shift+A")
    vision_hotkey = SimpleNamespace(shortcut="Ctrl+Shift+S")
    window = MainWindow(
        tray_mode=True,
        config_manager=manager,
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )

    text_hotkey.shortcut = "Ctrl+Alt+T"
    vision_hotkey.shortcut = "Ctrl+Alt+V"
    window._on_settings_saved()

    assert "Ctrl+Alt+T" in window.text_mode_button.text()
    assert "Ctrl+Alt+V" in window.vision_mode_button.text()
    window.close()
    qt_app.processEvents()


def test_main_window_disables_both_mode_controls_while_busy(qt_app) -> None:
    window = MainWindow(tray_mode=True)
    window._set_state(AppState.CAPTURING)
    window._set_capture_controls_enabled(False)

    assert window.text_mode_button.isEnabled() is False
    assert window.vision_mode_button.isEnabled() is False
    assert "Capturing" in window.status_label.text()

    window._restore_idle()
    assert window.text_mode_button.isEnabled() is True
    assert window.vision_mode_button.isEnabled() is True
    assert window.status_label.text() == "●  Ready"
    window.close()
    qt_app.processEvents()


def test_explicit_mode_entrypoints_override_radio_and_sync_selection(qt_app, monkeypatch) -> None:
    window = MainWindow(tray_mode=True)
    calls: list[AnalysisMode] = []
    monkeypatch.setattr(window, "_start_capture", lambda mode: calls.append(mode) or True)

    window.start_text_capture()
    assert calls == [AnalysisMode.TEXT]
    assert window._active_mode is AnalysisMode.TEXT

    window.start_vision_capture()
    assert calls == [AnalysisMode.TEXT, AnalysisMode.VISION]
    assert window._active_mode is AnalysisMode.VISION
    window.close()
    qt_app.processEvents()


def test_floating_controller_hides_for_capture_and_returns_after_completion_or_cancel(
    qt_app, monkeypatch
) -> None:
    class FakeOverlay(QObject):
        captured = Signal(QImage)
        cancelled = Signal()

        def __init__(self, **_kwargs) -> None:
            super().__init__()

        def begin(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(main_window_module, "CaptureOverlay", FakeOverlay)

    completed = MainWindow(tray_mode=False)
    completed.show()
    completed._ensure_screen_recording_permission = lambda: True
    monkeypatch.setattr(completed, "_launch_vision_worker", lambda _image: None)
    assert completed.start_vision_capture() is True
    assert completed.isVisible() is False
    overlay = completed._overlay
    assert overlay is not None
    overlay.captured.emit(_image())
    qt_app.processEvents()
    assert completed.isVisible() is True
    completed._busy = False
    completed.state = AppState.IDLE
    completed.shutdown()
    completed.close()

    cancelled = MainWindow(tray_mode=False)
    cancelled.show()
    cancelled._ensure_screen_recording_permission = lambda: True
    assert cancelled.start_text_capture() is True
    assert cancelled.isVisible() is False
    overlay = cancelled._overlay
    assert overlay is not None
    overlay.cancelled.emit()
    qt_app.processEvents()
    assert cancelled.isVisible() is True
    cancelled.shutdown()
    cancelled.close()
    qt_app.processEvents()
