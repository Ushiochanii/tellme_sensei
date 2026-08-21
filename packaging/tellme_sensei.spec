# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the Windows portable application."""

from pathlib import Path
import sys

import sysconfig

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


ROOT = Path(SPECPATH).resolve().parent


site_packages = Path(sysconfig.get_paths()["purelib"])
paddleocr_package_path = site_packages / "paddleocr"
datas = collect_data_files("paddleocr")
sys.path.insert(0, str(paddleocr_package_path))

# PaddleOCR 2.x imports these directories as top-level modules at runtime.
# Adding its package directory to pathex preserves that upstream layout.
paddleocr_hidden = (
    collect_submodules("ppocr")
    + collect_submodules("ppstructure")
    + collect_submodules("tools.infer")
)
keyring_hidden = collect_submodules("win32ctypes")

binaries = collect_dynamic_libs("paddle")
hiddenimports = sorted(
    set(
        paddleocr_hidden
        + keyring_hidden
        + [
            "paddle",
            "paddleocr",
            "keyring",
            "keyring.backends.Windows",
            "win32ctypes",
            "win32ctypes.pywin32",
            "win32ctypes.pywin32.pywintypes",
            "win32ctypes.pywin32.win32cred",
            "openai",
        ]
    )
)

a = Analysis(
    [str(ROOT / "gui.py")],
    pathex=[str(ROOT), str(site_packages), str(paddleocr_package_path)],
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
    a.binaries,
    a.datas,
    [],
    name="TellMeSensei",
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
    name="TellMeSensei",
)
