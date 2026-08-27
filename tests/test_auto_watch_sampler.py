from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from app.auto_watch.sampler import ScreenSampler
from app.auto_watch.models import AutoWatchSettings


class FakeScreen:
    def geometry(self): return QRect(0, 0, 100, 50)
    def grabWindow(self, _): return QImage(200, 100, QImage.Format.Format_RGBA8888)


class FakePixmapScreen(FakeScreen):
    def grabWindow(self, _):
        from PySide6.QtGui import QPixmap
        return QPixmap.fromImage(QImage(200, 100, QImage.Format.Format_RGBA8888))


class ZeroGeometryScreen(FakeScreen):
    def geometry(self): return QRect(0, 0, 0, 50)


class EmptyCaptureScreen(FakeScreen):
    def grabWindow(self, _): return QImage()


class FractionalScaleScreen:
    def __init__(self, scale, geometry=QRect(-120, 40, 100, 80)):
        self._scale = scale
        self._geometry = geometry

    def geometry(self): return QRect(self._geometry)
    def grabWindow(self, _):
        return QImage(round(self._geometry.width() * self._scale),
                      round(self._geometry.height() * self._scale),
                      QImage.Format.Format_RGBA8888)


def test_logical_roi_maps_to_physical_and_samples(qt_app):
    sampler = ScreenSampler(FakeScreen(), QRect(10, 5, 20, 10))
    assert sampler.physical_roi() == QRect(20, 10, 40, 20)
    assert sampler.sample().size().width() == 40
    assert ScreenSampler(FakePixmapScreen(), QRect(10, 5, 20, 10)).sample().width() == 40


def test_mapping_and_sample_use_same_clipped_roi():
    sampler = ScreenSampler(FakeScreen(), QRect(90, 40, 30, 30))
    assert sampler.physical_roi() == QRect(180, 80, 20, 20)
    assert sampler.sample().size().width() == sampler.physical_roi().width()


def test_fractional_scale_covers_logical_roi_endpoints():
    for scale, expected in ((1.25, QRect(12, 6, 26, 13)), (1.5, QRect(15, 7, 30, 16))):
        sampler = ScreenSampler(FractionalScaleScreen(scale), QRect(10, 5, 20, 10))
        assert sampler.physical_roi() == expected
        assert sampler.sample().size() == expected.size()


def test_one_to_two_scale_mapping_keeps_integer_results():
    for scale, expected in ((1.0, QRect(10, 5, 20, 10)), (2.0, QRect(20, 10, 40, 20))):
        sampler = ScreenSampler(FractionalScaleScreen(scale), QRect(10, 5, 20, 10))
        assert sampler.physical_roi() == expected


def test_fractional_scale_clips_roi_at_physical_edges():
    sampler = ScreenSampler(FractionalScaleScreen(1.25), QRect(90, 70, 20, 20))
    assert sampler.physical_roi() == QRect(112, 87, 13, 13)
    assert sampler.sample().size() == sampler.physical_roi().size()


def test_empty_roi_rejected():
    import pytest
    with pytest.raises(ValueError): ScreenSampler(FakeScreen(), QRect())
    with pytest.raises(ValueError): ScreenSampler(ZeroGeometryScreen(), QRect(1, 1, 2, 2))


def test_empty_capture_and_fully_out_of_bounds_roi_raise_clear_errors():
    import pytest
    with pytest.raises(RuntimeError, match="empty image"):
        ScreenSampler(EmptyCaptureScreen(), QRect(1, 1, 2, 2)).sample()
    with pytest.raises(RuntimeError, match="outside the captured screen"):
        ScreenSampler(FractionalScaleScreen(1.25), QRect(101, 81, 2, 2)).sample()


def test_sampler_uses_shared_settings_for_timer_interval():
    class Timer:
        def setInterval(self, value): self.interval = value
        class timeout:
            @staticmethod
            def connect(_callback): pass
    settings = AutoWatchSettings(poll_interval_ms=73)
    sampler = ScreenSampler(FakeScreen(), QRect(1, 1, 2, 2), timer_factory=Timer, settings=settings)
    timer = sampler.create_timer(lambda: None)
    assert timer.interval == 73
