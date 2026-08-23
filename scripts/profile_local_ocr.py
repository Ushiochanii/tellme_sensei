"""Opt-in benchmark for the packaged Local OCR worker."""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtGui import QImage  # noqa: E402

from app.ocr.profiling import read_profile  # noqa: E402
from app.ocr.providers.local_worker import LocalOCRProvider  # noqa: E402
from app.ocr.types import OCRError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile the packaged Local OCR worker")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--cold-runs", type=int, default=3)
    parser.add_argument("--warm-runs", type=int, default=3)
    parser.add_argument("--language", default="japan")
    return parser


def median_ms(values: list[float]) -> float:
    if not values:
        raise ValueError("at least one timing value is required")
    return float(statistics.median(values))


def _validate_args(args: argparse.Namespace) -> None:
    if args.cold_runs < 1:
        raise ValueError("--cold-runs must be at least 1")
    if args.warm_runs < 2:
        raise ValueError("--warm-runs must be at least 2")
    if not args.input.is_file():
        raise ValueError(f"image was not found: {args.input}")
    if not args.worker.is_file():
        raise ValueError(f"worker was not found: {args.worker}")


def _run_current_pipeline(
    image: QImage,
    worker: Path,
    language: str,
    runs_count: int,
) -> tuple[list[float], list[dict[str, Any]]]:
    totals: list[float] = []
    parent_timings: list[dict[str, Any]] = []
    for index in range(1, runs_count + 1):
        provider_timings: dict[str, float] = {}
        provider = LocalOCRProvider(language=language, executable=worker, timeout=180.0)
        started = time.perf_counter()
        provider.recognize(
            image,
            profile_timings=provider_timings,
        )
        total_ms = (time.perf_counter() - started) * 1000.0
        totals.append(total_ms)
        parent_timings.append(
            {
                "index": index,
                "end_to_end_ms": total_ms,
                "input_prepare_ms": provider_timings.get("input_prepare_ms", 0.0),
                "process_wall_ms": provider_timings.get("process_wall_ms", 0.0),
                "result_read_ms": provider_timings.get("result_read_ms", 0.0),
            }
        )
    return totals, parent_timings


def warm_sample_values(profile: dict[str, Any]) -> list[float]:
    """Return only post-initialization samples from a warm profile."""

    runs = profile.get("runs", [])
    return [float(run["total_ms"]) for run in runs[1:]]


def _run_worker_profile(
    image_path: Path,
    worker: Path,
    language: str,
    runs_count: int,
    temp_dir: Path,
) -> tuple[float, dict[str, Any]]:
    output_path = temp_dir / f"worker-{runs_count}.result.json"
    profile_path = temp_dir / f"worker-{runs_count}.profile.json"
    command = [
        str(worker),
        "--input",
        str(image_path),
        "--output",
        str(output_path),
        "--language",
        language,
        "--profile-output",
        str(profile_path),
        "--profile-runs",
        str(runs_count),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(worker.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        text=True,
        timeout=180.0 * runs_count,
        check=False,
    )
    process_wall_ms = (time.perf_counter() - started) * 1000.0
    if completed.returncode != 0:
        raise RuntimeError("packaged Local OCR worker returned a non-zero exit code")
    return process_wall_ms, read_profile(profile_path)


def _print_report(
    image: QImage,
    current_totals: list[float],
    current_details: list[dict[str, Any]],
    cold_details: list[tuple[float, dict[str, Any]]],
    warm_detail: tuple[float, dict[str, Any]],
) -> None:
    print("TellMeSensei Local OCR Profile")
    print("=" * 40)
    print(f"Image:\n  size: {image.width()} x {image.height()}")
    print("\nCurrent one-shot pipeline:")
    for index, value in enumerate(current_totals, 1):
        print(f"  run {index}: {value / 1000.0:.2f} s")
    print(f"  median: {median_ms(current_totals) / 1000.0:.2f} s")
    first = current_details[0]
    print("\nCurrent path breakdown (first run):")
    print(f"  QImage to temp PNG:          {first['input_prepare_ms'] / 1000.0:.3f} s")
    print(f"  process wall:                {first['process_wall_ms'] / 1000.0:.3f} s")
    worker = cold_details[0][1]
    worker_total = float(worker["worker_profiled_total_ms"])
    print("  (worker timings below come from a separate profiled run)")
    print(f"  estimated process overhead:  {(first['process_wall_ms'] - worker_total) / 1000.0:.3f} s")
    first_run = worker["runs"][0]
    print(f"  engine initialization:       {first_run['engine_init_ms'] / 1000.0:.3f} s")
    print(f"  Paddle engine call:          {first_run['engine_call_ms'] / 1000.0:.3f} s")
    print(f"  result parsing:              {first_run['result_parse_ms'] / 1000.0:.3f} s")
    print(f"  normalization:               {first_run['normalize_ms'] / 1000.0:.3f} s")
    print(f"  result JSON read:            {first['result_read_ms'] / 1000.0:.3f} s")
    print(f"  result JSON write:           {worker['result_write_ms'] / 1000.0:.3f} s")

    print("\nCold worker runs:")
    for index, (process_wall, profile) in enumerate(cold_details, 1):
        run = profile["runs"][0]
        print(
            f"  run {index}: process {process_wall / 1000.0:.2f} s, "
            f"engine init {run['engine_init_ms'] / 1000.0:.2f} s, "
            f"engine call {run['engine_call_ms'] / 1000.0:.2f} s"
        )

    warm_process_wall, warm_profile = warm_detail
    print("\nWarm engine reuse (same worker process):")
    warm_runs = warm_profile["runs"]
    print(
        f"  run 1 (initialization): total {warm_runs[0]['total_ms'] / 1000.0:.2f} s, "
        f"engine init {warm_runs[0]['engine_init_ms'] / 1000.0:.2f} s"
    )
    for run in warm_runs[1:]:
        print(
            f"  warm run {run['index']}: total {run['total_ms'] / 1000.0:.2f} s, "
            f"engine init {run['engine_init_ms'] / 1000.0:.3f} s, "
            f"engine call {run['engine_call_ms'] / 1000.0:.2f} s"
        )
    warm_values = warm_sample_values(warm_profile)
    print(f"  process wall: {warm_process_wall / 1000.0:.2f} s")
    print(f"  warm median (excluding run 1): {median_ms(warm_values) / 1000.0:.2f} s")
    if median_ms(warm_values) > 0:
        print(
            f"\nApproximate current median / warm median: "
            f"{median_ms(current_totals) / median_ms(warm_values):.2f}x"
        )
    print("\nengine_call_ms is Paddle engine call wall-clock time, not pure model inference.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _validate_args(args)
        image = QImage(str(args.input))
        if image.isNull():
            raise ValueError("image could not be decoded by Qt")
        with tempfile.TemporaryDirectory(prefix="tellme-sensei-ocr-profile-") as raw_dir:
            temp_dir = Path(raw_dir)
            current_totals, current_details = _run_current_pipeline(
                image, args.worker, args.language, args.cold_runs
            )
            cold_details = [
                _run_worker_profile(
                    args.input, args.worker, args.language, 1, temp_dir
                )
                for _ in range(args.cold_runs)
            ]
            warm_detail = _run_worker_profile(
                args.input, args.worker, args.language, args.warm_runs, temp_dir
            )
        _print_report(image, current_totals, current_details, cold_details, warm_detail)
        return 0
    except (OCRError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Local OCR profiling failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
