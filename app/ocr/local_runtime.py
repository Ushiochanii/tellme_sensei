"""Runtime discovery for the optional external local OCR component."""

from __future__ import annotations

import sys
from pathlib import Path

from app.local_ocr.platform import current_spec
from app.local_ocr.version import current_local_ocr_version
from app.runtime_paths import user_runtime_directory

def worker_script_path() -> Path:
    """Return the source-tree worker entry point used in development mode."""

    return Path(__file__).resolve().parents[2] / "local_ocr_worker.py"


def worker_executable_candidates() -> tuple[Path, ...]:
    """Return user-installed and development component locations in priority order."""

    platform_spec = current_spec()
    executable_name = platform_spec.executable_name
    user_component = (
        user_runtime_directory()
        / "components"
        / "local-ocr"
        / current_local_ocr_version()
        / executable_name
    )
    repo_root = worker_script_path().parent
    executable_dir = Path(sys.executable).resolve().parent
    development_component = (
        repo_root
        / "dist"
        / f"local-ocr-{platform_spec.platform_id}"
        / "LocalOCR"
        / executable_name
    )
    candidates = (
        user_component,
        development_component,
        repo_root / "dist" / "LocalOCR" / executable_name,
        repo_root / "dist" / "local-ocr-macos-x64" / "LocalOCR" / executable_name,
        executable_dir / "components" / "local-ocr" / executable_name,
        executable_dir / "LocalOCR" / executable_name,
        executable_dir / executable_name,
    )
    # The platform-specific development path may be the existing x64 path;
    # keep discovery deterministic without returning that path twice.
    return tuple(dict.fromkeys(candidates))


def component_model_root(executable: Path) -> Path | None:
    """Return a component executable's sibling ``models`` directory."""

    sibling_models = executable.parent / "models"
    if sibling_models.is_dir():
        return sibling_models
    return None
