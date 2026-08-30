from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.catalog import (
    CUSTOM_MODEL_ID,
    models_for_provider,
    provider_ids,
)
from app.ai.errors import AIProviderError
from app.ai.models import AIBackendConfig, AIRequest
from app.ai.providers.openai_compatible import MINIMAL_TEST_IMAGE_DATA_URL
from app.ai.providers.qwen import QwenProvider
from app.ai.providers.zai import ZAIProvider
from app.ai.service import AnalysisService
from app.config import ConfigManager
from app.settings.repository import SettingsRepository
from app.ui.settings_window import SettingsWindow


class FakeProviderSecrets:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.writes: list[tuple[str, str]] = []
        self.deletes: list[str] = []

    def get_provider_api_key(self, provider_id: str) -> str:
        return self.values.get(provider_id, "")

    def set_provider_api_key(self, provider_id: str, value: str) -> None:
        self.values[provider_id] = value
        self.writes.append((provider_id, value))

    def delete_provider_api_key(self, provider_id: str) -> None:
        self.values.pop(provider_id, None)
        self.deletes.append(provider_id)

    def get_google_vision_api_key(self) -> str:
        return ""


def manager(tmp_path: Path, secrets: FakeProviderSecrets | None = None) -> ConfigManager:
    return ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=secrets or FakeProviderSecrets(),
    )


def test_catalog_is_small_and_capability_filtered() -> None:
    assert provider_ids() == ("deepseek", "qwen", "zai")
    for provider_id in provider_ids():
        assert 2 <= len(models_for_provider(provider_id)) <= 4
        text_ids = {model.model_id for model in models_for_provider(provider_id, "text")}
        vision_ids = {model.model_id for model in models_for_provider(provider_id, "vision")}
        assert text_ids
        assert vision_ids
        assert text_ids | vision_ids == {
            model.model_id for model in models_for_provider(provider_id)
        }


def test_config_upgrade_keeps_deepseek_legacy_values_and_ignores_capability_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps({"model": "legacy-model", "base_url": "https://legacy/v1"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEXT_AI_BASE_URL", "https://wrong-capability-url/v1")
    config = manager(tmp_path, FakeProviderSecrets({"deepseek": "key"})).load()
    assert config.text_ai.model_id == "legacy-model"
    assert config.text_ai.base_url == "https://legacy/v1"
    assert config.vision_ai.base_url == "https://legacy/v1"


def test_provider_selection_uses_own_keys_endpoints_and_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    SettingsRepository(tmp_path / "settings.json").update(
        {
            "text_ai_provider": "qwen",
            "text_ai_model": "qwen-custom",
            "vision_ai_provider": "zai",
            "vision_ai_model": "glm-custom-vision",
            "qwen_base_url": "https://qwen.example/v1",
            "zai_base_url": "https://zai.example/v1",
        }
    )
    secrets = FakeProviderSecrets({"qwen": "q-key", "zai": "z-key"})
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = manager(tmp_path, secrets).load()
    assert config.text_ai.provider_id == "qwen"
    assert config.text_ai.api_key == "q-key"
    assert config.text_ai.base_url == "https://qwen.example/v1"
    assert config.vision_ai.provider_id == "zai"
    assert config.vision_ai.api_key == "z-key"
    assert config.vision_ai.base_url == "https://zai.example/v1"


def test_other_provider_does_not_require_deepseek_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("TEXT_AI_PROVIDER", "qwen")
    monkeypatch.setenv("VISION_AI_PROVIDER", "zai")
    monkeypatch.setenv("QWEN_API_KEY", "q-key")
    monkeypatch.setenv("ZAI_API_KEY", "z-key")
    config = manager(tmp_path).load()
    assert config.text_ai.api_key == "q-key"
    assert config.vision_ai.api_key == "z-key"


class FakeStream:
    def __iter__(self):
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="ok", reasoning_content=None),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        )

    def close(self) -> None:
        pass


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: object) -> FakeStream:
        self.calls.append(kwargs)
        return FakeStream()


@pytest.mark.parametrize("provider_type,provider_id", [(QwenProvider, "qwen"), (ZAIProvider, "zai")])
def test_explicit_adapters_share_streaming_transport(provider_type, provider_id: str) -> None:
    client = FakeClient()
    provider = provider_type(
        AIBackendConfig(provider_id=provider_id, api_key="key", base_url="https://example/v1"),
        client=client,
    )
    request = AIRequest(
        model_id="custom",
        capability="text",
        messages=({"role": "user", "content": "question"},),
    )
    assert provider.complete(request) == "ok"
    assert client.calls[0]["model"] == "custom"
    assert client.calls[0]["stream"] is True


@pytest.mark.parametrize("provider_type,provider_id", [(QwenProvider, "qwen"), (ZAIProvider, "zai")])
def test_explicit_adapters_keep_provider_error_wording(provider_type, provider_id: str) -> None:
    provider = provider_type(
        AIBackendConfig(provider_id=provider_id, api_key="key", base_url="https://example/v1"),
    )
    error = SimpleNamespace(status_code=401)
    assert provider._format_error(error).startswith("The ")
    provider_label = "Z.AI" if provider_id == "zai" else provider_id
    assert provider_label.upper() in provider._missing_api_key_message().upper()


def test_vision_connection_test_contains_real_image_url() -> None:
    client = FakeClient()
    provider = QwenProvider(
        AIBackendConfig(provider_id="qwen", api_key="key", base_url="https://example/v1"),
        client=client,
    )
    assert provider.test_connection(model_id="qwen3.7-plus", capability="vision") is True
    content = client.calls[0]["messages"][0]["content"]  # type: ignore[index]
    image = next(item for item in content if item["type"] == "image_url")  # type: ignore[union-attr]
    assert image["image_url"]["url"] == MINIMAL_TEST_IMAGE_DATA_URL  # type: ignore[index]


def test_analysis_service_routes_vision_to_selected_provider() -> None:
    config = SimpleNamespace(
        text_ai=AIBackendConfig(provider_id="qwen", model_id="qwen3.8-max", api_key="key", base_url="https://qwen"),
        vision_ai=AIBackendConfig(provider_id="zai", model_id="glm-4.6v", api_key="key", base_url="https://zai"),
        answer_language="en",
        interface_language="en",
    )
    client = FakeClient()
    assert AnalysisService(config, client=client).test_connection(capability="vision") is True
    assert client.calls[0]["model"] == "glm-4.6v"


def test_same_provider_key_is_reused_by_both_capabilities(
    tmp_path: Path,
) -> None:
    SettingsRepository(tmp_path / "settings.json").update(
        {
            "text_ai_provider": "qwen",
            "text_ai_model": "qwen3.8-max",
            "vision_ai_provider": "qwen",
            "vision_ai_model": "qwen3.7-plus",
        }
    )
    config = manager(tmp_path, FakeProviderSecrets({"qwen": "one-key"})).load()
    assert config.text_ai.api_key == config.vision_ai.api_key == "one-key"


def test_settings_can_round_trip_custom_models_and_provider_credentials(
    qt_app,
    tmp_path: Path,
) -> None:
    secrets = FakeProviderSecrets({"deepseek": "d-key"})
    window = SettingsWindow(manager(tmp_path, secrets), local_ocr_supported=False)
    window.text_provider_combo.setCurrentIndex(window.text_provider_combo.findData("qwen"))
    window.text_model_combo.setCurrentIndex(
        window.text_model_combo.findData(CUSTOM_MODEL_ID)
    )
    window.text_model_combo.setEditText("qwen-custom")
    window.vision_provider_combo.setCurrentIndex(window.vision_provider_combo.findData("zai"))
    window.vision_model_combo.setCurrentIndex(
        window.vision_model_combo.findData(CUSTOM_MODEL_ID)
    )
    window.vision_model_combo.setEditText("glm-custom-vision")
    window.provider_credentials_combo.setCurrentIndex(
        window.provider_credentials_combo.findData("qwen")
    )
    window.provider_api_key_edit.setText("q-key")
    window.save()
    saved = SettingsRepository(tmp_path / "settings.json").load()
    assert saved["text_ai_provider"] == "qwen"
    assert saved["text_ai_model"] == "qwen-custom"
    assert saved["vision_ai_provider"] == "zai"
    assert saved["vision_ai_model"] == "glm-custom-vision"
    assert secrets.values["qwen"] == "q-key"
    assert window.text_model_combo.currentData() == CUSTOM_MODEL_ID
    window.deleteLater()
    qt_app.processEvents()
