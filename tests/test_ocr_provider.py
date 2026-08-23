from dataclasses import dataclass
import inspect

from app.config import AppConfig
from app.ocr.base import OCRProvider
from app.ocr.factory import create_ocr_provider
from app.ocr.providers.local_worker import LocalOCRProvider
from app.ocr.providers.paddle import PaddleOCRProvider
from app.ocr.types import OCRLine, OCRResult
from app.ui import main_window as main_window_module
from app.workers.processing_worker import ProcessingWorker


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
