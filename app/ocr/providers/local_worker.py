"""OCR provider that delegates recognition to the external local worker."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.ocr.local_runtime import worker_executable_candidates, worker_script_path
from app.ocr.types import OCRCancelled, OCRError, OCRResult
from app.ocr.worker_protocol import read_error_message, read_result

ProcessFactory = Callable[..., Any]


class LocalOCRProvider:
    """Run PaddleOCR in a separate process and return its validated result."""

    def __init__(
        self,
        language: str = "japan",
        executable: str | Path | None = None,
        timeout: float = 60.0,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.language = language
        self.executable = Path(executable) if executable is not None else None
        self.timeout = timeout
        self._process_factory = process_factory or subprocess.Popen

    def recognize(
        self,
        image: Any,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        """Save the input safely, invoke the worker, and validate its response."""

        with tempfile.TemporaryDirectory(prefix="tellme-sensei-ocr-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = self._prepare_input(image, temp_path / "input.png")
            output_path = temp_path / "result.json"
            command = self._command(input_path, output_path)
            process = self._start_process(command)
            try:
                self._wait_for_process(process, cancel_event)
            except subprocess.TimeoutExpired as exc:
                self._stop_process(process)
                raise OCRError("本地 OCR 请求超时。") from exc

            if cancel_event is not None and cancel_event.is_set():
                raise OCRCancelled("本地 OCR 已取消。")

            if process.returncode != 0:
                if output_path.is_file():
                    try:
                        # A non-zero exit is always failure. This parse only
                        # distinguishes an error document from success/malformed data.
                        read_result(output_path)
                    except OCRError:
                        message = read_error_message(output_path)
                        if message is not None:
                            raise OCRError(message)
                raise OCRError("本地 OCR 进程执行失败。")
            if not output_path.is_file():
                raise OCRError("本地 OCR 未返回结果文件。")
            return read_result(output_path)

    def _wait_for_process(
        self,
        process: Any,
        cancel_event: threading.Event | None,
    ) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self._stop_process(process)
                raise OCRCancelled("本地 OCR 已取消。")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired([], self.timeout)
            try:
                process.communicate(timeout=min(0.2, remaining))
                return
            except subprocess.TimeoutExpired:
                continue

    def _command(self, input_path: Path, output_path: Path) -> list[str]:
        if self.executable is not None:
            if not self.executable.is_file():
                raise OCRError(f"找不到本地 OCR 组件：{self.executable}")
            return self._arguments(str(self.executable), input_path, output_path)

        for candidate in worker_executable_candidates():
            if candidate.is_file():
                return self._arguments(str(candidate), input_path, output_path)

        if getattr(sys, "frozen", False):
            raise OCRError("找不到本地 OCR 组件，请确认 TellMeSenseiOCR 已安装。")

        script = worker_script_path()
        if not script.is_file():
            raise OCRError(f"找不到本地 OCR worker：{script}")
        return self._arguments(sys.executable, input_path, output_path, script=script)

    def _arguments(
        self,
        executable: str,
        input_path: Path,
        output_path: Path,
        *,
        script: Path | None = None,
    ) -> list[str]:
        command = [executable]
        if script is not None:
            command.append(str(script))
        command.extend(
            [
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--language",
                self.language,
            ]
        )
        return command

    def _start_process(self, command: list[str]) -> Any:
        try:
            return self._process_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                text=True,
            )
        except FileNotFoundError as exc:
            raise OCRError("找不到本地 OCR 执行文件。") from exc
        except OSError as exc:
            raise OCRError("无法启动本地 OCR 进程。") from exc

    @staticmethod
    def _stop_process(process: Any) -> None:
        try:
            process.kill()
            process.communicate()
        except (OSError, subprocess.SubprocessError):
            pass

    @staticmethod
    def _prepare_input(image: Any, target: Path) -> Path:
        if isinstance(image, (str, Path)):
            source = Path(image)
            if not source.is_file():
                raise OCRError(f"图片文件不存在：{source}")
            return source

        image_copy = image.copy() if hasattr(image, "copy") else image
        save = getattr(image_copy, "save", None)
        if not callable(save):
            raise OCRError("本地 OCR 只支持图片路径或可保存为 PNG 的图片对象。")
        try:
            saved = save(str(target), "PNG")
        except TypeError:
            saved = save(str(target))
        if saved is False or not target.is_file():
            raise OCRError("无法准备本地 OCR 输入图片。")
        return target
