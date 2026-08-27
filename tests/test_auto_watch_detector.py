import numpy as np
import pytest
from PySide6.QtGui import QImage

from app.auto_watch.detector import compare_frames, preprocess_qimage
from app.auto_watch.models import DetectorConfig, DetectorFrame


def test_compare_is_vectorized_and_handles_uint8_underflow():
    low = DetectorFrame(np.array([[0, 250]], dtype=np.uint8))
    high = DetectorFrame(np.array([[250, 0]], dtype=np.uint8))
    assert compare_frames(low, high, 15).change_ratio == 1.0


def test_bbox_and_threshold():
    a = DetectorFrame(np.zeros((10, 10), dtype=np.uint8))
    b = np.zeros((10, 10), dtype=np.uint8); b[2:4, 3:6] = 20
    metrics = compare_frames(a, b)
    assert metrics.change_ratio == pytest.approx(0.06)
    assert metrics.changed_bbox_ratio == pytest.approx(0.06)
    assert compare_frames(a, a).changed_bbox_ratio is None


def test_threshold_below_noise_is_ignored():
    a = DetectorFrame(np.zeros((4, 4), dtype=np.uint8))
    noisy = np.ones((4, 4), dtype=np.uint8) * 14
    assert compare_frames(a, noisy, 15).change_ratio == 0


def test_numpy_matches_small_scalar_reference():
    rng = np.random.default_rng(7)
    a = rng.integers(0, 256, (4, 5), dtype=np.uint8)
    b = rng.integers(0, 256, (4, 5), dtype=np.uint8)
    threshold = 31
    changed = [(y, x) for y in range(4) for x in range(5)
               if abs(int(a[y, x]) - int(b[y, x])) >= threshold]
    expected = len(changed) / 20
    assert compare_frames(DetectorFrame(a), DetectorFrame(b), threshold).change_ratio == expected


def test_qimage_padding_and_owned_frame(qt_app):
    image = QImage(7, 3, QImage.Format.Format_RGBA8888); image.fill(0xFFFFFFFF)
    frame = preprocess_qimage(image)
    assert frame.pixels.shape == (3, 7)
    image.fill(0)
    assert int(frame.pixels[0, 0]) == 255


def test_small_input_is_not_upscaled_and_large_input_preserves_ratio(qt_app):
    small = QImage(7, 3, QImage.Format.Format_RGBA8888)
    assert preprocess_qimage(small, 96).pixels.shape == (3, 7)
    large = QImage(300, 100, QImage.Format.Format_RGBA8888)
    assert preprocess_qimage(large, 96).pixels.shape == (32, 96)


def test_invalid_frames_fail():
    with pytest.raises(ValueError): compare_frames(np.zeros((2, 2)), np.zeros((2, 3)))
    with pytest.raises(ValueError): preprocess_qimage(QImage())
    with pytest.raises(ValueError): preprocess_qimage(QImage(2, 2, QImage.Format.Format_RGB32), 0)
    with pytest.raises(ValueError): compare_frames(np.zeros((1, 1)), np.zeros((1, 1)), 0)
    with pytest.raises(ValueError): compare_frames(np.zeros((1, 1)), np.zeros((1, 1)), 256)


def test_invalid_config_fails_with_clear_bounds():
    with pytest.raises(ValueError): DetectorConfig(max_side=0)
    with pytest.raises(ValueError): DetectorConfig(pixel_delta_threshold=0)
    with pytest.raises(ValueError): DetectorConfig(pixel_delta_threshold=256)
    with pytest.raises(ValueError): DetectorConfig(novelty_ratio=1.1)
