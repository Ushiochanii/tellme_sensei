from pathlib import Path

import pytest

from app.local_ocr.model_layout import (
    ModelLayout,
    ModelLayoutError,
    detect_model_layout,
    find_model_pair,
    model_name_from_directory,
    model_root_is_complete,
)


def _write_model(root: Path, kind: str, name: str, files: tuple[str, ...]) -> Path:
    model_dir = root / kind / name
    model_dir.mkdir(parents=True)
    for filename in files:
        (model_dir / filename).write_bytes(b"model")
    return model_dir


def test_valid_2x_det_and_rec_layout_is_detected(tmp_path: Path) -> None:
    files = ("inference.pdmodel", "inference.pdiparams")
    det = _write_model(tmp_path, "det", "det-2", files)
    rec = _write_model(tmp_path, "rec", "rec-2", files)

    assert detect_model_layout(det) is ModelLayout.PADDLEOCR_2
    assert detect_model_layout(rec) is ModelLayout.PADDLEOCR_2
    assert find_model_pair(tmp_path) == (det, rec)
    assert model_root_is_complete(tmp_path)
    assert model_name_from_directory(det) is None


def test_valid_3x_det_and_rec_layout_is_detected(tmp_path: Path) -> None:
    files = ("inference.json", "inference.yml", "inference.pdiparams")
    det = _write_model(tmp_path, "det", "det-3", files)
    rec = _write_model(tmp_path, "rec", "rec-3", files)
    (det / "inference.yml").write_text("Global:\n  model_name: test_det\n", encoding="utf-8")
    (rec / "inference.yml").write_text("Global:\n  model_name: test_rec\n", encoding="utf-8")

    assert detect_model_layout(det) is ModelLayout.PADDLEX_3
    assert detect_model_layout(rec) is ModelLayout.PADDLEX_3
    assert find_model_pair(tmp_path) == (det, rec)
    assert model_root_is_complete(tmp_path)
    assert model_name_from_directory(det) == "test_det"
    assert model_name_from_directory(rec) == "test_rec"


@pytest.mark.parametrize(
    "files",
    [
        ("inference.pdmodel",),
        ("inference.pdiparams",),
        ("inference.json", "inference.pdiparams"),
        ("inference.yml", "inference.pdiparams"),
    ],
)
def test_incomplete_model_layout_is_rejected(tmp_path: Path, files: tuple[str, ...]) -> None:
    _write_model(tmp_path, "det", "det-incomplete", files)
    _write_model(tmp_path, "rec", "rec-incomplete", files)

    assert not model_root_is_complete(tmp_path)
    with pytest.raises(ModelLayoutError):
        find_model_pair(tmp_path)


def test_mixed_2x_and_3x_model_layout_is_rejected(tmp_path: Path) -> None:
    _write_model(tmp_path, "det", "det-2", ("inference.pdmodel", "inference.pdiparams"))
    rec = _write_model(tmp_path, "rec", "rec-3", ("inference.json", "inference.yml", "inference.pdiparams"))
    (rec / "inference.yml").write_text("Global:\n  model_name: test_rec\n", encoding="utf-8")

    assert not model_root_is_complete(tmp_path)
    with pytest.raises(ModelLayoutError, match="mixed"):
        find_model_pair(tmp_path)


def test_mixed_layouts_within_one_model_kind_are_rejected(tmp_path: Path) -> None:
    _write_model(tmp_path, "det", "det-2", ("inference.pdmodel", "inference.pdiparams"))
    det_3 = _write_model(
        tmp_path,
        "det",
        "det-3",
        ("inference.json", "inference.yml", "inference.pdiparams"),
    )
    (det_3 / "inference.yml").write_text("Global:\n  model_name: test_det\n", encoding="utf-8")
    _write_model(tmp_path, "rec", "rec-2", ("inference.pdmodel", "inference.pdiparams"))

    with pytest.raises(ModelLayoutError, match="mixed"):
        find_model_pair(tmp_path)


def test_model_directory_with_both_layouts_is_rejected(tmp_path: Path) -> None:
    model = _write_model(
        tmp_path,
        "det",
        "mixed",
        (
            "inference.pdmodel",
            "inference.pdiparams",
            "inference.json",
            "inference.yml",
        ),
    )
    assert model.exists()
    with pytest.raises(ModelLayoutError, match="mixed"):
        detect_model_layout(model)


def test_3x_model_without_model_name_config_is_rejected(tmp_path: Path) -> None:
    model = _write_model(
        tmp_path,
        "det",
        "missing-name",
        ("inference.json", "inference.yml", "inference.pdiparams"),
    )
    assert detect_model_layout(model) is None
