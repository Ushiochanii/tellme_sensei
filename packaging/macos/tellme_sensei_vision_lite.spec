# -*- mode: python ; coding: utf-8 -*-
"""Minimal Apple Silicon Vision Lite application bundle."""

from pathlib import Path
import sys

ROOT = Path(SPECPATH).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.lite_version import __version__ as LITE_VERSION


version = LITE_VERSION


a = Analysis(
    [str(ROOT / "vision_lite.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "app.platform.macos.hotkey",
        "app.platform.macos.window",
        "app.platform.unsupported",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "app.ui.main_window",
        "app.ui.settings_window",
        "app.ui.tray",
        "app.workers.processing_worker",
        "app.ocr",
        "app.local_ocr",
        "paddle",
        "paddleocr",
        "paddlex",
        "ppocr",
        "ppstructure",
        "google.cloud.vision",
        "Cython",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TellMeSenseiLite",
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
    name="TellMeSenseiLite",
)

app = BUNDLE(
    coll,
    name="TellMeSensei Lite.app",
    bundle_identifier="com.tellmesensei.vision-lite",
    info_plist={
        "CFBundleDisplayName": "TellMeSensei Lite",
        "CFBundleName": "TellMeSensei Lite",
        "CFBundleShortVersionString": LITE_VERSION,
        "CFBundleVersion": LITE_VERSION,
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
