"""External local OCR component support, loaded lazily by feature."""

__all__ = [
    "ComponentCancelled",
    "ComponentManager",
    "ComponentError",
    "ComponentManifest",
    "LocalOCRComponentManager",
    "ManifestError",
]


def __getattr__(name: str):
    if name in {"ComponentCancelled", "ComponentError", "ComponentManager", "LocalOCRComponentManager"}:
        from app.local_ocr.component_manager import ComponentCancelled, ComponentError, ComponentManager, LocalOCRComponentManager

        return {
            "ComponentCancelled": ComponentCancelled,
            "ComponentError": ComponentError,
            "ComponentManager": ComponentManager,
            "LocalOCRComponentManager": LocalOCRComponentManager,
        }[name]
    if name in {"ComponentManifest", "ManifestError"}:
        from app.local_ocr.manifest import ComponentManifest, ManifestError

        return {"ComponentManifest": ComponentManifest, "ManifestError": ManifestError}[name]
    raise AttributeError(name)
