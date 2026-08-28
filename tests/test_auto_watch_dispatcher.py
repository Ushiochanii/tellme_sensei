from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtGui import QImage
import pytest

from app.analysis import AnalysisMode
from app.auto_watch import AnalysisDispatcher, AnalysisState, AutoWatchSettings, AutoWatchDispatcherBridge
from app.auto_watch.models import AnalysisRequest


class FakeScheduler:
    def __init__(self): self.jobs = []
    def call_later(self, delay, callback):
        job = [delay, callback, False]; self.jobs.append(job); return job
    def cancel(self, job): job[2] = True
    def fire(self, index=0):
        job = self.jobs[index]
        if not job[2]: job[1]()


class FakeWorker(QObject):
    result_ready = Signal(object)
    error_occurred = Signal(str)
    cancelled = Signal()
    finished = Signal()
    def __init__(self, request): super().__init__(); self.request = request; self.cancel_calls = 0; self.runs = 0; self.fail_cancel = False
    def start(self): self.run()
    def run(self): self.runs += 1
    def request_cancel(self):
        self.cancel_calls += 1
        if self.fail_cancel: raise RuntimeError("cancel failed")
    def result(self, value): self.result_ready.emit(value)
    def error(self, value): self.error_occurred.emit(value)
    def done(self): self.finished.emit()


def image(w=80, h=40): return QImage(w, h, QImage.Format.Format_RGBA8888)


def make(**kwargs):
    workers = []
    def factory(req):
        worker = FakeWorker(req); workers.append(worker); return worker
    dispatcher = AnalysisDispatcher(worker_factory=factory, **kwargs)
    return dispatcher, workers


def test_immediate_single_flight_and_latest_pending():
    dispatcher, workers = make()
    q1 = dispatcher.submit(image())
    q2 = dispatcher.submit(image(), AnalysisMode.VISION)
    q3 = dispatcher.submit(image()); q4 = dispatcher.submit(image())
    assert len(workers) == 1 and dispatcher.pending_request is q4
    assert workers[0].cancel_calls == 1 and dispatcher.state is AnalysisState.CANCELLING
    workers[0].done()
    assert len(workers) == 2 and workers[1].request is q4
    assert dispatcher._active_relay.thread() is QThread.currentThread()
    workers[1].done()
    assert dispatcher.state is AnalysisState.IDLE and dispatcher.active_request is None
    assert q1.image.width() == 80


def test_finished_callback_is_delivered_and_reentry_does_not_old_cleanup():
    finished = []; dispatcher = None
    def on_finished(request):
        finished.append(request.generation)
        if request.generation == 1:
            dispatcher.submit(image())
    dispatcher, workers = make(on_finished=on_finished)
    dispatcher.submit(image()); workers[0].done()
    assert finished == [1] and len(workers) == 2
    assert dispatcher.active_request is workers[1].request and dispatcher.state is AnalysisState.RUNNING


def test_finished_duplicate_never_starts_two_workers_and_callbacks_once():
    results = []
    dispatcher, workers = make(on_result=lambda r, v: results.append((r.generation, v)))
    request = dispatcher.submit(image())
    workers[0].result("answer"); workers[0].result("duplicate")
    workers[0].done(); workers[0].done()
    assert results == [(request.generation, "answer")] and len(workers) == 1


def test_duplicate_finished_is_observed_as_stale_once():
    observations = []
    dispatcher, workers = make(on_observe=lambda kind, fields: observations.append((kind, fields)))
    dispatcher.submit(image()); workers[0].done(); workers[0].done()
    assert dispatcher.stale_discard_count == 1
    assert any(kind == "stale_discard" and item.get("event_kind") == "finished"
               for kind, item in observations)


def test_delay_replaced_and_stop_cancels_everything():
    scheduler = FakeScheduler()
    dispatcher, workers = make(settings=AutoWatchSettings(analysis_delay_ms=50), scheduler=scheduler)
    dispatcher.submit(image()); dispatcher.submit(image())
    assert scheduler.jobs[0][2] and len(workers) == 0
    dispatcher.stop(); dispatcher.stop()
    assert scheduler.jobs[1][2] and dispatcher.pending_request is None
    assert dispatcher.state is AnalysisState.IDLE
    assert not workers
    scheduler.fire(1); assert not workers and dispatcher.state is AnalysisState.IDLE


def test_duplicate_delay_callback_is_discarded_without_cancel_or_restart():
    scheduler = FakeScheduler(); dispatcher, workers = make(settings=AutoWatchSettings(analysis_delay_ms=5), scheduler=scheduler)
    dispatcher.submit(image()); scheduler.fire(0)
    request = dispatcher.active_request
    scheduler.jobs[0][1]()
    assert dispatcher.active_request is request and len(workers) == 1 and workers[0].cancel_calls == 0


def test_pause_does_not_cancel_accepted_delay_or_active():
    scheduler = FakeScheduler(); dispatcher, workers = make(settings=AutoWatchSettings(analysis_delay_ms=5), scheduler=scheduler)
    dispatcher.submit(image()); dispatcher.pause(); scheduler.fire()
    assert len(workers) == 1 and dispatcher.paused and not scheduler.jobs[0][2]
    dispatcher.submit(image()); dispatcher.pause(); assert workers[0].cancel_calls == 0
    scheduler.fire(1); assert workers[0].cancel_calls == 1


def test_q1_q2_q3_q4_delay_starts_only_q4_after_q1_finishes():
    scheduler = FakeScheduler(); dispatcher, workers = make(settings=AutoWatchSettings(analysis_delay_ms=5), scheduler=scheduler)
    dispatcher.submit(image()); scheduler.fire(0)
    q2 = dispatcher.submit(image()); dispatcher.submit(image()); q4 = dispatcher.submit(image())
    assert workers[0].cancel_calls == 0 and dispatcher.pending_request is None
    scheduler.fire(3)
    assert dispatcher.pending_request is q4 and workers[0].cancel_calls == 1
    workers[0].done()
    assert len(workers) == 2 and workers[1].request is q4


def test_callback_exception_and_reentry_do_not_break_dispatch():
    seen = []
    dispatcher = None
    def callback(request, _value):
        seen.append(request.generation)
        dispatcher.submit(image())
        raise RuntimeError("callback test")
    dispatcher, workers = make(on_result=callback)
    dispatcher.submit(image()); workers[0].result("ok")
    assert seen == [1] and dispatcher.pending_request is not None


def test_factory_error_is_delivered_once_and_next_generation_runs():
    errors = []; calls = []
    def factory(request):
        calls.append(request.generation)
        if request.generation == 1: raise RuntimeError("factory")
        worker = FakeWorker(request); return worker
    dispatcher = AnalysisDispatcher(worker_factory=factory, on_error=lambda r, e: errors.append((r.generation, e)))
    dispatcher.submit(image()); dispatcher.submit(image())
    assert errors == [(1, "factory")] and calls == [1, 2]


def test_factory_error_callback_reentry_is_not_cleared():
    errors = []; dispatcher = None
    def factory(request):
        if request.generation == 1: raise RuntimeError("factory")
        return FakeWorker(request)
    def on_error(request, message):
        errors.append((request.generation, message)); dispatcher.submit(image())
    dispatcher = AnalysisDispatcher(worker_factory=factory, on_error=on_error)
    dispatcher.submit(image())
    assert errors == [(1, "factory")] and dispatcher.active_request.generation == 2


def test_stale_callbacks_are_not_delivered_after_stop():
    results, errors = [], []
    dispatcher, workers = make(on_result=lambda *a: results.append(a), on_error=lambda *a: errors.append(a))
    dispatcher.submit(image()); worker = workers[0]; dispatcher.stop()
    worker.result("old"); worker.error("old"); worker.cancelled.emit(); worker.done()
    assert not results and not errors


def test_cancel_failure_is_guarded_and_cancel_is_idempotent():
    dispatcher, workers = make()
    dispatcher.submit(image()); workers[0].fail_cancel = True
    dispatcher.submit(image()); dispatcher.submit(image())
    assert workers[0].cancel_calls == 1 and dispatcher.state is AnalysisState.CANCELLING
    workers[0].done(); assert len(workers) == 2


def test_stop_while_cancelling_waits_for_real_finished_cleanup():
    dispatcher, workers = make()
    dispatcher.submit(image()); dispatcher.submit(image())
    dispatcher.stop()
    assert dispatcher.state is AnalysisState.CANCELLING and dispatcher.pending_request is None
    workers[0].done(); assert dispatcher.state is AnalysisState.IDLE and dispatcher.active_request is None


def test_stop_during_analysis_delay_never_starts_worker_after_late_timer_callback():
    scheduler = FakeScheduler()
    dispatcher, workers = make(
        settings=AutoWatchSettings(analysis_delay_ms=50), scheduler=scheduler
    )
    dispatcher.submit(image())
    dispatcher.stop()
    # A scheduler callback can still be invoked by a real event loop after
    # cancellation; it must be harmless and must not start a worker.
    scheduler.jobs[0][1]()
    assert workers == []
    assert dispatcher.active_request is None
    assert dispatcher.pending_request is None
    assert dispatcher.state is AnalysisState.IDLE


def test_full_resolution_copy_and_vision_request():
    dispatcher, workers = make()
    source = image(1200, 700); request = dispatcher.submit(source, AnalysisMode.VISION)
    source = QImage(2, 2, QImage.Format.Format_RGBA8888)
    assert (request.image.width(), request.image.height()) == (1200, 700)
    assert workers[0].request.mode is AnalysisMode.VISION


def test_error_keeps_monitor_accepting_next_generation():
    dispatcher, workers = make(on_error=lambda r, e: None)
    dispatcher.submit(image()); workers[0].error("bad"); workers[0].done()
    dispatcher.submit(image()); assert len(workers) == 2 and dispatcher.state is AnalysisState.RUNNING


def test_request_validates_identity_fields():
    with pytest.raises(ValueError): AnalysisRequest(0, AnalysisMode.TEXT, image(), request_id="x")
    with pytest.raises(ValueError): AnalysisRequest(1, "text", image(), request_id="x")
    with pytest.raises(ValueError): AnalysisRequest(1, AnalysisMode.TEXT, image(), source="manual", request_id="x")
    with pytest.raises(ValueError): AnalysisRequest(1, AnalysisMode.TEXT, image(), request_id="")


def test_default_factory_returns_async_handle_without_running_worker():
    from app.auto_watch import dispatcher as module
    from app.config import AppConfig
    request = AnalysisRequest(1, AnalysisMode.TEXT, image(), request_id="job")
    dispatcher = AnalysisDispatcher(config=AppConfig(api_key="test"), ocr_provider=object())
    handle = dispatcher._default_worker_factory(request)
    assert isinstance(handle, module._QtWorkerHandle)
    assert handle.thread.isRunning() is False


def test_default_factory_reuses_provider_across_generations(monkeypatch):
    from app.auto_watch import dispatcher as module
    from app.config import AppConfig

    providers = []

    class Provider:
        pass

    def factory(config, *, local_ocr_session=None):
        providers.append((config, local_ocr_session))
        return Provider()

    monkeypatch.setattr(module, "create_ocr_provider", factory)
    dispatcher = AnalysisDispatcher(
        config=AppConfig(api_key="test"),
        local_ocr_session=object(),
        deepseek_service=object(),
    )
    first = dispatcher._default_worker_factory(
        AnalysisRequest(1, AnalysisMode.TEXT, image(), request_id="one")
    )
    second = dispatcher._default_worker_factory(
        AnalysisRequest(2, AnalysisMode.TEXT, image(), request_id="two")
    )

    assert len(providers) == 1
    assert first.thread.isRunning() is False
    assert second.thread.isRunning() is False


def test_demo_fake_worker_start_delivers_result_and_returns_idle(qt_app):
    from tools.auto_watch_dispatcher_demo import FakeWorker
    results = []; finished = []
    dispatcher = AnalysisDispatcher(worker_factory=FakeWorker,
                                    on_result=lambda _request, value: results.append(value),
                                    on_finished=lambda request: finished.append(request.generation))
    dispatcher.submit(image(), AnalysisMode.VISION)
    assert results == ["fake result (no network)"]
    assert finished == [1]
    assert dispatcher.state is AnalysisState.IDLE
    assert dispatcher.active_request is None


def test_bridge_submits_stable_generation_once_with_full_resolution():
    from types import SimpleNamespace
    dispatcher, workers = make()
    bridge = AutoWatchDispatcherBridge(dispatcher, AnalysisMode.VISION)
    event = SimpleNamespace(generation=7)
    request = bridge.submit_event(event, image(1200, 700))
    assert request.generation == 7 and request.image.size().width() == 1200
    assert bridge.submit_event(event, image(1200, 700)) is None
    assert len(workers) == 1 and workers[0].request.mode is AnalysisMode.VISION
