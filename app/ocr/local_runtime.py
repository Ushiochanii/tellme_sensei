"""Runtime discovery for the optional external local OCR component."""

from __future__ import annotations

import sys
from pathlib import Path

from app.local_ocr.platform import current_spec
from app.local_ocr.version import LOCAL_OCR_VERSION
from app.runtime_paths import user_runtime_directory

def worker_script_path() -> Path:
    """Return the source-tree worker entry point used in development mode."""

    return Path(__file__).resolve().parents[2] / "local_ocr_worker.py"


def worker_executable_candidates() -> tuple[Path, ...]:
    """Return user-installed and development component locations in priority order."""

    executable_name = current_spec().executable_name
    user_component = (
        user_runtime_directory()
        / "components"
        / "local-ocr"
        / LOCAL_OCR_VERSION
        / executable_name
    )
    repo_root = worker_script_path().parent
    executable_dir = Path(sys.executable).resolve().parent
    return (
        user_component,
        repo_root / "dist" / "LocalOCR" / executable_name,
        repo_root / "dist" / "local-ocr-macos-x64" / "LocalOCR" / executable_name,
        executable_dir / "components" / "local-ocr" / executable_name,
        executable_dir / "LocalOCR" / executable_name,
        executable_dir / executable_name,
    )


def component_model_root(executable: Path) -> Path | None:
    """Return the model directory for an installed component executable."""

    if executable.parent.parent.name == "local-ocr":
        return executable.parent / "models"
    return None
