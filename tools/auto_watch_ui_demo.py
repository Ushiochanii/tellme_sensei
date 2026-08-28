"""Manual Phase 4B UI entry point; uses the normal MainWindow UI."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(auto_watch_fake=True)
    window.show_launcher()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
