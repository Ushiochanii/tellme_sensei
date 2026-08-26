"""Minimal settings dialog for the standalone Vision-only Lite app."""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QKeySequenceEdit,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.config import AppConfig, ConfigError, ConfigManager
from app.platform.base import GlobalHotkeyManager
from app.platform.hotkey import HotkeySpec, HotkeySpecError
from app.services.deepseek_service import DeepSeekError, DeepSeekService

logger = logging.getLogger(__name__)
CONNECTION_TEST_TIMEOUT = 10.0


class VisionLiteSettings(QDialog):
    """Edit only the API key and Vision shortcut used by Lite."""

    settings_saved = Signal()

    def __init__(
        self,
        config_manager: ConfigManager,
        hotkey_manager: GlobalHotkeyManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.hotkey_manager = hotkey_manager
        self._loaded_config = self._load_config()
        self.setWindowTitle("TellMeSensei Lite Settings")
        self.setModal(False)
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        if self._loaded_config.api_key:
            self.api_key_edit.setPlaceholderText("已配置（留空保持不变）")
        self.shortcut_edit = QKeySequenceEdit(
            QKeySequence(self._loaded_config.vision_global_shortcut)
        )
        form.addRow("DeepSeek API Key", self.api_key_edit)
        form.addRow("Vision Shortcut", self.shortcut_edit)
        root.addLayout(form)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.test_button = QPushButton("Test Connection")
        self.test_button.clicked.connect(self.test_connection)
        root.addWidget(self.test_button)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_config(self) -> AppConfig:
        try:
            return self.config_manager.load(require_api_key=False)
        except ConfigError:
            return AppConfig(api_key="")

    def show_missing_key_message(self) -> None:
        self.status_label.setText("请先输入并保存 DeepSeek API Key。")
        self.api_key_edit.setFocus()

    @Slot()
    def test_connection(self) -> None:
        config = self._config_for_request()
        if config is None:
            self.status_label.setText("请先输入 DeepSeek API Key。")
            return
        self.test_button.setEnabled(False)
        try:
            test_config = replace(config, request_timeout=min(config.request_timeout, CONNECTION_TEST_TIMEOUT))
            DeepSeekService(test_config).test_connection()
        except DeepSeekError as exc:
            self.status_label.setText(str(exc))
        except Exception:
            logger.exception("Vision Lite connection test failed")
            self.status_label.setText("连接测试失败，请检查网络和 API Key。")
        else:
            self.status_label.setText("连接成功。")
        finally:
            self.test_button.setEnabled(True)

    def _config_for_request(self) -> AppConfig | None:
        entered = self.api_key_edit.text().strip()
        if entered:
            return replace(self._loaded_config, api_key=entered)
        if self._loaded_config.api_key:
            return self._loaded_config
        return None

    @Slot()
    def save(self) -> None:
        try:
            shortcut = HotkeySpec.parse(self.shortcut_edit.keySequence().toString()).canonical
        except HotkeySpecError as exc:
            self.status_label.setText(str(exc))
            return

        manager = self.hotkey_manager
        old_shortcut = getattr(manager, "shortcut", shortcut) if manager is not None else shortcut
        old_registered = bool(getattr(manager, "registered", False)) if manager is not None else False
        changed = manager is not None and shortcut != old_shortcut
        if changed and not manager.rebind(shortcut):
            self.status_label.setText("快捷键注册失败，可能已被其他程序占用。")
            return

        entered_key = self.api_key_edit.text().strip()
        api_key = None
        has_env_override = getattr(self.config_manager, "has_explicit_api_key", lambda: False)()
        if entered_key and not has_env_override:
            if entered_key != self._loaded_config.api_key:
                api_key = entered_key
        try:
            self.config_manager.save_settings(
                api_key=api_key,
                model=self._loaded_config.model,
                request_timeout=self._loaded_config.request_timeout,
                vision_global_shortcut=shortcut,
            )
        except Exception as exc:
            if changed and manager is not None:
                if old_registered:
                    manager.rebind(old_shortcut)
                else:
                    manager.unregister()
            logger.warning("Vision Lite settings save failed exception_type=%s", type(exc).__name__)
            self.status_label.setText("设置保存失败。")
            return

        self._loaded_config = self._load_config()
        self.status_label.setText("设置已保存。")
        self.settings_saved.emit()
        self.accept()


__all__ = ["VisionLiteSettings", "CONNECTION_TEST_TIMEOUT"]
