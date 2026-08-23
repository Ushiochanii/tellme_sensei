# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the external PaddleOCR worker."""

from pathlib import Path
import sys
import sysconfig

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))

site_packages = Path(sysconfig.get_paths()["purelib"])
paddleocr_package_path = site_packages / "paddleocr"
paddleocr_e2e_path = paddleocr_package_path / "ppocr" / "utils" / "e2e_utils"
paddleocr_datas = collect_data_files("paddleocr", include_py_files=True)
cython_datas = collect_data_files("Cython", includes=["Utility/**/*"])
datas = paddleocr_datas + cython_datas
sys.path.insert(0, str(paddleocr_package_path))

# PaddleOCR 2.x imports these directories as top-level modules at runtime.
paddleocr_hidden = (
    collect_submodules("ppocr")
    + collect_submodules("ppstructure")
    + collect_submodules("tools.infer")
)
binaries = collect_dynamic_libs("paddle")
hiddenimports = sorted(
    set(
        paddleocr_hidden
        + [
            "paddle",
            "paddleocr",
            "extract_textpoint_slow",
            "extract_textpoint_fast",
        ]
    )
)

a = Analysis(
    [str(ROOT / "local_ocr_worker.py")],
    pathex=[
        str(ROOT),
        str(site_packages),
        str(paddleocr_package_path),
        str(paddleocr_e2e_path),
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
