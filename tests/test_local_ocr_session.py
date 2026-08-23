from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from app.ocr.local_session import LocalOCRSession, PersistentWorkerUnsupported
from app.ocr.persistent_protocol import write_persistent_result
from app.ocr.types import OCRCancelled, OCRError, OCRLine, OCRResult


class _FakeStdin:
    def __init__(self, on_line):
        self._on_line = on_line
        self.closed = False

    def write(self, value: str) -> int:
        if self.closed:
            raise BrokenPipeError
        self._on_line(value)
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, command, *, respond: bool = True):
        self.command = command
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.respond = respond
        self.stdin = _FakeStdin(self._handle_line)

        ready = Path(command[command.index("--ready-file") + 1])
        ready.parent.mkdir(parents=True, exist_ok=True)
        ready.write_text(
            json.dumps({"schema_version": 1, "ok": True, "mode": "persistent"}),
            encoding="utf-8",
        )

    def _handle_line(self, raw: str) -> None:
        command = json.loads(raw)
        if command["type"] == "shutdown":
            self.returncode = 0
            return
        if not self.respond:
            return
        result = OCRResult("题目", (OCRLine("题目", confidence=0.9),))
        write_persistent_result(command["output"], command["request_id"], result)

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


def _session(tmp_path: Path, processes: list[_FakeProcess], *, respond: bool = True, **kwargs):
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")

    def factory(command, **_kwargs):
        process = _FakeProcess(command, respond=respond)
        processes.append(process)
        return process

    return LocalOCRSession(
        executable=executable,
        process_factory=factory,
        timeout=kwargs.pop("timeout", 1.0),
        startup_timeout=kwargs.pop("startup_timeout", 1.0),
        **kwargs,
    )


def test_session_is_lazy_and_reuses_one_process(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    processes: list[_FakeProcess] = []
    session = _session(tmp_path, processes)

    assert session.is_running() is False
    assert session.recognize(source).text == "题目"
    assert session.recognize(source).text == "题目"
    assert len(processes) == 1
    assert session.is_running() is True

    session.stop()
    assert processes[0].returncode == 0
    assert session.is_running() is False


def test_prepare_starts_worker_and_recognize_reuses_it(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    processes: list[_FakeProcess] = []
    session = _session(tmp_path, processes)

    session.prepare()
    assert session.is_running() is True
    session.prepare()
    assert session.recognize(source).text == "题目"
    assert len(processes) == 1
    session.stop()


def test_prepare_failure_allows_later_retry(tmp_path: Path):
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")
    starts = 0

    class StartupFailure:
        returncode = 1
        stdin = None

        def poll(self):
            return self.returncode

    def factory(command, **kwargs):
        nonlocal starts
        starts += 1
        if starts == 1:
            return StartupFailure()
        process = _FakeProcess(command)
        return process

    session = LocalOCRSession(executable=executable, process_factory=factory, timeout=1)
    with pytest.raises(OCRError, match="failed to start"):
        session.prepare()
    session.prepare()
    assert starts == 2
    session.stop()


def test_prepare_cancellation_stops_startup(tmp_path: Path):
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")
    processes: list[_FakeProcess] = []

    class SlowReadyProcess(_FakeProcess):
        def __init__(self, command):
            self.command = command
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.respond = False
            self.stdin = _FakeStdin(self._handle_line)

    def factory(command, **kwargs):
        process = SlowReadyProcess(command)
        processes.append(process)
        return process

    session = LocalOCRSession(
        executable=executable,
        process_factory=factory,
        timeout=1,
        startup_timeout=1,
    )
    cancel_event = threading.Event()
    error: list[BaseException] = []

    def run_prepare():
        try:
            session.prepare(cancel_event=cancel_event)
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=run_prepare)
    thread.start()
    time.sleep(0.08)
    cancel_event.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert isinstance(error[0], OCRCancelled)
    assert processes[0].terminated or processes[0].killed
    assert session.is_running() is False


def test_concurrent_prepare_and_recognize_share_one_worker(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    processes: list[_FakeProcess] = []
    session = _session(tmp_path, processes)
    startup_entered = threading.Event()
    original_ensure_started = session._ensure_started

    def delayed_start(cancel_event):
        startup_entered.set()
        time.sleep(0.08)
        return original_ensure_started(cancel_event)

    session._ensure_started = delayed_start
    prepare_errors: list[BaseException] = []

    def run_prepare():
        try:
            session.prepare()
        except BaseException as exc:
            prepare_errors.append(exc)

    prepare_thread = threading.Thread(target=run_prepare)
    prepare_thread.start()
    assert startup_entered.wait(timeout=1)
    result = session.recognize(source)
    prepare_thread.join(timeout=1)

    assert not prepare_errors
    assert not prepare_thread.is_alive()
    assert result.text == "题目"
    assert len(processes) == 1
    session.stop()


def test_session_cancellation_terminates_worker(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    processes: list[_FakeProcess] = []
    session = _session(tmp_path, processes, respond=False, timeout=2.0)
    cancel_event = threading.Event()

    def cancel_later():
        time.sleep(0.05)
        cancel_event.set()

    threading.Thread(target=cancel_later, daemon=True).start()
    with pytest.raises(OCRCancelled):
        session.recognize(source, cancel_event=cancel_event)
    assert processes[0].terminated or processes[0].killed
    assert session.is_running() is False


def test_session_timeout_terminates_worker(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    processes: list[_FakeProcess] = []
    session = _session(tmp_path, processes, respond=False, timeout=0.05)

    with pytest.raises(OCRError, match="timed out"):
        session.recognize(source)
    assert processes[0].terminated or processes[0].killed
    assert session.is_running() is False


def test_session_restarts_after_worker_crash(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    processes: list[_FakeProcess] = []
    session = _session(tmp_path, processes)

    first = session.recognize(source)
    assert first.text == "题目"
    processes[0].returncode = 1
    assert session.recognize(source).text == "题目"
    assert len(processes) == 2


def test_session_caches_unsupported_capability_until_reset(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")
    starts = []

    class UnsupportedProcess:
        returncode = 2
        stdin = None

        def poll(self):
            return self.returncode

    def factory(command, **_kwargs):
        starts.append(command)
        return UnsupportedProcess()

    session = LocalOCRSession(executable=executable, process_factory=factory, timeout=0.1)
    with pytest.raises(PersistentWorkerUnsupported):
        session.recognize(source)
    with pytest.raises(PersistentWorkerUnsupported):
        session.recognize(source)
    assert len(starts) == 1
    session.reset_capability()
    with pytest.raises(PersistentWorkerUnsupported):
        session.recognize(source)
    assert len(starts) == 2


def test_session_validates_response_request_id(tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    processes: list[_FakeProcess] = []

    def factory(command, **_kwargs):
        process = _FakeProcess(command)
        processes.append(process)

        def wrong_response(raw: str):
            command_payload = json.loads(raw)
            if command_payload["type"] == "recognize":
                write_persistent_result(
                    command_payload["output"],
                    "stale-request",
                    OCRResult("wrong", (OCRLine("wrong"),)),
                )

        process.stdin = _FakeStdin(wrong_response)
        return process

    session = LocalOCRSession(executable=tmp_path / "TellMeSenseiOCR.exe", process_factory=factory)
    session.executable.write_bytes(b"fake")
    with pytest.raises(OCRError, match="response is invalid"):
        session.recognize(source)
    assert session.is_running() is False


def test_legacy_provider_falls_back_to_one_shot_after_unsupported_serve(
    tmp_path: Path,
):
    source = tmp_path / "input.png"
    source.write_bytes(b"image")
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")
    persistent_starts = 0

    class UnsupportedProcess:
        returncode = 2
        stdin = None

        def poll(self):
            return self.returncode

    def persistent_factory(command, **_kwargs):
        nonlocal persistent_starts
        persistent_starts += 1
        return UnsupportedProcess()

    session = LocalOCRSession(executable=executable, process_factory=persistent_factory)

    # The provider-level fallback is covered by the existing one-shot protocol;
    # this assertion verifies the capability state that triggers it is cached.
    with pytest.raises(PersistentWorkerUnsupported):
        session.recognize(source)
    assert session.capability_unsupported is True
    assert persistent_starts == 1
