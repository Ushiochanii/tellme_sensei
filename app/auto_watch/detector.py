from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage

from .models import DetectorFrame, DetectorMetrics


def preprocess_qimage(image: QImage, max_side: int = 96) -> DetectorFrame:
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError("cannot preprocess a null or empty QImage")
    if max_side < 1:
        raise ValueError("max_side must be positive")
    scale = min(1.0, max_side / max(image.width(), image.height()))
    size = QSize(max(1, round(image.width() * scale)), max(1, round(image.height() * scale)))
    scaled = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    rgba = scaled.convertToFormat(QImage.Format.Format_RGBA8888)
    stride, height = rgba.bytesPerLine(), rgba.height()
    raw = np.frombuffer(rgba.constBits(), dtype=np.uint8, count=stride * height)
    rows = raw.reshape(height, stride)[:, : rgba.width() * 4].reshape(height, rgba.width(), 4)
    # ITU-R BT.601 luminance, with an owned copy so Qt buffer lifetime is irrelevant.
    gray = np.rint(rows[..., :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)).astype(np.uint8)
    return DetectorFrame(gray)


def compare_frames(current: DetectorFrame | np.ndarray, reference: DetectorFrame | np.ndarray,
                   pixel_delta_threshold: int = 15) -> DetectorMetrics:
    a = np.asarray(current.pixels if isinstance(current, DetectorFrame) else current, dtype=np.uint8)
    b = np.asarray(reference.pixels if isinstance(reference, DetectorFrame) else reference, dtype=np.uint8)
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape or 0 in a.shape:
        raise ValueError("frames must be non-empty 2-D arrays with identical dimensions")
    if not 1 <= pixel_delta_threshold <= 255:
        raise ValueError("pixel_delta_threshold must be between 1 and 255")
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
    changed = delta >= pixel_delta_threshold
    ratio = float(changed.mean())
    if not changed.any():
        bbox_ratio = None
    else:
        ys, xs = np.nonzero(changed)
        bbox_ratio = float((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1) / changed.size)
    return DetectorMetrics(ratio, bbox_ratio)
