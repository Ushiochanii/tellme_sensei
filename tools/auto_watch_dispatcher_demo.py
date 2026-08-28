"""Small terminal demo for the Phase 3 dispatcher (fake by default)."""
from __future__ import annotations
import argparse
import logging
from pathlib import Path
import sys

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.analysis import AnalysisMode
from app.auto_watch import AnalysisDispatcher, AnalysisState, AutoWatchSettings
from app.config import ConfigManager


class FakeWorker(QObject):
    result_ready = Signal(object); error_occurred = Signal(str); cancelled = Signal(); finished = Signal()
    def __init__(self, request): super().__init__(); self.request = request
    def start(self): self.run()
    def run(self):
        print(f"active generation={self.request.generation} mode={self.request.mode.value}")
        self.result_ready.emit("fake result (no network)")
        self.finished.emit()
    def request_cancel(self): print(f"cancel requested generation={self.request.generation}")


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", choices=["text", "vision"], default="text")
    parser.add_argument("--real", action="store_true", help="use injected existing pipeline (requires application config)")
    parser.add_argument("--delay-ms", type=int, default=0); args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = QApplication.instance() or QApplication([sys.argv[0]])
    mode = AnalysisMode(args.mode)
    def finished(request):
        print(f"finished generation={request.generation} state={dispatcher.state.name} active={bool(dispatcher.active_request)} pending={bool(dispatcher.pending_request)}")
        app.quit()
    if args.real:
        config = ConfigManager().load(require_api_key=True)
        dispatcher = AnalysisDispatcher(settings=AutoWatchSettings(analysis_delay_ms=args.delay_ms), config=config,
                                        on_finished=finished)
    else:
        dispatcher = AnalysisDispatcher(settings=AutoWatchSettings(analysis_delay_ms=args.delay_ms),
                                        worker_factory=FakeWorker,
                                        on_finished=finished)
    dispatcher.submit(QImage(640, 360, QImage.Format.Format_RGBA8888), mode)
    print(f"state={dispatcher.state.name} active={bool(dispatcher.active_request)} pending={bool(dispatcher.pending_request)} generation={dispatcher.generation}")
    # Keep the event loop alive during both the configured delay and active work.
    # For delay=0 the finished callback has already requested quit, so exec returns immediately.
    app.exec()


if __name__ == "__main__": main()
