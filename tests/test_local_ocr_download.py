import hashlib
import io
import json
import threading
import tempfile
import urllib.error
import zipfile
from pathlib import Path

from app.local_ocr.component_manager import LocalOCRComponentManager
from app.local_ocr.download import LocalOCRDownloadWorker
from app.local_ocr.manifest import current_arch, current_platform
from app.local_ocr.version import LOCAL_OCR_VERSION


class _Response:
    def __init__(self, payload: bytes, on_read=None):
        self.payload = payload
        self.on_read = on_read
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int = -1) -> bytes:
        if self.on_read is not None:
            self.on_read()
            self.on_read = None
        if not self.payload:
            return b""
        if size < 0:
            value, self.payload = self.payload, b""
            return value
        value, self.payload = self.payload[:size], self.payload[size:]
        return value


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("TellMeSenseiOCR.exe", b"worker")
        bundle.writestr("_internal/runtime.dll", b"runtime")
    return buffer.getvalue()


def _manifest(archive: bytes) -> bytes:
    return json.dumps(
        {
            "component": "local-ocr",
            "version": LOCAL_OCR_VERSION,
            "platform": current_platform(),
            "arch": current_arch(),
            "url": "https://example.test/local.zip",
            "sha256": hashlib.sha256(archive).hexdigest(),
            "size": len(archive),
            "archive_format": "zip",
        }
    ).encode()


def test_download_worker_success(tmp_path: Path, monkeypatch) -> None:
    archive = _zip_bytes()
    manifest = _manifest(archive)

    def urlopen(request, timeout):
        return _Response(manifest if "manifest" in request.full_url else archive)

    monkeypatch.setattr("app.local_ocr.download.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("app.local_ocr.component_manager.subprocess.run", lambda *a, **k: type("R", (), {"returncode": 0})())
    worker = LocalOCRDownloadWorker("https://example.test/manifest", LocalOCRComponentManager(tmp_path / "runtime"))
    success: list[str] = []
    errors: list[str] = []
    worker.succeeded.connect(success.append)
    worker.failed.connect(errors.append)

    worker.run()

    assert len(success) == 1
    assert errors == []
    assert worker.manager.is_installed()


def test_download_worker_network_failure(tmp_path: Path, monkeypatch) -> None:
    def urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("app.local_ocr.download.urllib.request.urlopen", urlopen)
    worker = LocalOCRDownloadWorker("https://example.test/manifest", LocalOCRComponentManager(tmp_path / "runtime"))
    errors: list[str] = []
    worker.failed.connect(errors.append)

    worker.run()

    assert errors
    assert not (tmp_path / "runtime" / "components").exists()


def test_download_worker_cancellation_cleans_partial_archive(tmp_path: Path, monkeypatch) -> None:
    archive = _zip_bytes()
    manifest = _manifest(archive)
    cancel_event = threading.Event()

    def urlopen(request, timeout):
        if "manifest" in request.full_url:
            return _Response(manifest)
        return _Response(archive, on_read=cancel_event.set)

    monkeypatch.setattr("app.local_ocr.download.urllib.request.urlopen", urlopen)
    before = set(Path(tempfile.gettempdir()).glob("tellme-sensei-local-ocr-*.zip"))
    worker = LocalOCRDownloadWorker(
        "https://example.test/manifest",
        LocalOCRComponentManager(tmp_path / "runtime"),
        cancel_event,
    )
    cancelled: list[bool] = []
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.run()

    assert cancelled == [True]
    assert set(Path(tempfile.gettempdir()).glob("tellme-sensei-local-ocr-*.zip")) == before
