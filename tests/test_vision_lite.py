from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from app.config import AppConfig
from app.state import AppState
import vision_lite


class _Hotkey(QObject):
    triggered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.unregistered = False

    def unregister(self) -> None:
        self.unregistered = True

    @property
    def shortcut(self) -> str:
        return getattr(self, "_shortcut", "Ctrl+Shift+S")

    @property
    def registered(self) -> bool:
        return not self.unregistered

    def rebind(self, shortcut: str) -> bool:
        self._shortcut = shortcut
        self.unregistered = False
        return True


class _FailingHotkey(_Hotkey):
    def rebind(self, _shortcut: str) -> bool:
        return False


class _ConfigManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.saved = False
        self.save_calls: list[dict] = []
        self.settings_repository = None

    def load(self, require_api_key: bool = True) -> AppConfig:
        if require_api_key and not self.config.api_key:
            raise RuntimeError("missing key")
        return self.config

    def save_settings(self, **_kwargs) -> None:
        self.saved = True
        self.save_calls.append(_kwargs)

    def has_explicit_api_key(self) -> bool:
        return False


def _window(qt_app, config: AppConfig | None = None):
    manager = _ConfigManager(config or AppConfig(api_key="test-key"))
    hotkey = _Hotkey()
    window = vision_lite.VisionLiteWindow(
        config_manager=manager,
        hotkey_manager=hotkey,
    )
    return window, manager, hotkey


def test_capture_button_routes_to_vision_capture(qt_app, monkeypatch) -> None:
    window, _manager, _hotkey = _window(qt_app)
    called: list[bool] = []
    monkeypatch.setattr(window, "start_capture", lambda: called.append(True) or True)

    window.capture_button.click()

    assert called == [True]
    window.deleteLater()


def test_lite_entry_point_does_not_import_ocr_or_text_worker() -> None:
    source = Path(vision_lite.__file__).read_text(encoding="utf-8")
    assert "app.ocr" not in source
    assert "app.workers.processing_worker" not in source
    assert "app.ui.main_window" not in source


def test_busy_state_blocks_duplicate_capture(qt_app) -> None:
    window, _manager, _hotkey = _window(qt_app)
    window._busy = True

    assert window.start_capture() is False
    window.deleteLater()


def test_capture_cancellation_restores_lite_window(qt_app) -> None:
    window, _manager, _hotkey = _window(qt_app)
    window.show()
    window._busy = True
    window.state = AppState.CAPTURING
    window.hide()

    window._on_capture_cancelled()

    assert window.busy is False
    assert window.isVisible() is True
    window.close()


def test_missing_api_key_prompts_without_persisting_cancelled_value(qt_app, monkeypatch) -> None:
    window, manager, _hotkey = _window(qt_app, AppConfig(api_key=""))
    opened: list[bool] = []
    monkeypatch.setattr(window, "show_settings", lambda missing_key=False: opened.append(missing_key))

    assert window._load_config_for_request() is None
    assert opened == [True]
    assert manager.saved is False
    window.deleteLater()


def test_controller_close_hides_without_shutdown(qt_app) -> None:
    window, _manager, _hotkey = _window(qt_app)
    window.show()
    window.close()
    assert not window.isVisible()
    assert window._closing is False
    window.deleteLater()


def test_tray_capture_routes_to_lite_window(qt_app, monkeypatch) -> None:
    from app.lite_tray import VisionLiteTray

    tray = VisionLiteTray()
    window, _manager, _hotkey = _window(qt_app)
    called: list[bool] = []
    monkeypatch.setattr(window, "start_capture", lambda: called.append(True) or True)
    tray.capture_requested.connect(window.start_capture)
    tray.capture_requested.emit()
    assert called == [True]
    tray.deleteLater()
    window.deleteLater()


def test_tray_show_controller_routes_to_lite_window(qt_app, monkeypatch) -> None:
    from app.lite_tray import VisionLiteTray

    tray = VisionLiteTray()
    window, _manager, _hotkey = _window(qt_app)
    called: list[bool] = []
    monkeypatch.setattr(window, "show_controller", lambda: called.append(True))
    tray.show_controller_requested.connect(window.show_controller)
    tray.show_controller_requested.emit()
    assert called == [True]
    tray.deleteLater()
    window.deleteLater()


def test_tray_quit_routes_to_shutdown(qt_app) -> None:
    from app.lite_tray import VisionLiteTray

    tray = VisionLiteTray()
    called: list[bool] = []
    tray.quit_requested.connect(lambda: called.append(True))
    tray.quit_requested.emit()
    assert called == [True]
    tray.deleteLater()


def test_custom_shortcut_is_shown_on_controller(qt_app) -> None:
    window, _manager, hotkey = _window(qt_app, AppConfig(api_key="key", vision_global_shortcut="Ctrl+Shift+T"))
    hotkey._shortcut = "Ctrl+Shift+T"
    window.refresh_shortcut_label()
    assert "Ctrl+Shift+T" in window.shortcut_label.text()
    window.deleteLater()


def test_shortcut_label_refreshes_only_after_successful_rebind(qt_app) -> None:
    window, manager, hotkey = _window(qt_app)
    window.show_settings()
    settings = window._settings_window
    assert settings is not None
    settings.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+T"))
    settings.save()
    assert "Ctrl+Shift+T" in window.shortcut_label.text()
    assert manager.saved is True
    window.deleteLater()


def test_lite_settings_saves_key_and_shortcut(qt_app) -> None:
    from app.lite_settings import VisionLiteSettings

    manager = _ConfigManager(AppConfig(api_key="old-key"))
    hotkey = _Hotkey()
    dialog = VisionLiteSettings(manager, hotkey)
    dialog.api_key_edit.setText("new-key")
    dialog.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+T"))

    dialog.save()

    assert manager.saved is True
    assert manager.save_calls[0]["api_key"] == "new-key"
    assert manager.save_calls[0]["vision_global_shortcut"] == "Ctrl+Shift+T"
    assert hotkey.shortcut == "Ctrl+Shift+T"
    dialog.deleteLater()


def test_lite_settings_cancel_does_not_save(qt_app) -> None:
    from app.lite_settings import VisionLiteSettings

    manager = _ConfigManager(AppConfig(api_key="old-key"))
    dialog = VisionLiteSettings(manager, _Hotkey())
    dialog.api_key_edit.setText("new-key")
    dialog.reject()
    assert manager.saved is False
    dialog.deleteLater()


def test_lite_settings_invalid_shortcut_does_not_save(qt_app) -> None:
    from app.lite_settings import VisionLiteSettings

    manager = _ConfigManager(AppConfig(api_key="old-key"))
    dialog = VisionLiteSettings(manager, _Hotkey())
    dialog.shortcut_edit.clear()
    dialog.save()
    assert manager.saved is False
    assert dialog.status_label.text()
    dialog.deleteLater()


def test_lite_settings_rebind_failure_preserves_configuration(qt_app) -> None:
    from app.lite_settings import VisionLiteSettings

    manager = _ConfigManager(AppConfig(api_key="old-key"))
    dialog = VisionLiteSettings(manager, _FailingHotkey())
    dialog.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Shift+T"))
    dialog.save()
    assert manager.saved is False
    assert "注册失败" in dialog.status_label.text()
    dialog.deleteLater()


def test_lite_settings_connection_test_uses_short_timeout(qt_app, monkeypatch) -> None:
    from app import lite_settings

    manager = _ConfigManager(AppConfig(api_key="test-key", request_timeout=60.0))
    dialog = lite_settings.VisionLiteSettings(manager, _Hotkey())
    observed: list[float] = []

    class _Service:
        def __init__(self, config):
            observed.append(config.request_timeout)

        def test_connection(self, _cancel_event):
            return True

    monkeypatch.setattr(lite_settings, "DeepSeekService", _Service)
    dialog.test_connection()
    assert dialog.connection_running is True
    assert dialog.test_button.isEnabled() is False
    for _ in range(100):
        qt_app.processEvents()
        if not dialog.connection_running:
            break
        QTest.qWait(10)
    assert observed == [10.0]
    assert "成功" in dialog.status_label.text()
    assert dialog.test_button.isEnabled() is True
    dialog.deleteLater()


def test_lite_settings_connection_failure_is_user_visible(qt_app, monkeypatch) -> None:
    from app import lite_settings
    from app.services.deepseek_service import DeepSeekError

    manager = _ConfigManager(AppConfig(api_key="test-key"))
    dialog = lite_settings.VisionLiteSettings(manager, _Hotkey())

    class _Service:
        def __init__(self, _config):
            pass

        def test_connection(self, _cancel_event):
            raise DeepSeekError("DeepSeek API Key 无效（401）。")

    monkeypatch.setattr(lite_settings, "DeepSeekService", _Service)
    dialog.test_connection()
    for _ in range(100):
        qt_app.processEvents()
        if not dialog.connection_running:
            break
        QTest.qWait(10)
    assert "401" in dialog.status_label.text()
    assert dialog.test_button.isEnabled() is True
    dialog.deleteLater()


def test_lite_settings_close_cancels_connection_thread(qt_app, monkeypatch) -> None:
    from app import lite_settings

    manager = _ConfigManager(AppConfig(api_key="test-key"))
    dialog = lite_settings.VisionLiteSettings(manager, _Hotkey())

    class _Service:
        def __init__(self, _config):
            pass

        def test_connection(self, cancel_event):
            cancel_event.wait(0.1)

    monkeypatch.setattr(lite_settings, "DeepSeekService", _Service)
    dialog.test_connection()
    assert dialog.connection_running is True
    dialog.close()
    assert dialog.isVisible() is False
    for _ in range(100):
        qt_app.processEvents()
        if not dialog.connection_running:
            break
        QTest.qWait(10)
    assert dialog.connection_running is False
    dialog.deleteLater()


def test_lite_uses_independent_single_instance_name() -> None:
    assert vision_lite.LITE_SERVER_NAME == "tellme-sensei-lite-single-instance"


def test_lite_version_is_independent_from_full_version() -> None:
    from app.lite_version import __version__

    assert __version__ == "0.1.0"


def test_spec_has_lite_metadata_and_ocr_exclusions() -> None:
    source = Path("packaging/macos/tellme_sensei_vision_lite.spec").read_text(encoding="utf-8")
    assert "com.tellmesensei.vision-lite" in source
    assert '"CFBundleShortVersionString": LITE_VERSION' in source
    for forbidden in ("paddle", "paddleocr", "paddlex", "app.local_ocr", "google.cloud.vision"):
        assert forbidden in source
