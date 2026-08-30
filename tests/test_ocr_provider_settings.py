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
    assert window.local_mode_radio.isChecked()
    window.close()

    SettingsRepository(tmp_path / "settings.json").update({"ocr_provider": "google_vision"})
    window, _ = _window(tmp_path, secrets)
    assert window.online_mode_radio.isChecked()
    assert window.google_vision_api_key_edit.text() == "stored-google"
    # Navigation keeps both service pages available; provider selection is
    # still represented by the radio buttons and is saved independently.
    assert not window.local_ocr_group.isHidden()
    assert not window.google_vision_group.isHidden()
    window.close()


def test_ocr_provider_environment_override_locks_google_and_preserves_saved_value(
    qt_app, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "google_vision")
    window, _ = _window(tmp_path)
    assert window.online_mode_radio.isChecked()
    assert not window.online_mode_radio.isEnabled()
    assert not window.local_mode_radio.isEnabled()
    assert not window.online_service_combo.isEnabled()
    assert not window.ocr_provider_override_label.isHidden()
    window.close()

    repository = SettingsRepository(tmp_path / "settings.json")
    repository.update({"ocr_provider": "local"})
    window, _ = _window(tmp_path)
    window.save()
    assert repository.load()["ocr_provider"] == "local"
    window.close()


def test_ocr_provider_environment_override_locks_local(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "local")
    SettingsRepository(tmp_path / "settings.json").update({"ocr_provider": "google_vision"})
    window, _ = _window(tmp_path)
    assert window.local_mode_radio.isChecked()
    assert not window.local_mode_radio.isEnabled()
    assert not window.local_engine_combo.isEnabled()
    assert not window.ocr_provider_override_label.isHidden()
    window.close()


def test_ocr_provider_selector_enabled_without_environment_override(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    window, _ = _window(tmp_path)
    assert window.local_mode_radio.isEnabled()
    assert window.online_mode_radio.isEnabled()
    assert window.local_engine_combo.isEnabled()
    assert window.online_service_combo.isEnabled()
    assert window.ocr_provider_override_label.isHidden()
    window.close()


def test_provider_controls_are_disabled_while_background_operation_runs(qt_app, tmp_path) -> None:
    window, _ = _window(tmp_path)

    window._refresh_operation_controls(connection_running=True)

    assert not window.local_mode_radio.isEnabled()
    assert not window.online_mode_radio.isEnabled()
    assert not window.local_engine_combo.isEnabled()
    assert not window.online_service_combo.isEnabled()

    window._refresh_operation_controls(connection_running=False)
    assert window.local_mode_radio.isEnabled()
    assert window.online_mode_radio.isEnabled()
    assert window.local_engine_combo.isEnabled()
    assert window.online_service_combo.isEnabled()
    window.close()


def test_provider_save_and_cancel_semantics(qt_app, tmp_path) -> None:
    window, secrets = _window(tmp_path)
    window.online_mode_radio.setChecked(True)
    window.google_vision_api_key_edit.setText("google-key")
    window.save()
    assert secrets.google == "google-key"
    saved = window.config_manager.settings_repository.load()
    assert saved["ocr_mode"] == "online"
    assert saved["local_ocr_engine"] == "paddleocr"
    assert saved["online_ocr_provider"] == "google_vision"

    window.local_mode_radio.setChecked(True)
    window.google_vision_api_key_edit.setText("unsaved-key")
    window.close()
    window.reload_values()
    assert window.online_mode_radio.isChecked()
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
    assert "GOOGLE_VISION_API_KEY" in window.google_vision_override_label.text()
    assert "controlled" in window.google_vision_override_label.text()
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
    window.online_mode_radio.setChecked(True)
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
    assert window.local_mode_radio.isChecked()
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
