from app.local_ocr.platform import current_spec, normalize_arch, spec_for_manifest


def test_normalized_platform_specs_are_stable() -> None:
    assert spec_for_manifest("windows", "x86_64").platform_id == "windows-x64"
    assert spec_for_manifest("windows", "x86_64").executable_name == "TellMeSenseiOCR.exe"
    assert spec_for_manifest("macos", "x86_64").platform_id == "macos-x64"
    assert spec_for_manifest("macos", "x86_64").executable_name == "TellMeSenseiOCR"
    assert spec_for_manifest("macos", "arm64").supported is True


def test_architecture_aliases_are_normalized() -> None:
    assert normalize_arch("AMD64") == "x64"
    assert normalize_arch("x86_64") == "x64"
    assert normalize_arch("aarch64") == "arm64"


def test_current_intel_macos_descriptor(monkeypatch) -> None:
    import app.local_ocr.platform as platform_module

    monkeypatch.setattr(platform_module.sys, "platform", "darwin")
    monkeypatch.setattr(platform_module.host_platform, "machine", lambda: "x86_64")
    spec = current_spec()
    assert spec.platform_id == "macos-x64"
    assert spec.manifest_platform == "macos"
    assert spec.manifest_arch == "x86_64"
    assert spec.supported is True
