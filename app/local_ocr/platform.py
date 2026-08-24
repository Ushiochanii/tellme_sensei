"""Small platform descriptor for Local OCR component differences."""

from __future__ import annotations

import platform as host_platform
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalOCRPlatformSpec:
    """The platform-specific values needed by the component lifecycle."""

    platform_id: str
    manifest_platform: str
    manifest_arch: str
    executable_name: str
    supported: bool


def normalize_arch(value: str) -> str:
    value = value.lower()
    if value in {"amd64", "x86_64", "x64"}:
        return "x64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    return value


def current_spec() -> LocalOCRPlatformSpec:
    arch = normalize_arch(host_platform.machine())
    if sys.platform == "win32" and arch == "x64":
        return LocalOCRPlatformSpec("windows-x64", "windows", "x86_64", "TellMeSenseiOCR.exe", True)
    if sys.platform == "darwin" and arch == "x64":
        return LocalOCRPlatformSpec("macos-x64", "macos", "x86_64", "TellMeSenseiOCR", True)
    if sys.platform == "darwin" and arch == "arm64":
        return LocalOCRPlatformSpec("macos-arm64", "macos", "arm64", "TellMeSenseiOCR", False)
    return LocalOCRPlatformSpec(f"{sys.platform}-{arch}", sys.platform, arch, "TellMeSenseiOCR", False)


def spec_for_manifest(platform: str, arch: str) -> LocalOCRPlatformSpec | None:
    key = (platform.lower(), arch.lower())
    if key == ("windows", "x86_64"):
        return LocalOCRPlatformSpec("windows-x64", "windows", "x86_64", "TellMeSenseiOCR.exe", True)
    if key == ("macos", "x86_64"):
        return LocalOCRPlatformSpec("macos-x64", "macos", "x86_64", "TellMeSenseiOCR", True)
    if key == ("macos", "arm64"):
        return LocalOCRPlatformSpec("macos-arm64", "macos", "arm64", "TellMeSenseiOCR", False)
    return None


def is_supported() -> bool:
    return current_spec().supported
