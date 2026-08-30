from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import AppConfig, ConfigManager
from app.localization import (
    CATALOGS,
    DEFAULT_ANSWER_LANGUAGE,
    DEFAULT_INTERFACE_LANGUAGE,
    answer_language_headings,
    answer_language_instruction,
)
from app.services.deepseek_service import DeepSeekService
from app.settings.repository import SettingsRepository
from app.ui.answer_window import AnswerWindow
from app.ui.main_window import MainWindow
from app.ui.settings_window import SettingsWindow


class _Stream:
    def __init__(self, text: str = "answer") -> None:
        self._chunks = iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=text),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        )
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream()

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self.create))


def test_interface_catalogs_have_identical_keys() -> None:
    assert set(CATALOGS["en"]) == set(CATALOGS["zh-CN"])


def test_language_preferences_default_validate_and_remain_independent(tmp_path) -> None:
    path = tmp_path / "settings.json"
    repository = SettingsRepository(path)
    assert repository.interface_language() == DEFAULT_INTERFACE_LANGUAGE
    assert repository.answer_language() == DEFAULT_ANSWER_LANGUAGE

    repository.update(
        {
            "interface_language": "zh-CN",
            "answer_language": "en",
            "ocr_provider": "google_vision",
        }
    )
    assert repository.interface_language() == "zh-CN"
    assert repository.answer_language() == "en"
    assert repository.load()["ocr_provider"] == "google_vision"

    repository.update({"interface_language": "en"})
    assert repository.interface_language() == "en"
    assert repository.answer_language() == "en"

    path.write_text(
        json.dumps(
            {
                "interface_language": "ja",
                "answer_language": "fr",
            }
        ),
        encoding="utf-8",
    )
    assert repository.interface_language() == DEFAULT_INTERFACE_LANGUAGE
    assert repository.answer_language() == DEFAULT_ANSWER_LANGUAGE

    for key in ("interface_language", "answer_language"):
        try:
            repository.update({key: "ja"})
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid {key} was accepted")


def test_config_carries_languages_without_changing_ocr_settings(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update(
        {
            "interface_language": "zh-CN",
            "answer_language": "en",
            "ocr_language": "japan",
            "ocr_provider": "google_vision",
        }
    )
    config = ConfigManager(
        project_root=tmp_path,
        settings_repository=repository,
    ).load(require_api_key=False)

    assert config.interface_language == "zh-CN"
    assert config.answer_language == "en"
    assert config.ocr_language == "japan"
    assert config.ocr_provider == "google_vision"


def test_settings_language_selectors_persist_independently(qt_app, tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    manager = ConfigManager(project_root=tmp_path, settings_repository=repository)
    window = SettingsWindow(manager, interface_language="en")
    window.interface_language_combo.setCurrentIndex(
        window.interface_language_combo.findData("zh-CN")
    )
    window.answer_language_combo.setCurrentIndex(
        window.answer_language_combo.findData("en")
    )
    window.save()

    assert repository.interface_language() == "zh-CN"
    assert repository.answer_language() == "en"
    window.deleteLater()
    qt_app.processEvents()

    restored = SettingsWindow(manager, interface_language="zh-CN")
    assert restored.interface_language_combo.currentData() == "zh-CN"
    assert restored.answer_language_combo.currentData() == "en"
    restored.deleteLater()
    qt_app.processEvents()


def test_all_deepseek_prompt_paths_carry_answer_language_contract() -> None:
    image_bytes = b"png-bytes"

    for language in ("en", "zh-CN"):
        expected = answer_language_instruction(language)
        headings = answer_language_headings(language)
        for invoke in (
            lambda service: service.analyze("question text"),
            lambda service: service.analyze_context_question("context", "question"),
            lambda service: service.analyze_image(image_bytes),
        ):
            client = _Client()
            service = DeepSeekService(
                AppConfig(api_key="test", answer_language=language),
                client=client,
            )
            invoke(service)
            system_prompt = client.calls[0]["messages"][0]["content"]
            assert expected in system_prompt
            assert all(heading in system_prompt for heading in headings)


def test_translated_ui_keeps_structural_labels_invariant(qt_app) -> None:
    for language in ("en", "zh-CN"):
        main = MainWindow(tray_mode=True, interface_language=language)
        if language == "zh-CN":
            assert main.text_mode_button.text().endswith("提取文字")
            assert main.vision_mode_button.text().endswith("视觉分析")
        else:
            assert main.text_mode_button.text().endswith("Text extraction")
            assert main.vision_mode_button.text().endswith("Visual analysis")
        assert main.status_label.text() == "●  Ready"

        answer = AnswerWindow(interface_language=language)
        assert answer.context_section_label.text() == "Context"
        assert answer.question_section_label.text() == "Question"
        assert answer.answer_section_label.text() == "Answer"
        assert answer.copy_button.text() == (
            "复制" if language == "zh-CN" else "Copy"
        )
        answer.set_status("完成")
        assert (
            "分析完成" in answer.status_label.text()
            if language == "zh-CN"
            else "Analysis completed" in answer.status_label.text()
        )

        answer.deleteLater()
        main.deleteLater()
        qt_app.processEvents()

    answer = AnswerWindow(interface_language="zh-CN")
    settings = SettingsWindow(interface_language="zh-CN")
    assert settings.windowTitle() == "TellMeSensei 设置"
    assert settings.save_button.text() == "保存"
    assert settings.cancel_button.text() == "取消"
    assert settings.interface_language_combo.currentData() == "en"
    assert settings.answer_language_combo.currentData() == "zh-CN"

    settings.deleteLater()
    answer.deleteLater()
    qt_app.processEvents()
