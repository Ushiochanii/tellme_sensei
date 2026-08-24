"""Platform capabilities for OCR components."""

from __future__ import annotations

import sys


def is_local_ocr_supported() -> bool:
    """Return whether the bundled Local OCR component is supported."""

    # The currently published component is a Windows executable.  Keep this
    # capability check separate from manifest validation so unsupported hosts
    # never expose a download action in the settings UI.
    return sys.platform == "win32"
