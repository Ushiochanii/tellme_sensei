import hashlib
import json
import os
import subprocess
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.local_ocr.component_manager import ComponentError, LocalOCRComponentManager
from app.local_ocr.manifest import ComponentManifest, ManifestError
from app.local_ocr.version import LOCAL_OCR_VERSION, MACOS_LOCAL_OCR_VERSION
from app.local_ocr.platform import spec_for_manifest


def _manifest_for(archive: Path, *, platform: str = "windows", arch: str = "x86_64") -> ComponentManifest:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return ComponentManifest.from_dict(
        {
            "component": "local-ocr",
            "version": LOCAL_OCR_VERSION if platform == "windows" else MACOS_LOCAL_OCR_VERSION,
            "platform": platform,
            "arch": arch,
            "url": "https://example.test/local-ocr.zip",
            "sha256": digest,
            "size": archive.stat().st_size,
            "archive_format": "zip",
        },
        expected_platform=platform,
        expected_arch=arch,
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


def test_manifest_rejects_windows_and_darwin_cross_platform_payloads() -> None:
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

    with pytest.raises(ManifestError):
        ComponentManifest.from_dict(payload, expected_platform="darwin", expected_arch="x86_64")
    with pytest.raises(ManifestError):
        ComponentManifest.from_dict(
            {**payload, "platform": "darwin"},
            expected_platform="windows",
            expected_arch="x86_64",
        )
    with pytest.raises(ManifestError):
        ComponentManifest.from_dict(payload, expected_platform="windows", expected_arch="arm64")


def test_install_archive_success_and_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = _archive(tmp_path / "local.zip")
    manifest = _manifest_for(archive)
    manager = LocalOCRComponentManager(
        tmp_path / "runtime", version=LOCAL_OCR_VERSION,
        platform_spec=spec_for_manifest("windows", "x86_64")
    )
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    installed = manager.install_archive(archive, manifest)

    assert installed == manager.installed_path()
    assert manager.is_installed()
    assert manager.installed_version() == LOCAL_OCR_VERSION
    assert manager.remove() is True
    assert manager.is_installed() is False


def test_checksum_mismatch_deletes_archive(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "local.zip")
    manifest = ComponentManifest.from_dict(
        {
            "component": "local-ocr",
            "version": LOCAL_OCR_VERSION,
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
        LocalOCRComponentManager(
            tmp_path / "runtime", version=LOCAL_OCR_VERSION,
            platform_spec=spec_for_manifest("windows", "x86_64")
        ).install_archive(archive, manifest)
    assert not archive.exists()


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "unsafe.zip", unsafe="../outside.exe")
    manifest = _manifest_for(archive)
    manager = LocalOCRComponentManager(
        tmp_path / "runtime", version=LOCAL_OCR_VERSION,
        platform_spec=spec_for_manifest("windows", "x86_64")
    )
    with pytest.raises(ComponentError, match="unsafe"):
        manager.install_archive(archive, manifest)
    assert not (tmp_path / "outside.exe").exists()


def test_failed_smoke_preserves_existing_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = LocalOCRComponentManager(
        tmp_path / "runtime", version=LOCAL_OCR_VERSION,
        platform_spec=spec_for_manifest("windows", "x86_64")
    )
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
        LocalOCRComponentManager(
            tmp_path / "runtime", version=LOCAL_OCR_VERSION,
            platform_spec=spec_for_manifest("windows", "x86_64")
        ).install_archive(archive, manifest, cancel_event=event)
    assert not (tmp_path / "runtime" / "components").exists()


def test_macos_install_restores_macho_modes_and_requires_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = tmp_path / "macos.zip"
    with zipfile.ZipFile(archive_path, "w") as bundle:
        for name, data, mode in (
            ("TellMeSenseiOCR", b"worker", 0o755),
            ("_internal/runtime.dylib", b"runtime", 0o755),
            ("models/det/inference.pdmodel", b"model", 0o644),
            ("models/det/inference.pdiparams", b"params", 0o644),
            ("models/rec/inference.pdmodel", b"model", 0o644),
            ("models/rec/inference.pdiparams", b"params", 0o644),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            bundle.writestr(info, data)
    manifest = _manifest_for(archive_path, platform="macos", arch="x86_64")
    manager = LocalOCRComponentManager(
        tmp_path / "runtime", platform_spec=spec_for_manifest("macos", "x86_64")
    )
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    installed = manager.install_archive(archive_path, manifest)

    assert os.access(installed / "TellMeSenseiOCR", os.X_OK)
    assert os.access(installed / "_internal/runtime.dylib", os.X_OK)
    assert manager.verify_installation()
