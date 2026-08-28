"""Repeatable offscreen benchmark for synthetic QImage detector inputs."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auto_watch.detector import compare_frames, preprocess_qimage
from app.auto_watch.models import DetectorFrame


def percentile(values: list[float], value: float) -> float:
    return float(np.percentile(np.asarray(values), value))


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark synthetic detector preprocessing and comparison.")
    parser.add_argument("--samples", type=int, default=100, help="number of measured samples (default: 100)")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    _app = QApplication.instance() or QApplication([])
    image = QImage(960, 540, QImage.Format.Format_RGBA8888)
    image.fill(0xFF808080)
    reference = DetectorFrame(np.full((54, 96), 128, dtype=np.uint8))
    preprocess_times: list[float] = []
    compare_times: list[float] = []
    for _ in range(args.samples):
        started = time.perf_counter()
        frame = preprocess_qimage(image)
        preprocess_times.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        compare_frames(frame, reference)
        compare_times.append((time.perf_counter() - started) * 1000)
    for name, values in (("preprocess", preprocess_times), ("compare", compare_times)):
        print(f"{name}: samples={len(values)} p50_ms={percentile(values, 50):.4f} "
              f"p95_ms={percentile(values, 95):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
