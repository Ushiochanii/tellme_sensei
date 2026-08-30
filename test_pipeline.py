"""Manual Phase 3 smoke test: python test_pipeline.py path\to\test.png."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import ConfigError, ConfigManager
from app.logging_config import configure_logging
from app.pipeline import PipelineError, StudyPipeline
from app.ai.service import AnalysisService
from app.services.ocr_service import OCRService


def main() -> int:
    parser = argparse.ArgumentParser(description="Test image -> OCR -> DeepSeek pipeline")
    parser.add_argument("image", type=Path, help="题目截图路径")
    args = parser.parse_args()
    configure_logging()
    try:
        config = ConfigManager().load()
        result = StudyPipeline(
            OCRService(language=config.ocr_language), AnalysisService(config)
        ).run(args.image)
    except (ConfigError, PipelineError) as exc:
        print(f"测试失败：{exc}", file=sys.stderr)
        return 1
    print("【OCR 文本】")
    print(result.ocr.text)
    print("\n【DeepSeek 答案】")
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
