"""Lazy, single-request-at-a-time session for the persistent Local OCR worker."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from app.ocr.local_runtime import worker_executable_candidates, worker_script_path
from app.ocr.persistent_protocol import (
    PersistentProtocolError,
    read_persistent_response,
)
from app.ocr.types import OCRCancelled, OCRError, OCRResult

logger = logging.getLogger(__name__)
ProcessFactory = Callable[..., Any]


class PersistentWorkerUnsupported(OCRError):
    """The installed Local OCR component predates persistent serve mode."""


class LocalOCRSession:
    """Own one lazy persistent Local OCR process for the application lifetime."""

    def __init__(
        self,
        executable: str | Path | None = None,
        language: str = "japan",
        timeout: float = 60.0,
        startup_timeout: float | None = None,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.executable = Path(executable) if executable is not None else None
        self.language = language
        self.timeout = timeout
        self.startup_timeout = startup_timeout or timeout
        self._process_factory = process_factory or subprocess.Popen
        self._request_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process: Any | None = None
        self._ready_directory: tempfile.TemporaryDirectory[str] | None = None
        self._in_flight = False
        self._unsupported = False

    @property
    def capability_unsupported(self) -> bool:
        with self._state_lock:
            return self._unsupported

    def is_running(self) -> bool:
        with self._state_lock:
            process = self._process
        return process is not None and process.poll() is None

    def is_busy(self) -> bool:
        with self._state_lock:
            return self._in_flight

    def reset_capability(self) -> None:
        """Allow a newly installed component to retry serve mode."""

        with self._state_lock:
            self._unsupported = False

    def recognize(
        self,
        input_path: str | Path,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        """Send one request and wait for its validated response file."""

        source = Path(input_path).resolve()
        if not source.is_file():
            raise OCRError(f"图片文件不存在：{source}")
        if cancel_event is not None and cancel_event.is_set():
            raise OCRCancelled("Local OCR cancelled")

        with self._request_lock:
            with self._state_lock:
                self._in_flight = True
            try:
                self._ensure_started(cancel_event)
                request_id = uuid.uuid4().hex
                with tempfile.TemporaryDirectory(prefix="tellme-sensei-ocr-response-") as raw_dir:
                    response_path = Path(raw_dir) / "response.json"
                    self._send_command(request_id, source, response_path)
                    return self._wait_for_response(request_id, response_path, cancel_event)
            finally:
                with self._state_lock:
                    self._in_flight = False

    def stop(self) -> None:
        """Stop the worker, idempotently, without leaving an orphan process."""

        with self._state_lock:
            process = self._process
            busy = self._in_flight
        if process is None:
            return
        if not busy:
            self._send_shutdown(process)
            if not self._wait_for_exit(process, 0.5):
                self._terminate_process(process)
        else:
            self._terminate_process(process)
        self._clear_process(process)

    shutdown = stop

    def _ensure_started(self, cancel_event: threading.Event | None) -> None:
        with self._state_lock:
            if self._unsupported:
                raise PersistentWorkerUnsupported(
                    "Local OCR component does not support persistent mode"
                )
            process = self._process
        if process is not None:
            if process.poll() is None:
                return
            self._clear_process(process)

        ready_directory = tempfile.TemporaryDirectory(prefix="tellme-sensei-ocr-ready-")
        ready_path = Path(ready_directory.name) / "ready.json"
        with self._state_lock:
            self._ready_directory = ready_directory
        try:
            command = self._serve_command()
        except Exception:
            with self._state_lock:
                self._ready_directory = None
            ready_directory.cleanup()
            raise
        try:
            process = self._process_factory(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            with self._state_lock:
                self._ready_directory = None
            ready_directory.cleanup()
            raise OCRError("找不到本地 OCR 执行文件。") from exc
        except OSError as exc:
            with self._state_lock:
                self._ready_directory = None
            ready_directory.cleanup()
            raise OCRError("无法启动本地 OCR 进程。") from exc

        with self._state_lock:
            self._process = process
        deadline = time.monotonic() + self.startup_timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self._terminate_process(process)
                self._clear_process(process)
                raise OCRCancelled("Local OCR cancelled")
            if ready_path.is_file():
                try:
                    payload = json.loads(ready_path.read_text(encoding="utf-8"))
                    if (
                        payload.get("schema_version") == 1
                        and payload.get("ok") is True
                        and payload.get("mode") == "persistent"
                    ):
                        return
                except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
                    pass
                self._terminate_process(process)
                self._clear_process(process)
                raise OCRError("Local OCR persistent ready response is invalid.")
            if process.poll() is not None:
                exit_code = process.returncode
                self._clear_process(process)
                if exit_code == 2:
                    with self._state_lock:
                        self._unsupported = True
                    raise PersistentWorkerUnsupported(
                        "Local OCR component does not support persistent mode."
                    )
                raise OCRError("Local OCR persistent worker failed to start.")
            if time.monotonic() >= deadline:
                self._terminate_process(process)
                self._clear_process(process)
                raise OCRError("Local OCR persistent worker startup timed out.")
            time.sleep(0.05)

    def _send_command(self, request_id: str, input_path: Path, response_path: Path) -> None:
        with self._state_lock:
            process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            self._clear_process(process)
            raise OCRError("Local OCR persistent worker is not running.")
        command = {
            "schema_version": 1,
            "type": "recognize",
            "request_id": request_id,
            "input": str(input_path.resolve()),
            "output": str(response_path.resolve()),
        }
        try:
            process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._clear_process(process)
            raise OCRError("Local OCR persistent worker input failed.") from exc

    def _wait_for_response(
        self,
        request_id: str,
        response_path: Path,
        cancel_event: threading.Event | None,
    ) -> OCRResult:
        deadline = time.monotonic() + self.timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self.stop()
                raise OCRCancelled("Local OCR cancelled")
            with self._state_lock:
                process = self._process
            if response_path.is_file():
                try:
                    return read_persistent_response(response_path, request_id)
                except PersistentProtocolError as exc:
                    self._terminate_process(process)
                    self._clear_process(process)
                    raise OCRError("Local OCR persistent response is invalid.") from exc
            if process is None or process.poll() is not None:
                self._clear_process(process)
                raise OCRError("Local OCR persistent worker exited unexpectedly.")
            if time.monotonic() >= deadline:
                self.stop()
                raise OCRError("Local OCR persistent request timed out.")
            time.sleep(0.05)

    def _serve_command(self) -> list[str]:
        if self.executable is not None:
            if not self.executable.is_file():
                raise OCRError(f"找不到本地 OCR 组件：{self.executable}")
            executable = str(self.executable.resolve())
            return [executable, "--serve", "--ready-file", self._ready_placeholder(), "--language", self.language]

        for candidate in worker_executable_candidates():
            if candidate.is_file():
                return [
                    str(candidate.resolve()),
                    "--serve",
                    "--ready-file",
                    self._ready_placeholder(),
                    "--language",
                    self.language,
                ]
        if getattr(sys, "frozen", False):
            raise OCRError("找不到本地 OCR 组件，请先安装 Local OCR。")
        script = worker_script_path()
        if not script.is_file():
            raise OCRError("找不到本地 OCR worker。")
        return [
            sys.executable,
            str(script.resolve()),
            "--serve",
            "--ready-file",
            self._ready_placeholder(),
            "--language",
            self.language,
        ]

    def _ready_placeholder(self) -> str:
        with self._state_lock:
            directory = self._ready_directory
        if directory is None:
            # This is only a defensive fallback; normal startup creates the
            # ready directory before constructing the command.
            return "ready.json"
        return str(Path(directory.name) / "ready.json")

    @staticmethod
    def _send_shutdown(process: Any) -> None:
        try:
            if process.stdin is not None:
                process.stdin.write(json.dumps({"schema_version": 1, "type": "shutdown"}) + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    @staticmethod
    def _wait_for_exit(process: Any, timeout: float) -> bool:
        try:
            process.wait(timeout=timeout)
            return True
        except (subprocess.TimeoutExpired, AttributeError):
            return process.poll() is not None

    @staticmethod
    def _terminate_process(process: Any) -> None:
        try:
            process.terminate()
            if not LocalOCRSession._wait_for_exit(process, 0.5):
                process.kill()
                LocalOCRSession._wait_for_exit(process, 0.5)
        except (OSError, subprocess.SubprocessError, AttributeError):
            try:
                process.kill()
            except (OSError, AttributeError):
                pass

    def _clear_process(self, process: Any | None) -> None:
        with self._state_lock:
            if process is not None and self._process is not process:
                return
            self._process = None
            ready_directory = self._ready_directory
            self._ready_directory = None
        if ready_directory is not None:
            ready_directory.cleanup()
