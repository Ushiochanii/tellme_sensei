"""TellMeSensei tray-mode GUI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.core_smoke import run_core_smoke

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TellMeSensei desktop study assistant")
    parser.add_argument(
        "--show-window",
        action="store_true",
        help="兼容旧参数；浮动控制器现在默认显示。",
    )
    parser.add_argument(
        "--debug-capture",
        type=Path,
        default=None,
        help="可选：将本次框选结果保存到指定 PNG，用于确认截图区域。",
    )
    parser.add_argument(
        "--smoke-core",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.smoke_core:
        return _smoke_core()

    from PySide6.QtWidgets import QApplication

    from app.config import ConfigError, ConfigManager
    from app.logging_config import configure_logging
    from app.platform.factory import create_global_hotkey_manager
    from app.platform.hotkey import (
        DEFAULT_SHORTCUT,
        DEFAULT_VISION_SHORTCUT,
        TEXT_HOTKEY_ID,
        VISION_HOTKEY_ID,
    )
    from app.runtime_paths import APPLICATION_DIRECTORY
    from app.single_instance import SingleInstanceGuard
    from app.ui.application_controller import ApplicationController
    from app.ui.main_window import MainWindow
    from app.ui.tray import SystemTrayController
    from app.version import __version__

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APPLICATION_DIRECTORY)
    app.setOrganizationName(APPLICATION_DIRECTORY)
    single_instance = SingleInstanceGuard(parent=app)
    if not single_instance.acquire():
        return 0
    configure_logging()
    app.setQuitOnLastWindowClosed(False)
    logger.info("TellMeSensei version=%s", __version__)
    logger.info("GUI 程序启动")

    config_manager = ConfigManager()
    try:
        startup_config = config_manager.load(require_api_key=False)
        startup_shortcut = startup_config.global_shortcut
        startup_vision_shortcut = startup_config.vision_global_shortcut
    except ConfigError as exc:
        logger.warning("invalid startup settings; using default shortcut: %s", exc)
        startup_shortcut = DEFAULT_SHORTCUT
        startup_vision_shortcut = DEFAULT_VISION_SHORTCUT
    tray = SystemTrayController(parent=app)
    text_hotkey = create_global_hotkey_manager(
        parent=app,
        shortcut=startup_shortcut,
        hotkey_id=TEXT_HOTKEY_ID,
    )
    vision_hotkey = create_global_hotkey_manager(
        parent=app,
        shortcut=startup_vision_shortcut,
        hotkey_id=VISION_HOTKEY_ID,
    )
    window = MainWindow(
        debug_capture_path=args.debug_capture,
        tray_mode=False,
        config_manager=config_manager,
        hotkey_manager=text_hotkey,
        vision_hotkey_manager=vision_hotkey,
    )
    controller = ApplicationController(app, window, tray, text_hotkey, vision_hotkey)
    # Keep the Python wrapper alive as well as the QObject parent relationship.
    controller.single_instance_guard = single_instance
    app.aboutToQuit.connect(controller.cleanup)
    app.aboutToQuit.connect(single_instance.release)
    controller.start(show_window=True)
    return app.exec()


def _smoke_core() -> int:
    """Run the packaged Core integrity check without starting the GUI."""

    return run_core_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
