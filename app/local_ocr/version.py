"""Version of the separately installed local OCR component."""

LOCAL_OCR_VERSION = "1.4.0"
LOCAL_OCR_RELEASE_TAG = "local-ocr-v1.4.0"


def local_ocr_version_for_spec(platform_spec: object | None = None) -> str:
    """Return the immutable component version for a normalized platform spec."""

    if platform_spec is None:
        from app.local_ocr.platform import current_spec

        platform_spec = current_spec()

    platform_id = getattr(platform_spec, "platform_id", None)
    if platform_id in {"windows-x64", "macos-x64", "macos-arm64"}:
        return LOCAL_OCR_VERSION
    raise ValueError(f"unsupported Local OCR production platform: {platform_id}")


def current_local_ocr_version() -> str:
    """Return the immutable component version for the current platform."""

    return local_ocr_version_for_spec()


def local_ocr_release_tag_for_spec(platform_spec: object | None = None) -> str:
    """Return the immutable release tag for a normalized platform spec."""

    if platform_spec is None:
        from app.local_ocr.platform import current_spec

        platform_spec = current_spec()
    platform_id = getattr(platform_spec, "platform_id", None)
    if platform_id in {"windows-x64", "macos-x64", "macos-arm64"}:
        return LOCAL_OCR_RELEASE_TAG
    raise ValueError(f"unsupported Local OCR production platform: {platform_id}")
