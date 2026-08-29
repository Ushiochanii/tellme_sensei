from __future__ import annotations

from pathlib import Path

from app.config import ConfigManager
from app.logging_config import read_log_tail
from app.local_ocr.component_manager import LocalOCRComponentManager
from app.settings.repository import SettingsRepository
from app.ui.settings_window import SettingsWindow


def test_read_log_tail_is_bounded_and_redacts_secret_values(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text(
        "line-1\nline-2\napi_key=do-not-show\nline-4\n",
        encoding="utf-8",
    )

    assert read_log_tail(path, max_bytes=1024, max_lines=2) == "api_key=[REDACTED]\nline-4"


def test_read_log_tail_redacts_authorization_and_quoted_credentials(tmp_path: Path) -> None:
    secrets = (
        "Bearer bearer-secret-value",
        "api-secret-value",
        "token with spaces",
        "password-secret-value",
    )
    path = tmp_path / "app.log"
    path.write_text(
        "\n".join(
            (
                "Authorization: Bearer bearer-secret-value",
                "api_key='api-secret-value' other=keep",
                'token: "token with spaces"',
                "password=password-secret-value",
            )
        ),
        encoding="utf-8",
    )

    redacted = read_log_tail(path, max_bytes=1024, max_lines=20)

    for secret in secrets:
        assert secret not in redacted
    assert "Authorization: Bearer [REDACTED]" in redacted
    assert "other=keep" in redacted


def test_debug_page_reports_missing_log_and_refreshes_tail(qt_app, tmp_path: Path) -> None:
    log_path = tmp_path / "app.log"
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
    )
    window = SettingsWindow(
        config_manager=manager,
        component_manager=LocalOCRComponentManager(tmp_path / "runtime"),
        log_path=log_path,
    )

    assert "No runtime log" in window.debug_log_status_label.text()
    log_path.write_text("first\nsecond\n", encoding="utf-8")
    window.refresh_debug_log()
    assert window.debug_log_view.toPlainText() == "first\nsecond"
    assert "2 log lines" in window.debug_log_status_label.text()
    window.deleteLater()
    qt_app.processEvents()


def test_debug_page_reports_read_error(qt_app, tmp_path: Path, monkeypatch) -> None:
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
    )
    window = SettingsWindow(
        config_manager=manager,
        component_manager=LocalOCRComponentManager(tmp_path / "runtime"),
        log_path=tmp_path / "app.log",
    )
    monkeypatch.setattr(
        "app.ui.settings_window.read_log_tail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    window.refresh_debug_log()

    assert window.debug_log_view.toPlainText() == ""
    assert "Unable to read" in window.debug_log_status_label.text()
    window.deleteLater()
    qt_app.processEvents()


def test_local_ocr_download_failure_survives_finished_refresh(qt_app, tmp_path: Path) -> None:
    manager = ConfigManager(
        project_root=tmp_path,
        settings_repository=SettingsRepository(tmp_path / "settings.json"),
    )
    window = SettingsWindow(
        config_manager=manager,
        component_manager=LocalOCRComponentManager(tmp_path / "runtime"),
        log_path=tmp_path / "app.log",
    )

    window._on_local_ocr_download_failed(
        "Unable to download the Local OCR manifest (HTTP 404)."
    )
    window._on_local_ocr_download_finished()

    assert "HTTP 404" in window.local_ocr_status_label.text()
    window.deleteLater()
    qt_app.processEvents()
