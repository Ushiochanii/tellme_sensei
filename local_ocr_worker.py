"""Source and PyInstaller entry point for TellMeSenseiOCR."""

from app.local_ocr.worker_main import main


if __name__ == "__main__":
    raise SystemExit(main())
