"""Make PaddlePaddle 2.x discover its bundled macOS shared libraries."""

from __future__ import annotations

import site
import sys


if sys.platform == "darwin" and getattr(sys, "frozen", False):
    # PaddlePaddle 2.6.2 searches site.getsitepackages() for paddle/libs.
    # PyInstaller's onedir runtime stores that package below _MEIPASS instead.
    bundle_root = str(sys._MEIPASS)
    site.getsitepackages = lambda: [bundle_root]
