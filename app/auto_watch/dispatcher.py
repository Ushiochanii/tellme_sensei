"""Generation-safe, single-flight dispatch for auto-watch analysis."""
from __future__ import annotations

from collections.abc import Callable
import logging
import inspect
import uuid
from typing import Any

from PySide6.QtCore import QThread, QTimer, QObject, Signal, Slot

from app.analysis import AnalysisMode
from app.config import AppConfig
from app.ocr.factory import create_ocr_provider
from app.services.deepseek_service import DeepSeekService
from app.workers.processing_worker import ProcessingWorker
from app.workers.vision_processing_worker import VisionProcessingWorker
from .models import AnalysisRequest, AnalysisState, AutoWatchSettings

logger = logging.getLogger(__name__)


class _TimerScheduler:
    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> Any:
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: (timer.deleteLater(), callback()))
        timer.start(delay_ms)
        return timer

    def cancel(self, handle: Any) -> None:
        if handle is not None:
            handle.stop()
            handle.deleteLater()


class _QtWorkerHandle(QObject):
    """Thin asynchronous boundary around an existing processing worker."""

    result_ready = Signal(object)
    error_occurred = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, worker: QObject) -> None:
        super().__init__()
        self.worker = worker
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self._connect_worker_signal("job_result_ready", lambda *args: self.result_ready.emit(args[-1]))
        self._connect_worker_signal("result_ready", lambda *args: self.result_ready.emit(args[-1]), only_if_missing="job_result_ready")
        self._connect_worker_signal("job_error_occurred", lambda *args: self.error_occurred.emit(args[-1]))
        self._connect_worker_signal("error_occurred", lambda *args: self.error_occurred.emit(args[-1]), only_if_missing="job_error_occurred")
        self._connect_worker_signal("cancelled", lambda *args: self.cancelled.emit())
        finished_signal = getattr(self.worker, "finished", None)
        if finished_signal is not None:
            finished_signal.connect(self.thread.quit)
            finished_signal.connect(self.worker.deleteLater)
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self._cleanup)
        self._cancel_called = False
        self._finished_emitted = False

    def _connect_worker_signal(self, name, callback, only_if_missing=None):
        if only_if_missing is not None and getattr(self.worker, only_if_missing, None) is not None:
            return
        signal = getattr(self.worker, name, None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(callback)

    def start(self) -> None:
        self.thread.start()

    def request_cancel(self) -> None:
        if self._cancel_called:
            return
        self._cancel_called = True
        self.worker.request_cancel()

    def _cleanup(self) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self.finished.emit()
        self.thread.deleteLater()


class _HandleRelay(QObject):
    """Per-handle receiver: Qt queues worker-thread signals to owner thread."""

    def __init__(self, dispatcher, request, handle) -> None:
        super().__init__()
        self.dispatcher, self.request, self.handle = dispatcher, request, handle
        handle.result_ready.connect(self.result)
        handle.error_occurred.connect(self.error)
        handle.cancelled.connect(self.cancelled)
        handle.finished.connect(self.finished)

    @Slot(object)
    def result(self, value): self.dispatcher._result(self.request, self.handle, value)

    @Slot(str)
    def error(self, value): self.dispatcher._error(self.request, self.handle, value)

    @Slot()
    def cancelled(self): self.dispatcher._cancelled(self.request, self.handle)

    @Slot()
    def finished(self): self.dispatcher._finished(self.request, self.handle)


class AnalysisDispatcher:
    """Accept requests while guaranteeing one active worker and one latest pending."""

    def __init__(self, settings: AutoWatchSettings | None = None, *, worker_factory=None,
                 scheduler=None, config: AppConfig | None = None, ocr_provider=None,
                 local_ocr_session=None,
                 deepseek_service=None, on_result=None, on_error=None, on_cancelled=None,
                 on_finished=None, on_observe=None, session_id: str = "auto-watch") -> None:
        self.settings = settings or AutoWatchSettings()
        self.worker_factory = worker_factory or self._default_worker_factory
        self.scheduler = scheduler or _TimerScheduler()
        self.config, self.ocr_provider, self.deepseek_service = config, ocr_provider, deepseek_service
        # Keep the session separate from the provider so callers can own its
        # lifetime (MainWindow and the real demo do).  The provider itself is
        # cached after first construction, avoiding a model/worker cold start
        # on every generation while retaining the old provider injection API.
        self.local_ocr_session = local_ocr_session
        self.on_result, self.on_error = on_result, on_error
        self.on_cancelled, self.on_finished = on_cancelled, on_finished
        self.on_observe = on_observe
        self.session_id = session_id
        self.state = AnalysisState.IDLE
        self.paused = False
        self.generation = 0
        self.active_request: AnalysisRequest | None = None
        self.pending_request: AnalysisRequest | None = None
        self._active_handle = None
        self._active_relay = None
        self._delay_handle = None
        self._delay_request: AnalysisRequest | None = None
        self._pending_ready = False
        self._cancel_requested = False
        self._delivered: set[tuple[int, str, str]] = set()
        self._stopped = False
        self._accepted_external: set[tuple[str, int]] = set()
        self.stale_discard_count = 0

    def _observe(self, kind, request=None, **fields):
        if request is not None:
            fields.update(generation=request.generation, request_id=request.request_id, session=request.session_id)
        fields.update(active=bool(self.active_request), pending=bool(self.pending_request),
                      state=self.state.name, delay_ms=self.settings.analysis_delay_ms)
        if self.on_observe is not None:
            try:
                self.on_observe(kind, fields)
            except Exception:
                logger.exception("observability callback failed kind=%s", kind)

    def submit(self, image, mode: AnalysisMode = AnalysisMode.TEXT, *, session_id=None, request_id=None, generation=None) -> AnalysisRequest | None:
        self._stopped = False
        if session_id is not None:
            self.session_id = session_id
        if generation is None:
            self.generation += 1
        else:
            if generation <= 0 or (self.session_id, generation) in self._accepted_external:
                logger.info("stale external generation discard generation=%s session=%s", generation, self.session_id)
                return None
            self.generation = generation
            self._accepted_external.add((self.session_id, generation))
        request = AnalysisRequest(self.generation, AnalysisMode(mode), image,
                                  session_id=session_id or self.session_id,
                                  request_id=request_id or uuid.uuid4().hex)
        logger.info("accepted generation=%s request=%s session=%s active=%s pending=%s", request.generation, request.request_id, request.session_id, bool(self.active_request), bool(self.pending_request))
        self._observe("accepted", request)
        if self.active_request is not None and self._pending_ready:
            self.pending_request = None
            self._pending_ready = False
        self._replace_delay(request)
        return request

    def analyze_now(self, image, mode=AnalysisMode.TEXT, **kwargs):
        return self.submit(image, mode, **kwargs)

    def reset_session(self, session_id: str) -> None:
        self.stop()
        self.session_id = session_id
        self.generation = 0
        self._accepted_external.clear()

    def stop(self) -> None:
        self._stopped = True
        self.generation += 1
        self._cancel_delay()
        self.pending_request = None
        self._pending_ready = False
        if self.active_request is not None:
            self._request_cancel()
        else:
            self.state = AnalysisState.IDLE

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def _replace_delay(self, request):
        self._cancel_delay()
        self._delay_request = request
        if self.settings.analysis_delay_ms == 0:
            self._delay_ready(request)
            return
        self._delay_handle = self.scheduler.call_later(self.settings.analysis_delay_ms,
                                                        lambda: self._delay_ready(request))
        logger.info("delay schedule generation=%s request=%s session=%s delay_ms=%s", request.generation, request.request_id, request.session_id, self.settings.analysis_delay_ms)
        self._observe("delay_schedule", request)

    def _cancel_delay(self):
        if self._delay_handle is not None:
            self.scheduler.cancel(self._delay_handle)
            request = self._delay_request
            logger.info("delay cancel generation=%s request=%s session=%s", request.generation if request else None, request.request_id if request else None, request.session_id if request else self.session_id)
            self._observe("delay_cancel", request)
        self._delay_handle = self._delay_request = None

    def _delay_ready(self, request):
        if self._delay_request is not request:
            logger.info("delay discard generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            self.stale_discard_count += 1; self._observe("stale_discard", request, count=self.stale_discard_count)
            return
        self._delay_handle = self._delay_request = None
        if self._stopped or request.generation != self.generation:
            logger.info("delay discard generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            self.stale_discard_count += 1; self._observe("stale_discard", request, count=self.stale_discard_count)
            return
        if self.active_request is not None:
            self.pending_request = request
            self._pending_ready = True
            self._request_cancel()
            return
        self._start(request)

    def _start(self, request):
        if self._stopped or request.generation != self.generation:
            logger.info("stale start discard generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            return
        self.active_request = request
        self.state = AnalysisState.RUNNING
        self._cancel_requested = False
        try:
            handle = self.worker_factory(request)
            self._active_handle = handle
            self._active_relay = _HandleRelay(self, request, handle)
            # Keep the receiver alive for late duplicate signals emitted by the handle.
            handle._dispatcher_relay = self._active_relay
            logger.info("started generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            self._observe("started", request)
            handle.start()
        except Exception as exc:
            logger.exception("factory failed generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            self._error(request, self._active_handle, str(exc))
            self.active_request = self._active_handle = self._active_relay = None
            if self.pending_request is not None and self._pending_ready and not self._stopped:
                pending = self.pending_request
                self.pending_request = None; self._pending_ready = False
                logger.info("latest pending started generation=%s request=%s session=%s", pending.generation, pending.request_id, pending.session_id)
                self._start(pending)
            else:
                self.state = AnalysisState.IDLE

    @staticmethod
    def _connect(worker, name, callback):
        signal = getattr(worker, name, None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(callback)

    def _request_cancel(self):
        if self.active_request is None or self._cancel_requested:
            return
        self._cancel_requested = True
        self.state = AnalysisState.CANCELLING
        request, handle = self.active_request, self._active_handle
        logger.info("cancel requested generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
        self._observe("cancel_requested", request)
        try:
            if handle is not None: handle.request_cancel()
        except Exception:
            logger.exception("cancel failed generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            self._observe("cancel_failed", request)

    def _valid(self, request, kind):
        if self.active_request is not request or request.generation != self.generation or request.session_id != self.session_id or self._stopped:
            logger.info("stale %s discard generation=%s request=%s session=%s", kind, request.generation, request.request_id, request.session_id)
            return False
        return True

    def _deliver(self, request, handle, kind, callback, value=None):
        if self.active_request is not request or self._active_handle is not handle:
            logger.info("stale %s discard generation=%s request=%s session=%s", kind, request.generation, request.request_id, request.session_id)
            self.stale_discard_count += 1; self._observe("stale_discard", request, event_kind=kind, count=self.stale_discard_count)
            return
        if not self._valid(request, kind) or (request.generation, request.session_id, kind) in self._delivered:
            return
        self._delivered.add((request.generation, request.session_id, kind))
        self._observe(kind, request)
        if callback is None: return
        try:
            callback(request) if value is None else callback(request, value)
        except Exception:
            logger.exception("external %s callback failed generation=%s request=%s session=%s", kind, request.generation, request.request_id, request.session_id)

    def _result(self, request, handle, *args): self._deliver(request, handle, "result", self.on_result, args[-1])
    def _error(self, request, handle, *args): self._deliver(request, handle, "error", self.on_error, args[-1])

    def _cancelled(self, request, handle, *args):
        self._deliver(request, handle, "cancelled", self.on_cancelled)
        logger.info("cancel completed generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
        self._observe("cancel_completed", request)

    def _finished(self, request, handle, *args):
        if self.active_request is not request or self._active_handle is not handle:
            logger.info("stale finished discard generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            self.stale_discard_count += 1; self._observe("stale_discard", request, event_kind="finished", count=self.stale_discard_count)
            return
        current = request.generation == self.generation and request.session_id == self.session_id and not self._stopped
        next_pending = self.pending_request if self._pending_ready else None
        self.pending_request = None
        self._pending_ready = False
        self.active_request = self._active_handle = self._active_relay = None
        self._cancel_requested = False
        self.state = AnalysisState.IDLE
        self._deliver_finished(request, handle, current)
        # on_finished may synchronously submit a newer request. Never overwrite it.
        if self.active_request is not None or self._stopped:
            return
        if next_pending is not None and next_pending.generation == self.generation:
            logger.info("latest pending started generation=%s request=%s session=%s", next_pending.generation, next_pending.request_id, next_pending.session_id)
            self._start(next_pending)

    def _deliver_finished(self, request, handle, current):
        key = (request.generation, request.session_id, "finished")
        if not current:
            logger.info("stale finished discard generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)
            return
        if key in self._delivered:
            return
        self._delivered.add(key)
        self._observe("finished", request)
        if self.on_finished is None:
            return
        try:
            self.on_finished(request)
        except Exception:
            logger.exception("external finished callback failed generation=%s request=%s session=%s", request.generation, request.request_id, request.session_id)

    def _default_worker_factory(self, request):
        config = self.config
        if self.deepseek_service is None:
            if config is None: raise ValueError("config or worker_factory is required")
            self.deepseek_service = DeepSeekService(config)
        if request.mode is AnalysisMode.VISION:
            worker = VisionProcessingWorker(request.image, self.deepseek_service, request.request_id)
        else:
            if self.ocr_provider is None:
                try:
                    factory_parameters = inspect.signature(create_ocr_provider).parameters
                except (TypeError, ValueError):
                    factory_parameters = {}
                supports_session = (
                    "local_ocr_session" in factory_parameters
                    or any(p.kind is inspect.Parameter.VAR_KEYWORD
                           for p in factory_parameters.values())
                )
                if supports_session:
                    self.ocr_provider = create_ocr_provider(
                        config, local_ocr_session=self.local_ocr_session
                    )
                else:
                    # Compatibility with tests and integrations that still
                    # expose the pre-session factory signature.
                    self.ocr_provider = create_ocr_provider(config)
                logger.info(
                    "OCR provider initialized once for dispatcher session=%s provider=%s",
                    self.session_id, type(self.ocr_provider).__name__,
                )
            provider = self.ocr_provider
            worker = ProcessingWorker(request.image, provider, self.deepseek_service, job_id=request.request_id)
        return _QtWorkerHandle(worker)


__all__ = ["AnalysisDispatcher"]


class AutoWatchDispatcherBridge:
    """Submit each stable coordinator event once, retaining its full-res image."""

    def __init__(self, dispatcher: AnalysisDispatcher, mode: AnalysisMode = AnalysisMode.TEXT):
        self.dispatcher, self.mode = dispatcher, AnalysisMode(mode)
        self._submitted: set[tuple[str, int]] = set()

    def submit_event(self, event, image, *, mode=None, session_id=None, request_id=None):
        session = session_id or self.dispatcher.session_id
        key = (session, event.generation)
        if key in self._submitted:
            logger.info("duplicate stable event discard generation=%s session=%s", event.generation, session)
            return None
        request = self.dispatcher.submit(image, mode or self.mode, session_id=session,
                                         request_id=request_id, generation=event.generation)
        if request is not None:
            self._submitted.add(key)
        return request

    def reset_session(self, session_id: str) -> None:
        self._submitted.clear()
        self.dispatcher.reset_session(session_id)


__all__.append("AutoWatchDispatcherBridge")
