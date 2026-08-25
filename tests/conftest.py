from PySide6.QtWidgets import QApplication
import pytest


@pytest.fixture(autouse=True)
def windows_local_ocr_ui(monkeypatch):
    """Keep existing Local OCR UI tests host-independent with a dev source."""

    import app.ui.settings_window as settings_window_module

    monkeypatch.setattr(settings_window_module, "is_local_ocr_supported", lambda: True)
    monkeypatch.setattr(settings_window_module, "manifest_url_available", lambda _root=None: True)


@pytest.fixture(scope="session")
def qt_app():
    """Shared QApplication fixture for tests that exercise Qt objects."""
    return QApplication.instance() or QApplication([])
