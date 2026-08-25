"""Validation for PaddleOCR model directory layouts."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path


class ModelLayoutError(ValueError):
    """Raised when a component-owned model directory is incomplete or mixed."""


class ModelLayout(StrEnum):
    """Supported PaddleOCR inference model layouts."""

    PADDLEOCR_2 = "paddleocr-2.x"
    PADDLEX_3 = "paddlex-3.x"


_REQUIRED_FILES: dict[ModelLayout, frozenset[str]] = {
    ModelLayout.PADDLEOCR_2: frozenset({"inference.pdmodel", "inference.pdiparams"}),
    ModelLayout.PADDLEX_3: frozenset({"inference.json", "inference.yml", "inference.pdiparams"}),
}


def detect_model_layout(model_dir: Path) -> ModelLayout | None:
    """Return the validated layout for one model directory, or ``None``."""

    if not model_dir.is_dir():
        return None
    present = {name for name in _all_required_names() if (model_dir / name).is_file()}
    matches = [
        layout
        for layout, required in _REQUIRED_FILES.items()
        if required <= present
    ]
    if len(matches) > 1:
        raise ModelLayoutError(f"mixed PaddleOCR model layouts: {model_dir}")
    if not matches:
        return None
    if matches == [ModelLayout.PADDLEX_3] and model_name_from_directory(model_dir) is None:
        return None
    return matches[0]


def model_name_from_directory(model_dir: Path) -> str | None:
    """Read the PaddleX model name needed when loading a 3.x directory."""

    config_path = model_dir / "inference.yml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = re.search(r"^\s*model_name:\s*([^#\s]+)\s*$", text, flags=re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip("'\"") or None


def find_model_pair(model_root: Path) -> tuple[Path, Path]:
    """Find a complete det/rec pair and require both sides to use one layout."""

    if not model_root.is_dir():
        raise ModelLayoutError(f"Local OCR model root does not exist: {model_root}")
    resolved: list[tuple[Path, ModelLayout]] = []
    for kind in ("det", "rec"):
        kind_root = model_root / kind
        candidates = _candidate_directories(kind_root)
        if not candidates:
            raise ModelLayoutError(f"Local OCR {kind} model files are missing.")
        layouts = [(path, detect_model_layout(path)) for path in candidates]
        complete = [(path, layout) for path, layout in layouts if layout is not None]
        if not complete:
            raise ModelLayoutError(f"Local OCR {kind} model directory is incomplete.")
        complete_layouts = {layout for _, layout in complete}
        if len(complete_layouts) > 1:
            raise ModelLayoutError(
                f"Local OCR {kind} model directories use mixed PaddleOCR layouts."
            )
        resolved.append(complete[0])

    if resolved[0][1] is not resolved[1][1]:
        raise ModelLayoutError(
            "Local OCR det and rec models use mixed PaddleOCR layouts."
        )
    return resolved[0][0], resolved[1][0]


def model_root_is_complete(model_root: Path) -> bool:
    """Return whether a model root contains one complete det/rec layout."""

    try:
        find_model_pair(model_root)
    except ModelLayoutError:
        return False
    return True


def _candidate_directories(kind_root: Path) -> list[Path]:
    if not kind_root.is_dir():
        return []
    candidates: set[Path] = set()
    for filename in _all_required_names():
        candidates.update(path.parent for path in kind_root.rglob(filename))
    return sorted(candidates)


def _all_required_names() -> frozenset[str]:
    names: set[str] = set()
    for required in _REQUIRED_FILES.values():
        names.update(required)
    return frozenset(names)


__all__ = [
    "ModelLayout",
    "ModelLayoutError",
    "detect_model_layout",
    "find_model_pair",
    "model_name_from_directory",
    "model_root_is_complete",
]
