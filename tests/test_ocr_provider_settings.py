from __future__ import annotations

import threading
import time

from PySide6.QtCore import QEventLoop, QTimer

from app.config import ConfigManager
from app.ocr.types import OCRCancelled, OCRResult
from app.settings.repository import SettingsRepository
from app.ui import settings_window as settings_window_module
from app.ui.settings_window import SettingsWindow


class _Secrets:
    def __init__(self, deepseek: str = "deepseek", google: str = "") -> None:
        self.deepseek = deepseek
        self.google = google

    def get_api_key(self) -> str:
        return self.deepseek

    def set_api_key(self, value: str) -> None:
        self.deepseek = value

    def delete_api_key(self) -> None:
        self.deepseek = ""

    def get_google_vision_api_key(self) -> str:
        return self.google

    def set_google_vision_api_key(self, value: str) -> None:
        self.google = value

    def delete_google_vision_api_key(self) -> None:
        self.google = ""


class _ComponentManager:
    version = "1.0.0"

    def is_installed(self) -> bool:
        return False

    def verify_installation(self) -> bool:
        return False

    def smoke_test(self) -> bool:
        return False


def _window(tmp_path, secrets: _Secrets | None = None) -> tuple[SettingsWindow, _Secrets]:
    secrets = secrets or _Secrets()
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
        secret_store=secrets,
    )
    return SettingsWindow(manager, component_manager=_ComponentManager()), secrets


def _wait_for(qt_app, predicate) -> None:
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    timer.stop()
    qt_app.processEvents()


def test_provider_defaults_local_and_saved_google_is_loaded(qt_app, tmp_path) -> None:
    window, secrets = _window(tmp_path, _Secrets(google="stored-google"))
    assert window.ocr_provider_combo.currentData() == "local"
    window.close()

    SettingsRepository(tmp_path / "settings.json").update({"ocr_provider": "google_vision"})
    window, _ = _window(tmp_path, secrets)
    assert window.ocr_provider_combo.currentData() == "google_vision"
    assert window.google_vision_api_key_edit.text() == "stored-google"
    assert window.local_ocr_group.isHidden()
    assert not window.google_vision_group.isHidden()
    window.close()


def test_provider_save_and_cancel_semantics(qt_app, tmp_path) -> None:
    window, secrets = _window(tmp_path)
    window.ocr_provider_combo.setCurrentIndex(window.ocr_provider_combo.findData("google_vision"))
    window.google_vision_api_key_edit.setText("google-key")
    window.save()
    assert secrets.google == "google-key"
    assert window.config_manager.settings_repository.load()["ocr_provider"] == "google_vision"

    window.ocr_provider_combo.setCurrentIndex(window.ocr_provider_combo.findData("local"))
    window.google_vision_api_key_edit.setText("unsaved-key")
    window.close()
    window.reload_values()
    assert window.ocr_provider_combo.currentData() == "google_vision"
    assert window.google_vision_api_key_edit.text() == "google-key"
    window.google_vision_api_key_edit.clear()
    window.save()
    assert secrets.google == ""
    window.close()


def test_google_key_environment_override_is_visible(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "environment-google")
    window, _ = _window(tmp_path, _Secrets(google="stored-google"))
    assert window.google_vision_api_key_edit.text() == "environment-google"
    assert window.google_vision_api_key_edit.isReadOnly()
    assert not window.google_vision_api_key_edit.isEnabled()
    assert not window.google_vision_override_label.isHidden()
    assert "GOOGLE_VISION_API_KEY" in window.status_label.text()
    assert "overridden" in window.status_label.text()
    window.close()


def test_google_test_uses_effective_environment_key(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "environment-google")
    received: list[str] = []

    class FakeProvider:
        def __init__(self, api_key, **_kwargs) -> None:
            received.append(api_key)

        def test_connection(self, _cancel_event) -> OCRResult:
            return OCRResult("TEST", ())

    monkeypatch.setattr(settings_window_module, "GoogleVisionOCRProvider", FakeProvider)
    window, _ = _window(tmp_path, _Secrets(google="stored-google"))
    window.google_vision_api_key_edit.setText("different-field-value")
    window.test_google_vision()
    _wait_for(qt_app, lambda: not window.is_google_test_running())
    assert received == ["environment-google"]
    window.close()


def test_save_does_not_copy_environment_key_to_secret_store(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "environment-google")
    secrets = _Secrets(google="stored-google")
    window, _ = _window(tmp_path, secrets)
    window.ocr_provider_combo.setCurrentIndex(window.ocr_provider_combo.findData("google_vision"))
    window.save()
    assert secrets.google == "stored-google"
    window.close()


def test_google_test_runs_off_gui_thread_and_uses_current_field(qt_app, tmp_path, monkeypatch) -> None:
    main_thread = threading.get_ident()
    calls: list[tuple[str, int]] = []

    class FakeProvider:
        def __init__(self, api_key, language, timeout) -> None:
            calls.append((api_key, threading.get_ident()))

        def test_connection(self, cancel_event) -> OCRResult:
            time.sleep(0.05)
            return OCRResult("TEST", ())

    monkeypatch.setattr(settings_window_module, "GoogleVisionOCRProvider", FakeProvider)
    window, _ = _window(tmp_path)
    window.google_vision_api_key_edit.setText("typed-google-key")
    window.test_google_vision()
    assert window.is_google_test_running()
    assert not window.google_vision_test_button.isEnabled()
    _wait_for(qt_app, lambda: not window.is_google_test_running())
    assert window.google_vision_status_label.text() == "Google Vision connection successful."
    assert calls and calls[0][0] == "typed-google-key"
    assert calls[0][1] != main_thread
    window.close()


def test_google_test_failure_is_shown_without_fallback(qt_app, tmp_path, monkeypatch) -> None:
    class FakeProvider:
        def __init__(self, **_kwargs) -> None:
            pass

        def test_connection(self, _cancel_event):
            raise RuntimeError("Google Vision API Key invalid (403)")

    monkeypatch.setattr(settings_window_module, "GoogleVisionOCRProvider", FakeProvider)
    window, _ = _window(tmp_path)
    window.google_vision_api_key_edit.setText("bad-key")
    window.test_google_vision()
    _wait_for(qt_app, lambda: not window.is_google_test_running())
    assert "Google Vision connection test failed" in window.google_vision_status_label.text()
    assert window.ocr_provider_combo.currentData() == "local"
    window.close()


def test_shutdown_waits_for_google_test_and_cancels_it(qt_app, tmp_path) -> None:
    started = threading.Event()

    class FakeProvider:
        def __init__(self, **_kwargs) -> None:
            pass

        def test_connection(self, cancel_event):
            started.set()
            while not cancel_event.is_set():
                time.sleep(0.01)
            raise OCRCancelled("cancelled")

    original = settings_window_module.GoogleVisionOCRProvider
    settings_window_module.GoogleVisionOCRProvider = FakeProvider
    try:
        window, _ = _window(tmp_path)
        window.google_vision_api_key_edit.setText("key")
        window.test_google_vision()
        assert started.wait(1)
        ready: list[bool] = []
        window.shutdown_ready.connect(lambda: ready.append(True))
        window.request_shutdown()
        assert ready == []
        _wait_for(qt_app, lambda: not window.has_running_background_operations())
        assert ready == [True]
        window.deleteLater()
        qt_app.processEvents()
    finally:
        settings_window_module.GoogleVisionOCRProvider = original
