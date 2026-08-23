"""Concrete OCR provider implementations, loaded lazily by name."""

__all__ = ["GoogleVisionOCRProvider", "LocalOCRProvider", "PaddleOCRProvider"]


def __getattr__(name: str):
    if name == "GoogleVisionOCRProvider":
        from app.ocr.providers.google_vision import GoogleVisionOCRProvider

        return GoogleVisionOCRProvider
    if name == "LocalOCRProvider":
        from app.ocr.providers.local_worker import LocalOCRProvider

        return LocalOCRProvider
    if name == "PaddleOCRProvider":
        from app.ocr.providers.paddle import PaddleOCRProvider

        return PaddleOCRProvider
    raise AttributeError(name)
