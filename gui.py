"""Phase 4-6 GUI entry point. Global hotkeys and system tray are not included yet."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.logging_config import configure_logging
from app.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study Assistant GUI Phase 4-6")
    parser.add_argument(
        "--debug-capture",
        type=Path,
        default=None,
        help="可选：将本次框选结果保存到指定 PNG，用于确认截图区域。",
    )
    args = parser.parse_args(argv)
    configure_logging()
    logging.getLogger(__name__).info("GUI 程序启动")

    app = QApplication(sys.argv)
    window = MainWindow(debug_capture_path=args.debug_capture)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
