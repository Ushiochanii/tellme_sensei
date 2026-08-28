"""Synchronous pair-level coordination for Context + Question Auto Watch."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PySide6.QtGui import QImage

from .coordinator import AutoWatchCoordinator
from .detector import preprocess_qimage
from .models import (AutoWatchSettings, ContextQuestionSnapshot, DetectorConfig, DetectorFrame,
                     MonitorState, PairMonitorState, PairSnapshot)
from .pair_sampler import ContextQuestionImages


class PairCoordinator:
    """Combine two existing region coordinators into one accepted pair stream.

    Region coordinators decide whether an individual ROI reached a stable frame.
    This class only joins those accepted events and waits until both components
    are stable before advancing the pair generation.
    """

    def __init__(self, config: DetectorConfig | AutoWatchSettings | AutoWatchCoordinator | None = None,
                 question_coordinator: AutoWatchCoordinator | None = None, *,
                 settings: AutoWatchSettings | None = None,
                 context_coordinator: AutoWatchCoordinator | None = None,
                 analysis_callback: Callable[[PairSnapshot], None] | None = None) -> None:
        if isinstance(config, AutoWatchCoordinator):
            if context_coordinator is not None:
                raise ValueError("context coordinator was provided twice")
            context_coordinator = config
            config = None
        elif isinstance(config, AutoWatchSettings):
            if settings is not None:
                raise ValueError("provide config or settings, not both")
            settings = config
            config = None
        if config is not None and settings is not None:
            raise ValueError("provide config or settings, not both")
        self.settings = settings or AutoWatchSettings(detector_config=config or DetectorConfig())
        self.context_coordinator = context_coordinator or AutoWatchCoordinator(settings=self.settings)
        self.question_coordinator = question_coordinator or AutoWatchCoordinator(settings=self.settings)
        self.analysis_callback = analysis_callback
        self.callback_errors: list[Exception] = []

        self._pair_generation = 0
        self._context_revision = 0
        self._question_revision = 0
        self._context_image: QImage | None = None
        self._question_image: QImage | None = None
        self._latest_context_image: QImage | None = None
        self._latest_question_image: QImage | None = None
        self._latest_context_frame: DetectorFrame | None = None
        self._latest_question_frame: DetectorFrame | None = None
        self._pending_pair_change = False
        self.last_snapshot: PairSnapshot | None = None

    @property
    def state(self) -> PairMonitorState:
        context_state = self.context_coordinator.state
        question_state = self.question_coordinator.state
        if context_state is MonitorState.STOPPED or question_state is MonitorState.STOPPED:
            return PairMonitorState.STOPPED
        if context_state is MonitorState.PAUSED or question_state is MonitorState.PAUSED:
            return PairMonitorState.PAUSED
        if context_state is MonitorState.CHANGING or question_state is MonitorState.CHANGING:
            return PairMonitorState.CHANGING
        if context_state is MonitorState.ARMING or question_state is MonitorState.ARMING:
            return PairMonitorState.ARMING
        return PairMonitorState.WATCHING

    @property
    def generation(self) -> int:
        return self._pair_generation

    @property
    def pair_generation(self) -> int:
        return self._pair_generation

    @property
    def context_revision(self) -> int:
        return self._context_revision

    @property
    def question_revision(self) -> int:
        return self._question_revision

    @property
    def pending_pair_change(self) -> bool:
        return self._pending_pair_change

    def start(self) -> None:
        self.context_coordinator.start()
        self.question_coordinator.start()

    @property
    def context(self) -> AutoWatchCoordinator:
        return self.context_coordinator

    @property
    def question(self) -> AutoWatchCoordinator:
        return self.question_coordinator

    def tick(self, context=None, question=None, context_image: QImage | None = None,
             question_image: QImage | None = None, *, context_frame=None, question_frame=None,
             images: ContextQuestionImages | None = None) -> PairSnapshot | None:
        """Drive both region detectors with one synchronous sample.

        The normal production-shaped input is ``ContextQuestionImages``. Tests
        may inject detector frames directly and optionally provide full-resolution
        images for the resulting snapshot.
        """
        if context is None:
            context = context_frame
        if question is None:
            question = question_frame
        if (images is None and context is None and question is None
                and isinstance(context_image, QImage) and isinstance(question_image, QImage)):
            context, question = context_image, question_image
        if self.state in (PairMonitorState.STOPPED, PairMonitorState.PAUSED):
            return None
        context_frame, question_frame, context_image, question_image = self._prepare_sample(
            context, question, context_image, question_image, images
        )

        self._latest_context_frame = context_frame
        self._latest_question_frame = question_frame
        self._latest_context_image = context_image.copy()
        self._latest_question_image = question_image.copy()

        context_event = self.context_coordinator.tick(context_frame)
        question_event = self.question_coordinator.tick(question_frame)
        if context_event is not None:
            self._context_revision = context_event.generation
            self._context_image = context_image.copy()
            self._pending_pair_change = True
        if question_event is not None:
            self._question_revision = question_event.generation
            self._question_image = question_image.copy()
            self._pending_pair_change = True
        return self._accept_if_ready()

    def pause(self) -> None:
        if self.state not in (PairMonitorState.STOPPED, PairMonitorState.PAUSED):
            self.context_coordinator.pause()
            self.question_coordinator.pause()

    def resume(self) -> None:
        if self.state is PairMonitorState.PAUSED:
            self.context_coordinator.resume()
            self.question_coordinator.resume()

    def stop(self) -> None:
        self.context_coordinator.stop()
        self.question_coordinator.stop()
        self._pair_generation = 0
        self._context_revision = 0
        self._question_revision = 0
        self._context_image = self._question_image = None
        self._latest_context_image = self._latest_question_image = None
        self._latest_context_frame = self._latest_question_frame = None
        self._pending_pair_change = False
        self.last_snapshot = None

    def analyze_now(self, images: ContextQuestionImages | None = None, *,
                    context_frame: DetectorFrame | np.ndarray | None = None,
                    question_frame: DetectorFrame | np.ndarray | None = None,
                    context_image: QImage | None = None,
                    question_image: QImage | None = None) -> PairSnapshot | None:
        """Accept the most recent pair immediately and re-arm both baselines."""
        if self.state in (PairMonitorState.STOPPED, PairMonitorState.PAUSED):
            return None
        if images is not None:
            if any(value is not None for value in (context_frame, question_frame, context_image, question_image)):
                raise ValueError("provide images or individual Analyze Now inputs, not both")
            context_image, question_image = images.context, images.question
            context_frame = preprocess_qimage(context_image, self.settings.max_side)
            question_frame = preprocess_qimage(question_image, self.settings.max_side)
        else:
            context_frame, context_image = self._complete_analyze_input(
                context_frame, context_image, self._latest_context_frame, self._latest_context_image
            )
            question_frame, question_image = self._complete_analyze_input(
                question_frame, question_image, self._latest_question_frame, self._latest_question_image
            )
        if context_frame is None or question_frame is None or context_image is None or question_image is None:
            return None
        context_frame = self._as_frame(context_frame)
        question_frame = self._as_frame(question_frame)
        context_image = self._as_image(context_image)
        question_image = self._as_image(question_image)
        self._latest_context_frame = context_frame
        self._latest_question_frame = question_frame
        self._latest_context_image = context_image.copy()
        self._latest_question_image = question_image.copy()

        # analyze_now() uses the frame most recently sampled by each existing
        # coordinator; explicit inputs update that sample before acceptance.
        context_event = self.context_coordinator.analyze_now(frame=context_frame)
        question_event = self.question_coordinator.analyze_now(frame=question_frame)
        if context_event is None or question_event is None:
            return None
        self._context_revision = context_event.generation
        self._question_revision = question_event.generation
        self._context_image = context_image.copy()
        self._question_image = question_image.copy()
        self._pending_pair_change = False
        return self._emit_snapshot()

    def _prepare_sample(self, context, question, context_image, question_image, images):
        if images is not None:
            if context is not None or question is not None or context_image is not None or question_image is not None:
                raise ValueError("provide images or individual tick inputs, not both")
            context, question = images.context, images.question
        elif isinstance(context, ContextQuestionImages) and question is None:
            if context_image is not None or question_image is not None:
                raise ValueError("provide ContextQuestionImages or individual images, not both")
            context, question = context.context, context.question

        if isinstance(context, QImage) and isinstance(question, QImage):
            context_image = context
            question_image = question
            context = preprocess_qimage(context_image, self.settings.max_side)
            question = preprocess_qimage(question_image, self.settings.max_side)

        if context is None or question is None:
            raise ValueError("both Context and Question detector frames are required")
        context = self._as_frame(context)
        question = self._as_frame(question)
        if context_image is None:
            context_image = self._image_from_frame(context)
        if question_image is None:
            question_image = self._image_from_frame(question)
        return context, question, self._as_image(context_image), self._as_image(question_image)

    @staticmethod
    def _as_frame(value) -> DetectorFrame:
        return value if isinstance(value, DetectorFrame) else DetectorFrame(value)

    @staticmethod
    def _as_image(value) -> QImage:
        if not isinstance(value, QImage) or value.isNull() or value.width() <= 0 or value.height() <= 0:
            raise ValueError("pair image must be a non-empty QImage")
        return value

    def _complete_analyze_input(self, frame, image, latest_frame, latest_image):
        if frame is None and image is None:
            return latest_frame, latest_image
        if frame is None:
            image = self._as_image(image)
            return preprocess_qimage(image, self.settings.max_side), image
        frame = self._as_frame(frame)
        if image is None:
            image = self._image_from_frame(frame)
        return frame, self._as_image(image)

    @staticmethod
    def _image_from_frame(frame: DetectorFrame) -> QImage:
        image = QImage(frame.pixels.tobytes(), frame.pixels.shape[1], frame.pixels.shape[0],
                       frame.pixels.shape[1], QImage.Format.Format_Grayscale8)
        return image.copy()

    def _accept_if_ready(self) -> PairSnapshot | None:
        if not self._pending_pair_change:
            return None
        if self.state is not PairMonitorState.WATCHING:
            return None
        if self._context_revision <= 0 or self._question_revision <= 0:
            return None
        if self._context_image is None or self._question_image is None:
            return None
        self._pending_pair_change = False
        return self._emit_snapshot()

    def _emit_snapshot(self) -> PairSnapshot:
        self._pair_generation += 1
        snapshot = PairSnapshot(
            generation=self._pair_generation,
            context_revision=self._context_revision,
            question_revision=self._question_revision,
            context_image=self._context_image,
            question_image=self._question_image,
        )
        self.last_snapshot = snapshot
        if self.analysis_callback is not None:
            try:
                self.analysis_callback(snapshot)
            except Exception as exc:  # callbacks must not break monitoring
                self.callback_errors.append(exc)
        return snapshot


__all__ = ["PairCoordinator", "PairSnapshot", "ContextQuestionSnapshot"]
