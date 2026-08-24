from __future__ import annotations

import uuid

import gui
from PySide6.QtNetwork import QLocalServer

from app.single_instance import SingleInstanceGuard


def _server_name() -> str:
    return f"tellme-sensei-test-{uuid.uuid4().hex}"


def test_first_acquire_and_second_instance_detection(qt_app) -> None:
    name = _server_name()
    first = SingleInstanceGuard(name, qt_app)
    second = SingleInstanceGuard(name, qt_app)

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()
    second.deleteLater()
    first.deleteLater()
    qt_app.processEvents()


def test_release_allows_reacquire(qt_app) -> None:
    name = _server_name()
    first = SingleInstanceGuard(name, qt_app)
    replacement = SingleInstanceGuard(name, qt_app)

    assert first.acquire() is True
    first.release()
    assert replacement.acquire() is True

    replacement.release()
    replacement.deleteLater()
    first.deleteLater()
    qt_app.processEvents()


def test_stale_endpoint_is_recovered(qt_app) -> None:
    name = _server_name()
    stale_server = QLocalServer(qt_app)
    assert stale_server.listen(name) is True
    stale_server.close()

    guard = SingleInstanceGuard(name, qt_app)
    assert guard.acquire() is True

    guard.release()
    stale_server.deleteLater()
    guard.deleteLater()
    qt_app.processEvents()


def test_core_diagnostic_bypasses_single_instance_guard(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(gui, "_smoke_core", lambda: called.append("smoke") or 0)
    assert gui.main(["--smoke-core"]) == 0
    assert called == ["smoke"]
