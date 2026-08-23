from dataclasses import dataclass
import json
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import AppConfig
from app.ocr.base import OCRProvider
from app.ocr.factory import create_ocr_provider
from app.ocr.local_session import LocalOCRSession
from app.ocr.profiling import read_profile, write_profile
from app.ocr.providers.local_worker import LocalOCRProvider
from app.ocr.providers.paddle import PaddleOCRProvider
from app.ocr.types import OCRError, OCRLine, OCRResult
from app.ocr.worker_protocol import error_payload
from app.ui import main_window as main_window_module
from app.workers.processing_worker import ProcessingWorker
from scripts import profile_local_ocr as profiling_script
from scripts.profile_local_ocr import median_ms


def test_factory_returns_local_provider_by_default() -> None:
    provider = create_ocr_provider(AppConfig(api_key="test", ocr_language="en"))

    assert isinstance(provider, LocalOCRProvider)
    assert provider.language == "en"


def test_factory_injects_shared_local_session_without_starting_it(tmp_path) -> None:
    executable = tmp_path / "TellMeSenseiOCR.exe"
    executable.write_bytes(b"fake")
    session = LocalOCRSession(executable=executable)

    provider = create_ocr_provider(
        AppConfig(api_key="test", ocr_provider="local"),
        local_ocr_session=session,
    )

    assert isinstance(provider, LocalOCRProvider)
    assert provider.session is session
    assert session.is_running() is False


def test_ocr_result_contract_is_provider_independent() -> None:
    result = OCRResult("question", (OCRLine("question", confidence=0.9),))

    assert result.text == "question"
    assert result.lines[0].confidence == 0.9


def test_processing_worker_accepts_generic_ocr_provider() -> None:
    @dataclass
    class FakeOCR:
        def recognize(self, image) -> OCRResult:
            assert image == "image"
            return OCRResult("OCR text", (OCRLine("OCR text"),))

    @dataclass
    class FakeAI:
        def analyze(self, text: str) -> str:
            return f"answer: {text}"

    provider: OCRProvider = FakeOCR()
    worker = ProcessingWorker("image", provider, FakeAI())
    results: list[object] = []
    worker.result_ready.connect(results.append)
    worker.run()

    assert results[0].ocr.text == "OCR text"
    assert results[0].answer == "answer: OCR text"


def test_main_window_uses_factory_without_paddle_construction() -> None:
    source = inspect.getsource(main_window_module)

    assert "create_ocr_provider" in source
    assert "PaddleOCR" not in source
    assert "OCRService(" not in source


def test_paddle_profile_reuses_one_lazy_engine(tmp_path) -> None:
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"image")

    class FakeEngine:
        def predict(self, _image):
            return {
                "rec_texts": ["hello"],
                "rec_scores": [0.9],
                "rec_boxes": [[[0, 0], [10, 10]]],
            }

    class FakeProvider(PaddleOCRProvider):
        def _get_engine(self):
            if self._engine is None:
                self._engine = FakeEngine()
            return self._engine

    provider = FakeProvider()
    first, first_timings = provider.recognize_profiled(image_path)
    second, second_timings = provider.recognize_profiled(image_path)

    assert first.text == second.text == "hello"
    assert first_timings["engine_init_ms"] >= 0.0
    assert second_timings["engine_init_ms"] == 0.0
    assert first_timings["engine_call_ms"] >= 0.0
    assert first_timings["result_parse_ms"] >= 0.0
    assert first_timings["normalize_ms"] >= 0.0


def test_profile_schema_rejects_malformed_documents(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed"):
        read_profile(profile_path)


def test_profile_schema_round_trip_contains_timings_only(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    write_profile(
        profile_path,
        {
            "schema_version": 1,
            "runs": [
                {
                    "index": 1,
                    "engine_init_ms": 1.0,
                    "input_prepare_ms": 2.0,
                    "engine_call_ms": 3.0,
                    "result_parse_ms": 4.0,
                    "normalize_ms": 5.0,
                    "total_ms": 15.0,
                }
            ],
            "worker_profiled_total_ms": 15.0,
            "result_write_ms": 1.0,
        },
    )

    assert read_profile(profile_path)["runs"][0]["engine_call_ms"] == 3.0


def test_profile_benchmark_median() -> None:
    assert median_ms([30.0, 10.0, 20.0]) == 20.0


def test_profiled_missing_image_error_is_readable(tmp_path) -> None:
    provider = PaddleOCRProvider()

    with pytest.raises(OCRError, match="图片文件不存在"):
        provider.recognize_profiled(tmp_path / "missing.png")


def test_current_benchmark_uses_normal_provider_path_without_child_profile(
    tmp_path, monkeypatch
) -> None:
    worker = tmp_path / "TellMeSenseiOCR.exe"
    worker.write_bytes(b"worker")
    calls: list[dict[str, object]] = []

    class FakeProvider:
        def __init__(self, **_kwargs) -> None:
            pass

        def recognize(self, _image, **kwargs):
            calls.append(kwargs)
            kwargs["profile_timings"].update(
                {
                    "input_prepare_ms": 1.0,
                    "process_wall_ms": 2.0,
                    "result_read_ms": 3.0,
                }
            )
            return OCRResult("text", ())

    monkeypatch.setattr(profiling_script, "LocalOCRProvider", FakeProvider)
    totals, details = profiling_script._run_current_pipeline(
        object(), worker, "japan", 1
    )

    assert len(totals) == 1
    assert details[0]["process_wall_ms"] == 2.0
    assert "profile_output" not in calls[0]
    assert "profile_timings" in calls[0]


def test_warm_median_excludes_initialization_run() -> None:
    profile = {
        "runs": [
            {"index": 1, "total_ms": 100.0},
            {"index": 2, "total_ms": 20.0},
            {"index": 3, "total_ms": 30.0},
        ]
    }

    warm_values = profiling_script.warm_sample_values(profile)
    assert warm_values == [20.0, 30.0]
    assert median_ms(warm_values) == 25.0


def test_warm_runs_one_is_rejected_and_two_is_valid(tmp_path) -> None:
    image = tmp_path / "input.png"
    worker = tmp_path / "worker.exe"
    image.write_bytes(b"image")
    worker.write_bytes(b"worker")

    with pytest.raises(ValueError, match="--warm-runs must be at least 2"):
        profiling_script._validate_args(
            profiling_script.argparse.Namespace(
                cold_runs=1, warm_runs=1, input=image, worker=worker
            )
        )

    profiling_script._validate_args(
        profiling_script.argparse.Namespace(
            cold_runs=1, warm_runs=2, input=image, worker=worker
        )
    )


def test_profile_cli_resolves_relative_input_and_worker_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    image = Path("question.png")
    worker = Path("dist") / "TellMeSenseiOCR.exe"
    image.write_bytes(b"image")
    worker.parent.mkdir()
    worker.write_bytes(b"worker")
    args = profiling_script.argparse.Namespace(
        cold_runs=1, warm_runs=2, input=image, worker=worker
    )

    profiling_script._validate_args(args)

    assert args.input == image.resolve()
    assert args.worker == worker.resolve()
    assert args.input.is_absolute()
    assert args.worker.is_absolute()


def _valid_profile_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "runs": [
            {
                "index": 1,
                "engine_init_ms": 1.0,
                "input_prepare_ms": 1.0,
                "engine_call_ms": 1.0,
                "result_parse_ms": 1.0,
                "normalize_ms": 1.0,
                "total_ms": 5.0,
            }
        ],
        "worker_profiled_total_ms": 5.0,
        "result_write_ms": 1.0,
    }


def test_profile_worker_receives_absolute_paths(tmp_path, monkeypatch) -> None:
    image = (tmp_path / "question.png").resolve()
    worker = (tmp_path / "TellMeSenseiOCR.exe").resolve()
    image.write_bytes(b"image")
    worker.write_bytes(b"worker")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        profile_path = Path(command[command.index("--profile-output") + 1])
        profile_path.write_text(json.dumps(_valid_profile_payload()), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(profiling_script.subprocess, "run", fake_run)
    profiling_script._run_worker_profile(image, worker, "japan", 1, tmp_path)

    command = captured["command"]
    assert command[0] == str(worker)
    assert command[command.index("--input") + 1] == str(image)
    assert captured["kwargs"]["cwd"] == str(worker.parent)


@pytest.mark.parametrize("payload", [{"schema_version": 1, "ok": "bad"}, None])
def test_profile_worker_failure_uses_error_payload_or_generic_fallback(
    tmp_path, monkeypatch, payload
) -> None:
    image = tmp_path / "question.png"
    worker = tmp_path / "TellMeSenseiOCR.exe"
    image.write_bytes(b"image")
    worker.write_bytes(b"worker")

    def fake_run(command, **_kwargs):
        output_path = Path(command[command.index("--output") + 1])
        if payload is not None:
            output_path.write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(profiling_script.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as exc_info:
        profiling_script._run_worker_profile(image, worker, "japan", 1, tmp_path)
    assert str(exc_info.value) == (
        "Local OCR worker failed with exit code 1: "
        "no valid worker error payload was returned"
    )


def test_profile_worker_failure_surfaces_valid_error_payload(tmp_path, monkeypatch) -> None:
    image = tmp_path / "question.png"
    worker = tmp_path / "TellMeSenseiOCR.exe"
    image.write_bytes(b"image")
    worker.write_bytes(b"worker")

    def fake_run(command, **_kwargs):
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(error_payload("图片文件不存在：question.png")), encoding="utf-8"
        )
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(profiling_script.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="exit code 1: 图片文件不存在：question.png"):
        profiling_script._run_worker_profile(image, worker, "japan", 1, tmp_path)
