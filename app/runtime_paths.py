"""User-writable paths used by the running application."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths


APPLICATION_DIRECTORY = "TellMeSensei"


def user_runtime_directory() -> Path:
    """Return the per-user application data directory."""

    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not location:
        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
    if not location:
        raise RuntimeError("无法确定应用运行时数据目录")

    path = Path(location)
    application_name = QCoreApplication.applicationName().strip()
    if (
        path.name.lower() == APPLICATION_DIRECTORY.lower()
        and path.parent.name.lower() == APPLICATION_DIRECTORY.lower()
    ):
        path = path.parent
    elif not application_name or application_name.lower() != APPLICATION_DIRECTORY.lower():
        path = path / APPLICATION_DIRECTORY
    return path


def default_log_path() -> Path:
    """Return the user-writable operational log path."""

    return user_runtime_directory() / "logs" / "app.log"
