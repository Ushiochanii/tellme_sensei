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
    def guard_must_not_be_created(*_args, **_kwargs):
        raise AssertionError("diagnostic CLI must bypass the single-instance guard")

    monkeypatch.setattr(gui, "SingleInstanceGuard", guard_must_not_be_created)
    assert gui.main(["--smoke-core"]) == 0
