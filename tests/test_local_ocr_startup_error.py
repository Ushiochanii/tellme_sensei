from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ocr.local_session import LocalOCRSession
from app.ocr.types import OCRError


class _ReadyProcess:
    def __init__(self, command, payload: object) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.stdin = None

        ready = Path(command[command.index("--ready-file") + 1])
        ready.parent.mkdir(parents=True, exist_ok=True)
        ready.write_text(json.dumps(payload), encoding="utf-8")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


def _session_for_payload(tmp_path: Path, payload: object, processes: list[_ReadyProcess]) -> LocalOCRSession:
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")

    def factory(command, **_kwargs):
        process = _ReadyProcess(command, payload)
        processes.append(process)
        return process

    return LocalOCRSession(
        executable=executable,
        process_factory=factory,
        startup_timeout=1.0,
    )


def test_startup_error_ready_payload_surfaces_worker_error(tmp_path: Path) -> None:
    processes: list[_ReadyProcess] = []
    session = _session_for_payload(
        tmp_path,
        {"schema_version": 1, "ok": False, "error": "PaddleOCR model initialization failed"},
        processes,
    )

    with pytest.raises(OCRError, match="PaddleOCR model initialization failed"):
        session.prepare()

    assert processes[0].terminated or processes[0].killed
    assert session.is_running() is False


def test_malformed_ready_payload_keeps_generic_invalid_response(tmp_path: Path) -> None:
    processes: list[_ReadyProcess] = []
    session = _session_for_payload(
        tmp_path,
        {"schema_version": 99, "ok": False, "error": "do not surface this"},
        processes,
    )

    with pytest.raises(OCRError, match="persistent ready response is invalid"):
        session.prepare()

    assert processes[0].terminated or processes[0].killed
    assert session.is_running() is False
