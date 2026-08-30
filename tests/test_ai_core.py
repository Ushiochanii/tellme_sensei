from __future__ import annotations

import inspect
import json
import threading
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.ai.errors import AIProviderError, AIRequestCancelled
from app.ai.models import (
    AIBackendConfig,
    AIRequest,
    DEFAULT_DEEPSEEK_VISION_MODEL,
)
from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.prompts import AnalysisPromptBuilder
from app.ai.service import AnalysisService
from app.config import AppConfig, ConfigManager
from app.settings.repository import SettingsRepository


class _SecretStore:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get_api_key(self) -> str:
        return self.value


class _Stream:
    def __init__(self, *chunks) -> None:
        self._chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, stream: _Stream) -> None:
        self.stream = stream
        self.calls: list[dict[str, object]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream


def _chunk(content: str | None = None, reasoning: str | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning,
                ),
                finish_reason="stop" if content else None,
            )
        ]
    )


def test_backend_and_request_contracts_are_immutable() -> None:
    backend = AIBackendConfig(api_key="secret")
    request = AIRequest(
        model_id="model",
        capability="text",
        messages=({"role": "user", "content": "question"},),
    )

    with pytest.raises(FrozenInstanceError):
        backend.model_id = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        request.model_id = "other"  # type: ignore[misc]


def test_app_config_uses_authoritative_backend_fields_without_legacy_wrapper() -> None:
    config = AppConfig()

    assert config.text_ai.api_key == ""
    assert config.text_ai.model_id != config.vision_ai.model_id
    assert not hasattr(config, "api_key")
    assert not hasattr(config, "model")
    assert "api_key" not in inspect.signature(AppConfig).parameters
    assert "model" not in inspect.signature(AppConfig).parameters


def test_config_resolves_independent_capabilities_and_legacy_fallbacks(tmp_path, monkeypatch) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "model": "legacy-model",
                "base_url": "https://legacy.example/v1",
                "request_timeout": 12,
                "vision_ai_model": "vision-custom",
                "text_ai_provider": "deepseek",
                "vision_ai_provider": "deepseek",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("TEXT_AI_BASE_URL", "https://text-capability.example/v1")
    monkeypatch.setenv("VISION_AI_BASE_URL", "https://vision-capability.example/v1")
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=_SecretStore("stored-key"),
    )

    config = manager.load()

    assert config.text_ai.model_id == "legacy-model"
    assert config.vision_ai.model_id == "vision-custom"
    assert config.text_ai.base_url == "https://legacy.example/v1"
    assert config.vision_ai.base_url == "https://legacy.example/v1"
    assert config.text_ai.request_timeout == 12.0
    assert config.vision_ai.request_timeout == 12.0
    assert config.text_ai.api_key == "stored-key"
    assert config.vision_ai.api_key == "stored-key"


def test_config_load_without_key_defers_failure_until_selected_provider_request(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=_SecretStore(),
    )

    config = manager.load()
    assert config.text_ai.api_key == ""

    with pytest.raises(AIProviderError, match="API Key"):
        AnalysisService(config).analyze("question")


def test_vision_model_does_not_follow_legacy_text_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_MODEL", "text-override")
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=_SecretStore(),
    )

    config = manager.load()

    assert config.text_ai.model_id == "text-override"
    assert config.vision_ai.model_id == DEFAULT_DEEPSEEK_VISION_MODEL


def test_deepseek_adapter_preserves_streaming_and_vision_extra() -> None:
    stream = _Stream(_chunk("answer"), _chunk(reasoning="hidden"))
    client = _Client(stream)
    provider = DeepSeekProvider(
        AIBackendConfig(api_key="test"),
        client=client,
    )
    request = AIRequest(
        model_id="vision-model",
        capability="vision",
        messages=({"role": "user", "content": "image"},),
    )

    assert provider.complete(request) == "answer"
    assert client.calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert stream.closed is True


def test_analysis_service_uses_vision_runtime_model() -> None:
    config = AppConfig(
        text_ai=AIBackendConfig(api_key="test", model_id="text-model"),
        vision_ai=AIBackendConfig(api_key="test", model_id="vision-custom"),
    )
    stream = _Stream(_chunk("vision answer"))
    client = _Client(stream)
    service = AnalysisService(config, client=client)

    assert service.analyze_image(b"png") == "vision answer"
    assert client.calls[0]["model"] == "vision-custom"


def test_prompt_builder_keeps_one_answer_language_contract() -> None:
    builder = AnalysisPromptBuilder("en")

    messages = builder.build_text("question")
    context_messages = builder.build_context_question("context", "question")
    vision_messages = builder.build_vision("data:image/png;base64,AAAA")

    for values in (messages, context_messages, vision_messages):
        assert "Output language:" in values[0]["content"]
        assert "【Answer】" in values[0]["content"]


def test_stream_cancellation_is_provider_neutral() -> None:
    cancel_event = threading.Event()

    class _CancellingStream(_Stream):
        def __next__(self):
            chunk = super().__next__()
            cancel_event.set()
            return chunk

    stream = _CancellingStream(_chunk("partial"))
    provider = DeepSeekProvider(
        AIBackendConfig(api_key="test"),
        client=_Client(stream),
    )
    request = AIRequest(
        model_id="text-model",
        capability="text",
        messages=({"role": "user", "content": "question"},),
    )

    with pytest.raises(AIRequestCancelled):
        provider.complete(request, cancel_event=cancel_event)
    assert stream.closed is True


def test_missing_key_uses_provider_neutral_error_type() -> None:
    provider = DeepSeekProvider(AIBackendConfig(api_key=""))
    request = AIRequest(
        model_id="text-model",
        capability="text",
        messages=({"role": "user", "content": "question"},),
    )

    with pytest.raises(AIProviderError):
        provider.complete(request)
