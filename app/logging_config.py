"""Logging setup used by command-line entry points and services."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(project_root: Path | None = None) -> None:
    """Write operational logs to logs/app.log without including user/API data."""

    root = project_root or Path(__file__).resolve().parents[1]
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
