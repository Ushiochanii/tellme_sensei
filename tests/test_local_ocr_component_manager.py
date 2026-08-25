import hashlib
import json
import os
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.local_ocr.component_manager import ComponentError, LocalOCRComponentManager
from app.local_ocr.manifest import ComponentManifest, ManifestError
from app.local_ocr.version import (
    ARM64_LOCAL_OCR_ACCEPTANCE_VERSION,
    LOCAL_OCR_VERSION,
    MACOS_LOCAL_OCR_VERSION,
)
from app.local_ocr.platform import spec_for_manifest


def _manifest_for(archive: Path, *, platform: str = "windows", arch: str = "x86_64") -> ComponentManifest:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    version = {
        ("windows", "x86_64"): LOCAL_OCR_VERSION,
        ("macos", "x86_64"): MACOS_LOCAL_OCR_VERSION,
        ("macos", "arm64"): ARM64_LOCAL_OCR_ACCEPTANCE_VERSION,
    }[(platform, arch)]
    return ComponentManifest.from_dict(
        {
            "component": "local-ocr",
            "version": version,
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
    assert (
        ComponentManifest.from_dict(
            payload, expected_platform="windows", expected_arch="x86_64"
        ).version
        == "1.0.0"
    )
    with pytest.raises(ManifestError):
        ComponentManifest.from_dict(
            {**payload, "sha256": "bad"},
            expected_platform="windows",
            expected_arch="x86_64",
        )
    with pytest.raises(ManifestError):
        ComponentManifest.from_dict(
            {**payload, "platform": "linux"},
            expected_platform="windows",
            expected_arch="x86_64",
        )
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
        ComponentManifest.from_dict(
            payload, expected_platform="windows", expected_arch="arm64"
        )


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


def test_size_mismatch_deletes_archive(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "local.zip")
    manifest = ComponentManifest.from_dict(
        {
            "component": "local-ocr",
            "version": LOCAL_OCR_VERSION,
            "platform": "windows",
            "arch": "x86_64",
            "url": "https://example.test/local-ocr.zip",
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "size": archive.stat().st_size + 1,
            "archive_format": "zip",
        },
        expected_platform="windows",
        expected_arch="x86_64",
    )
    with pytest.raises(ComponentError, match="size"):
        LocalOCRComponentManager(
            tmp_path / "runtime",
            version=LOCAL_OCR_VERSION,
            platform_spec=spec_for_manifest("windows", "x86_64"),
        ).install_archive(archive, manifest)
    assert not archive.exists()


def test_arm64_explicit_lifecycle_accepts_native_layout_while_capability_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = tmp_path / "arm64.zip"
    with zipfile.ZipFile(archive_path, "w") as bundle:
        for name, data, mode in (
            ("TellMeSenseiOCR", b"worker", 0o755),
            ("_internal/libphi.dylib", b"runtime", 0o755),
            ("models/det/PP-OCRv6_medium_det/inference.json", b"{}", 0o644),
            (
                "models/det/PP-OCRv6_medium_det/inference.yml",
                b"Global:\n  model_name: PP-OCRv6_medium_det\n",
                0o644,
            ),
            ("models/det/PP-OCRv6_medium_det/inference.pdiparams", b"params", 0o644),
            ("models/rec/PP-OCRv6_medium_rec/inference.json", b"{}", 0o644),
            (
                "models/rec/PP-OCRv6_medium_rec/inference.yml",
                b"Global:\n  model_name: PP-OCRv6_medium_rec\n",
                0o644,
            ),
            ("models/rec/PP-OCRv6_medium_rec/inference.pdiparams", b"params", 0o644),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            bundle.writestr(info, data)
    manifest = _manifest_for(archive_path, platform="macos", arch="arm64")
    arm_spec = spec_for_manifest("macos", "arm64")
    assert arm_spec is not None
    assert arm_spec.supported is True
    manager = LocalOCRComponentManager(
        tmp_path / "runtime",
        platform_spec=arm_spec,
    )
    assert manager.version == ARM64_LOCAL_OCR_ACCEPTANCE_VERSION
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    installed = manager.install_archive(archive_path, manifest)

    assert installed == manager.installed_path()
    assert os.access(installed / "TellMeSenseiOCR", os.X_OK)
    assert os.access(installed / "_internal/libphi.dylib", os.X_OK)
    assert manager.verify_installation()
    assert manager.remove() is True
    assert not installed.exists()


def test_arm64_explicit_lifecycle_rejects_intel_manifest(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path / "intel.zip")
    manifest = ComponentManifest.from_dict(
        {
            "component": "local-ocr",
            "version": ARM64_LOCAL_OCR_ACCEPTANCE_VERSION,
            "platform": "macos",
            "arch": "x86_64",
            "url": "https://example.test/local-ocr.zip",
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "size": archive.stat().st_size,
            "archive_format": "zip",
        },
        expected_platform="macos",
        expected_arch="x86_64",
    )
    arm_spec = spec_for_manifest("macos", "arm64")
    assert arm_spec is not None
    manager = LocalOCRComponentManager(tmp_path / "runtime", platform_spec=arm_spec)

    with pytest.raises(ComponentError, match="does not match"):
        manager.install_archive(archive, manifest)
    assert not manager.installed_path().exists()


@pytest.mark.parametrize(
    "archive_mutator, message",
    [
        (lambda root: (root / "TellMeSenseiOCR").unlink(), "layout"),
        (lambda root: shutil.rmtree(root / "models/det"), "layout"),
        (lambda root: shutil.rmtree(root / "models/rec"), "layout"),
        (
            lambda root: (root / "models/det/PP-OCRv6_medium_det/inference.yml").unlink(),
            "layout",
        ),
    ],
)
def test_arm64_incomplete_component_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive_mutator, message: str
) -> None:
    source = tmp_path / "source"
    (source / "models/det/PP-OCRv6_medium_det").mkdir(parents=True)
    (source / "models/rec/PP-OCRv6_medium_rec").mkdir(parents=True)
    for model in (
        source / "models/det/PP-OCRv6_medium_det",
        source / "models/rec/PP-OCRv6_medium_rec",
    ):
        (model / "inference.json").write_text("{}", encoding="utf-8")
        (model / "inference.yml").write_text(
            f"Global:\n  model_name: {model.name}\n", encoding="utf-8"
        )
        (model / "inference.pdiparams").write_bytes(b"params")
    (source / "TellMeSenseiOCR").write_bytes(b"worker")
    (source / "_internal").mkdir()
    archive_path = tmp_path / "arm64-incomplete.zip"
    with zipfile.ZipFile(archive_path, "w") as bundle:
        for path in source.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(source))
    extracted = tmp_path / "mutated"
    with zipfile.ZipFile(archive_path) as bundle:
        bundle.extractall(extracted)
    archive_mutator(extracted)
    mutated_archive = tmp_path / "mutated.zip"
    with zipfile.ZipFile(mutated_archive, "w") as bundle:
        for path in extracted.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(extracted))
    manifest = _manifest_for(mutated_archive, platform="macos", arch="arm64")
    arm_spec = spec_for_manifest("macos", "arm64")
    assert arm_spec is not None
    manager = LocalOCRComponentManager(
        tmp_path / "runtime", platform_spec=arm_spec,
    )
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    with pytest.raises(ComponentError, match=message):
        manager.install_archive(mutated_archive, manifest)
    assert not manager.installed_path().exists()


def test_activation_failure_preserves_existing_arm64_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "new.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("TellMeSenseiOCR", b"new")
        bundle.writestr("_internal/runtime.dylib", b"runtime")
        for kind, name in (("det", "det"), ("rec", "rec")):
            bundle.writestr(f"models/{kind}/{name}/inference.json", b"{}")
            bundle.writestr(
                f"models/{kind}/{name}/inference.yml",
                f"Global:\n  model_name: {name}\n",
            )
            bundle.writestr(f"models/{kind}/{name}/inference.pdiparams", b"params")
    manifest = _manifest_for(archive, platform="macos", arch="arm64")
    arm_spec = spec_for_manifest("macos", "arm64")
    assert arm_spec is not None
    manager = LocalOCRComponentManager(tmp_path / "runtime", platform_spec=arm_spec)
    old = manager.installed_path()
    old.mkdir(parents=True)
    (old / "TellMeSenseiOCR").write_bytes(b"old")
    (old / "_internal").mkdir()
    (old / "models/det/old").mkdir(parents=True)
    (old / "models/rec/old").mkdir(parents=True)
    for kind in ("det", "rec"):
        model = old / "models" / kind / "old"
        (model / "inference.pdmodel").write_bytes(b"model")
        (model / "inference.pdiparams").write_bytes(b"params")
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    def fail_activation(_staging: Path) -> Path:
        raise ComponentError("activation failed")

    monkeypatch.setattr(manager, "_atomic_activate", fail_activation)

    with pytest.raises(ComponentError, match="activation"):
        manager.install_archive(archive, manifest)
    assert (old / "TellMeSenseiOCR").read_bytes() == b"old"


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
        tmp_path / "runtime",
        version=MACOS_LOCAL_OCR_VERSION,
        platform_spec=spec_for_manifest("macos", "x86_64"),
    )
    monkeypatch.setattr(
        "app.local_ocr.component_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    installed = manager.install_archive(archive_path, manifest)

    assert os.access(installed / "TellMeSenseiOCR", os.X_OK)
    assert os.access(installed / "_internal/runtime.dylib", os.X_OK)
    assert manager.verify_installation()
