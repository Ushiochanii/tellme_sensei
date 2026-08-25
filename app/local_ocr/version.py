"""Version of the separately installed local OCR component."""

LOCAL_OCR_VERSION = "1.1.0"
MACOS_LOCAL_OCR_VERSION = "1.2.0"
MACOS_LOCAL_OCR_RELEASE_TAG = "local-ocr-v1.2.0-macos-x64"
# This value is only for explicit ARM64 lifecycle acceptance.  It is not a
# published component version and must never be used to construct a
# production release URL.
ARM64_LOCAL_OCR_ACCEPTANCE_VERSION = "0.0.0"


def local_ocr_version_for_spec(platform_spec: object | None = None) -> str:
    """Return the immutable component version for a normalized platform spec."""

    if platform_spec is None:
        from app.local_ocr.platform import current_spec

        platform_spec = current_spec()

    platform_id = getattr(platform_spec, "platform_id", None)
    if platform_id == "windows-x64":
        return LOCAL_OCR_VERSION
    if platform_id == "macos-x64":
        return MACOS_LOCAL_OCR_VERSION
    if platform_id == "macos-arm64":
        return ARM64_LOCAL_OCR_ACCEPTANCE_VERSION
    # Unsupported hosts have no production component either.  Retaining the
    # historical Windows value here keeps source-mode discovery predictable;
    # production manifest routing rejects unsupported specs below.
    return LOCAL_OCR_VERSION


def current_local_ocr_version() -> str:
    """Return the immutable component version for the current platform."""

    return local_ocr_version_for_spec()


def local_ocr_release_tag_for_spec(platform_spec: object | None = None) -> str:
    """Return the immutable release tag for a normalized platform spec."""

    if platform_spec is None:
        from app.local_ocr.platform import current_spec

        platform_spec = current_spec()
    platform_id = getattr(platform_spec, "platform_id", None)
    if platform_id == "macos-arm64":
        raise ValueError("macos-arm64 has no production Local OCR release")
    if platform_id == "macos-x64":
        return MACOS_LOCAL_OCR_RELEASE_TAG
    if platform_id == "windows-x64":
        return f"local-ocr-v{LOCAL_OCR_VERSION}"
    raise ValueError(f"unsupported Local OCR production platform: {platform_id}")
