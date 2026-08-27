from __future__ import annotations

import json
import io
import subprocess
import threading
from pathlib import Path

import pytest

from app.config import AppConfig
from app.ocr.factory import create_local_ocr_provider
from app.ocr import local_runtime
from app.ocr.local_session import LocalOCRSession
from app.ocr.providers.local_worker import LocalOCRProvider
from app.ocr.profiling import read_profile
from app.ocr.types import OCRCancelled, OCRError, OCRLine, OCRResult
from app.ocr.worker_protocol import error_payload, parse_result, result_payload
from app.local_ocr import worker_main
from app.local_ocr.version import current_local_ocr_version
from app.local_ocr.platform import current_spec, spec_for_manifest


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


def test_worker_serve_initializes_provider_once_and_reuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.png"
    input_path.write_bytes(b"image")
    ready_path = tmp_path / "ready.json"
    response_one = tmp_path / "response-one.json"
    response_two = tmp_path / "response-two.json"
    commands = [
        {
            "schema_version": 1,
            "type": "recognize",
            "request_id": "request-1",
            "input": str(input_path.resolve()),
            "output": str(response_one.resolve()),
        },
        {
            "schema_version": 1,
            "type": "recognize",
            "request_id": "request-2",
            "input": str(input_path.resolve()),
            "output": str(response_two.resolve()),
        },
        {"schema_version": 1, "type": "shutdown"},
    ]

    class FakeProvider:
        instances = []

        def __init__(self, language: str) -> None:
            self.language = language
            self.initialize_calls = 0
            self.recognize_calls = 0
            self.__class__.instances.append(self)

        def initialize(self) -> None:
            self.initialize_calls += 1

        def recognize(self, image: Path) -> OCRResult:
            self.recognize_calls += 1
            assert image == input_path
            return OCRResult("题目", (OCRLine("题目"),))

    monkeypatch.setattr(worker_main, "PaddleOCRProvider", FakeProvider)
    monkeypatch.setattr(
        worker_main,
        "sys",
        type("FakeSys", (), {"stdin": io.StringIO("\n".join(json.dumps(c) for c in commands) + "\n"), "stderr": None})(),
    )

    args = worker_main.build_parser().parse_args(
        ["--serve", "--ready-file", str(ready_path), "--language", "japan"]
    )
    assert worker_main._serve(args) == 0
    assert len(FakeProvider.instances) == 1
    assert FakeProvider.instances[0].initialize_calls == 1
    assert FakeProvider.instances[0].recognize_calls == 2
    assert json.loads(ready_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "ok": True,
        "mode": "persistent",
    }
    assert json.loads(response_one.read_text(encoding="utf-8"))["request_id"] == "request-1"
    assert json.loads(response_two.read_text(encoding="utf-8"))["request_id"] == "request-2"


def test_worker_passes_component_model_directories_to_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_root = tmp_path / "models"
    for kind in ("det", "rec"):
        model_dir = model_root / kind / f"{kind}-model"
        model_dir.mkdir(parents=True)
        (model_dir / "inference.pdmodel").write_bytes(b"model")
        (model_dir / "inference.pdiparams").write_bytes(b"params")

    received: list[tuple[Path, Path]] = []

    class FakeProvider:
        def __init__(self, language: str, det_model_dir=None, rec_model_dir=None) -> None:
            assert language == "japan"
            received.append((Path(det_model_dir), Path(rec_model_dir)))

        def initialize(self) -> None:
            pass

    monkeypatch.setattr(worker_main, "PaddleOCRProvider", FakeProvider)
    ready = tmp_path / "ready.json"
    monkeypatch.setattr(
        worker_main,
        "sys",
        type("FakeSys", (), {"stdin": io.StringIO('{"schema_version": 1, "type": "shutdown"}\n'), "stderr": None})(),
    )
    args = worker_main.build_parser().parse_args(
        ["--serve", "--ready-file", str(ready), "--model-root", str(model_root)]
    )
    assert worker_main._serve(args) == 0
    assert received == [
        (model_root / "det" / "det-model", model_root / "rec" / "rec-model")
    ]


def test_worker_model_root_missing_fails_without_fallback(tmp_path: Path) -> None:
    assert worker_main.main(["--smoke", "--model-root", str(tmp_path / "missing")]) == 1


def test_worker_serve_writes_error_response_for_ocr_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.png"
    input_path.write_bytes(b"image")
    ready_path = tmp_path / "ready.json"
    response_path = tmp_path / "response.json"

    class FailingProvider:
        def __init__(self, language: str) -> None:
            pass

        def initialize(self) -> None:
            pass

        def recognize(self, image: Path) -> OCRResult:
            raise OCRError("Local OCR failed")

    monkeypatch.setattr(worker_main, "PaddleOCRProvider", FailingProvider)
    monkeypatch.setattr(
        worker_main,
        "sys",
        type(
            "FakeSys",
            (),
            {
                "stdin": io.StringIO(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "type": "recognize",
                            "request_id": "request-1",
                            "input": str(input_path.resolve()),
                            "output": str(response_path.resolve()),
                        }
                    )
                    + "\n"
                ),
                "stderr": None,
            },
        )(),
    )
    args = worker_main.build_parser().parse_args(
        ["--serve", "--ready-file", str(ready_path)]
    )
    assert worker_main._serve(args) == 0
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    assert payload["request_id"] == "request-1"
    assert payload["ok"] is False
    assert payload["error"] == "Local OCR failed"


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


def test_worker_profile_output_is_separate_from_result_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "result.json"
    profile_path = tmp_path / "profile.json"
    input_path.write_bytes(b"image")

    class ProfiledProvider:
        def __init__(self, language: str) -> None:
            assert language == "japan"
            self.calls = 0

        def recognize_profiled(self, image: Path):
            self.calls += 1
            return OCRResult("secret OCR text", (OCRLine("secret OCR text"),)), {
                "engine_init_ms": 10.0 if self.calls == 1 else 0.0,
                "input_prepare_ms": 1.0,
                "engine_call_ms": 5.0,
                "result_parse_ms": 2.0,
                "normalize_ms": 0.1,
                "total_ms": 18.1,
            }

    monkeypatch.setattr(worker_main, "PaddleOCRProvider", ProfiledProvider)

    assert worker_main.main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--profile-output",
            str(profile_path),
            "--profile-runs",
            "2",
        ]
    ) == 0
    result_payload_text = output_path.read_text(encoding="utf-8")
    profile_payload_text = profile_path.read_text(encoding="utf-8")
    profile = read_profile(profile_path)
    assert json.loads(result_payload_text)["ok"] is True
    assert len(profile["runs"]) == 2
    assert "secret OCR text" not in profile_payload_text
    assert "secret OCR text" in result_payload_text


def test_worker_profile_runs_must_be_positive(tmp_path: Path) -> None:
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "result.json"
    input_path.write_bytes(b"image")

    assert worker_main.main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--profile-runs",
            "0",
        ]
    ) == 2


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
    assert "--profile-output" not in processes[0].command
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
        runtime / "components" / "local-ocr" / current_local_ocr_version() / current_spec().executable_name
    )


def test_local_macos_arm64_development_component_is_discovered_before_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    executable = repo_root / "dist" / "local-ocr-macos-arm64" / "LocalOCR" / "TellMeSenseiOCR"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"worker")
    monkeypatch.setattr(local_runtime, "worker_script_path", lambda: repo_root / "local_ocr_worker.py")
    monkeypatch.setattr(local_runtime, "user_runtime_directory", lambda: tmp_path / "runtime")
    monkeypatch.setattr(
        local_runtime,
        "current_spec",
        lambda: spec_for_manifest("macos", "arm64"),
    )

    candidates = local_runtime.worker_executable_candidates()

    assert candidates[1] == executable


def test_component_model_root_finds_development_sibling_models(tmp_path: Path) -> None:
    executable = tmp_path / "dist" / "local-ocr-macos-arm64" / "LocalOCR" / "TellMeSenseiOCR"
    models = executable.parent / "models"
    models.mkdir(parents=True)
    executable.write_bytes(b"worker")

    assert local_runtime.component_model_root(executable) == models


def test_session_and_provider_pass_development_sibling_model_root(tmp_path: Path) -> None:
    executable = tmp_path / "dist" / "local-ocr-macos-arm64" / "LocalOCR" / "TellMeSenseiOCR"
    models = executable.parent / "models"
    models.mkdir(parents=True)
    executable.write_bytes(b"worker")
    expected = str(models.resolve())

    session_command = LocalOCRSession(executable=executable)._serve_command()
    provider = LocalOCRProvider(executable=executable)
    provider_command = provider._command(tmp_path / "input.png", tmp_path / "result.json")

    assert session_command[session_command.index("--model-root") + 1] == expected
    assert provider_command[provider_command.index("--model-root") + 1] == expected


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
