from pathlib import Path

import pytest

from app.local_ocr.download import USER_AGENT
from app.local_ocr.manifest import (
    ComponentManifest,
    DEFAULT_MANIFEST_URL,
    DISTRIBUTION_REPOSITORY,
    ManifestError,
    manifest_url_available,
    production_manifest_url,
    resolve_manifest_url,
)
from app.local_ocr.platform import spec_for_manifest
from app.local_ocr.version import (
    ARM64_LOCAL_OCR_ACCEPTANCE_VERSION,
    LOCAL_OCR_VERSION,
    MACOS_LOCAL_OCR_RELEASE_TAG,
    MACOS_LOCAL_OCR_VERSION,
    current_local_ocr_version,
    local_ocr_release_tag_for_spec,
)
from app.version import __version__
from app.local_ocr.component_manager import LocalOCRComponentManager


def test_local_ocr_version_and_production_manifest_url() -> None:
    assert LOCAL_OCR_VERSION == "1.1.0"
    assert MACOS_LOCAL_OCR_VERSION == "1.2.0"
    assert MACOS_LOCAL_OCR_RELEASE_TAG == "local-ocr-v1.2.0-macos-x64"
    assert DISTRIBUTION_REPOSITORY == "Ushiochanii/tellme-sensei-releases"
    intel_spec = spec_for_manifest("macos", "x86_64")
    assert local_ocr_release_tag_for_spec(intel_spec) == "local-ocr-v1.2.0-macos-x64"
    assert production_manifest_url(intel_spec) == (
        "https://github.com/Ushiochanii/tellme-sensei-releases/releases/download/"
        "local-ocr-v1.2.0-macos-x64/local-ocr-manifest.json"
    )


def test_platform_production_manifest_routes_are_pinned() -> None:
    assert production_manifest_url(spec_for_manifest("windows", "x86_64")) == (
        "https://github.com/Ushiochanii/tellme-sensei-releases/releases/download/"
        "local-ocr-v1.1.0/local-ocr-manifest.json"
    )
    assert production_manifest_url(spec_for_manifest("macos", "x86_64")) == (
        "https://github.com/Ushiochanii/tellme-sensei-releases/releases/download/"
        "local-ocr-v1.2.0-macos-x64/local-ocr-manifest.json"
    )
    with pytest.raises(ManifestError, match="no production"):
        production_manifest_url(spec_for_manifest("macos", "arm64"))


def test_arm64_acceptance_version_is_not_a_production_route() -> None:
    arm_spec = spec_for_manifest("macos", "arm64")
    assert arm_spec is not None
    assert arm_spec.supported is True
    assert current_local_ocr_version() == ARM64_LOCAL_OCR_ACCEPTANCE_VERSION


def test_arm64_manifest_requires_macos_arm64_pair() -> None:
    payload = {
        "component": "local-ocr",
        "version": ARM64_LOCAL_OCR_ACCEPTANCE_VERSION,
        "platform": "macos",
        "arch": "arm64",
        "url": "http://127.0.0.1:8765/arm64.zip",
        "sha256": "a" * 64,
        "size": 1,
        "archive_format": "zip",
    }
    assert ComponentManifest.from_dict(
        payload, expected_platform="macos", expected_arch="arm64"
    ).arch == "arm64"
    for wrong_platform, wrong_arch in (
        ("macos", "x86_64"),
        ("windows", "x86_64"),
        ("windows", "arm64"),
    ):
        with pytest.raises(ManifestError):
            ComponentManifest.from_dict(
                {**payload, "platform": wrong_platform, "arch": wrong_arch},
                expected_platform="macos",
                expected_arch="arm64",
            )


def test_manifest_url_precedence_keeps_environment_and_dotenv_separate(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LOCAL_OCR_MANIFEST_URL=https://dotenv.test/manifest.json\n", encoding="utf-8")
    monkeypatch.delenv("LOCAL_OCR_MANIFEST_URL", raising=False)
    assert resolve_manifest_url(tmp_path) == "https://dotenv.test/manifest.json"

    monkeypatch.setenv("LOCAL_OCR_MANIFEST_URL", "https://env.test/manifest.json")
    assert resolve_manifest_url(tmp_path) == "https://env.test/manifest.json"

    monkeypatch.delenv("LOCAL_OCR_MANIFEST_URL", raising=False)
    env_file.unlink()
    assert resolve_manifest_url(tmp_path) == DEFAULT_MANIFEST_URL


def test_arm_distribution_is_unavailable_without_override(tmp_path: Path) -> None:
    assert manifest_url_available(tmp_path) is False
    (tmp_path / ".env").write_text(
        "LOCAL_OCR_MANIFEST_URL=http://127.0.0.1:8765/manifest.json\n",
        encoding="utf-8",
    )
    assert manifest_url_available(tmp_path) is True


def test_download_user_agent_follows_application_version() -> None:
    assert USER_AGENT == f"TellMeSensei/{__version__}"


def test_old_local_ocr_component_directory_does_not_satisfy_new_version(tmp_path: Path) -> None:
    manager = LocalOCRComponentManager(tmp_path / "runtime")
    old = manager.components_root / "1.0.0"
    (old / "_internal").mkdir(parents=True)
    (old / "TellMeSenseiOCR.exe").write_bytes(b"old")

    assert manager.installed_path().name == current_local_ocr_version()
    assert manager.is_installed() is False
