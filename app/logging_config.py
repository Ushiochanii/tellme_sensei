"""Logging setup used by command-line entry points and services."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import gettempdir

from app.runtime_paths import APPLICATION_DIRECTORY, default_log_path


def configure_logging(project_root: Path | None = None) -> None:
    """Configure logging without writing to the source tree by default.

    ``project_root`` is an explicit test/development override retained for
    callers that need an isolated log directory.
    """

    log_file = (
        Path(project_root) / "logs" / "app.log"
        if project_root is not None
        else default_log_path()
    )
    log_dir = log_file.parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        if project_root is not None:
            raise
        log_file = Path(gettempdir()) / APPLICATION_DIRECTORY / "logs" / "app.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
