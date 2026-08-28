from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
import pytest

from app.auto_watch.models import ContextQuestionRegions, WatchRegion, WatchRegionRole
from app.auto_watch.pair_sampler import ContextQuestionSampler


class FakeScreen:
    def __init__(self, geometry=QRect(0, 0, 100, 50), scale=2.0):
        self._geometry = QRect(geometry)
        self.scale = scale
        self.grab_calls = 0

    def geometry(self):
        return QRect(self._geometry)

    def devicePixelRatio(self):
        return self.scale

    def grabWindow(self, _window):
        self.grab_calls += 1
        image = QImage(round(self._geometry.width() * self.scale),
                       round(self._geometry.height() * self.scale),
                       QImage.Format.Format_RGBA8888)
        image.fill(QColor("black"))
        painter = QPainter(image)
        painter.fillRect(QRect(20, 10, 40, 20), QColor("red"))
        painter.fillRect(QRect(100, 40, 20, 20), QColor("blue"))
        painter.end()
        return image


def make_regions(screen=None, *, context_session="session-1", question_session=None):
    screen = screen or FakeScreen()
    question_session = question_session or context_session
    context = WatchRegion.create(screen, QRect(10, 5, 20, 10), context_session)
    question = WatchRegion.create(screen, QRect(50, 20, 10, 10), question_session)
    return ContextQuestionRegions.create(context, question)


def test_region_roles_and_same_screen_model_validation():
    assert WatchRegionRole.CONTEXT.value == "context"
    assert WatchRegionRole.QUESTION.value == "question"
    regions = make_regions()
    assert regions.screen_geometry == QRect(0, 0, 100, 50)
    assert regions.device_pixel_ratio == 2.0

    other_screen = FakeScreen()
    context = WatchRegion.create(other_screen, QRect(10, 5, 20, 10), "session-1")
    with pytest.raises(ValueError, match="same screen"):
        ContextQuestionRegions.create(context, regions.question)

    different_session = WatchRegion.create(regions.screen, QRect(50, 20, 10, 10), "session-2")
    with pytest.raises(ValueError, match="same session"):
        ContextQuestionRegions.create(regions.context, different_session)

    from dataclasses import replace
    with pytest.raises(ValueError, match="same screen geometry"):
        ContextQuestionRegions.create(regions.context, replace(regions.question, screen_geometry=QRect(0, 0, 101, 50)))
    with pytest.raises(ValueError, match="same device pixel ratio"):
        ContextQuestionRegions.create(regions.context, replace(regions.question, device_pixel_ratio=1.5))


def test_pair_sampler_grabs_once_and_returns_two_physical_crops():
    screen = FakeScreen()
    sampler = ContextQuestionSampler(make_regions(screen))

    images = sampler.sample()

    assert screen.grab_calls == 1
    assert (images.context.width(), images.context.height()) == (40, 20)
    assert (images.question.width(), images.question.height()) == (20, 20)
    assert images.context.pixelColor(0, 0) == QColor("red")
    assert images.question.pixelColor(0, 0) == QColor("blue")


def test_pair_sampler_mapping_preserves_fractional_scale_and_timer_settings():
    from app.auto_watch.models import AutoWatchSettings

    screen = FakeScreen(scale=1.25)
    sampler = ContextQuestionSampler(make_regions(screen), AutoWatchSettings(poll_interval_ms=73))
    context = sampler.sample().context
    assert (context.width(), context.height()) == (26, 13)

    class Timer:
        def setInterval(self, value):
            self.interval = value

        class timeout:
            @staticmethod
            def connect(_callback):
                pass

    timed = ContextQuestionSampler(make_regions(FakeScreen()), timer_factory=Timer,
                                   settings=AutoWatchSettings(poll_interval_ms=73))
    timer = timed.create_timer(lambda: None)
    assert timer.interval == 73


def test_pair_sampler_rejects_changed_screen_geometry_before_capture():
    screen = FakeScreen()
    sampler = ContextQuestionSampler(make_regions(screen))
    screen._geometry = QRect(0, 0, 120, 50)
    with pytest.raises(RuntimeError, match="geometry changed"):
        sampler.sample()
    assert screen.grab_calls == 0
