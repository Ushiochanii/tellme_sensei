from __future__ import annotations

import json
import os
import threading
import time
from itertools import combinations

import pytest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

from app.analysis import AnalysisMode
from app.config import AppConfig, ConfigManager
from app.ai.errors import AIProviderError
from app.auto_watch.models import AutoWatchSettings
from app.settings.repository import SettingsRepository
from app.settings.secret_store import SecretStore
from app.ui import settings_window as settings_window_module
from app.ui.main_window import MainWindow
from app.ui.settings_window import SettingsWindow


class FakeSecretStore:
    def __init__(self, value: str = "", google: str = "") -> None:
        self.value = value
        self.set_values: list[str] = []
        self.delete_count = 0
        self.google_value = google
        self.google_set_values: list[str] = []
        self.google_delete_count = 0

    def get_api_key(self) -> str:
        return self.value

    def set_api_key(self, value: str) -> None:
        self.value = value
        self.set_values.append(value)

    def delete_api_key(self) -> None:
        self.value = ""
        self.delete_count += 1

    def get_google_vision_api_key(self) -> str:
        return self.google_value

    def set_google_vision_api_key(self, value: str) -> None:
        self.google_value = value
        self.google_set_values.append(value)

    def delete_google_vision_api_key(self) -> None:
        self.google_value = ""
        self.google_delete_count += 1


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


class FakeHotkeyManager:
    def __init__(self, shortcut: str = "Ctrl+Shift+Q", rebind_result: bool = True) -> None:
        self.shortcut = shortcut
        self.rebind_result = rebind_result
        self.rebind_calls: list[str] = []
        self.registered = True
        self.register_calls = 0
        self.unregister_calls = 0

    def rebind(self, shortcut: str) -> bool:
        self.rebind_calls.append(shortcut)
        if self.rebind_result:
            self.shortcut = shortcut
            self.registered = True
        return self.rebind_result

    def register(self) -> bool:
        self.register_calls += 1
        self.registered = True
        return True

    def unregister(self) -> None:
        self.unregister_calls += 1
        self.registered = False


class OwnedHotkeyManager:
    """Small native-registration double that models shortcut ownership."""

    def __init__(self, shortcut: str, owners: set[str], fail_shortcuts: set[str] | None = None) -> None:
        self.shortcut = shortcut
        self.owners = owners
        self.fail_shortcuts = fail_shortcuts or set()
        self.rebind_calls: list[str] = []
        self.registered = False
        assert self.register() is True

    def register(self) -> bool:
        if self.shortcut in self.fail_shortcuts or self.shortcut in self.owners:
            return False
        self.owners.add(self.shortcut)
        self.registered = True
        return True

    def unregister(self) -> None:
        self.owners.discard(self.shortcut)
        self.registered = False

    def rebind(self, shortcut: str) -> bool:
        self.rebind_calls.append(shortcut)
        old_shortcut = self.shortcut
        was_registered = self.registered
        if was_registered:
            self.unregister()
        self.shortcut = shortcut
        if self.register():
            return True
        self.shortcut = old_shortcut
        if was_registered:
            self.register()
        return False


def make_manager(tmp_path, secret_store=None) -> ConfigManager:
    return ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=secret_store or FakeSecretStore(),
    )


def write_dotenv(tmp_path, **values: str) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )


def wait_for_connection(window: SettingsWindow, qt_app) -> None:
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: loop.quit() if not window.is_connection_running() else None)
    timer.start()
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    timer.stop()
    qt_app.processEvents()


def test_env_overrides_saved_model_and_timeout(tmp_path, monkeypatch) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.save({"model": "saved-model", "request_timeout": 10})
    write_dotenv(tmp_path, DEEPSEEK_MODEL="dotenv-model", DEEPSEEK_TIMEOUT="15")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT", "25")

    config = make_manager(tmp_path).load()

    assert config.text_ai.model_id == "env-model"
    assert config.text_ai.request_timeout == 25.0


def test_secret_store_api_key_overrides_dotenv_api_key(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = make_manager(tmp_path, FakeSecretStore("stored-key")).load()
    assert config.text_ai.api_key == "stored-key"


def test_explicit_os_api_key_overrides_secret_store(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    config = make_manager(tmp_path, FakeSecretStore("stored-key")).load()
    assert config.text_ai.api_key == "env-key"


def test_dotenv_api_key_is_used_when_secret_store_is_empty(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_TIMEOUT", raising=False)
    config = make_manager(tmp_path, FakeSecretStore()).load()
    assert config.text_ai.api_key == "dotenv-key"


def test_saved_shortcut_is_restored_on_startup(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GLOBAL_SHORTCUT", raising=False)
    SettingsRepository(tmp_path / "settings.json").update(
        {"global_shortcut": "Ctrl+Alt+A"}
    )
    assert make_manager(tmp_path).load().global_shortcut == "Ctrl+Alt+A"


def test_fresh_shortcut_defaults_and_saved_legacy_values_are_preserved(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GLOBAL_SHORTCUT", raising=False)
    monkeypatch.delenv("VISION_GLOBAL_SHORTCUT", raising=False)
    manager = make_manager(tmp_path)
    assert manager.load().global_shortcut == "Ctrl+Shift+A"
    assert manager.load().vision_global_shortcut == "Ctrl+Shift+S"
    assert manager.load().watch_global_shortcut == "Ctrl+Shift+W"
    assert manager.load().context_watch_global_shortcut == "Ctrl+Shift+C"

    manager.settings_repository.update(
        {
            "global_shortcut": "Ctrl+Shift+Q",
            "vision_global_shortcut": "Ctrl+Shift+E",
            "watch_global_shortcut": "Ctrl+Shift+W",
            "context_watch_global_shortcut": "Ctrl+Shift+C",
        }
    )
    config = manager.load()
    assert config.global_shortcut == "Ctrl+Shift+Q"
    assert config.vision_global_shortcut == "Ctrl+Shift+E"
    assert config.watch_global_shortcut == "Ctrl+Shift+W"
    assert config.context_watch_global_shortcut == "Ctrl+Shift+C"


def test_vision_shortcut_uses_environment_saved_dotenv_default_precedence(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, VISION_GLOBAL_SHORTCUT="Ctrl+Alt+F1")
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update({"vision_global_shortcut": "Ctrl+Alt+F2"})
    monkeypatch.delenv("VISION_GLOBAL_SHORTCUT", raising=False)
    assert make_manager(tmp_path).load().vision_global_shortcut == "Ctrl+Alt+F2"

    monkeypatch.setenv("VISION_GLOBAL_SHORTCUT", "Ctrl+Alt+F3")
    assert make_manager(tmp_path).load().vision_global_shortcut == "Ctrl+Alt+F3"

    repository.path.unlink()
    monkeypatch.delenv("VISION_GLOBAL_SHORTCUT", raising=False)
    assert make_manager(tmp_path).load().vision_global_shortcut == "Ctrl+Alt+F1"

    (tmp_path / ".env").unlink()
    assert make_manager(tmp_path).load().vision_global_shortcut == "Ctrl+Shift+S"


def test_invalid_saved_shortcut_falls_back_to_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GLOBAL_SHORTCUT", raising=False)
    SettingsRepository(tmp_path / "settings.json").update(
        {"global_shortcut": "Ctrl+Win+Q"}
    )
    assert make_manager(tmp_path).load().global_shortcut == "Ctrl+Shift+A"


def test_duplicate_saved_shortcuts_are_normalized_to_unique_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GLOBAL_SHORTCUT", raising=False)
    monkeypatch.delenv("VISION_GLOBAL_SHORTCUT", raising=False)
    monkeypatch.delenv("WATCH_GLOBAL_SHORTCUT", raising=False)
    monkeypatch.delenv("CONTEXT_WATCH_GLOBAL_SHORTCUT", raising=False)
    SettingsRepository(tmp_path / "settings.json").update(
        {
            "global_shortcut": "Ctrl+Shift+A",
            "vision_global_shortcut": "Ctrl+Shift+A",
            "watch_global_shortcut": "Ctrl+Shift+A",
            "context_watch_global_shortcut": "Ctrl+Shift+A",
        }
    )

    config = make_manager(tmp_path).load()

    assert len({
        config.global_shortcut,
        config.vision_global_shortcut,
        config.watch_global_shortcut,
        config.context_watch_global_shortcut,
    }) == 4


def test_saved_model_and_timeout_override_dotenv(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_MODEL="dotenv-model", DEEPSEEK_TIMEOUT="15")
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.save({"model": "saved-model", "request_timeout": 20})
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_TIMEOUT", raising=False)

    config = make_manager(tmp_path).load()

    assert config.text_ai.model_id == "saved-model"
    assert config.text_ai.request_timeout == 20.0


def test_explicit_os_model_and_timeout_override_saved_settings(tmp_path, monkeypatch) -> None:
    SettingsRepository(tmp_path / "settings.json").save(
        {"model": "saved-model", "request_timeout": 20}
    )
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT", "25")

    config = make_manager(tmp_path).load()

    assert config.text_ai.model_id == "env-model"
    assert config.text_ai.request_timeout == 25.0


def test_config_manager_does_not_inject_dotenv_into_os_environment(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert "DEEPSEEK_API_KEY" not in os.environ
    config = make_manager(tmp_path, FakeSecretStore()).load()

    assert config.text_ai.api_key == "dotenv-key"
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_secret_store_uses_injected_keyring_only() -> None:
    keyring = FakeKeyring()
    store = SecretStore(keyring_module=keyring)
    store.set_api_key("fake-key")
    assert store.get_api_key() == "fake-key"
    store.delete_api_key()
    assert store.get_api_key() == ""


def test_config_test_path_never_uses_real_keyring(tmp_path, monkeypatch) -> None:
    import keyring

    def fail_if_real_keyring_is_used(*_args, **_kwargs):
        raise AssertionError("tests must not access the OS keyring")

    monkeypatch.setattr(keyring, "get_password", fail_if_real_keyring_is_used)
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=FakeSecretStore(),
    )

    assert manager.load().text_ai.api_key == ""


def test_repository_partial_update_preserves_existing_settings(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update(
        {
            "model": "model-a",
            "request_timeout": 12,
            "global_shortcut": "Ctrl+Alt+A",
            "answer_window_geometry": {"x": -1200, "y": 80, "width": 450, "height": 600},
        }
    )
    repository.update({"model": "model-b"})
    saved = repository.load()
    assert saved["model"] == "model-b"
    assert saved["request_timeout"] == 12.0
    assert saved["global_shortcut"] == "Ctrl+Alt+A"
    assert saved["answer_window_geometry"]["x"] == -1200


def test_geometry_round_trip_and_offscreen_fallback(qt_app, tmp_path) -> None:
    from app.ui.answer_window import AnswerWindow

    repository = SettingsRepository(tmp_path / "settings.json")
    window = AnswerWindow(settings_repository=repository)
    window.setGeometry(20, 30, 500, 550)
    window.close()
    qt_app.processEvents()
    assert repository.load()["answer_window_geometry"] == {
        "x": 20,
        "y": 30,
        "width": 500,
        "height": 550,
    }

    repository.update(
        {"answer_window_geometry": {"x": 100000, "y": 100000, "width": 500, "height": 550}}
    )
    restored = AnswerWindow(settings_repository=repository)
    assert restored._geometry_restored is False
    restored.show_at_current_screen()
    restored.close()
    qt_app.processEvents()


def test_settings_save_applies_shortcut_immediately(qt_app, tmp_path) -> None:
    hotkey = FakeHotkeyManager()
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")), hotkey_manager=hotkey)
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+A"))
    window.save()
    assert hotkey.rebind_calls == ["Ctrl+Alt+A"]
    assert window.config_manager.settings_repository.load()["global_shortcut"] == "Ctrl+Alt+A"
    window.deleteLater()
    qt_app.processEvents()


def test_four_shortcut_save_rebinds_and_persists_all_managers(qt_app, tmp_path) -> None:
    manager = make_manager(tmp_path, FakeSecretStore("key"))
    text_hotkey = FakeHotkeyManager("Ctrl+Shift+A")
    vision_hotkey = FakeHotkeyManager("Ctrl+Shift+S")
    watch_hotkey = FakeHotkeyManager("Ctrl+Shift+W")
    context_watch_hotkey = FakeHotkeyManager("Ctrl+Shift+C")
    window = SettingsWindow(
        manager,
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
        watch_hotkey_manager=watch_hotkey,
        context_watch_hotkey_manager=context_watch_hotkey,
    )
    for field, shortcut in (
        (window.shortcut_edit, "Ctrl+Alt+F1"),
        (window.vision_shortcut_edit, "Ctrl+Alt+F2"),
        (window.watch_shortcut_edit, "Ctrl+Alt+F3"),
        (window.context_watch_shortcut_edit, "Ctrl+Alt+F4"),
    ):
        field.setKeySequence(QKeySequence(shortcut))

    window.save()

    assert text_hotkey.rebind_calls == ["Ctrl+Alt+F1"]
    assert vision_hotkey.rebind_calls == ["Ctrl+Alt+F2"]
    assert watch_hotkey.rebind_calls == ["Ctrl+Alt+F3"]
    assert context_watch_hotkey.rebind_calls == ["Ctrl+Alt+F4"]
    saved = manager.settings_repository.load()
    assert saved["global_shortcut"] == "Ctrl+Alt+F1"
    assert saved["vision_global_shortcut"] == "Ctrl+Alt+F2"
    assert saved["watch_global_shortcut"] == "Ctrl+Alt+F3"
    assert saved["context_watch_global_shortcut"] == "Ctrl+Alt+F4"
    window.deleteLater()
    qt_app.processEvents()


def test_settings_loads_all_four_saved_shortcuts(qt_app, tmp_path) -> None:
    manager = make_manager(tmp_path, FakeSecretStore("key"))
    manager.settings_repository.update(
        {
            "global_shortcut": "Ctrl+Alt+F1",
            "vision_global_shortcut": "Ctrl+Alt+F2",
            "watch_global_shortcut": "Ctrl+Alt+F3",
            "context_watch_global_shortcut": "Ctrl+Alt+F4",
        }
    )

    window = SettingsWindow(manager)

    assert window.shortcut_edit.keySequence().toString() == "Ctrl+Alt+F1"
    assert window.vision_shortcut_edit.keySequence().toString() == "Ctrl+Alt+F2"
    assert window.watch_shortcut_edit.keySequence().toString() == "Ctrl+Alt+F3"
    assert window.context_watch_shortcut_edit.keySequence().toString() == "Ctrl+Alt+F4"
    window.deleteLater()
    qt_app.processEvents()


def test_unchanged_deepseek_key_is_not_written_when_saving(qt_app, tmp_path) -> None:
    secrets = FakeSecretStore("stored-key")
    window = SettingsWindow(make_manager(tmp_path, secrets))
    window.save()
    assert secrets.set_values == []
    assert secrets.delete_count == 0
    window.deleteLater()
    qt_app.processEvents()


def test_changed_deepseek_key_is_written_once(qt_app, tmp_path) -> None:
    secrets = FakeSecretStore("stored-key")
    window = SettingsWindow(make_manager(tmp_path, secrets))
    window.provider_api_key_edit.setText("new-key")
    window.save()
    assert secrets.set_values == ["new-key"]
    assert secrets.delete_count == 0
    window.deleteLater()
    qt_app.processEvents()


def test_cleared_deepseek_key_is_deleted_once(qt_app, tmp_path) -> None:
    secrets = FakeSecretStore("stored-key")
    window = SettingsWindow(make_manager(tmp_path, secrets))
    window.provider_api_key_edit.clear()
    window.save()
    assert secrets.set_values == []
    assert secrets.delete_count == 1
    window.deleteLater()
    qt_app.processEvents()


def test_shortcut_only_change_saves_without_touching_deepseek_key(qt_app, tmp_path) -> None:
    secrets = FakeSecretStore("stored-key")
    window = SettingsWindow(make_manager(tmp_path, secrets))
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+A"))
    window.save()
    assert secrets.set_values == []
    assert secrets.delete_count == 0
    assert window.config_manager.settings_repository.load()["global_shortcut"] == "Ctrl+Alt+A"
    window.deleteLater()
    qt_app.processEvents()


def test_unchanged_environment_deepseek_key_is_not_written(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    secrets = FakeSecretStore("stored-key")
    window = SettingsWindow(make_manager(tmp_path, secrets))
    window.save()
    assert secrets.set_values == []
    assert secrets.delete_count == 0
    window.deleteLater()
    qt_app.processEvents()


def test_unchanged_google_key_is_not_written_and_changed_key_is_written(qt_app, tmp_path) -> None:
    secrets = FakeSecretStore("stored-key", google="stored-google")
    window = SettingsWindow(make_manager(tmp_path, secrets))
    window.save()
    assert secrets.google_set_values == []
    assert secrets.google_delete_count == 0
    window.google_vision_api_key_edit.setText("new-google")
    window.save()
    assert secrets.google_set_values == ["new-google"]
    assert secrets.google_delete_count == 0
    window.deleteLater()
    qt_app.processEvents()


def test_cleared_google_key_is_deleted_once(qt_app, tmp_path) -> None:
    secrets = FakeSecretStore("stored-key", google="stored-google")
    window = SettingsWindow(make_manager(tmp_path, secrets))
    window.google_vision_api_key_edit.clear()
    window.save()
    assert secrets.google_set_values == []
    assert secrets.google_delete_count == 1
    window.deleteLater()
    qt_app.processEvents()


def test_failed_shortcut_rebind_does_not_persist_new_value(qt_app, tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update({"global_shortcut": "Ctrl+Shift+Q"})
    hotkey = FakeHotkeyManager(rebind_result=False)
    manager = make_manager(tmp_path, FakeSecretStore("key"))
    window = SettingsWindow(manager, hotkey_manager=hotkey)
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+A"))
    window.save()
    assert repository.load()["global_shortcut"] == "Ctrl+Shift+Q"
    assert "Shortcut registration failed" in window.status_label.text()
    window.deleteLater()
    qt_app.processEvents()


def test_identical_text_and_vision_shortcuts_are_rejected(qt_app, tmp_path) -> None:
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.vision_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+A"))
    window.save()
    assert "different" in window.status_label.text()
    assert window.config_manager.settings_repository.load() == {}
    window.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize(
    ("first_field", "second_field"),
    list(combinations(
        (
            "shortcut_edit",
            "vision_shortcut_edit",
            "watch_shortcut_edit",
            "context_watch_shortcut_edit",
        ),
        2,
    )),
)
def test_any_pair_of_four_shortcuts_is_rejected_when_identical(
    qt_app, tmp_path, first_field, second_field
) -> None:
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    duplicate = QKeySequence("Ctrl+Alt+Z")
    getattr(window, first_field).setKeySequence(duplicate)
    getattr(window, second_field).setKeySequence(duplicate)

    window.save()

    assert "different" in window.status_label.text()
    assert window.config_manager.settings_repository.load() == {}
    window.deleteLater()
    qt_app.processEvents()


def test_two_shortcut_rebinds_roll_back_when_vision_registration_fails(qt_app, tmp_path) -> None:
    text_hotkey = FakeHotkeyManager()
    vision_hotkey = FakeHotkeyManager("Ctrl+Shift+W", rebind_result=False)
    window = SettingsWindow(
        make_manager(tmp_path, FakeSecretStore("key")),
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+A"))
    window.vision_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+B"))
    window.save()

    assert text_hotkey.shortcut == "Ctrl+Shift+Q"
    assert vision_hotkey.shortcut == "Ctrl+Shift+W"
    assert text_hotkey.registered is True
    assert vision_hotkey.registered is True
    assert window.config_manager.settings_repository.load() == {}
    assert "Shortcut registration failed" in window.status_label.text()
    window.deleteLater()
    qt_app.processEvents()


def test_two_shortcut_rebinds_attempt_vision_after_text_failure(qt_app, tmp_path) -> None:
    text_hotkey = FakeHotkeyManager(rebind_result=False)
    vision_hotkey = FakeHotkeyManager("Ctrl+Shift+W")
    window = SettingsWindow(
        make_manager(tmp_path, FakeSecretStore("key")),
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+A"))
    window.vision_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+B"))
    window.save()

    assert text_hotkey.rebind_calls == ["Ctrl+Alt+A"]
    assert vision_hotkey.rebind_calls == ["Ctrl+Alt+B", "Ctrl+Shift+W"]
    assert vision_hotkey.shortcut == "Ctrl+Shift+W"
    assert window.config_manager.settings_repository.load() == {}
    window.deleteLater()
    qt_app.processEvents()


def test_two_shortcut_rebind_direct_swap_succeeds(qt_app, tmp_path) -> None:
    owners: set[str] = set()
    text_hotkey = OwnedHotkeyManager("Ctrl+Shift+Q", owners)
    vision_hotkey = OwnedHotkeyManager("Ctrl+Shift+W", owners)
    window = SettingsWindow(
        make_manager(tmp_path, FakeSecretStore("key")),
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+W"))
    window.vision_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+Q"))
    window.watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+R"))
    window.context_watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+T"))
    window.save()

    assert text_hotkey.shortcut == "Ctrl+Shift+W"
    assert vision_hotkey.shortcut == "Ctrl+Shift+Q"
    assert text_hotkey.registered is True
    assert vision_hotkey.registered is True
    assert owners == {"Ctrl+Shift+Q", "Ctrl+Shift+W"}
    assert window.config_manager.settings_repository.load()["global_shortcut"] == "Ctrl+Shift+W"
    assert window.config_manager.settings_repository.load()["vision_global_shortcut"] == "Ctrl+Shift+Q"
    window.deleteLater()
    qt_app.processEvents()


def test_two_shortcut_rebind_transfer_succeeds(qt_app, tmp_path) -> None:
    owners: set[str] = set()
    text_hotkey = OwnedHotkeyManager("Ctrl+Shift+Q", owners)
    vision_hotkey = OwnedHotkeyManager("Ctrl+Shift+W", owners)
    window = SettingsWindow(
        make_manager(tmp_path, FakeSecretStore("key")),
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+W"))
    window.vision_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+E"))
    window.watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+R"))
    window.context_watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+T"))
    window.save()

    assert text_hotkey.shortcut == "Ctrl+Shift+W"
    assert vision_hotkey.shortcut == "Ctrl+Alt+E"
    assert owners == {"Ctrl+Shift+W", "Ctrl+Alt+E"}
    assert window.config_manager.settings_repository.load()["vision_global_shortcut"] == "Ctrl+Alt+E"
    window.deleteLater()
    qt_app.processEvents()


def test_two_shortcut_rebind_preserves_unregistered_state(qt_app, tmp_path) -> None:
    text_hotkey = FakeHotkeyManager()
    vision_hotkey = FakeHotkeyManager("Ctrl+Shift+W")
    text_hotkey.unregister()
    vision_hotkey.unregister()
    window = SettingsWindow(
        make_manager(tmp_path, FakeSecretStore("key")),
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+W"))
    window.vision_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+E"))
    window.watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+R"))
    window.context_watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+T"))
    window.save()

    assert text_hotkey.registered is False
    assert vision_hotkey.registered is False
    window.deleteLater()
    qt_app.processEvents()


def test_two_shortcut_rebind_restores_after_second_registration_fails(qt_app, tmp_path) -> None:
    owners: set[str] = set()
    text_hotkey = OwnedHotkeyManager("Ctrl+Shift+Q", owners)
    vision_hotkey = OwnedHotkeyManager("Ctrl+Shift+W", owners, {"Ctrl+Alt+E"})
    window = SettingsWindow(
        make_manager(tmp_path, FakeSecretStore("key")),
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )
    window.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+W"))
    window.vision_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+E"))
    window.watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+R"))
    window.context_watch_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+T"))
    window.save()

    assert text_hotkey.shortcut == "Ctrl+Shift+Q"
    assert vision_hotkey.shortcut == "Ctrl+Shift+W"
    assert text_hotkey.registered is True
    assert vision_hotkey.registered is True
    assert owners == {"Ctrl+Shift+Q", "Ctrl+Shift+W"}
    assert window.config_manager.settings_repository.load() == {}
    assert "Shortcut registration failed" in window.status_label.text()
    window.deleteLater()
    qt_app.processEvents()


def test_settings_cancel_discards_edits_and_reopen_reloads_saved_values(qt_app, tmp_path) -> None:
    manager = make_manager(tmp_path, FakeSecretStore("key"))
    window = MainWindow(tray_mode=True, config_manager=manager)
    window.show_settings()
    settings = window._settings_window
    settings.text_model_combo.setEditText("unsaved-model")
    settings.close()
    window.show_settings()
    assert window._settings_window.text_model_combo.currentText() == "deepseek-chat"
    window.shutdown()
    window.close()
    qt_app.processEvents()


def test_api_key_never_appears_in_settings_json(tmp_path) -> None:
    path = tmp_path / "settings.json"
    SettingsRepository(path).save({"model": "deepseek-chat", "request_timeout": 60})
    assert "fake-key" not in path.read_text(encoding="utf-8")
    assert "api_key" not in path.read_text(encoding="utf-8")


def test_settings_repository_round_trip_and_invalid_json(tmp_path) -> None:
    path = tmp_path / "settings.json"
    repository = SettingsRepository(path)
    repository.save({"model": "custom-model", "request_timeout": 42})
    assert repository.load() == {"model": "custom-model", "request_timeout": 42.0}

    path.write_text("not json", encoding="utf-8")
    assert repository.load() == {}


def test_settings_navigation_switches_pages_without_changing_provider(qt_app, tmp_path) -> None:
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    assert window.page_stack.currentIndex() == 0
    assert window._navigation_buttons[0].isChecked()
    assert window._navigation_buttons[2].property("navLevel") == "primary"
    assert window._navigation_buttons[3].property("navLevel") == "child"
    assert window._navigation_buttons[4].property("navLevel") == "child"
    assert window.local_mode_radio.isChecked()

    window._navigation_buttons[2].click()
    assert window.page_stack.currentIndex() == 2
    assert window._ocr_mode_from_ui() == "local"
    window.online_mode_radio.click()
    assert window._ocr_mode_from_ui() == "online"

    window._navigation_buttons[3].click()
    assert window.page_stack.currentIndex() == 3
    assert window._navigation_buttons[3].isChecked()
    assert window.online_mode_radio.isChecked()

    window._navigation_buttons[4].click()
    assert window.page_stack.currentIndex() == 4
    assert window.online_mode_radio.isChecked()
    window.close()
    qt_app.processEvents()


def test_environment_warnings_stay_on_their_own_pages(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "environment-google")
    monkeypatch.setenv("OCR_PROVIDER", "google_vision")
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("stored-key", "stored-google")))

    assert not window.api_key_override_label.isHidden()
    assert not window.google_vision_override_label.isHidden()
    assert not window.ocr_provider_override_label.isHidden()
    assert window.status_label.text() == ""
    window.close()


def test_settings_window_loads_and_saves_values(qt_app, tmp_path) -> None:
    secret_store = FakeSecretStore("stored-key")
    manager = make_manager(tmp_path, secret_store)
    window = SettingsWindow(manager)

    assert window.provider_api_key_edit.text() == "stored-key"
    window.provider_api_key_edit.setText("new-key")
    window.text_model_combo.setCurrentIndex(window.text_model_combo.findData("__custom__"))
    window.text_custom_model_edit.setText("new-model")
    window.timeout_spin.setValue(33)
    window.save()

    assert secret_store.set_values == ["new-key"]
    assert manager.settings_repository.load() == {
        "text_ai_provider": "deepseek",
        "text_ai_model": "new-model",
        "vision_ai_provider": "deepseek",
        "vision_ai_model": "deepseek-v4-flash-vision-exp",
        "request_timeout": 33.0,
        "global_shortcut": "Ctrl+Shift+A",
        "vision_global_shortcut": "Ctrl+Shift+S",
        "watch_global_shortcut": "Ctrl+Shift+W",
        "context_watch_global_shortcut": "Ctrl+Shift+C",
        "ocr_mode": "local",
        "local_ocr_engine": "paddleocr",
        "online_ocr_provider": "google_vision",
        "online_ocr_timeout": 15.0,
    }
    window.deleteLater()
    qt_app.processEvents()


def test_settings_warns_when_os_api_key_overrides_saved_key(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    secret_store = FakeSecretStore("stored-key")
    window = SettingsWindow(make_manager(tmp_path, secret_store))

    assert "DEEPSEEK_API_KEY" in window.api_key_override_label.text()
    assert not window.api_key_override_label.isHidden()
    window.provider_api_key_edit.setText("new-saved-key")
    window.save()

    assert secret_store.set_values == []
    assert "will not change the key currently in use" in window.api_key_override_label.text()
    window.deleteLater()
    qt_app.processEvents()


def test_connection_success_runs_off_gui_thread(qt_app, tmp_path, monkeypatch) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []

    class FakeService:
        def __init__(self, _config: AppConfig) -> None:
            pass

        def test_connection(self, cancel_event) -> bool:
            worker_threads.append(threading.get_ident())
            time.sleep(0.05)
            return True

    monkeypatch.setattr(settings_window_module, "AnalysisService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.test_text_connection()
    assert window.is_connection_running()
    assert "Testing connection" in window.status_label.text()
    assert window.text_ai_status_label.property("state") == "busy"
    assert not window.text_provider_combo.isEnabled()
    assert window.vision_provider_combo.isEnabled()
    wait_for_connection(window, qt_app)
    assert window.status_label.text() == "Connection successful."
    assert window.text_ai_status_label.property("state") == "ready"
    assert window.text_provider_combo.isEnabled()
    assert worker_threads and worker_threads[0] != main_thread
    window.deleteLater()
    qt_app.processEvents()


def test_connection_uses_current_input_key_and_bounded_timeout(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    received: list[AppConfig] = []

    class FakeService:
        def __init__(self, config: AppConfig) -> None:
            received.append(config)

        def test_connection(self, _cancel_event) -> bool:
            return True

    monkeypatch.setattr(settings_window_module, "AnalysisService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("stored-key")))
    window.provider_api_key_edit.setText("input-key")
    window.timeout_spin.setValue(60)
    window.test_text_connection()
    wait_for_connection(window, qt_app)

    assert received and received[0].text_ai.api_key == "input-key"
    assert received[0].text_ai.request_timeout == 10.0
    window.deleteLater()
    qt_app.processEvents()


def test_connection_401_is_shown_in_window(qt_app, tmp_path, monkeypatch) -> None:
    class FakeService:
        def __init__(self, _config: AppConfig) -> None:
            pass

        def test_connection(self, _cancel_event) -> bool:
            raise AIProviderError("DeepSeek API Key 无效（401）")

    monkeypatch.setattr(settings_window_module, "AnalysisService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("bad-key")))
    window.test_text_connection()
    wait_for_connection(window, qt_app)
    assert "401" in window.status_label.text()
    assert "401" in window.text_ai_status_label.text()
    assert window.text_ai_status_label.property("state") == "error"
    window.deleteLater()
    qt_app.processEvents()


def test_closing_connection_test_cleans_up_thread(qt_app, tmp_path, monkeypatch) -> None:
    class FakeService:
        def __init__(self, _config: AppConfig) -> None:
            pass

        def test_connection(self, cancel_event) -> bool:
            time.sleep(0.05)
            return not cancel_event.is_set()

    monkeypatch.setattr(settings_window_module, "AnalysisService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.test_text_connection()
    window.close()
    wait_for_connection(window, qt_app)
    assert not window.is_connection_running()
    window.deleteLater()
    qt_app.processEvents()


def test_repeated_settings_open_reuses_one_window(qt_app, tmp_path) -> None:
    window = MainWindow(tray_mode=True, config_manager=make_manager(tmp_path))
    window.show_settings()
    first = window._settings_window
    window.show_settings()
    assert first is window._settings_window
    window.shutdown()
    window.close()
    qt_app.processEvents()


def test_auto_watch_repository_round_trip_partial_and_validation(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    defaults = AutoWatchSettings()
    assert repository.auto_watch_settings() == defaults
    assert repository.auto_watch_analysis_mode() is AnalysisMode.TEXT
    repository.update({"auto_watch_analysis_mode": AnalysisMode.VISION})
    assert repository.auto_watch_analysis_mode() is AnalysisMode.VISION
    with pytest.raises(ValueError):
        repository.update({"auto_watch_analysis_mode": "invalid"})
    assert repository.auto_watch_analysis_mode() is AnalysisMode.VISION
    repository.save({"model": "kept", "poll_interval_ms": 1, "novelty_ratio": 0.0})
    repository.update({"stable_samples_required": 1000, "analysis_delay_ms": 60000})
    assert repository.auto_watch_settings().poll_interval_ms == 1
    assert repository.auto_watch_settings().novelty_ratio == 0.0
    assert repository.load()["model"] == "kept"
    for key, value in {
        "poll_interval_ms": 1, "pixel_delta_threshold": 1,
        "novelty_ratio": 0.0, "stability_ratio": 0.0,
        "stable_samples_required": 1, "analysis_delay_ms": 0,
    }.items():
        repository.update({key: value})
        assert getattr(repository.auto_watch_settings(), key) == value
    for key, value in {"pixel_delta_threshold": 255, "novelty_ratio": 1.0, "stability_ratio": 1.0}.items():
        repository.update({key: value})
        assert getattr(repository.auto_watch_settings(), key) == value
    for key, value in {
        "poll_interval_ms": 0, "pixel_delta_threshold": 256,
        "novelty_ratio": 1.1, "stability_ratio": -0.1,
        "stable_samples_required": 0, "analysis_delay_ms": -1,
    }.items():
        with pytest.raises(ValueError):
            repository.update({key: value})
    for key in ("poll_interval_ms", "pixel_delta_threshold", "novelty_ratio", "stability_ratio", "stable_samples_required", "analysis_delay_ms"):
        with pytest.raises(ValueError):
            repository.update({key: True})
        with pytest.raises(ValueError):
            repository.update({key: "invalid"})
    for key in ("novelty_ratio", "stability_ratio"):
        for value in (float("nan"), float("inf")):
            with pytest.raises(ValueError):
                repository.update({key: value})


def test_auto_watch_corrupt_values_fall_back_independently(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "model": "kept",
        "auto_watch_analysis_mode": "not-a-mode",
        "poll_interval_ms": "bad",
        "novelty_ratio": 0.25,
    }), encoding="utf-8")
    repository = SettingsRepository(path)
    defaults = AutoWatchSettings()
    settings = repository.auto_watch_settings()
    assert repository.auto_watch_analysis_mode() is AnalysisMode.TEXT
    assert repository.load()["model"] == "kept"
    assert settings.poll_interval_ms == defaults.poll_interval_ms
    assert settings.novelty_ratio == 0.25
    path.write_text("[not an object]", encoding="utf-8")
    assert repository.load() == {}


def test_auto_watch_settings_window_load_save_and_navigation(qt_app, tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update({
        "poll_interval_ms": 500, "pixel_delta_threshold": 20,
        "novelty_ratio": 0.125, "stability_ratio": 0.25,
        "stable_samples_required": 4, "analysis_delay_ms": 30,
        "auto_watch_analysis_mode": AnalysisMode.VISION,
    })
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    assert isinstance(window.poll_interval_ms_spin, QSpinBox)
    assert isinstance(window.novelty_ratio_spin, QDoubleSpinBox)
    assert window.poll_interval_ms_spin.value() == 500
    assert window.novelty_ratio_spin.value() == 12.5
    assert window.auto_watch_vision_radio.isChecked()
    assert not window.auto_watch_text_radio.isChecked()
    assert next(button for button in window._navigation_buttons if button.text() == "Auto Watch").property("navLevel") == "primary"
    window.poll_interval_ms_spin.setValue(200)
    window.pixel_delta_threshold_spin.setValue(25)
    window.novelty_ratio_spin.setValue(12.5)
    window.stability_ratio_spin.setValue(50.0)
    window.stable_samples_required_spin.setValue(6)
    window.analysis_delay_ms_spin.setValue(40)
    window.auto_watch_text_radio.click()
    window.save()
    saved = repository.auto_watch_settings()
    assert saved.poll_interval_ms == 200
    assert saved.pixel_delta_threshold == 25
    assert saved.novelty_ratio == 0.125
    assert saved.stability_ratio == 0.5
    assert saved.stable_samples_required == 6
    assert saved.analysis_delay_ms == 40
    assert repository.auto_watch_analysis_mode() is AnalysisMode.TEXT
    window.deleteLater()
    qt_app.processEvents()


def test_auto_watch_settings_window_cancel_restore_and_expected_time(qt_app, tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update({
        "poll_interval_ms": 500,
        "stable_samples_required": 4,
        "auto_watch_analysis_mode": AnalysisMode.VISION,
    })
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.poll_interval_ms_spin.setValue(200)
    window.stable_samples_required_spin.setValue(6)
    assert "1200 ms" in window.expected_stability_label.text()
    window.restore_auto_watch_button.click()
    assert window.poll_interval_ms_spin.value() == AutoWatchSettings().poll_interval_ms
    assert window.auto_watch_text_radio.isChecked()
    assert not window.auto_watch_vision_radio.isChecked()
    assert repository.auto_watch_settings().poll_interval_ms == 500
    assert repository.auto_watch_analysis_mode() is AnalysisMode.VISION
    window.save()
    assert repository.auto_watch_settings() == AutoWatchSettings()
    assert repository.auto_watch_analysis_mode() is AnalysisMode.TEXT
    repository.update({"poll_interval_ms": 500})
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.poll_interval_ms_spin.setValue(200)
    window.cancel_button.click()
    assert repository.auto_watch_settings().poll_interval_ms == 500
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.poll_interval_ms_spin.setValue(200)
    window.close()
    assert repository.auto_watch_settings().poll_interval_ms == 500
    window.deleteLater()
    qt_app.processEvents()


def test_auto_watch_save_failure_is_shown_without_storage_damage(qt_app, tmp_path, monkeypatch) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update({"poll_interval_ms": 500})
    manager = make_manager(tmp_path, FakeSecretStore("key"))
    manager.settings_repository = repository
    window = SettingsWindow(manager)
    window.poll_interval_ms_spin.setValue(200)
    before = repository.load()

    def fail_update(_settings) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(repository, "update", fail_update)
    window.save()
    assert "disk unavailable" in window.status_label.text()
    assert SettingsRepository(tmp_path / "settings.json").load() == before
    window.deleteLater()
    qt_app.processEvents()
