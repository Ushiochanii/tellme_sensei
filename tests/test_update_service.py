from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.update_service import UpdateCancelled, UpdateError, UpdateService


class FakeResponse:
    def __init__(self, payload: bytes, *, chunk_size: int | None = None) -> None:
        self.payload = payload
        self.chunk_size = chunk_size
        self.offset = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            self.offset = len(self.payload)
            return self.payload
        if self.offset >= len(self.payload):
            return b""
        take = self.chunk_size or size
        chunk = self.payload[self.offset : self.offset + min(size, take)]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def _release(version: str, asset_names: list[str], *, tag: str | None = None) -> dict:
    release_tag = tag or f"v{version}"
    return {
        "tag_name": release_tag,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://example.invalid/{name}",
            }
            for name in asset_names
        ],
    }


def _opener_for_releases(releases: list[dict]):
    payload = json.dumps(releases).encode("utf-8")

    def opener(_request, **_kwargs):
        return FakeResponse(payload)

    return opener


def test_windows_update_skips_local_ocr_release_and_selects_installer() -> None:
    releases = [
        _release("1.4.0", ["TellMeSenseiOCR-1.4.0-windows-x64.zip"], tag="local-ocr-v1.4.0"),
        _release("0.8.2", ["TellMeSensei-Setup-0.8.2.exe"]),
    ]
    service = UpdateService(
        opener=_opener_for_releases(releases), system="Windows", machine="AMD64"
    )

    result = service.check_for_update("0.8.1")

    assert result.update_available is True
    assert result.latest_version == "0.8.2"
    assert result.asset.name == "TellMeSensei-Setup-0.8.2.exe"


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ("arm64", "TellMeSensei-0.8.2-macos-arm64.dmg"),
        ("x86_64", "TellMeSensei-0.8.2-macos-x64.dmg"),
    ],
)
def test_macos_update_selects_native_dmg(machine: str, expected: str) -> None:
    releases = [
        _release(
            "0.8.2",
            [
                "TellMeSensei-0.8.2-macos-arm64.dmg",
                "TellMeSensei-0.8.2-macos-x64.dmg",
            ],
        )
    ]
    service = UpdateService(
        opener=_opener_for_releases(releases), system="Darwin", machine=machine
    )

    assert service.check_for_update("0.8.1").asset.name == expected


def test_current_stable_release_reports_no_update() -> None:
    releases = [_release("0.8.1", ["TellMeSensei-Setup-0.8.1.exe"])]
    service = UpdateService(
        opener=_opener_for_releases(releases), system="Windows", machine="x86_64"
    )

    result = service.check_for_update("0.8.1")

    assert result.update_available is False
    assert result.latest_version == "0.8.1"


def test_stable_release_updates_same_version_release_candidate() -> None:
    releases = [_release("0.8.2", ["TellMeSensei-Setup-0.8.2.exe"])]
    service = UpdateService(
        opener=_opener_for_releases(releases), system="Windows", machine="x86_64"
    )

    assert service.check_for_update("0.8.2-rc.2").update_available is True


def test_missing_platform_asset_is_actionable() -> None:
    releases = [_release("0.8.2", ["TellMeSensei-0.8.2-macos-arm64.dmg"])]
    service = UpdateService(
        opener=_opener_for_releases(releases), system="Windows", machine="x86_64"
    )

    with pytest.raises(UpdateError, match="TellMeSensei-Setup-0.8.2.exe"):
        service.check_for_update("0.8.1")


def test_download_writes_asset_and_launches_it() -> None:
    release_payload = json.dumps(
        [_release("0.8.2", ["TellMeSensei-Setup-0.8.2.exe"])]
    ).encode("utf-8")
    package = b"installer-bytes"
    responses = [FakeResponse(release_payload), FakeResponse(package, chunk_size=4)]
    launched: list[Path] = []

    def opener(_request, **_kwargs):
        return responses.pop(0)

    service = UpdateService(
        opener=opener,
        launcher=launched.append,
        system="Windows",
        machine="x86_64",
    )
    result = service.check_for_update("0.8.1")

    path = service.download_and_launch(result.asset)

    assert path.read_bytes() == package
    assert launched == [path]


def test_cancelled_download_does_not_launch() -> None:
    package = FakeResponse(b"abcdef", chunk_size=2)
    launched: list[Path] = []
    cancel_event = threading.Event()

    def opener(_request, **_kwargs):
        original_read = package.read

        def read_and_cancel(size=-1):
            chunk = original_read(size)
            if chunk:
                cancel_event.set()
            return chunk

        package.read = read_and_cancel  # type: ignore[method-assign]
        return package

    service = UpdateService(
        opener=opener,
        launcher=launched.append,
        system="Windows",
        machine="x86_64",
    )

    from app.update_service import ReleaseAsset

    with pytest.raises(UpdateCancelled):
        service.download_and_launch(
            ReleaseAsset("TellMeSensei-Setup-0.8.2.exe", "https://example.invalid/update.exe"),
            cancel_event,
        )
    assert launched == []
