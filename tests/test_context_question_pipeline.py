from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage
import pytest

from app.analysis import AnalysisMode
from app.auto_watch import (
    AnalysisDispatcher,
    ContextOCRCache,
    ContextQuestionAnalysisRequest,
    PairSnapshot,
    AutoWatchDispatcherBridge,
    compose_context_question_image,
)
from app.config import AppConfig
from app.ocr.types import OCRLine, OCRResult
from app.pipeline import ContextQuestionPipelineResult
from app.services.deepseek_service import DeepSeekService
from app.workers.context_question_processing_worker import ContextQuestionProcessingWorker
from app.workers.vision_processing_worker import VisionProcessingWorker


def test_context_question_worker_direct_import_avoids_auto_watch_cycle() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.workers.context_question_processing_worker import ContextQuestionProcessingWorker",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _image(color: str, width: int = 20, height: int = 12) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor(color))
    return image


def _ocr(text: str) -> OCRResult:
    return OCRResult(text, (OCRLine(text),))


def test_context_question_request_detaches_both_images_and_validates_revisions() -> None:
    context = _image("red")
    question = _image("blue")
    request = ContextQuestionAnalysisRequest(
        4,
        AnalysisMode.TEXT,
        context,
        question,
        2,
        7,
        request_id="pair-request",
    )

    context.fill(QColor("green"))
    question.fill(QColor("yellow"))

    assert request.context_image.pixelColor(0, 0) == QColor("red")
    assert request.question_image.pixelColor(0, 0) == QColor("blue")
    assert (request.generation, request.context_revision, request.question_revision) == (4, 2, 7)

    with pytest.raises(ValueError):
        ContextQuestionAnalysisRequest(0, AnalysisMode.TEXT, _image("red"), _image("blue"), 1, 1, request_id="x")
    with pytest.raises(ValueError):
        ContextQuestionAnalysisRequest(1, AnalysisMode.TEXT, _image("red"), _image("blue"), 0, 1, request_id="x")


def test_context_ocr_cache_uses_only_context_revision_and_clears() -> None:
    cache = ContextOCRCache()
    result = _ocr("context one")

    cache.put(3, result)

    assert cache.get(3) is result
    assert cache.get(4) is None
    assert cache.cached_context_revision == 3
    assert cache.cached_context_ocr_result is result

    cache.clear()

    assert cache.cached_context_revision is None
    assert cache.cached_context_ocr_result is None
    assert cache.get(3) is None


def test_dispatcher_stop_and_new_session_clear_context_cache() -> None:
    cache = ContextOCRCache()
    cache.put(1, _ocr("session one"))
    dispatcher = AnalysisDispatcher(worker_factory=lambda _request: None, context_ocr_cache=cache)

    dispatcher.stop()

    assert cache.cached_context_ocr_result is None
    cache.put(2, _ocr("session two"))
    dispatcher.reset_session("new-session")
    assert cache.cached_context_ocr_result is None


def test_context_ocr_cache_rejects_worker_write_after_stop_clear() -> None:
    class _StopBeforeWriteCache(ContextOCRCache):
        def __init__(self) -> None:
            super().__init__()
            self.dispatcher = AnalysisDispatcher(
                worker_factory=lambda _request: None,
                context_ocr_cache=self,
            )

        def put(self, context_revision, result, *, clear_generation=None):
            self.dispatcher.stop()
            return super().put(
                context_revision,
                result,
                clear_generation=clear_generation,
            )

    cache = _StopBeforeWriteCache()
    _run_context_question_worker(
        cache,
        _RecordingOCR(),
        _RecordingContextQuestionAI(),
        _image("red"),
        _image("blue"),
        1,
        1,
    )

    assert cache.cached_context_revision is None
    assert cache.cached_context_ocr_result is None


class _RecordingOCR:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def recognize(self, image: QImage, cancel_event=None) -> OCRResult:
        assert cancel_event is not None
        color = image.pixelColor(0, 0).name()
        self.calls.append(color)
        return _ocr(f"ocr-{color}")


class _RecordingContextQuestionAI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def analyze_context_question(self, context_text: str, question_text: str, cancel_event=None) -> str:
        assert cancel_event is not None
        self.calls.append((context_text, question_text))
        return f"answer:{context_text}:{question_text}"


def _run_context_question_worker(
    cache: ContextOCRCache,
    ocr: _RecordingOCR,
    ai: _RecordingContextQuestionAI,
    context: QImage,
    question: QImage,
    context_revision: int,
    question_revision: int,
) -> ContextQuestionPipelineResult:
    results: list[ContextQuestionPipelineResult] = []
    worker = ContextQuestionProcessingWorker(
        context,
        question,
        ocr,
        ai,
        context_revision,
        question_revision,
        job_id=f"pair-{context_revision}-{question_revision}",
        context_ocr_cache=cache,
    )
    worker.job_result_ready.connect(lambda _job_id, result: results.append(result))
    worker.run()
    assert len(results) == 1
    return results[0]


def test_context_question_worker_caches_c1_across_questions_but_reocr_c2() -> None:
    cache = ContextOCRCache()
    ocr = _RecordingOCR()
    ai = _RecordingContextQuestionAI()
    context_one = _image("red")
    context_two = _image("green")

    first = _run_context_question_worker(cache, ocr, ai, context_one, _image("blue"), 1, 1)
    second = _run_context_question_worker(cache, ocr, ai, _image("yellow"), _image("yellow"), 1, 2)
    third = _run_context_question_worker(cache, ocr, ai, context_one, _image("orange"), 1, 3)
    fourth = _run_context_question_worker(cache, ocr, ai, context_two, _image("blue"), 2, 1)

    assert [item.context_revision for item in (first, second, third, fourth)] == [1, 1, 1, 2]
    assert [item.question_revision for item in (first, second, third, fourth)] == [1, 2, 3, 1]
    assert ocr.calls == ["#ff0000", "#0000ff", "#ffff00", "#ffa500", "#008000", "#0000ff"]
    assert ai.calls == [
        ("ocr-#ff0000", "ocr-#0000ff"),
        ("ocr-#ff0000", "ocr-#ffff00"),
        ("ocr-#ff0000", "ocr-#ffa500"),
        ("ocr-#008000", "ocr-#0000ff"),
    ]


def test_context_question_worker_emits_structured_result_and_uses_one_ai_call() -> None:
    ocr = _RecordingOCR()
    ai = _RecordingContextQuestionAI()
    result = _run_context_question_worker(
        ContextOCRCache(),
        ocr,
        ai,
        _image("red"),
        _image("blue"),
        5,
        6,
    )

    assert isinstance(result, ContextQuestionPipelineResult)
    assert result.context_ocr.text == "ocr-#ff0000"
    assert result.question_ocr.text == "ocr-#0000ff"
    assert result.answer.startswith("answer:")
    assert len(ai.calls) == 1


def test_compose_context_question_image_keeps_two_sources_in_one_memory_image() -> None:
    context = _image("red", width=20, height=10)
    question = _image("blue", width=30, height=12)

    composite = compose_context_question_image(context, question)

    assert composite.size().width() == 30 + 32
    assert composite.size().height() == 16 + 32 + 10 + 8 + 32 + 12 + 16
    assert composite.pixelColor(16, 48) == QColor("red")
    assert composite.pixelColor(16, 98) == QColor("blue")
    assert context.pixelColor(0, 0) == QColor("red")
    assert question.pixelColor(0, 0) == QColor("blue")


class _VisionService:
    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def analyze_image(self, image_bytes: bytes, cancel_event=None) -> str:
        assert cancel_event is not None
        self.calls.append(image_bytes)
        return "vision answer"


class _TextStream:
    def __init__(self, text: str) -> None:
        self._chunks = iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])])
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self) -> None:
        self.closed = True


def test_deepseek_context_question_request_preserves_semantic_sections() -> None:
    stream = _TextStream("structured answer")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: setattr(client, "kwargs", kwargs) or stream)
        )
    )
    service = DeepSeekService(AppConfig(api_key="test"), client=client)

    assert service.analyze_context_question("common context", "current question") == "structured answer"

    user_content = client.kwargs["messages"][1]["content"]
    assert "【公共题干 / Context】\ncommon context" in user_content
    assert "【当前问题 / Question】\ncurrent question" in user_content
    assert "extra_body" not in client.kwargs
    assert stream.closed is True


def test_dispatcher_routes_dual_vision_through_existing_worker_once() -> None:
    service = _VisionService()
    dispatcher = AnalysisDispatcher(
        config=AppConfig(api_key="test"),
        deepseek_service=service,
    )
    request = ContextQuestionAnalysisRequest(
        10,
        AnalysisMode.VISION,
        _image("red"),
        _image("blue"),
        3,
        4,
        request_id="vision-pair",
    )

    handle = dispatcher._default_worker_factory(request)

    assert isinstance(handle.worker, VisionProcessingWorker)
    assert handle.worker.image.width() == 20 + 32
    assert handle.worker.image.height() > request.context_image.height() + request.question_image.height()
    handle.worker.run()
    assert len(service.calls) == 1


def test_dispatcher_routes_dual_text_to_dedicated_worker_and_shared_cache() -> None:
    cache = ContextOCRCache()
    dispatcher = AnalysisDispatcher(
        config=AppConfig(api_key="test"),
        deepseek_service=_RecordingContextQuestionAI(),
        ocr_provider=_RecordingOCR(),
        context_ocr_cache=cache,
    )
    request = ContextQuestionAnalysisRequest(
        10,
        AnalysisMode.TEXT,
        _image("red"),
        _image("blue"),
        3,
        4,
        request_id="text-pair",
    )

    handle = dispatcher._default_worker_factory(request)

    assert isinstance(handle.worker, ContextQuestionProcessingWorker)
    assert handle.worker.context_ocr_cache is cache


class _ManualWorker(QObject):
    result_ready = Signal(object)
    error_occurred = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, request) -> None:
        super().__init__()
        self.request = request
        self.cancel_calls = 0

    def start(self) -> None:
        pass

    def request_cancel(self) -> None:
        self.cancel_calls += 1

    def result(self, value) -> None:
        self.result_ready.emit(value)

    def done(self) -> None:
        self.finished.emit()


def test_context_ocr_cache_survives_pause_and_latest_wins_cancellation() -> None:
    cache = ContextOCRCache()
    cached = _ocr("cached context")
    cache.put(1, cached)
    workers: list[_ManualWorker] = []

    def factory(request):
        worker = _ManualWorker(request)
        workers.append(worker)
        return worker

    dispatcher = AnalysisDispatcher(
        worker_factory=factory,
        context_ocr_cache=cache,
    )
    pair_args = dict(
        mode=AnalysisMode.TEXT,
        context_revision=1,
        question_revision=1,
        session_id="cache-session",
    )

    dispatcher.submit_context_question(_image("red"), _image("blue"), generation=1, **pair_args)
    dispatcher.pause()
    assert cache.cached_context_ocr_result is cached

    dispatcher.submit_context_question(_image("red"), _image("green"), generation=2, **pair_args)
    assert workers[0].cancel_calls == 1
    assert cache.cached_context_ocr_result is cached


def test_pair_10_11_12_latest_wins_and_old_result_cannot_replace_pair_12() -> None:
    workers: list[_ManualWorker] = []
    results: list[tuple[int, object]] = []

    def factory(request):
        worker = _ManualWorker(request)
        workers.append(worker)
        return worker

    dispatcher = AnalysisDispatcher(
        worker_factory=factory,
        on_result=lambda request, value: results.append((request.generation, value)),
    )
    pair_args = dict(
        mode=AnalysisMode.TEXT,
        context_revision=1,
        question_revision=1,
        session_id="pair-session",
    )
    pair10 = dispatcher.submit_context_question(_image("red"), _image("blue"), generation=10, **pair_args)
    pair11 = dispatcher.submit_context_question(_image("red"), _image("green"), generation=11, **pair_args)
    pair12 = dispatcher.submit_context_question(_image("red"), _image("yellow"), generation=12, **pair_args)

    assert pair10 is not None and pair11 is not None and pair12 is not None
    assert len(workers) == 1
    assert dispatcher.pending_request is pair12
    assert workers[0].cancel_calls == 1
    assert dispatcher.submit_context_question(_image("red"), _image("black"), generation=11, **pair_args) is None

    workers[0].result("stale pair 10")
    workers[0].done()

    assert results == []
    assert len(workers) == 2
    assert workers[1].request is pair12
    assert dispatcher.pending_request is None
    workers[1].done()
    assert dispatcher.active_request is None


def test_pair_bridge_deduplicates_snapshot_generation() -> None:
    requests = []

    class Dispatcher:
        session_id = "pair-session"

        def submit_context_question(self, *args, **kwargs):
            requests.append((args, kwargs))
            return SimpleNamespace(generation=kwargs["generation"])

        def reset_session(self, _session_id):
            pass

    snapshot = PairSnapshot(1, 2, 3, _image("red"), _image("blue"))
    bridge = AutoWatchDispatcherBridge(Dispatcher())

    assert bridge.submit_pair_event(snapshot) is not None
    assert bridge.submit_pair_event(snapshot) is None
    assert len(requests) == 1
    assert requests[0][1]["context_revision"] == 2
    assert requests[0][1]["question_revision"] == 3
