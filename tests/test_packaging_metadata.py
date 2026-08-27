from pathlib import Path

from app.version import __version__
from app.local_ocr.version import LOCAL_OCR_VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_packaging_uses_single_release_version_source() -> None:
    assert __version__ == "0.7.1"
    assert LOCAL_OCR_VERSION == "1.4.0"
    spec = (ROOT / "packaging" / "tellme_sensei.spec").read_text(encoding="utf-8")
    assert "from app.version import __version__" in spec
    assert "version=str(version_file)" in spec


def test_windows_packaging_metadata_is_present() -> None:
    icon = ROOT / "assets" / "tellme_sensei.ico"
    iss = (ROOT / "packaging" / "windows" / "tellme_sensei.iss").read_text(
        encoding="utf-8"
    )
    build_script = (ROOT / "scripts" / "build_installer.ps1").read_text(
        encoding="utf-8"
    )

    assert icon.is_file()
    assert icon.stat().st_size > 0
    assert "PrivilegesRequired=lowest" in iss
    assert "AppId={{D4B4E8C6-8B91-4C8B-9C20-2C3A0DA2A8B4}" in iss
    assert "Source: \"{#PortableDir}\\*\"" in iss
    assert "OutputBaseFilename=TellMeSensei-Setup-{#VersionLabel}" in iss
    assert '{app}\\_internal\\paddle' in iss
    assert '{app}\\_internal\\paddleocr' in iss
    assert '{app}\\_internal\\Cython' in iss
    assert "ISCC.exe not found" in build_script
    assert "build_windows.ps1" in build_script
    assert ".sha256" in build_script


def test_rc_versions_are_independent_and_installer_fallback_is_current() -> None:
    iss = (ROOT / "packaging" / "windows" / "tellme_sensei.iss").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")

    assert 'VersionLabel "0.6.0"' in iss
    assert 'AppVersion "0.6.0"' in iss
    assert 'from app.version import __version__' in build_script


def test_local_ocr_distribution_metadata_is_versioned_and_public() -> None:
    package_script = (ROOT / "scripts" / "package_local_ocr.ps1").read_text(encoding="utf-8")
    publish_script = (ROOT / "scripts" / "publish_local_ocr.ps1").read_text(encoding="utf-8")
    manifest = (ROOT / "app" / "local_ocr" / "manifest.py").read_text(encoding="utf-8")

    assert "Ushiochanii/tellme_sensei" in manifest
    assert "local_ocr_release_tag_for_spec" in manifest
    assert "downloads.example.invalid" not in package_script
    assert "schema_version = 1" in package_script
    assert "release create" in publish_script
    assert "Release already exists. Bump the component version" in publish_script
