from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools.benchmark_text_vs_vision import (
    BenchmarkError,
    VISION_EXTRA_BODY,
    aggregate_results,
    evaluate_answer,
    extract_chunk_text,
    extract_usage,
    load_cases,
    validate_fe_dataset,
    vision_messages,
    stream_completion,
)


def _content_chunk(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)],
        usage=None,
    )


def test_usage_only_chunk_with_empty_choices_is_extracted() -> None:
    chunk = SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=11,
            prompt_cache_hit_tokens=5,
            prompt_cache_miss_tokens=6,
            completion_tokens=7,
            total_tokens=18,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
        ),
    )

    assert extract_chunk_text(chunk) == ("", "")
    assert extract_usage(chunk) == {
        "prompt_tokens": 11,
        "prompt_cache_hit_tokens": 5,
        "prompt_cache_miss_tokens": 6,
        "completion_tokens": 7,
        "reasoning_tokens": 2,
        "total_tokens": 18,
    }


def test_stream_completion_assembles_content_and_usage() -> None:
    usage_chunk = SimpleNamespace(
        choices=[],
        usage={
            "prompt_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 4, "cache_miss_tokens": 6},
            "completion_tokens": 3,
            "completion_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 13,
        },
    )

    class Stream:
        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            return iter([_content_chunk("答案"), usage_chunk])

        def close(self) -> None:
            self.closed = True

    stream = Stream()

    class Client:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return stream

    client = Client()
    answer, usage, timings = stream_completion(
        client,
        model="deepseek-v4-flash",
        messages=[],
        timeout=10,
    )

    assert answer == "答案"
    assert usage["prompt_cache_hit_tokens"] == 4
    assert usage["prompt_cache_miss_tokens"] == 6
    assert timings["api_first_chunk_ms"] is not None
    assert timings["api_first_visible_token_ms"] is not None
    assert timings["api_total_ms"] is not None
    assert client.kwargs["stream"] is True
    assert client.kwargs["stream_options"] == {"include_usage": True}
    assert stream.closed is True


def test_vision_request_keeps_image_payload_and_thinking_configuration() -> None:
    class Stream:
        def __iter__(self):
            return iter([_content_chunk("【答案】 1")])

        def close(self) -> None:
            pass

    class Client:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return Stream()

    client = Client()
    messages = vision_messages(b"png-bytes")
    stream_completion(
        client,
        model="deepseek-v4-flash-vision-exp",
        messages=messages,
        timeout=10,
        extra_body=VISION_EXTRA_BODY,
    )

    assert client.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    image_url = client.kwargs["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    assert "png-bytes" not in image_url


def test_answer_parser_normalizes_numeric_and_letter_choices() -> None:
    assert evaluate_answer("【答案】 C\n【解析】...", "3") == ("3", True, "parsed")
    assert evaluate_answer("【答案】 3\n【解析】...", "C") == ("C", True, "parsed")
    assert evaluate_answer("【答案】 A", "3") == ("1", False, "parsed")


def test_answer_parser_supports_japanese_fe_labels() -> None:
    assert evaluate_answer("【答案】ア\n【解析】...", "ア") == ("ア", True, "parsed")
    assert evaluate_answer("【答案】\nエ", "ウ") == ("エ", False, "parsed")
    assert evaluate_answer("正解はイです。", "イ") == ("イ", True, "parsed")


def test_answer_parser_marks_missing_structured_answer_unparsed() -> None:
    assert evaluate_answer("答案是 3，但没有结构化标题", "3") == (None, None, "unparsed")
    assert evaluate_answer("【答案】无法判断", "3") == (None, None, "unparsed")


def test_aggregate_results_reports_modes_categories_and_comparisons() -> None:
    rows = [
        {
            "case_id": "one",
            "category": "diagram",
            "mode": "text",
            "status": "parsed",
            "correct": True,
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "reasoning_tokens": 0,
            "total_tokens": 14,
            "cost_cny": 0.01,
            "api_first_chunk_ms": 10.0,
            "api_first_visible_token_ms": 12.0,
            "api_total_ms": 30.0,
            "end_to_end_ms": 50.0,
        },
        {
            "case_id": "one",
            "category": "diagram",
            "mode": "vision",
            "status": "parsed",
            "correct": False,
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "reasoning_tokens": 3,
            "total_tokens": 28,
            "cost_cny": None,
            "api_first_chunk_ms": 15.0,
            "api_first_visible_token_ms": 25.0,
            "api_total_ms": 40.0,
            "end_to_end_ms": 45.0,
        },
        {
            "case_id": "two",
            "category": "text",
            "mode": "text",
            "status": "unparsed",
            "correct": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
            "cost_cny": None,
            "api_first_chunk_ms": None,
            "api_first_visible_token_ms": None,
            "api_total_ms": None,
            "end_to_end_ms": 5.0,
        },
        {
            "case_id": "two",
            "category": "text",
            "mode": "vision",
            "status": "parsed",
            "correct": True,
            "prompt_tokens": 30,
            "completion_tokens": 6,
            "reasoning_tokens": 2,
            "total_tokens": 36,
            "cost_cny": None,
            "api_first_chunk_ms": 20.0,
            "api_first_visible_token_ms": 22.0,
            "api_total_ms": 50.0,
            "end_to_end_ms": 55.0,
        },
    ]

    summary = aggregate_results(rows)
    assert summary["comparison"] == {
        "text_only_correct": 1,
        "vision_only_correct": 0,
        "both_correct": 0,
        "both_wrong": 0,
        "unparsed": 1,
    }
    assert summary["overall"]["text"]["accuracy"] == 1.0
    assert summary["overall"]["vision"]["accuracy"] == 0.5
    assert summary["by_category"]["diagram"]["text"]["count"] == 1


def test_load_cases_reads_jsonl_and_resolves_paths(tmp_path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image = image_dir / "question.png"
    image.write_bytes(b"png")
    dataset = tmp_path / "benchmark.jsonl"
    dataset.write_text(
        json.dumps({"id": "fe-01", "image": "images/question.png", "year": 2024, "answer": "ア"}) + "\n",
        encoding="utf-8",
    )

    cases = load_cases(dataset)
    assert cases[0].case_id == "fe-01"
    assert cases[0].image == image
    assert cases[0].expected_answer == "ア"
    assert cases[0].year == 2024
    assert cases[0].category == "mixed"


def test_validate_fe_dataset_checks_distribution_and_images(tmp_path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    rows = []
    for index in range(40):
        year = 2024 if index < 20 else 2025
        image_name = f"q{index:02d}.png"
        (image_dir / image_name).write_bytes(b"png")
        rows.append({"id": f"fe-{index:02d}", "image": f"images/{image_name}", "year": year, "answer": "アイウエ"[index % 4]})
    dataset = tmp_path / "benchmark.jsonl"
    dataset.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    assert validate_fe_dataset(dataset) == {"cases": 40, "years": {"2024": 20, "2025": 20}}


def test_load_cases_rejects_duplicate_or_missing_images(tmp_path) -> None:
    dataset = tmp_path / "benchmark.jsonl"
    duplicate = {"id": "same", "image": "missing.png", "year": 2024, "answer": "ア"}
    dataset.write_text("\n".join(json.dumps(duplicate) for _ in range(2)), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="benchmark image is missing"):
        load_cases(dataset)

    image = tmp_path / "ok.png"
    image.write_bytes(b"png")
    dataset.write_text(
        "\n".join(json.dumps({"id": "same", "image": "ok.png", "year": 2024, "answer": "ア"}) for _ in range(2)),
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkError, match="duplicate benchmark case id"):
        load_cases(dataset)
