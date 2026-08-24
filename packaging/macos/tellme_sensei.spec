# -*- mode: python ; coding: utf-8 -*-
"""Minimal macOS app bundle for the tray-based Core application."""

from pathlib import Path
import sys


ROOT = Path(SPECPATH).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.version import __version__


a = Analysis(
    [str(ROOT / "gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TellMeSensei",
)

app = BUNDLE(
    coll,
    name="TellMeSensei.app",
    bundle_identifier="com.tellmesensei.app",
    version=__version__,
    info_plist={
        "CFBundleDisplayName": "TellMeSensei",
        "CFBundleName": "TellMeSensei",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
