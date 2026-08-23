"""Background manifest and archive download for the Local OCR component."""

from __future__ import annotations

import json
import logging
import threading
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.local_ocr.component_manager import ComponentCancelled, ComponentError, LocalOCRComponentManager
from app.local_ocr.manifest import ComponentManifest
from app.version import __version__

logger = logging.getLogger(__name__)
DOWNLOAD_TIMEOUT = 30.0
CHUNK_SIZE = 1024 * 1024
USER_AGENT = f"TellMeSensei/{__version__}"


class LocalOCRDownloadWorker(QObject):
    """Download, validate, smoke-test, and activate one Local OCR component."""

    progress_changed = Signal(int)
    manifest_loaded = Signal(int)
    status_changed = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        manifest_url: str,
        manager: LocalOCRComponentManager,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.manifest_url = manifest_url
        self.manager = manager
        self.cancel_event = cancel_event or threading.Event()

    @Slot()
    def run(self) -> None:
        archive: Path | None = None
        try:
            self.status_changed.emit("Downloading...")
            manifest = self._fetch_manifest()
            self.manifest_loaded.emit(manifest.size)
            archive = self._download(manifest)
            self.status_changed.emit("Verifying...")
            self.progress_changed.emit(90)
            self.status_changed.emit("Installing...")
            installed = self.manager.install_archive(
                archive,
                manifest,
                cancel_event=self.cancel_event,
                progress=self.progress_changed.emit,
            )
            archive = None
            self.succeeded.emit(str(installed))
        except ComponentCancelled:
            self.cancelled.emit()
        except (ComponentError, OSError, urllib.error.URLError, ValueError) as exc:
            logger.warning("local OCR component operation failed: %s", type(exc).__name__)
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("local OCR component operation failed")
            self.failed.emit("Local OCR component operation failed.")
        finally:
            if archive is not None:
                try:
                    archive.unlink(missing_ok=True)
                except OSError:
                    pass
            self.finished.emit()

    @Slot()
    def request_cancel(self) -> None:
        self.cancel_event.set()

    def _fetch_manifest(self) -> ComponentManifest:
        if self.cancel_event.is_set():
            raise ComponentCancelled("Local OCR download cancelled.")
        request = urllib.request.Request(self.manifest_url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
                payload = response.read()
        except (urllib.error.URLError, OSError) as exc:
            raise ComponentError("Unable to download the Local OCR manifest.") from exc
        if self.cancel_event.is_set():
            raise ComponentCancelled("Local OCR download cancelled.")
        try:
            return ComponentManifest.from_json(payload.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise ComponentError("The Local OCR manifest is invalid.") from exc

    def _download(self, manifest: ComponentManifest) -> Path:
        fd, name = tempfile.mkstemp(prefix="tellme-sensei-local-ocr-", suffix=".zip")
        path = Path(name)
        total = 0
        try:
            with open(fd, "wb", closefd=True) as output:
                request = urllib.request.Request(manifest.url, headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
                        expected = response.headers.get("Content-Length")
                        expected_size = int(expected) if expected and expected.isdigit() else manifest.size
                        while True:
                            if self.cancel_event.is_set():
                                raise ComponentCancelled("Local OCR download cancelled.")
                            chunk = response.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            output.write(chunk)
                            total += len(chunk)
                            self.progress_changed.emit(min(89, int(total * 89 / max(expected_size, 1))))
                except (urllib.error.URLError, OSError) as exc:
                    raise ComponentError("Unable to download the Local OCR component.") from exc
            return path
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
