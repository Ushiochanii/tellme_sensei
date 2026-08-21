from PySide6.QtWidgets import QApplication
import pytest


@pytest.fixture(scope="session")
def qt_app():
    """Shared QApplication fixture for tests that exercise Qt objects."""
    return QApplication.instance() or QApplication([])
