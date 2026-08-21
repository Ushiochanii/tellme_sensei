"""Phase 1-3 command-line entry point; GUI is intentionally not included yet."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.config import ConfigError, ConfigManager
from app.logging_config import configure_logging
from app.pipeline import PipelineError, StudyPipeline
from app.services.deepseek_service import DeepSeekService
from app.services.ocr_service import OCRService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Study Assistant Phase 1-3 CLI pipeline")
    parser.add_argument("image", type=Path, help="题目截图路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    logger = logging.getLogger(__name__)
    args = build_parser().parse_args(argv)
    try:
        config = ConfigManager().load()
        pipeline = StudyPipeline(
            ocr_service=OCRService(language=config.ocr_language),
            deepseek_service=DeepSeekService(config),
        )
        result = pipeline.run(args.image)
    except (ConfigError, PipelineError) as exc:
        logger.error("处理失败: %s", exc)
        return 1

    print("【OCR 文本】")
    print(result.ocr.text)
    print("\n【DeepSeek 答案】")
    print(result.answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
