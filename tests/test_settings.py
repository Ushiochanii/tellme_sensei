from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QEventLoop, QTimer

from app.config import AppConfig, ConfigManager
from app.services.deepseek_service import DeepSeekError
from app.settings.repository import SettingsRepository
from app.settings.secret_store import SecretStore
from app.ui import settings_window as settings_window_module
from app.ui.main_window import MainWindow
from app.ui.settings_window import SettingsWindow


class FakeSecretStore:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.set_values: list[str] = []
        self.delete_count = 0

    def get_api_key(self) -> str:
        return self.value

    def set_api_key(self, value: str) -> None:
        self.value = value
        self.set_values.append(value)

    def delete_api_key(self) -> None:
        self.value = ""
        self.delete_count += 1


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


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

    config = make_manager(tmp_path).load(require_api_key=False)

    assert config.model == "env-model"
    assert config.request_timeout == 25.0


def test_secret_store_api_key_overrides_dotenv_api_key(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = make_manager(tmp_path, FakeSecretStore("stored-key")).load(False)
    assert config.api_key == "stored-key"


def test_explicit_os_api_key_overrides_secret_store(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    config = make_manager(tmp_path, FakeSecretStore("stored-key")).load(False)
    assert config.api_key == "env-key"


def test_dotenv_api_key_is_used_when_secret_store_is_empty(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_TIMEOUT", raising=False)
    config = make_manager(tmp_path, FakeSecretStore()).load(False)
    assert config.api_key == "dotenv-key"


def test_saved_model_and_timeout_override_dotenv(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_MODEL="dotenv-model", DEEPSEEK_TIMEOUT="15")
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.save({"model": "saved-model", "request_timeout": 20})
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_TIMEOUT", raising=False)

    config = make_manager(tmp_path).load(False)

    assert config.model == "saved-model"
    assert config.request_timeout == 20.0


def test_explicit_os_model_and_timeout_override_saved_settings(tmp_path, monkeypatch) -> None:
    SettingsRepository(tmp_path / "settings.json").save(
        {"model": "saved-model", "request_timeout": 20}
    )
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT", "25")

    config = make_manager(tmp_path).load(False)

    assert config.model == "env-model"
    assert config.request_timeout == 25.0


def test_config_manager_does_not_inject_dotenv_into_os_environment(tmp_path, monkeypatch) -> None:
    write_dotenv(tmp_path, DEEPSEEK_API_KEY="dotenv-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert "DEEPSEEK_API_KEY" not in os.environ
    config = make_manager(tmp_path, FakeSecretStore()).load(False)

    assert config.api_key == "dotenv-key"
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_secret_store_uses_injected_keyring_only() -> None:
    keyring = FakeKeyring()
    store = SecretStore(keyring_module=keyring)
    store.set_api_key("fake-key")
    assert store.get_api_key() == "fake-key"
    store.delete_api_key()
    assert store.get_api_key() == ""


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


def test_settings_window_loads_and_saves_values(qt_app, tmp_path) -> None:
    secret_store = FakeSecretStore("stored-key")
    manager = make_manager(tmp_path, secret_store)
    window = SettingsWindow(manager)

    assert window.api_key_edit.text() == "stored-key"
    window.api_key_edit.setText("new-key")
    window.model_edit.setText("new-model")
    window.timeout_edit.setText("33")
    window.save()

    assert secret_store.set_values == ["new-key"]
    assert manager.settings_repository.load() == {"model": "new-model", "request_timeout": 33.0}
    window.deleteLater()
    qt_app.processEvents()


def test_settings_warns_when_os_api_key_overrides_saved_key(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    secret_store = FakeSecretStore("stored-key")
    window = SettingsWindow(make_manager(tmp_path, secret_store))

    assert "DEEPSEEK_API_KEY" in window.status_label.text()
    window.api_key_edit.setText("new-saved-key")
    window.save()

    assert secret_store.set_values == ["new-saved-key"]
    assert "不会改变当前实际使用" in window.status_label.text()
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

    monkeypatch.setattr(settings_window_module, "DeepSeekService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.test_connection()
    assert window.is_connection_running()
    assert "正在测试" in window.status_label.text()
    wait_for_connection(window, qt_app)
    assert window.status_label.text() == "连接成功"
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

    monkeypatch.setattr(settings_window_module, "DeepSeekService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("stored-key")))
    window.api_key_edit.setText("input-key")
    window.timeout_edit.setText("60")
    window.test_connection()
    wait_for_connection(window, qt_app)

    assert received and received[0].api_key == "input-key"
    assert received[0].request_timeout == 10.0
    window.deleteLater()
    qt_app.processEvents()


def test_connection_401_is_shown_in_window(qt_app, tmp_path, monkeypatch) -> None:
    class FakeService:
        def __init__(self, _config: AppConfig) -> None:
            pass

        def test_connection(self, _cancel_event) -> bool:
            raise DeepSeekError("DeepSeek API Key 无效（401）")

    monkeypatch.setattr(settings_window_module, "DeepSeekService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("bad-key")))
    window.test_connection()
    wait_for_connection(window, qt_app)
    assert "401" in window.status_label.text()
    window.deleteLater()
    qt_app.processEvents()


def test_closing_connection_test_cleans_up_thread(qt_app, tmp_path, monkeypatch) -> None:
    class FakeService:
        def __init__(self, _config: AppConfig) -> None:
            pass

        def test_connection(self, cancel_event) -> bool:
            time.sleep(0.05)
            return not cancel_event.is_set()

    monkeypatch.setattr(settings_window_module, "DeepSeekService", FakeService)
    window = SettingsWindow(make_manager(tmp_path, FakeSecretStore("key")))
    window.test_connection()
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
