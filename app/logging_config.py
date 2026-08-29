"""Logging setup used by command-line entry points and services."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from tempfile import gettempdir

from app.runtime_paths import APPLICATION_DIRECTORY, default_log_path


DEFAULT_LOG_TAIL_BYTES = 256 * 1024
DEFAULT_LOG_TAIL_LINES = 1000
_SENSITIVE_LOG_VALUE_RE = re.compile(
    r"(?P<prefix>\b(?:api[_-]?key|authorization|token|password|secret)\b\s*[:=]\s*)"
    r"(?:"
    r"(?P<quote>['\"])(?P<quoted>.*?)(?P=quote)"
    r"|(?P<scheme>(?:Bearer|Basic|Token|Digest)\s+)?(?P<unquoted>[^\s,;]+)"
    r")",
    re.IGNORECASE,
)


def configure_logging(project_root: Path | None = None) -> None:
    """Configure logging without writing to the source tree by default.

    ``project_root`` is an explicit test/development override retained for
    callers that need an isolated log directory.
    """

    log_file = (
        Path(project_root) / "logs" / "app.log"
        if project_root is not None
        else default_log_path()
    )
    log_dir = log_file.parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        if project_root is not None:
            raise
        log_file = Path(gettempdir()) / APPLICATION_DIRECTORY / "logs" / "app.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, encoding="utf-8")
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def redact_log_secrets(text: str) -> str:
    """Mask common key/value secret forms before displaying diagnostics."""

    if not text:
        return text

    def replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        quote = match.group("quote")
        if quote is not None:
            return f"{prefix}{quote}[REDACTED]{quote}"
        scheme = match.group("scheme") or ""
        return f"{prefix}{scheme}[REDACTED]"

    return _SENSITIVE_LOG_VALUE_RE.sub(replace, text)


def read_log_tail(
    path: Path | str | None = None,
    *,
    max_bytes: int = DEFAULT_LOG_TAIL_BYTES,
    max_lines: int = DEFAULT_LOG_TAIL_LINES,
    redact: bool = True,
) -> str:
    """Read a bounded UTF-8 tail of the operational log.

    Reading from the end avoids loading an accidentally large log into the GUI
    thread.  ``FileNotFoundError`` and other ``OSError`` instances deliberately
    propagate so callers can show an explicit missing/read-failure state.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    target = Path(path) if path is not None else default_log_path()
    with target.open("rb") as stream:
        stream.seek(0, 2)
        file_size = stream.tell()
        offset = max(0, file_size - max_bytes)
        stream.seek(offset)
        data = stream.read(max_bytes)
    text = data.decode("utf-8", errors="replace")
    if offset:
        # The first bytes may be the middle of a line; omit that fragment.
        _, separator, text = text.partition("\n")
        if not separator:
            text = ""
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    result = "\n".join(lines)
    return redact_log_secrets(result) if redact else result
