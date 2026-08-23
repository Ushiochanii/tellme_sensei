"""Runtime discovery for the optional external local OCR component."""

from __future__ import annotations

import sys
from pathlib import Path


def worker_script_path() -> Path:
    """Return the source-tree worker entry point used in development mode."""

    return Path(__file__).resolve().parents[2] / "local_ocr_worker.py"


def worker_executable_candidates() -> tuple[Path, ...]:
    """Return frozen component locations without assuming an install directory."""

    executable_dir = Path(sys.executable).resolve().parent
    return (
        executable_dir / "components" / "local-ocr" / "TellMeSenseiOCR.exe",
        executable_dir / "LocalOCR" / "TellMeSenseiOCR.exe",
        executable_dir / "TellMeSenseiOCR.exe",
    )
