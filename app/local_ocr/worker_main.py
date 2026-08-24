"""CLI implementation for the standalone PaddleOCR worker."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from app.ocr.profiling import make_profile_payload, make_profile_run, write_profile
from app.ocr.persistent_protocol import (
    PersistentProtocolError,
    parse_command,
    write_persistent_error,
    write_persistent_result,
)
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
    parser.add_argument("--serve", action="store_true", help="run as a persistent OCR sidecar")
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--model-root", type=Path, help="component-owned PaddleOCR model root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke:
        try:
            model_dirs = _resolve_model_dirs(args.model_root)
            return _smoke_import(model_dirs)
        except OCRError as exc:
            _log_error("Local OCR model validation failed: %s", exc)
            return 1
    if args.serve:
        if args.ready_file is None:
            _log_error("--ready-file is required with --serve")
            return 2
        return _serve(args)
    if args.input is None or args.output is None:
        _log_error("--input and --output are required unless --smoke is used")
        return 2
    if args.profile_runs < 1:
        _log_error("--profile-runs must be at least 1")
        return 2

    try:
        if not args.input.is_file():
            raise OCRError("输入图片不存在。")
        provider = _provider(args)
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


def _serve(args: argparse.Namespace) -> int:
    try:
        provider = _provider(args)
        provider.initialize()
        from app.ocr.worker_protocol import write_payload_atomic

        write_payload_atomic(
            args.ready_file,
            {"schema_version": 1, "ok": True, "mode": "persistent"},
        )
    except Exception as exc:
        try:
            from app.ocr.worker_protocol import write_payload_atomic

            write_payload_atomic(
                args.ready_file,
                {"schema_version": 1, "ok": False, "error": str(exc) or "Local OCR startup failed."},
            )
        except OSError:
            pass
        _log_exception("persistent Local OCR worker initialization failed")
        return 1

    seen_request_ids: set[str] = set()
    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        try:
            command = parse_command(json.loads(raw_line))
        except (json.JSONDecodeError, PersistentProtocolError):
            _log_error("persistent OCR command rejected")
            continue
        if command["type"] == "shutdown":
            break

        request_id = command["request_id"]
        output_path = Path(command["output"])
        if request_id in seen_request_ids:
            try:
                write_persistent_error(output_path, request_id, "duplicate request_id")
            except OSError:
                _log_error("persistent OCR response write failed")
            continue
        seen_request_ids.add(request_id)
        try:
            result = provider.recognize(Path(command["input"]))
            write_persistent_result(output_path, request_id, result)
        except OCRError as exc:
            try:
                write_persistent_error(output_path, request_id, str(exc))
            except OSError:
                _log_error("persistent OCR response write failed")
        except Exception:
            try:
                write_persistent_error(output_path, request_id, "Local OCR processing failed.")
            except OSError:
                _log_error("persistent OCR response write failed")
            _log_exception("persistent Local OCR request failed")
    return 0


def _provider(args: argparse.Namespace) -> PaddleOCRProvider:
    model_dirs = _resolve_model_dirs(args.model_root)
    if model_dirs is None:
        return PaddleOCRProvider(language=args.language)
    return PaddleOCRProvider(
        language=args.language,
        det_model_dir=model_dirs[0],
        rec_model_dir=model_dirs[1],
    )


def _resolve_model_dirs(model_root: Path | None) -> tuple[Path, Path] | None:
    if model_root is None:
        return None
    if not model_root.is_dir():
        raise OCRError(f"Local OCR model root does not exist: {model_root}")
    resolved: list[Path] = []
    for kind in ("det", "rec"):
        candidates = sorted(
            path.parent
            for path in (model_root / kind).rglob("inference.pdmodel")
            if (path.parent / "inference.pdiparams").is_file()
        ) if (model_root / kind).is_dir() else []
        if not candidates:
            raise OCRError(f"Local OCR {kind} model files are missing.")
        resolved.append(candidates[0])
    return resolved[0], resolved[1]


def _smoke_import(model_dirs: tuple[Path, Path] | None = None) -> int:
    try:
        if model_dirs is None:
            from paddleocr import PaddleOCR  # noqa: F401
        else:
            PaddleOCRProvider(
                det_model_dir=model_dirs[0],
                rec_model_dir=model_dirs[1],
            ).initialize()
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
