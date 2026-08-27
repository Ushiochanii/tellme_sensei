from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from app.auto_watch.sampler import ScreenSampler


class FakeScreen:
    def geometry(self): return QRect(0, 0, 100, 50)
    def grabWindow(self, _): return QImage(200, 100, QImage.Format.Format_RGBA8888)


class FakePixmapScreen(FakeScreen):
    def grabWindow(self, _):
        from PySide6.QtGui import QPixmap
        return QPixmap.fromImage(QImage(200, 100, QImage.Format.Format_RGBA8888))


class ZeroGeometryScreen(FakeScreen):
    def geometry(self): return QRect(0, 0, 0, 50)


def test_logical_roi_maps_to_physical_and_samples():
    sampler = ScreenSampler(FakeScreen(), QRect(10, 5, 20, 10))
    assert sampler.physical_roi() == QRect(20, 10, 40, 20)
    assert sampler.sample().size().width() == 40
    assert ScreenSampler(FakePixmapScreen(), QRect(10, 5, 20, 10)).sample().width() == 40


def test_mapping_and_sample_use_same_clipped_roi():
    sampler = ScreenSampler(FakeScreen(), QRect(90, 40, 30, 30))
    assert sampler.physical_roi() == QRect(180, 80, 20, 20)
    assert sampler.sample().size().width() == sampler.physical_roi().width()


def test_empty_roi_rejected():
    import pytest
    with pytest.raises(ValueError): ScreenSampler(FakeScreen(), QRect())
    with pytest.raises(ValueError): ScreenSampler(ZeroGeometryScreen(), QRect(1, 1, 2, 2))
