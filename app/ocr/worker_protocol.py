"""Versioned JSON protocol shared by the local OCR worker and its client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ocr.types import OCRError, OCRLine, OCRResult

SCHEMA_VERSION = 1


def result_payload(result: OCRResult) -> dict[str, Any]:
    """Serialize a normalized OCR result into the stable wire schema."""

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "text": result.text,
        "lines": [
            {
                "text": line.text,
                "confidence": line.confidence,
                "top": line.top,
                "left": line.left,
            }
            for line in result.lines
        ],
    }


def error_payload(message: str) -> dict[str, Any]:
    """Serialize a user-facing worker error without traceback details."""

    return {"schema_version": SCHEMA_VERSION, "ok": False, "error": str(message)}


def write_payload(path: str | Path, payload: dict[str, Any]) -> None:
    """Write one complete protocol document as UTF-8 JSON."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def read_result(path: str | Path) -> OCRResult:
    """Read and strictly validate a worker result document."""

    return parse_result(_read_document(path))


def read_error_message(path: str | Path) -> str | None:
    """Return a validated worker error message, or None for other payloads."""

    try:
        payload = _read_document(path)
    except OCRError:
        return None
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("ok") is not False:
        return None
    message = payload.get("error")
    if not isinstance(message, str) or not message.strip():
        return None
    return message.strip()


def _read_document(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OCRError("本地 OCR 返回结果缺失或不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise OCRError("本地 OCR 返回结果格式无效。")
    return payload


def parse_result(payload: Any) -> OCRResult:
    """Validate a decoded protocol payload and return the public OCR type."""

    if not isinstance(payload, dict):
        raise OCRError("本地 OCR 返回结果格式无效。")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise OCRError("本地 OCR 返回结果版本不受支持。")
    if not isinstance(payload.get("ok"), bool):
        raise OCRError("本地 OCR 返回结果缺少有效状态。")
    if not payload["ok"]:
        message = payload.get("error")
        if not isinstance(message, str) or not message.strip():
            raise OCRError("本地 OCR 返回了无效错误信息。")
        raise OCRError(message.strip())

    text = payload.get("text")
    raw_lines = payload.get("lines")
    if not isinstance(text, str) or not isinstance(raw_lines, list):
        raise OCRError("本地 OCR 成功结果格式无效。")

    lines: list[OCRLine] = []
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict) or not isinstance(raw_line.get("text"), str):
            raise OCRError("本地 OCR 行结果格式无效。")
        confidence = _number_or_none(raw_line.get("confidence"), "confidence")
        top = _number(raw_line.get("top", 0.0), "top")
        left = _number(raw_line.get("left", 0.0), "left")
        lines.append(
            OCRLine(
                text=raw_line["text"],
                confidence=confidence,
                top=top,
                left=left,
            )
        )
    return OCRResult(text=text, lines=tuple(lines))


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OCRError(f"本地 OCR 字段 {field} 格式无效。")
    return float(value)


def _number_or_none(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _number(value, field)
