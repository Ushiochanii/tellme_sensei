from pathlib import Path

from app.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_packaging_uses_single_release_version_source() -> None:
    assert __version__ == "0.4.0"
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
    assert "ISCC.exe not found" in build_script
    assert "build_windows.ps1" in build_script
