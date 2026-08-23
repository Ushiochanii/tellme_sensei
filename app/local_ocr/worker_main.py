"""CLI implementation for the standalone PaddleOCR worker."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.ocr.providers.paddle import PaddleOCRProvider
from app.ocr.types import OCRError
from app.ocr.worker_protocol import error_payload, result_payload, write_payload

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TellMeSensei external local OCR worker")
    parser.add_argument("--smoke", action="store_true", help="verify PaddleOCR import only")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--language", default="japan")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke:
        return _smoke_import()
    if args.input is None or args.output is None:
        logger.error("--input and --output are required unless --smoke is used")
        return 2

    try:
        if not args.input.is_file():
            raise OCRError("输入图片不存在。")
        result = PaddleOCRProvider(language=args.language).recognize(args.input)
        write_payload(args.output, result_payload(result))
        return 0
    except OCRError as exc:
        write_payload(args.output, error_payload(str(exc)))
        logger.error("local OCR failed: %s", type(exc).__name__)
        return 1
    except Exception:
        write_payload(args.output, error_payload("本地 OCR 处理失败。"))
        logger.exception("local OCR worker failed")
        return 1


def _smoke_import() -> int:
    try:
        from paddleocr import PaddleOCR  # noqa: F401
    except Exception:
        logger.exception("PaddleOCR import smoke failed")
        return 1
    return 0
