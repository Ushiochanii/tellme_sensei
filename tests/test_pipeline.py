from dataclasses import dataclass

from app.pipeline import StudyPipeline
from app.services.ocr_service import OCRLine, OCRResult


@dataclass
class FakeOCR:
    def recognize(self, image: str) -> OCRResult:
        return OCRResult("RAM 和 ROM 的区别？", (OCRLine("RAM 和 ROM 的区别？"),))


@dataclass
class FakeDeepSeek:
    received: str = ""

    def analyze(self, text: str) -> str:
        self.received = text
        return "【答案】RAM 易失，ROM 非易失。"


def test_pipeline_connects_ocr_to_deepseek() -> None:
    deepseek = FakeDeepSeek()
    result = StudyPipeline(FakeOCR(), deepseek).run("question.png")
    assert deepseek.received == "RAM 和 ROM 的区别？"
    assert result.answer.startswith("【答案】")
