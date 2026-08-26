"""Experiment harness for comparing TellMeSensei Text and Vision requests.

This module is intentionally outside the application execution path. It uses
the production configuration and Local OCR interfaces, but sends benchmark
requests directly so API usage-only stream chunks can be measured.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any, Iterable

# Allow the documented ``python tools/...`` invocation from the repository
# root without changing the application's import/runtime behavior.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ConfigManager
from app.ocr.factory import create_ocr_provider
from app.ocr.local_session import LocalOCRSession
from app.ocr.local_runtime import component_model_root, worker_executable_candidates
from app.services.deepseek_service import SYSTEM_PROMPT, VISION_MODEL, VISION_SYSTEM_PROMPT


TEXT_MODEL = "deepseek-v4-flash"
ALLOWED_CATEGORIES = frozenset({"text", "code_table", "diagram", "math", "mixed"})
JAPANESE_ANSWERS = frozenset({"ア", "イ", "ウ", "エ"})
JAPANESE_LABELS = "アイウエ"
VISION_EXTRA_BODY = {"thinking": {"type": "enabled"}}
TEXT_PRICING = {
    "model": TEXT_MODEL,
    "pricing_as_of": "2026-08-26",
    "currency": "CNY",
    "cache_hit_price_per_million": 0.02,
    "cache_miss_price_per_million": 1.00,
    "output_price_per_million": 2.00,
}


class BenchmarkError(RuntimeError):
    """A safe, user-facing benchmark setup or request error."""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    image: Path
    expected_answer: str
    category: str
    year: int | None = None


def load_cases(path: Path) -> list[BenchmarkCase]:
    """Load either the real FE JSONL dataset or the legacy JSON-array format."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BenchmarkError(f"无法读取 benchmark cases: {path}") from exc

    if path.suffix.lower() == ".jsonl":
        raw_items: list[Any] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BenchmarkError(f"invalid JSONL at line {line_number}") from exc
            raw_items.append(item)
    else:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(f"无法读取 benchmark cases: {path}") from exc
        if not isinstance(raw, list):
            raise BenchmarkError("benchmark cases must be a JSON array")
        raw_items = raw

    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise BenchmarkError(f"case {index} must be an object")
        case_id = item.get("id")
        image_name = item.get("image")
        answer = item.get("answer")
        category = item.get("category", "mixed")
        year = item.get("year")
        if not all(isinstance(value, str) and value.strip() for value in (case_id, image_name, answer, category)):
            raise BenchmarkError(f"case {index} has invalid id/image/answer/category")
        if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
            raise BenchmarkError(f"case {index} has invalid year")
        case_id = case_id.strip()
        category = category.strip()
        if case_id in seen:
            raise BenchmarkError(f"duplicate benchmark case id: {case_id}")
        if category not in ALLOWED_CATEGORIES:
            raise BenchmarkError(f"unsupported benchmark category: {category}")
        image = path.parent / image_name
        if not image.is_file():
            raise BenchmarkError(f"benchmark image is missing for {case_id}: {image}")
        seen.add(case_id)
        cases.append(BenchmarkCase(case_id, image, answer.strip(), category, year))
    if not cases:
        raise BenchmarkError("benchmark cases file is empty")
    return cases


def validate_fe_dataset(path: Path) -> dict[str, Any]:
    """Validate the prepared 2024/2025 FE dataset without OCR or API calls."""

    cases = load_cases(path)
    if len(cases) != 40:
        raise BenchmarkError(f"FE benchmark must contain exactly 40 cases (found {len(cases)})")
    if any(case.image.suffix.lower() != ".png" for case in cases):
        raise BenchmarkError("FE benchmark images must be PNG files")
    if any(case.expected_answer not in JAPANESE_ANSWERS for case in cases):
        raise BenchmarkError("FE benchmark answers must be one of ア, イ, ウ, エ")
    years = {case.year for case in cases}
    if years != {2024, 2025}:
        raise BenchmarkError("FE benchmark years must be exactly 2024 and 2025")
    counts = {str(year): sum(case.year == year for case in cases) for year in (2024, 2025)}
    if counts != {"2024": 20, "2025": 20}:
        raise BenchmarkError(f"FE benchmark year distribution must be 20/20 (found {counts})")
    return {"cases": len(cases), "years": counts}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def extract_usage(chunk: Any) -> dict[str, int | None] | None:
    """Extract API usage without assuming the chunk has choices[0]."""

    usage = _field(chunk, "usage")
    if usage is None:
        return None
    prompt_details = _field(usage, "prompt_tokens_details")
    completion_details = _field(usage, "completion_tokens_details")
    return {
        "prompt_tokens": _int_value(_field(usage, "prompt_tokens")),
        "prompt_cache_hit_tokens": _int_value(
            _field(usage, "prompt_cache_hit_tokens")
            if _field(usage, "prompt_cache_hit_tokens") is not None
            else _field(prompt_details, "cached_tokens")
        ),
        "prompt_cache_miss_tokens": _int_value(
            _field(usage, "prompt_cache_miss_tokens")
            if _field(usage, "prompt_cache_miss_tokens") is not None
            else _field(prompt_details, "cache_miss_tokens")
        ),
        "completion_tokens": _int_value(_field(usage, "completion_tokens")),
        "reasoning_tokens": _int_value(
            _field(usage, "reasoning_tokens")
            if _field(usage, "reasoning_tokens") is not None
            else _field(completion_details, "reasoning_tokens")
        ),
        "total_tokens": _int_value(_field(usage, "total_tokens")),
    }


def extract_chunk_text(chunk: Any) -> tuple[str, str]:
    """Read content/reasoning independently; usage-only chunks have no choices."""

    choices = _field(chunk, "choices")
    if not choices:
        return "", ""
    try:
        choice = choices[0]
    except (IndexError, TypeError):
        return "", ""
    delta = _field(choice, "delta")
    if delta is None:
        return "", ""
    content = _field(delta, "content")
    reasoning = _field(delta, "reasoning_content")
    if reasoning is None:
        reasoning = _field(choice, "reasoning_content")
    return (
        content if isinstance(content, str) else "",
        reasoning if isinstance(reasoning, str) else "",
    )


def _close_stream(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def stream_completion(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    extra_body: dict[str, Any] | None = None,
) -> tuple[str, dict[str, int | None] | None, dict[str, float | None]]:
    """Run one measured streaming request and return answer, usage, timings."""

    started = time.perf_counter()
    first_chunk_ms: float | None = None
    first_visible_ms: float | None = None
    answer_parts: list[str] = []
    usage: dict[str, int | None] | None = None
    response = None
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "timeout": timeout,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if extra_body is not None:
        request["extra_body"] = extra_body
    try:
        response = client.chat.completions.create(**request)
        for chunk in response:
            if first_chunk_ms is None:
                first_chunk_ms = (time.perf_counter() - started) * 1000.0
            chunk_usage = extract_usage(chunk)
            if chunk_usage is not None:
                usage = chunk_usage
            content, _reasoning = extract_chunk_text(chunk)
            if content:
                answer_parts.append(content)
                if first_visible_ms is None and content.strip():
                    first_visible_ms = (time.perf_counter() - started) * 1000.0
    except Exception as exc:
        raise BenchmarkError(f"DeepSeek request failed ({type(exc).__name__})") from exc
    finally:
        _close_stream(response)
    answer = "".join(answer_parts).strip()
    if not answer:
        raise BenchmarkError("DeepSeek returned no visible answer")
    return answer, usage, {
        "api_first_chunk_ms": first_chunk_ms,
        "api_first_visible_token_ms": first_visible_ms,
        "api_total_ms": (time.perf_counter() - started) * 1000.0,
    }


def text_messages(ocr_text: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"下面是 OCR 识别到的题目：\n\n{ocr_text.strip()}"},
    ]


def vision_messages(image_bytes: bytes) -> list[dict[str, Any]]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return [
        {"role": "system", "content": VISION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请直接分析这张题目截图，并按指定格式给出答案、解析和知识点。"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        },
    ]


def image_as_png(path: Path) -> bytes:
    """Preserve PNGs; convert other supported image files through QImage."""

    raw = path.read_bytes()
    if path.suffix.lower() == ".png":
        return raw
    try:
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage

        image = QImage(str(path))
        if image.isNull():
            raise BenchmarkError(f"无法读取 benchmark image: {path}")
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise BenchmarkError(f"无法转换 benchmark image 为 PNG: {path}")
        return bytes(buffer.data())
    except ImportError as exc:
        raise BenchmarkError("读取非 PNG benchmark image 需要 PySide6") from exc


def normalize_choice(value: str) -> str | None:
    token = value.strip().upper()
    if token in {"1", "2", "3", "4"}:
        return token
    if token in {"A", "B", "C", "D"}:
        return str(ord(token) - ord("A") + 1)
    if token in JAPANESE_ANSWERS:
        return str(JAPANESE_LABELS.index(token) + 1)
    return None


_ANSWER_SECTION = re.compile(r"【答案】\s*(.*?)(?=【解析】|【知识点】|$)", re.DOTALL)
_CHOICE = re.compile(r"(?<![A-Z0-9])([A-D]|[1-4]|[アイウエ])(?![A-Z0-9])", re.IGNORECASE)
_ANSWER_FALLBACK = re.compile(r"正解\s*(?:是|为|は|：|:)?\s*([A-D]|[1-4]|[アイウエ])", re.IGNORECASE)


def evaluate_answer(response: str, expected: str) -> tuple[str | None, bool | None, str]:
    """Parse only the structured answer section and compare a choice."""

    expected_index = normalize_choice(expected)
    section = _ANSWER_SECTION.search(response)
    if expected_index is None:
        return None, None, "unparsed"
    match = _CHOICE.search(section.group(1)) if section is not None else _ANSWER_FALLBACK.search(response)
    if match is None:
        return None, None, "unparsed"
    parsed_index = normalize_choice(match.group(1))
    if parsed_index is None:
        return None, None, "unparsed"
    expected_token = expected.strip()
    if expected_token in {"1", "2", "3", "4"}:
        display = parsed_index
    elif expected_token in JAPANESE_ANSWERS:
        display = JAPANESE_LABELS[int(parsed_index) - 1]
    else:
        display = "ABCD"[int(parsed_index) - 1]
    return display, parsed_index == expected_index, "parsed"


def calculate_text_cost(usage: dict[str, int | None] | None) -> float | None:
    if usage is None:
        return None
    keys = ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "completion_tokens")
    if any(not isinstance(usage.get(key), int) for key in keys):
        return None
    return (
        usage["prompt_cache_hit_tokens"] * TEXT_PRICING["cache_hit_price_per_million"]
        + usage["prompt_cache_miss_tokens"] * TEXT_PRICING["cache_miss_price_per_million"]
        + usage["completion_tokens"] * TEXT_PRICING["output_price_per_million"]
    ) / 1_000_000


def discover_local_worker() -> tuple[Path, Path | None]:
    """Find an installed worker or a platform-specific development build."""

    candidates = list(worker_executable_candidates())
    repo_root = Path(__file__).resolve().parents[1]
    candidates.extend(
        repo_root / relative
        for relative in (
            "dist/local-ocr-macos-arm64/LocalOCR/TellMeSenseiOCR",
            "dist/local-ocr-macos-x64/LocalOCR/TellMeSenseiOCR",
            "dist/LocalOCR/TellMeSenseiOCR",
        )
    )
    for executable in candidates:
        if not executable.is_file():
            continue
        model_root = component_model_root(executable)
        if model_root is None:
            sibling_models = executable.parent / "models"
            if sibling_models.is_dir():
                model_root = sibling_models
        return executable, model_root
    raise BenchmarkError("找不到 Local OCR worker，请使用 --worker 和 --model-root 指定组件")


def _numeric_average(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    return sum(values) / len(values) if values else None


def _numeric_median(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    return statistics.median(values) if values else None


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = [row for row in rows if row.get("status") == "parsed"]
    return {
        "count": len(rows),
        "accuracy": (sum(bool(row["correct"]) for row in parsed) / len(parsed)) if parsed else None,
        "average_prompt_tokens": _numeric_average(rows, "prompt_tokens"),
        "average_completion_tokens": _numeric_average(rows, "completion_tokens"),
        "average_reasoning_tokens": _numeric_average(rows, "reasoning_tokens"),
        "average_total_tokens": _numeric_average(rows, "total_tokens"),
        "average_cost_cny": _numeric_average(rows, "cost_cny"),
        "median_first_chunk_ms": _numeric_median(rows, "api_first_chunk_ms"),
        "median_first_visible_token_ms": _numeric_median(rows, "api_first_visible_token_ms"),
        "median_api_latency_ms": _numeric_median(rows, "api_total_ms"),
        "median_end_to_end_ms": _numeric_median(rows, "end_to_end_ms"),
    }


def aggregate_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build overall, category, and paired Text/Vision summaries."""

    by_mode = {
        mode: _group_summary([row for row in rows if row.get("mode") == mode])
        for mode in ("text", "vision")
    }
    categories = sorted({row["category"] for row in rows})
    by_category = {
        category: {
            mode: _group_summary(
                [row for row in rows if row["category"] == category and row["mode"] == mode]
            )
            for mode in ("text", "vision")
        }
        for category in categories
    }
    paired: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        paired.setdefault(row["case_id"], {})[row["mode"]] = row
    comparison = {"text_only_correct": 0, "vision_only_correct": 0, "both_correct": 0, "both_wrong": 0, "unparsed": 0}
    for pair in paired.values():
        text_row, vision_row = pair.get("text"), pair.get("vision")
        if not text_row or not vision_row or text_row.get("status") != "parsed" or vision_row.get("status") != "parsed":
            comparison["unparsed"] += 1
        elif text_row["correct"] and vision_row["correct"]:
            comparison["both_correct"] += 1
        elif not text_row["correct"] and not vision_row["correct"]:
            comparison["both_wrong"] += 1
        elif text_row["correct"]:
            comparison["text_only_correct"] += 1
        else:
            comparison["vision_only_correct"] += 1
    return {"overall": by_mode, "by_category": by_category, "comparison": comparison}


def _build_client(config: Any) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise BenchmarkError("未安装 openai 依赖") from exc
    return OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.request_timeout,
        max_retries=0,
    )


def _base_row(case: BenchmarkCase, mode: str, timestamp: str) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "year": case.year,
        "mode": mode,
        "model": TEXT_MODEL if mode == "text" else VISION_MODEL,
        "expected_answer": case.expected_answer,
        "parsed_answer": None,
        "correct": None,
        "status": "failed",
        "prompt_tokens": None,
        "prompt_cache_hit_tokens": None,
        "prompt_cache_miss_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
        "ocr_ms": None,
        "api_first_chunk_ms": None,
        "api_first_visible_token_ms": None,
        "api_total_ms": None,
        "end_to_end_ms": None,
        "timestamp_utc": timestamp,
        "ocr_text": None,
        "response_text": None,
        "cost_cny": None,
        "error": None,
    }


def _apply_usage(row: dict[str, Any], usage: dict[str, int | None] | None) -> None:
    if usage is None:
        return
    for key in ("prompt_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "completion_tokens", "reasoning_tokens", "total_tokens"):
        row[key] = usage.get(key)


def run_benchmark(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any]]:
    cases = load_cases(Path(args.dataset))
    smoke_case = getattr(args, "smoke_case", None)
    if smoke_case:
        cases = [case for case in cases if case.case_id == smoke_case]
        if not cases:
            raise BenchmarkError(f"benchmark case not found: {smoke_case}")
    config = ConfigManager().load(require_api_key=True)
    if config.ocr_provider != "local":
        raise BenchmarkError("benchmark requires OCR_PROVIDER=local; Google Vision is not used")
    worker = args.worker
    model_root = args.model_root
    if worker is None:
        worker, discovered_model_root = discover_local_worker()
        model_root = model_root or discovered_model_root
    session = LocalOCRSession(
        executable=worker,
        model_root=model_root,
        language=config.ocr_language,
        timeout=config.request_timeout,
    )
    provider = create_ocr_provider(config, local_ocr_session=session)
    try:
        session.prepare()
    except Exception as exc:
        session.stop()
        raise BenchmarkError(f"Local OCR 初始化失败 ({type(exc).__name__})") from exc
    client = _build_client(config)
    rows: list[dict[str, Any]] = []
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        for index, case in enumerate(cases, start=1):
            order = ("text", "vision") if index % 2 else ("vision", "text")
            for mode in order:
                row = _base_row(case, mode, timestamp)
                started = time.perf_counter()
                try:
                    if mode == "text":
                        ocr_started = time.perf_counter()
                        ocr_result = provider.recognize(case.image)
                        row["ocr_ms"] = (time.perf_counter() - ocr_started) * 1000.0
                        row["ocr_text"] = ocr_result.text
                        answer, usage, timings = stream_completion(
                            client,
                            model=TEXT_MODEL,
                            messages=text_messages(ocr_result.text),
                            timeout=config.request_timeout,
                        )
                    else:
                        answer, usage, timings = stream_completion(
                            client,
                            model=VISION_MODEL,
                            messages=vision_messages(image_as_png(case.image)),
                            timeout=config.request_timeout,
                            extra_body=VISION_EXTRA_BODY,
                        )
                    row["response_text"] = answer
                    row["parsed_answer"], row["correct"], row["status"] = evaluate_answer(answer, case.expected_answer)
                    _apply_usage(row, usage)
                    row.update(timings)
                    row["cost_cny"] = calculate_text_cost(usage) if mode == "text" else None
                except Exception as exc:
                    row["error"] = type(exc).__name__
                row["end_to_end_ms"] = (time.perf_counter() - started) * 1000.0
                rows.append(row)
    finally:
        session.stop()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.output) if args.output else Path("benchmark_results") / f"benchmark-{stamp}.jsonl"
    summary_path = Path(args.summary_output) if args.summary_output else output.with_name(output.stem + "-summary.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = aggregate_results(rows)
    summary["pricing"] = {"text": TEXT_PRICING, "vision": None}
    summary["result_file"] = str(output)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_summary(summary)
    return output, summary_path, summary


def _print_summary(summary: dict[str, Any]) -> None:
    print(json.dumps(summary["overall"], ensure_ascii=False, indent=2))
    print("comparison:", json.dumps(summary["comparison"], ensure_ascii=False, sort_keys=True))
    for category, values in summary["by_category"].items():
        print(f"{category}: {json.dumps(values, ensure_ascii=False, sort_keys=True)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare TellMeSensei Text/OCR and Vision using real DeepSeek usage.")
    parser.add_argument("--dataset", type=Path, default=Path("fe_benchmark/benchmark.jsonl"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--worker", type=Path, help="optional Local OCR worker executable")
    parser.add_argument("--model-root", type=Path, help="optional component-owned Local OCR model root")
    parser.add_argument("--validate-only", action="store_true", help="validate the FE JSONL dataset without OCR or API requests")
    parser.add_argument("--smoke-case", help="run exactly one case through both modes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.validate_only:
            print(json.dumps(validate_fe_dataset(Path(args.dataset)), ensure_ascii=False, sort_keys=True))
        else:
            run_benchmark(args)
    except BenchmarkError as exc:
        print(f"benchmark failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
