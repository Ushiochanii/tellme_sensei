"""Phase 7 tray-mode GUI entry point."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.config import ConfigError, ConfigManager
from app.logging_config import configure_logging
from app.platform.factory import create_global_hotkey_manager
from app.platform.hotkey import DEFAULT_SHORTCUT
from app.runtime_paths import APPLICATION_DIRECTORY
from app.single_instance import SingleInstanceGuard
from app.ui.application_controller import ApplicationController
from app.ui.main_window import MainWindow
from app.ui.tray import SystemTrayController
from app.version import __version__

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
    parser.add_argument(
        "--smoke-core",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.smoke_core:
        return _smoke_core()

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
    except ConfigError as exc:
        logger.warning("invalid startup settings; using default shortcut: %s", exc)
        startup_shortcut = DEFAULT_SHORTCUT
    tray = SystemTrayController(parent=app)
    hotkey = create_global_hotkey_manager(parent=app, shortcut=startup_shortcut)
    window = MainWindow(
        debug_capture_path=args.debug_capture,
        tray_mode=not args.show_window,
        config_manager=config_manager,
        hotkey_manager=hotkey,
    )
    controller = ApplicationController(app, window, tray, hotkey)
    # Keep the Python wrapper alive as well as the QObject parent relationship.
    controller.single_instance_guard = single_instance
    app.aboutToQuit.connect(controller.cleanup)
    app.aboutToQuit.connect(single_instance.release)
    controller.start(show_window=args.show_window)
    return app.exec()


def _smoke_core() -> int:
    """Validate the frozen Core import graph without starting the GUI loop."""

    try:
        app = QApplication.instance() or QApplication([])
        app.setApplicationName(APPLICATION_DIRECTORY)
        app.setOrganizationName(APPLICATION_DIRECTORY)
        from app.config import ConfigManager
        from app.ocr.factory import create_ocr_provider
        from app.ocr.providers.google_vision import GoogleVisionOCRProvider
        from app.platform.factory import create_global_hotkey_manager
        from app.platform.hotkey import DEFAULT_SHORTCUT
        from app.services.deepseek_service import DeepSeekService

        config = ConfigManager().load(require_api_key=False)
        create_ocr_provider(config)
        GoogleVisionOCRProvider(api_key="diagnostic-key")
        DeepSeekService(config)
        create_global_hotkey_manager(parent=app, shortcut=DEFAULT_SHORTCUT)

        if getattr(sys, "frozen", False):
            for module_name in ("paddle", "paddleocr"):
                try:
                    importlib.import_module(module_name)
                except ModuleNotFoundError:
                    continue
                raise RuntimeError(f"forbidden Core dependency was bundled: {module_name}")
        return 0
    except Exception:
        if sys.stderr is not None:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
