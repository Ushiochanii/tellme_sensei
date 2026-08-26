from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

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


class _ConfigManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.saved = False
        self.settings_repository = None

    def load(self, require_api_key: bool = True) -> AppConfig:
        if require_api_key and not self.config.api_key:
            raise RuntimeError("missing key")
        return self.config

    def save_settings(self, **_kwargs) -> None:
        self.saved = True


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
    monkeypatch.setattr(
        vision_lite.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("test-secret", False),
    )

    assert window._load_config_for_request() is None
    assert manager.saved is False
    window.deleteLater()
