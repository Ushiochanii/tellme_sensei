"""Small, schema-validated diagnostics for local OCR profiling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

PROFILE_SCHEMA_VERSION = 1
PROFILE_TIMING_FIELDS = (
    "engine_init_ms",
    "input_prepare_ms",
    "engine_call_ms",
    "result_parse_ms",
    "normalize_ms",
    "total_ms",
)


def make_profile_run(index: int, timings: Mapping[str, float]) -> dict[str, Any]:
    """Return one timing record without any OCR content."""

    if index < 1:
        raise ValueError("profile run index must be positive")
    record: dict[str, Any] = {"index": index}
    for field in PROFILE_TIMING_FIELDS:
        value = float(timings.get(field, 0.0))
        if value < 0:
            raise ValueError(f"profile timing must be non-negative: {field}")
        record[field] = value
    return record


def make_profile_payload(
    runs: list[Mapping[str, Any]],
    worker_profiled_total_ms: float,
    result_write_ms: float,
) -> dict[str, Any]:
    """Build the stable diagnostic profile document."""

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "runs": [dict(run) for run in runs],
        "worker_profiled_total_ms": float(worker_profiled_total_ms),
        "result_write_ms": float(result_write_ms),
    }


def write_profile(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write a profile document as JSON."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def read_profile(path: str | Path) -> dict[str, Any]:
    """Read and validate a profile document."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("OCR profile is missing or malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("OCR profile must be a JSON object")
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported OCR profile schema")
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise ValueError("OCR profile runs are invalid")
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("index"), int):
            raise ValueError("OCR profile run is invalid")
        for field in PROFILE_TIMING_FIELDS:
            value = run.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"OCR profile timing is invalid: {field}")
    for field in ("worker_profiled_total_ms", "result_write_ms"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"OCR profile timing is invalid: {field}")
    return payload
