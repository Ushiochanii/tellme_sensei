"""Version of the separately installed local OCR component."""

LOCAL_OCR_VERSION = "1.1.0"
MACOS_LOCAL_OCR_VERSION = "1.2.0"
MACOS_LOCAL_OCR_RELEASE_TAG = "local-ocr-v1.2.0-macos-x64"


def local_ocr_version_for_spec(platform_spec: object | None = None) -> str:
    """Return the immutable component version for a normalized platform spec."""

    if platform_spec is None:
        from app.local_ocr.platform import current_spec

        platform_spec = current_spec()

    if getattr(platform_spec, "platform_id", None) == "macos-x64":
        return MACOS_LOCAL_OCR_VERSION
    return LOCAL_OCR_VERSION


def current_local_ocr_version() -> str:
    """Return the immutable component version for the current platform."""

    return local_ocr_version_for_spec()


def local_ocr_release_tag_for_spec(platform_spec: object | None = None) -> str:
    """Return the immutable release tag for a normalized platform spec."""

    if platform_spec is None:
        from app.local_ocr.platform import current_spec

        platform_spec = current_spec()
    if getattr(platform_spec, "platform_id", None) == "macos-x64":
        return MACOS_LOCAL_OCR_RELEASE_TAG
    return f"local-ocr-v{local_ocr_version_for_spec(platform_spec)}"
