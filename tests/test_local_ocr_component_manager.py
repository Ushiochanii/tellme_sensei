import hashlib
import json
import subprocess
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.local_ocr.component_manager import ComponentError, LocalOCRComponentManager
from app.local_ocr.manifest import ComponentManifest, ManifestError


def _manifest_for(archive: Path, *, platform: str = "windows", arch: str = "x86_64") -> ComponentManifest:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return ComponentManifest.from_dict(
        {
            "component": "local-ocr",
            "version": "1.0.0",
            "platform": platform,
            "arch": arch,
            "url": "https://example.test/local-ocr.zip",
            "sha256": digest,
            "size": archive.stat().st_size,
            "archive_format": "zip",
        }
    )


def _archive(path: Path, *, unsafe: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("TellMeSenseiOCR.exe", b"worker")
        bundle.writestr("_internal/runtime.dll", b"runtime")
        if unsafe is not None:
            bundle.writestr(unsafe, b"bad")
    return path


def test_manifest_validates_platform_arch_and_sha() -> None:
    payload = {
        "component": "local-ocr",
        "version": "1.0.0",
        "platform": "windows",
        "arch": "x86_64",
        "url": "https://example.test/component.zip",
        "sha256": "a" * 64,
        "size": 10,
        "archive_format": "zip",
    }
    assert ComponentManifest.from_dict(payload, expected_platform="windows", expected_arch="x86_64").version == "1.0.0"
    with pytest.raises(ManifestError):
        ComponentManifest.from_dict({**payload, "sha256": "bad"}, expected_platform="windows", expected_arch="x86_64")
    with pytest.raises(ManifestError):
        ComponentManifest.from_dict({**payload, "platform": "linux"}, expected_platform="windows", expected_arch="x86_64")
    with pytest.raises(ManifestError):
        ComponentManifest.from_dict({**payload, "arch": "arm64"}, expected_platform="windows", expected_arch="x86_64")


def test_install_archive_success_and_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = _archive(tmp_path / "local.zip")
    manifest = _manifest_for(archive)
    manager = LocalOCRComponentManager(tmp_path / "runtime")
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    installed = manager.install_archive(archive, manifest)

    assert installed == manager.installed_path()
    assert manager.is_installed()
    assert manager.installed_version() == "1.0.0"
    assert manager.remove() is True
    assert manager.is_installed() is False


def test_checksum_mismatch_deletes_archive(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "local.zip")
    manifest = ComponentManifest.from_dict(
        {
            "component": "local-ocr",
            "version": "1.0.0",
            "platform": "windows",
            "arch": "x86_64",
            "url": "https://example.test/component.zip",
            "sha256": "b" * 64,
            "size": archive.stat().st_size,
            "archive_format": "zip",
        },
        expected_platform="windows",
        expected_arch="x86_64",
    )
    with pytest.raises(ComponentError, match="checksum"):
        LocalOCRComponentManager(tmp_path / "runtime").install_archive(archive, manifest)
    assert not archive.exists()


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "unsafe.zip", unsafe="../outside.exe")
    manifest = _manifest_for(archive)
    manager = LocalOCRComponentManager(tmp_path / "runtime")
    with pytest.raises(ComponentError, match="unsafe"):
        manager.install_archive(archive, manifest)
    assert not (tmp_path / "outside.exe").exists()


def test_failed_smoke_preserves_existing_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = LocalOCRComponentManager(tmp_path / "runtime")
    old = manager.installed_path()
    old.mkdir(parents=True)
    (old / "TellMeSenseiOCR.exe").write_bytes(b"old")
    (old / "_internal").mkdir()
    archive = _archive(tmp_path / "new.zip")
    manifest = _manifest_for(archive)
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    with pytest.raises(ComponentError, match="smoke"):
        manager.install_archive(archive, manifest)
    assert (old / "TellMeSenseiOCR.exe").read_bytes() == b"old"


def test_install_cancellation_does_not_activate(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "local.zip")
    manifest = _manifest_for(archive)
    event = threading.Event()
    event.set()
    with pytest.raises(Exception):
        LocalOCRComponentManager(tmp_path / "runtime").install_archive(archive, manifest, cancel_event=event)
    assert not (tmp_path / "runtime" / "components").exists()
