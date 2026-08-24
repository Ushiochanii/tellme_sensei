from __future__ import annotations

import gui
from app import core_smoke


def test_smoke_core_branches_before_gui_startup(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(gui, "_smoke_core", lambda: calls.append("smoke") or 0)

    assert gui.main(["--smoke-core"]) == 0
    assert calls == ["smoke"]


def test_smoke_core_does_not_construct_gui_services(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        core_smoke,
        "_run_checks",
        lambda: calls.append("safe-core-checks"),
    )

    assert core_smoke.run_core_smoke() == 0
    assert calls == ["safe-core-checks"]


def test_smoke_core_injected_failure_is_nonzero_and_actionable(monkeypatch, capsys) -> None:
    def fail() -> None:
        raise core_smoke.CoreSmokeError(
            "CORE_SMOKE_PLATFORM_FAILED", "test platform failure"
        )

    monkeypatch.setattr(core_smoke, "_run_checks", fail)

    assert core_smoke.run_core_smoke() == 1
    assert "CORE_SMOKE_PLATFORM_FAILED: test platform failure" in capsys.readouterr().err
