"""CLI implementation for the standalone PaddleOCR worker."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from app.ocr.profiling import make_profile_payload, make_profile_run, write_profile
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
    parser.add_argument("--profile-output", type=Path)
    parser.add_argument("--profile-runs", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke:
        return _smoke_import()
    if args.input is None or args.output is None:
        _log_error("--input and --output are required unless --smoke is used")
        return 2
    if args.profile_runs < 1:
        _log_error("--profile-runs must be at least 1")
        return 2

    try:
        if not args.input.is_file():
            raise OCRError("输入图片不存在。")
        provider = PaddleOCRProvider(language=args.language)
        if args.profile_output is None:
            result = provider.recognize(args.input)
            write_payload(args.output, result_payload(result))
        else:
            _run_profile(
                provider,
                args.input,
                args.output,
                args.profile_output,
                args.profile_runs,
            )
        return 0
    except OCRError as exc:
        write_payload(args.output, error_payload(str(exc)))
        _log_error("local OCR failed: %s", type(exc).__name__)
        return 1
    except Exception:
        write_payload(args.output, error_payload("本地 OCR 处理失败。"))
        _log_exception("local OCR worker failed")
        return 1


def _run_profile(
    provider: PaddleOCRProvider,
    input_path: Path,
    output_path: Path,
    profile_path: Path,
    runs_count: int,
) -> None:
    runs: list[dict[str, object]] = []
    profiled_started = time.perf_counter()
    result = None
    for index in range(1, runs_count + 1):
        result, timings = provider.recognize_profiled(input_path)
        runs.append(make_profile_run(index, timings))
    worker_profiled_total_ms = (time.perf_counter() - profiled_started) * 1000.0

    result_write_started = time.perf_counter()
    write_payload(output_path, result_payload(result))
    result_write_ms = (time.perf_counter() - result_write_started) * 1000.0
    write_profile(
        profile_path,
        make_profile_payload(runs, worker_profiled_total_ms, result_write_ms),
    )


def _smoke_import() -> int:
    try:
        from paddleocr import PaddleOCR  # noqa: F401
    except Exception:
        _log_exception("PaddleOCR import smoke failed")
        return 1
    return 0


def _log_error(message: str, *args: object) -> None:
    if sys.stderr is not None:
        logger.error(message, *args)


def _log_exception(message: str) -> None:
    if sys.stderr is not None:
        logger.exception(message)
