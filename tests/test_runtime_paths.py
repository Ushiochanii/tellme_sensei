from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.logging_config import configure_logging
from app.runtime_paths import default_log_path, user_runtime_directory
from app.version import __version__


def test_default_runtime_log_path_is_outside_repository() -> None:
    path = default_log_path()
    repository_root = Path(__file__).resolve().parents[1]

    assert path.name == "app.log"
    assert path.parent.name == "logs"
    assert repository_root not in path.parents


def test_runtime_directory_has_application_name() -> None:
    assert user_runtime_directory().name == "TellMeSensei"


def test_logging_accepts_explicit_test_path(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    try:
        logging.getLogger("runtime-path-test").info("test log")
        assert (tmp_path / "logs" / "app.log").is_file()
    finally:
        for handler in logging.getLogger().handlers:
            handler.flush()
            handler.close()


def test_logging_without_stderr_uses_file_handler(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stderr", None)
    configure_logging(tmp_path)
    try:
        handlers = logging.getLogger().handlers
        assert any(isinstance(handler, logging.FileHandler) for handler in handlers)
        assert not any(type(handler) is logging.StreamHandler for handler in handlers)
        assert (tmp_path / "logs" / "app.log").is_file()
    finally:
        for handler in logging.getLogger().handlers:
            handler.flush()
            handler.close()


def test_version_is_defined() -> None:
    assert __version__ == "0.8.2"
