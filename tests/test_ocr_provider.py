from dataclasses import dataclass
import inspect

import pytest

from app.config import AppConfig
from app.ocr.base import OCRProvider
from app.ocr.factory import create_ocr_provider
from app.ocr.profiling import read_profile, write_profile
from app.ocr.providers.local_worker import LocalOCRProvider
from app.ocr.providers.paddle import PaddleOCRProvider
from app.ocr.types import OCRLine, OCRResult
from app.ui import main_window as main_window_module
from app.workers.processing_worker import ProcessingWorker
from scripts.profile_local_ocr import median_ms


def test_factory_returns_local_provider_by_default() -> None:
    provider = create_ocr_provider(AppConfig(api_key="test", ocr_language="en"))

    assert isinstance(provider, LocalOCRProvider)
    assert provider.language == "en"


def test_ocr_result_contract_is_provider_independent() -> None:
    result = OCRResult("question", (OCRLine("question", confidence=0.9),))

    assert result.text == "question"
    assert result.lines[0].confidence == 0.9


def test_processing_worker_accepts_generic_ocr_provider() -> None:
    @dataclass
    class FakeOCR:
        def recognize(self, image) -> OCRResult:
            assert image == "image"
            return OCRResult("OCR text", (OCRLine("OCR text"),))

    @dataclass
    class FakeAI:
        def analyze(self, text: str) -> str:
            return f"answer: {text}"

    provider: OCRProvider = FakeOCR()
    worker = ProcessingWorker("image", provider, FakeAI())
    results: list[object] = []
    worker.result_ready.connect(results.append)
    worker.run()

    assert results[0].ocr.text == "OCR text"
    assert results[0].answer == "answer: OCR text"


def test_main_window_uses_factory_without_paddle_construction() -> None:
    source = inspect.getsource(main_window_module)

    assert "create_ocr_provider" in source
    assert "PaddleOCR" not in source
    assert "OCRService(" not in source


def test_paddle_profile_reuses_one_lazy_engine(tmp_path) -> None:
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"image")

    class FakeEngine:
        def predict(self, _image):
            return {
                "rec_texts": ["hello"],
                "rec_scores": [0.9],
                "rec_boxes": [[[0, 0], [10, 10]]],
            }

    class FakeProvider(PaddleOCRProvider):
        def _get_engine(self):
            if self._engine is None:
                self._engine = FakeEngine()
            return self._engine

    provider = FakeProvider()
    first, first_timings = provider.recognize_profiled(image_path)
    second, second_timings = provider.recognize_profiled(image_path)

    assert first.text == second.text == "hello"
    assert first_timings["engine_init_ms"] >= 0.0
    assert second_timings["engine_init_ms"] == 0.0
    assert first_timings["engine_call_ms"] >= 0.0
    assert first_timings["result_parse_ms"] >= 0.0
    assert first_timings["normalize_ms"] >= 0.0


def test_profile_schema_rejects_malformed_documents(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed"):
        read_profile(profile_path)


def test_profile_schema_round_trip_contains_timings_only(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    write_profile(
        profile_path,
        {
            "schema_version": 1,
            "runs": [
                {
                    "index": 1,
                    "engine_init_ms": 1.0,
                    "input_prepare_ms": 2.0,
                    "engine_call_ms": 3.0,
                    "result_parse_ms": 4.0,
                    "normalize_ms": 5.0,
                    "total_ms": 15.0,
                }
            ],
            "worker_profiled_total_ms": 15.0,
            "result_write_ms": 1.0,
        },
    )

    assert read_profile(profile_path)["runs"][0]["engine_call_ms"] == 3.0


def test_profile_benchmark_median() -> None:
    assert median_ms([30.0, 10.0, 20.0]) == 20.0
