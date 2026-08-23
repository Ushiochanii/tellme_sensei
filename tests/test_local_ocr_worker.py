from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from app.config import AppConfig
from app.ocr.factory import create_local_ocr_provider
from app.ocr import local_runtime
from app.ocr.providers.local_worker import LocalOCRProvider
from app.ocr.types import OCRCancelled, OCRError, OCRLine, OCRResult
from app.ocr.worker_protocol import error_payload, parse_result, result_payload
from app.local_ocr import worker_main


def test_worker_success_serialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "result.json"
    input_path.write_bytes(b"image")

    class FakeProvider:
        def __init__(self, language: str) -> None:
            assert language == "japan"

        def recognize(self, image: Path) -> OCRResult:
            assert image == input_path
            return OCRResult("题目", (OCRLine("题目", 0.96, 12.0, 20.0),))

    monkeypatch.setattr(worker_main, "PaddleOCRProvider", FakeProvider)

    assert worker_main.main(
        ["--input", str(input_path), "--output", str(output_path), "--language", "japan"]
    ) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "ok": True,
        "text": "题目",
        "lines": [{"text": "题目", "confidence": 0.96, "top": 12.0, "left": 20.0}],
    }


def test_worker_error_serialization_has_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "result.json"
    input_path.write_bytes(b"image")

    class FailingProvider:
        def __init__(self, language: str) -> None:
            pass

        def recognize(self, image: Path) -> OCRResult:
            raise OCRError("PaddleOCR unavailable")

    monkeypatch.setattr(worker_main, "PaddleOCRProvider", FailingProvider)

    assert worker_main.main(["--input", str(input_path), "--output", str(output_path)]) == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "ok": False, "error": "PaddleOCR unavailable"}
    assert "Traceback" not in output_path.read_text(encoding="utf-8")


def test_protocol_rejects_malformed_payloads() -> None:
    with pytest.raises(OCRError):
        parse_result({"schema_version": 2, "ok": True, "text": "", "lines": []})
    with pytest.raises(OCRError):
        parse_result({"schema_version": 1, "ok": True, "text": "", "lines": "bad"})
    with pytest.raises(OCRError):
        parse_result({"schema_version": 1, "ok": True, "text": "", "lines": [{"text": 1}]})
    with pytest.raises(OCRError):
        parse_result({"schema_version": 1, "ok": False, "error": ""})


class _FakeProcess:
    def __init__(self, command: list[str], *, returncode: int = 0, payload: dict | None = None, timeout: bool = False, **kwargs: object) -> None:
        self.command = command
        self.returncode = returncode
        self.payload = payload
        self.timeout = timeout
        self.kwargs = kwargs
        self.killed = False

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired(self.command, timeout)
        if self.payload is not None:
            output = Path(self.command[self.command.index("--output") + 1])
            output.write_text(json.dumps(self.payload), encoding="utf-8")
        return "", ""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _provider_with_fake_process(
    tmp_path: Path,
    process_kwargs: dict,
) -> tuple[LocalOCRProvider, list[_FakeProcess]]:
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")
    processes: list[_FakeProcess] = []

    def factory(command: list[str], **kwargs: object) -> _FakeProcess:
        process = _FakeProcess(command, **process_kwargs, **kwargs)
        processes.append(process)
        return process

    return LocalOCRProvider(executable=executable, process_factory=factory), processes


def test_local_provider_returns_result_and_cleans_temp_files(tmp_path: Path) -> None:
    payload = result_payload(OCRResult("识别", (OCRLine("识别", 0.9),)))
    provider, processes = _provider_with_fake_process(tmp_path, {"payload": payload})
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")

    result = provider.recognize(input_path)

    assert result.text == "识别"
    assert processes[0].kwargs["shell"] is False
    output_path = Path(processes[0].command[processes[0].command.index("--output") + 1])
    assert not output_path.parent.exists()


def test_local_provider_cleans_qimage_like_input(tmp_path: Path) -> None:
    payload = result_payload(OCRResult("识别", (OCRLine("识别"),)))
    provider, processes = _provider_with_fake_process(tmp_path, {"payload": payload})

    class FakeImage:
        def copy(self) -> "FakeImage":
            return self

        def save(self, path: str, image_format: str) -> bool:
            assert image_format == "PNG"
            Path(path).write_bytes(b"png")
            return True

    assert provider.recognize(FakeImage()).text == "识别"
    input_path = Path(processes[0].command[processes[0].command.index("--input") + 1])
    assert not input_path.exists()


def test_local_provider_rejects_missing_executable(tmp_path: Path) -> None:
    provider = LocalOCRProvider(executable=tmp_path / "missing.exe")
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    with pytest.raises(OCRError, match="找不到本地 OCR 组件"):
        provider.recognize(source)


def test_local_provider_propagates_nonzero_worker_error_payload(tmp_path: Path) -> None:
    provider, _ = _provider_with_fake_process(
        tmp_path,
        {"returncode": 3, "payload": error_payload("Paddle model failed")},
    )
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")
    with pytest.raises(OCRError, match="Paddle model failed"):
        provider.recognize(input_path)


def test_local_provider_handles_nonzero_worker_without_result(tmp_path: Path) -> None:
    provider, _ = _provider_with_fake_process(tmp_path, {"returncode": 3})
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")
    with pytest.raises(OCRError, match="进程执行失败"):
        provider.recognize(input_path)


def test_local_provider_handles_nonzero_worker_with_malformed_result(tmp_path: Path) -> None:
    provider, _ = _provider_with_fake_process(
        tmp_path,
        {"returncode": 3, "payload": {"schema_version": 1, "ok": "nope"}},
    )
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")
    with pytest.raises(OCRError, match="进程执行失败"):
        provider.recognize(input_path)


def test_local_provider_rejects_nonzero_worker_success_payload(tmp_path: Path) -> None:
    provider, _ = _provider_with_fake_process(
        tmp_path,
        {"returncode": 3, "payload": result_payload(OCRResult("unexpected", ()))},
    )
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")
    with pytest.raises(OCRError, match="进程执行失败"):
        provider.recognize(input_path)


def test_worker_error_payload_is_written_when_stderr_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "result.json"
    input_path.write_bytes(b"image")

    class FailingProvider:
        def __init__(self, language: str) -> None:
            pass

        def recognize(self, image: Path) -> OCRResult:
            raise OCRError("worker failure")

    monkeypatch.setattr(worker_main, "PaddleOCRProvider", FailingProvider)
    monkeypatch.setattr(worker_main.sys, "stderr", None)

    assert worker_main.main(["--input", str(input_path), "--output", str(output_path)]) == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "ok": False,
        "error": "worker failure",
    }


def test_local_provider_kills_worker_on_timeout(tmp_path: Path) -> None:
    provider, processes = _provider_with_fake_process(tmp_path, {"timeout": True})
    provider.timeout = 0.01
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")
    with pytest.raises(OCRError, match="请求超时"):
        provider.recognize(input_path)
    assert processes[0].killed is True


def test_local_component_versioned_user_path_is_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(local_runtime, "user_runtime_directory", lambda: runtime)
    monkeypatch.setattr(local_runtime.sys, "executable", str(tmp_path / "python.exe"))

    candidates = local_runtime.worker_executable_candidates()

    assert candidates[0] == (
        runtime / "components" / "local-ocr" / "1.0.0" / "TellMeSenseiOCR.exe"
    )


def test_local_provider_kills_worker_when_cancelled(tmp_path: Path) -> None:
    cancel_event = threading.Event()
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")
    processes: list[object] = []

    class CancelAwareProcess:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: object) -> None:
            self.command = command
            self.killed = False
            processes.append(self)

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            if not self.killed:
                cancel_event.set()
                raise subprocess.TimeoutExpired(self.command, timeout)
            return "", ""

        def kill(self) -> None:
            self.killed = True

    def factory(command: list[str], **kwargs: object) -> CancelAwareProcess:
        return CancelAwareProcess(command, **kwargs)

    provider = LocalOCRProvider(executable=executable, process_factory=factory)
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")

    with pytest.raises(OCRCancelled):
        provider.recognize(input_path, cancel_event=cancel_event)
    assert processes[0].killed is True


def test_local_provider_rejects_malformed_worker_result(tmp_path: Path) -> None:
    provider, _ = _provider_with_fake_process(tmp_path, {"payload": {"ok": True}})
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"source")
    with pytest.raises(OCRError, match="格式无效|缺失|版本不受支持"):
        provider.recognize(input_path)


def test_factory_exposes_local_provider_without_changing_default() -> None:
    config = AppConfig(api_key="test-key")
    provider = create_local_ocr_provider(config)
    assert isinstance(provider, LocalOCRProvider)
