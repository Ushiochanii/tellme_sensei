# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the Windows portable application."""

from pathlib import Path
import re
import sys

import sysconfig

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))

from app.version import __version__


def _version_info_file() -> Path:
    """Create PyInstaller's VERSIONINFO from the single app version source."""

    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", __version__)
    if match is None:
        raise ValueError(f"Unsupported application version: {__version__!r}")
    major, minor, patch = (int(part) for part in match.groups())
    version_file = ROOT / "build" / "version_info.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(
        """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [StringTable(
        '040904B0',
        [StringStruct('CompanyName', ''),
        StringStruct('FileDescription', 'TellMeSensei Study Assistant'),
        StringStruct('FileVersion', '{major}.{minor}.{patch}.0'),
        StringStruct('InternalName', 'TellMeSensei'),
        StringStruct('OriginalFilename', 'TellMeSensei.exe'),
        StringStruct('ProductName', 'TellMeSensei'),
        StringStruct('ProductVersion', '{product_version}'),
        StringStruct('LegalCopyright', '')]
      )]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)""".format(
            major=major,
            minor=minor,
            patch=patch,
            product_version=__version__,
        ),
        encoding="utf-8",
    )
    return version_file


icon_path = ROOT / "assets" / "tellme_sensei.ico"
if not icon_path.is_file():
    raise FileNotFoundError(f"Application icon was not found: {icon_path}")
version_file = _version_info_file()


site_packages = Path(sysconfig.get_paths()["purelib"])
paddleocr_package_path = site_packages / "paddleocr"
paddleocr_e2e_path = paddleocr_package_path / "ppocr" / "utils" / "e2e_utils"
paddleocr_datas = collect_data_files(
    "paddleocr",
    include_py_files=True,
)
cython_datas = collect_data_files(
    "Cython",
    includes=["Utility/**/*"],
)
datas = paddleocr_datas + cython_datas
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
            "extract_textpoint_slow",
            "extract_textpoint_fast",
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
    name="TellMeSensei",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path),
    version=str(version_file),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TellMeSensei",
)
