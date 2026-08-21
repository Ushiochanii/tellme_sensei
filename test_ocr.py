"""Manual Phase 2 smoke test: python test_ocr.py path\to\test.png."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.logging_config import configure_logging
from app.services.ocr_service import OCRError, OCRService


def main() -> int:
    parser = argparse.ArgumentParser(description="Test PaddleOCR service")
    parser.add_argument("image", type=Path, help="待识别图片路径")
    args = parser.parse_args()
    configure_logging()
    try:
        result = OCRService().recognize(args.image)
    except OCRError as exc:
        print(f"测试失败：{exc}", file=sys.stderr)
        return 1
    print(result.text or "（没有识别到文字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
