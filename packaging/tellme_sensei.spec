# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the Windows portable application."""

from pathlib import Path
import re
import sys

from PyInstaller.utils.hooks import (
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


keyring_hidden = collect_submodules("win32ctypes")
hiddenimports = sorted(
    set(
        keyring_hidden
        + [
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
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["paddle", "paddleocr", "ppocr", "ppstructure", "Cython"],
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
