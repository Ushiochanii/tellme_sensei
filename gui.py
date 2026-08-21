"""Phase 7 tray-mode GUI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.logging_config import configure_logging
from app.platform.factory import create_global_hotkey_manager
from app.ui.application_controller import ApplicationController
from app.ui.main_window import MainWindow
from app.ui.tray import SystemTrayController

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study Assistant GUI Phase 7")
    parser.add_argument(
        "--show-window",
        action="store_true",
        help="显示保留的开发窗口；默认仅运行系统托盘模式。",
    )
    parser.add_argument(
        "--debug-capture",
        type=Path,
        default=None,
        help="可选：将本次框选结果保存到指定 PNG，用于确认截图区域。",
    )
    args = parser.parse_args(argv)
    configure_logging()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    logger.info("GUI 程序启动")

    window = MainWindow(debug_capture_path=args.debug_capture, tray_mode=not args.show_window)
    tray = SystemTrayController(parent=app)
    hotkey = create_global_hotkey_manager(parent=app)
    controller = ApplicationController(app, window, tray, hotkey)
    app.aboutToQuit.connect(controller.cleanup)
    controller.start(show_window=args.show_window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
