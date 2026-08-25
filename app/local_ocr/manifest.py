"""Validated metadata for downloadable Local OCR components."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from app.local_ocr.platform import current_spec
from app.local_ocr.version import local_ocr_release_tag_for_spec

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
DISTRIBUTION_REPOSITORY = "Ushiochanii/tellme-sensei-releases"


class ManifestError(ValueError):
    """Raised when component metadata is missing or unsafe."""


def _production_url_for_spec(platform_spec: object | None = None) -> str:
    release_tag = local_ocr_release_tag_for_spec(platform_spec)
    return (
        f"https://github.com/{DISTRIBUTION_REPOSITORY}/releases/download/"
        f"{release_tag}/local-ocr-manifest.json"
    )


try:
    # Unsupported development hosts (including ARM64 during A4.1) have no
    # production manifest URL.  Keep import-time defaults harmless there.
    DISTRIBUTION_RELEASE_TAG = local_ocr_release_tag_for_spec()
except ValueError:
    DISTRIBUTION_RELEASE_TAG = ""
    DEFAULT_MANIFEST_URL = ""
else:
    DEFAULT_MANIFEST_URL = _production_url_for_spec()


def production_manifest_url(platform_spec: object | None = None) -> str:
    """Return the pinned production manifest URL for a normalized platform spec."""

    try:
        return _production_url_for_spec(platform_spec)
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc


def current_platform() -> str:
    return current_spec().manifest_platform


def current_arch() -> str:
    return current_spec().manifest_arch


@dataclass(frozen=True)
class ComponentManifest:
    component: str
    version: str
    platform: str
    arch: str
    url: str
    sha256: str
    size: int
    archive_format: str = "zip"

    @classmethod
    def from_dict(
        cls,
        payload: object,
        *,
        expected_platform: str | None = None,
        expected_arch: str | None = None,
    ) -> "ComponentManifest":
        if not isinstance(payload, dict):
            raise ManifestError("Local OCR manifest must be a JSON object.")
        required = ("component", "version", "platform", "arch", "url", "sha256", "size", "archive_format")
        if any(key not in payload for key in required):
            raise ManifestError("Local OCR manifest is missing required fields.")
        values = {key: payload[key] for key in required}
        if not all(isinstance(values[key], str) and values[key].strip() for key in required if key != "size"):
            raise ManifestError("Local OCR manifest contains invalid text fields.")
        version = values["version"].strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ManifestError("Local OCR manifest version is invalid.")
        parsed = urlparse(values["url"].strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ManifestError("Local OCR manifest URL is invalid.")
        sha256 = values["sha256"].strip()
        if not SHA256_RE.fullmatch(sha256):
            raise ManifestError("Local OCR manifest SHA-256 is invalid.")
        size = values["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ManifestError("Local OCR manifest size is invalid.")
        if values["component"].strip() != "local-ocr" or values["archive_format"].strip().lower() != "zip":
            raise ManifestError("Unsupported Local OCR component manifest.")
        expected_platform = expected_platform or current_platform()
        expected_arch = expected_arch or current_arch()
        if values["platform"].strip().lower() != expected_platform.lower():
            raise ManifestError("Local OCR component platform is not supported on this system.")
        if values["arch"].strip().lower() != expected_arch.lower():
            raise ManifestError("Local OCR component architecture is not supported on this system.")
        return cls(
            component="local-ocr",
            version=version,
            platform=values["platform"].strip().lower(),
            arch=values["arch"].strip().lower(),
            url=values["url"].strip(),
            sha256=sha256.lower(),
            size=size,
            archive_format="zip",
        )

    @classmethod
    def from_json(cls, text: str, **kwargs: object) -> "ComponentManifest":
        try:
            payload = json.loads(text.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise ManifestError("Local OCR manifest is not valid JSON.") from exc
        return cls.from_dict(payload, **kwargs)


def resolve_manifest_url(project_root: Path | None = None) -> str:
    """Resolve distribution metadata without exposing a URL setting in the UI."""

    explicit = os.environ.get("LOCAL_OCR_MANIFEST_URL", "").strip()
    if explicit:
        return explicit
    root = project_root or Path(__file__).resolve().parents[2]
    try:
        values = dotenv_values(root / ".env")
    except OSError:
        values = {}
    fallback = values.get("LOCAL_OCR_MANIFEST_URL")
    return str(fallback).strip() if isinstance(fallback, str) and fallback.strip() else DEFAULT_MANIFEST_URL
