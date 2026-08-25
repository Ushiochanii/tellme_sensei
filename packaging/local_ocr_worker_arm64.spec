# -*- mode: python ; coding: utf-8 -*-
"""Native Apple Silicon onedir build for the PaddleOCR 3.x worker."""

from pathlib import Path
import sys
from importlib.metadata import PackageNotFoundError, requires

from packaging.requirements import Requirement
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))

datas = []
for package in ("paddle", "paddleocr", "paddlex"):
    datas.extend(collect_data_files(package, include_py_files=True))
for distribution in ("paddlepaddle", "paddleocr", "paddlex"):
    datas.extend(copy_metadata(distribution))
for requirement in requires("paddlex") or ():
    parsed = Requirement(requirement)
    marker = parsed.marker
    if marker is None or not any(
        marker.evaluate({"extra": extra}) for extra in ("ocr", "ocr-core")
    ):
        continue
    try:
        datas.extend(copy_metadata(parsed.name))
    except PackageNotFoundError:
        # OCR-only extras include optional document features that this worker
        # does not use; the OCR core alternative remains fully self-contained.
        continue

binaries = []
for package in ("paddle", "paddlex"):
    binaries.extend(collect_dynamic_libs(package))

hiddenimports = sorted(
    set(
        ["paddle", "paddleocr", "paddlex"]
        + collect_submodules("paddle")
        + collect_submodules("paddleocr")
        + collect_submodules("paddlex")
    )
)

a = Analysis(
    [str(ROOT / "local_ocr_worker.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TellMeSenseiOCR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LocalOCR",
)
