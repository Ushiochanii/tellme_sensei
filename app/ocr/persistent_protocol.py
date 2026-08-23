"""Validation and serialization for the persistent Local OCR sidecar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ocr.types import OCRError, OCRResult
from app.ocr.worker_protocol import SCHEMA_VERSION, parse_result, write_payload_atomic


class PersistentProtocolError(ValueError):
    """Raised when a persistent worker command or response is invalid."""


def parse_command(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise PersistentProtocolError("persistent OCR command must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise PersistentProtocolError("unsupported persistent OCR command schema")
    command_type = payload.get("type")
    if command_type == "shutdown":
        return {"type": "shutdown"}
    if command_type != "recognize":
        raise PersistentProtocolError("unsupported persistent OCR command type")
    request_id = _required_string(payload, "request_id")
    input_path = _absolute_path(payload, "input")
    output_path = _absolute_path(payload, "output")
    return {
        "type": "recognize",
        "request_id": request_id,
        "input": input_path,
        "output": output_path,
    }


def persistent_result_payload(request_id: str, result: OCRResult) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
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


def persistent_error_payload(request_id: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "ok": False,
        "error": str(message),
    }


def write_persistent_result(path: str | Path, request_id: str, result: OCRResult) -> None:
    write_payload_atomic(path, persistent_result_payload(request_id, result))


def write_persistent_error(path: str | Path, request_id: str, message: str) -> None:
    write_payload_atomic(path, persistent_error_payload(request_id, message))


def read_persistent_response(path: str | Path, expected_request_id: str) -> OCRResult:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PersistentProtocolError("persistent OCR response is missing or malformed") from exc
    if not isinstance(payload, dict):
        raise PersistentProtocolError("persistent OCR response must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise PersistentProtocolError("unsupported persistent OCR response schema")
    if payload.get("request_id") != expected_request_id:
        raise PersistentProtocolError("persistent OCR response request_id mismatch")
    try:
        return parse_result(payload)
    except OCRError:
        raise
    except Exception as exc:
        raise PersistentProtocolError("persistent OCR response is invalid") from exc


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PersistentProtocolError(f"persistent OCR command field is invalid: {field}")
    return value.strip()


def _absolute_path(payload: dict[str, Any], field: str) -> str:
    value = _required_string(payload, field)
    if not Path(value).is_absolute():
        raise PersistentProtocolError(f"persistent OCR path must be absolute: {field}")
    return value
