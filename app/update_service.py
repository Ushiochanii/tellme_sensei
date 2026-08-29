"""Manual application updates backed by TellMeSensei GitHub Releases."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.network import urlopen_https

RELEASES_API_URL = (
    "https://api.github.com/repos/Ushiochanii/tellme_sensei/releases?per_page=20"
)
_APP_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([^+]+))?(?:\+.+)?$")


class UpdateError(RuntimeError):
    """Raised when a manual update cannot be checked, downloaded, or launched."""


class UpdateCancelled(UpdateError):
    """Raised when an in-progress update operation is cancelled."""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    update_available: bool
    asset: ReleaseAsset


Launcher = Callable[[Path], None]


class UpdateService:
    """Find the newest stable app release and launch its platform package."""

    def __init__(
        self,
        *,
        releases_url: str = RELEASES_API_URL,
        timeout: float = 10.0,
        opener: Callable[..., Any] | None = None,
        launcher: Launcher | None = None,
        system: str | None = None,
        machine: str | None = None,
    ) -> None:
        self.releases_url = releases_url
        self.timeout = timeout
        self.opener = opener
        self.launcher = launcher
        self.system = system or platform.system()
        self.machine = (machine or platform.machine()).lower()

    def check_for_update(
        self,
        current_version: str,
        cancel_event: threading.Event | None = None,
    ) -> UpdateCheckResult:
        """Return the newest stable TellMeSensei app release for this machine."""

        self._raise_if_cancelled(cancel_event)
        releases = self._fetch_releases()
        self._raise_if_cancelled(cancel_event)
        current_key = _version_key(current_version)

        for release in releases:
            if not isinstance(release, dict):
                continue
            if release.get("draft") or release.get("prerelease"):
                continue
            tag = str(release.get("tag_name") or "")
            match = _APP_RELEASE_TAG.fullmatch(tag)
            if match is None:
                # The repository also publishes Local OCR releases.  Those are
                # a separate component stream and must not drive app updates.
                continue
            latest_version = ".".join(match.groups())
            asset = self._select_asset(release, latest_version)
            return UpdateCheckResult(
                current_version=current_version,
                latest_version=latest_version,
                update_available=_version_key(latest_version) > current_key,
                asset=asset,
            )

        raise UpdateError("No stable TellMeSensei application release was found on GitHub.")

    def download_and_launch(
        self,
        asset: ReleaseAsset,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """Download one already-selected release asset and open it with the OS."""

        self._raise_if_cancelled(cancel_event)
        directory = Path(tempfile.mkdtemp(prefix="tellme-sensei-update-"))
        target = directory / asset.name
        request = urllib.request.Request(
            asset.download_url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "TellMeSensei-Updater",
            },
            method="GET",
        )
        response = None
        try:
            response = urlopen_https(request, timeout=self.timeout, opener=self.opener)
            with target.open("wb") as output:
                while True:
                    self._raise_if_cancelled(cancel_event)
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            self._raise_if_cancelled(cancel_event)
            (self.launcher or self._launch_package)(target)
            return target
        except UpdateCancelled:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, UpdateError):
                raise
            raise UpdateError(f"Unable to download or open the update: {exc}") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _fetch_releases(self) -> list[Any]:
        request = urllib.request.Request(
            self.releases_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "TellMeSensei-Updater",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        response = None
        try:
            response = urlopen_https(request, timeout=self.timeout, opener=self.opener)
            payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise UpdateError(f"Unable to check GitHub Releases: {exc}") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not isinstance(payload, list):
            raise UpdateError("GitHub Releases returned an unexpected response.")
        return payload

    def _select_asset(self, release: dict[str, Any], version: str) -> ReleaseAsset:
        expected_name = self._expected_asset_name(version)
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise UpdateError(f"Release v{version} does not contain downloadable assets.")
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("name") != expected_name:
                continue
            download_url = str(asset.get("browser_download_url") or "")
            if download_url:
                return ReleaseAsset(expected_name, download_url)
        raise UpdateError(
            f"Release v{version} does not include the package for this platform: "
            f"{expected_name}"
        )

    def _expected_asset_name(self, version: str) -> str:
        if self.system == "Windows" and self.machine in {"amd64", "x86_64"}:
            return f"TellMeSensei-Setup-{version}.exe"
        if self.system == "Darwin" and self.machine in {"arm64", "aarch64"}:
            return f"TellMeSensei-{version}-macos-arm64.dmg"
        if self.system == "Darwin" and self.machine == "x86_64":
            return f"TellMeSensei-{version}-macos-x64.dmg"
        raise UpdateError(
            f"Automatic update is not available for {self.system} {self.machine}."
        )

    def _launch_package(self, path: Path) -> None:
        try:
            if self.system == "Windows":
                subprocess.Popen([str(path)], close_fds=True)
                return
            if self.system == "Darwin":
                subprocess.Popen(["open", str(path)], close_fds=True)
                return
        except OSError as exc:
            raise UpdateError(f"Unable to open the downloaded update: {exc}") from exc
        raise UpdateError(f"Automatic update is not available for {self.system}.")

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise UpdateCancelled("Update cancelled")


def _version_key(version: str) -> tuple[int, int, int, int]:
    """Compare the project's stable versions and its reachable RC/dev builds."""

    match = _VERSION.fullmatch(version.strip())
    if match is None:
        raise UpdateError(f"Unsupported application version: {version}")
    major, minor, patch, prerelease = match.groups()
    # A stable release sorts after any prerelease with the same numeric core.
    return int(major), int(minor), int(patch), 0 if prerelease else 1


__all__ = [
    "ReleaseAsset",
    "UpdateCancelled",
    "UpdateCheckResult",
    "UpdateError",
    "UpdateService",
]
