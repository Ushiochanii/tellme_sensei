from PySide6.QtWidgets import QApplication
import pytest


class _TestKeyring:
    """In-memory keyring used by pytest; never delegates to the OS backend."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


@pytest.fixture(autouse=True)
def isolated_keyring(monkeypatch):
    """Prevent tests from ever resolving the developer's OS keyring."""

    import keyring
    import keyring.core

    backend = _TestKeyring()
    # keyring.get_password is exported from keyring.core, so replacing only
    # keyring.get_keyring would leave the real backend reachable. Patching the
    # resolver function avoids mutating native backend state at test teardown.
    monkeypatch.setattr(keyring.core, "get_keyring", lambda: backend)
    return backend


@pytest.fixture(autouse=True)
def isolated_secret_environment(monkeypatch):
    """Keep developer credentials out of every pytest configuration load."""

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)


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
