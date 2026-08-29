"""Google Cloud Vision OCR provider using the REST API."""

from __future__ import annotations

import base64
import io
import json
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

from app.network import urlopen_https
from app.ocr.types import OCRCancelled, OCRError, OCRLine, OCRResult

VISION_ANNOTATE_URL = "https://vision.googleapis.com/v1/images:annotate"
DEFAULT_TIMEOUT = 15.0
_LANGUAGE_HINTS = {
    "japan": "ja",
    "ja": "ja",
    "japanese": "ja",
}

Urlopen = Callable[..., Any]


class GoogleVisionOCRProvider:
    """Recognize an in-memory image with Google Cloud Vision."""

    def __init__(
        self,
        api_key: str,
        language: str = "japan",
        timeout: float = DEFAULT_TIMEOUT,
        urlopen: Urlopen | None = None,
    ) -> None:
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""
        self.language = language
        self.timeout = float(timeout)
        if self.timeout <= 0 or self.timeout > 15:
            raise ValueError("Google Vision timeout must be between 0 and 15 seconds")
        self._urlopen = urlopen

    def recognize(
        self,
        image: Any,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        self._check_cancel(cancel_event)
        if not self._api_key:
            raise OCRError("Google Vision API key is not configured.")

        image_bytes = self._encode_png(image)
        self._check_cancel(cancel_event)
        request_body = self._request_payload(image_bytes)
        request = urllib.request.Request(
            VISION_ANNOTATE_URL,
            data=json.dumps(request_body, separators=(",", ":")).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )
        self._check_cancel(cancel_event)

        response_bytes = self._request(request)
        self._check_cancel(cancel_event)
        return self._parse_response(response_bytes, cancel_event)

    def test_connection(
        self,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        """Send a generated tiny image, never a user's screenshot."""

        # Draw a tiny bitmap directly into the image. This intentionally avoids
        # QPainter/QFontDatabase so this diagnostic also works without a GUI app.
        glyphs = {
            "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
            "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
            "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
        }
        scale = 3
        image = QImage(4 * 5 * scale + 3 * scale + 6, 7 * scale + 6, QImage.Format.Format_RGB32)
        image.fill(0xFFFFFFFF)
        for index, character in enumerate("TEST"):
            glyph = glyphs[character]
            origin_x = 3 + index * 6 * scale
            origin_y = 3
            for row, bitmap_row in enumerate(glyph):
                for column, pixel in enumerate(bitmap_row):
                    if pixel == "1":
                        for dy in range(scale):
                            for dx in range(scale):
                                image.setPixel(origin_x + column * scale + dx, origin_y + row * scale + dy, 0xFF000000)
        return self.recognize(image, cancel_event=cancel_event)

    def _request_payload(self, image_bytes: bytes) -> dict[str, Any]:
        request: dict[str, Any] = {
            "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
        }
        language_hint = _LANGUAGE_HINTS.get(str(self.language).strip().lower())
        if language_hint:
            request["imageContext"] = {"languageHints": [language_hint]}
        return {"requests": [request]}

    def _request(self, request: urllib.request.Request) -> bytes:
        try:
            response = urlopen_https(
                request,
                timeout=self.timeout,
                opener=self._urlopen,
            )
            try:
                return response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise OCRError(
                    "Google Vision OCR authentication failed. "
                    "Please check your API key and whether Cloud Vision API is enabled."
                ) from exc
            if exc.code == 429:
                raise OCRError("Google Vision OCR quota has been exceeded.") from exc
            if exc.code == 400:
                raise OCRError("Google Vision OCR rejected the request.") from exc
            raise OCRError(f"Google Vision OCR request failed (HTTP {exc.code}).") from exc
        except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as exc:
            raise OCRError("Unable to reach Google Vision OCR.") from exc

    def _parse_response(
        self,
        response_bytes: bytes,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        try:
            payload = json.loads(response_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise OCRError("Google Vision OCR returned malformed JSON.") from exc
        if not isinstance(payload, dict):
            raise OCRError("Google Vision OCR returned malformed JSON.")

        api_error = payload.get("error")
        if isinstance(api_error, dict):
            raise self._api_error(api_error)
        responses = payload.get("responses")
        if not isinstance(responses, list) or not responses or not isinstance(responses[0], dict):
            raise OCRError("Google Vision OCR returned an empty response.")
        response = responses[0]
        if isinstance(response.get("error"), dict):
            raise self._api_error(response["error"])
        annotation = response.get("fullTextAnnotation")
        if not isinstance(annotation, dict):
            raise OCRError("Google Vision OCR found no text.")
        text = annotation.get("text")
        if not isinstance(text, str) or not text.strip():
            raise OCRError("Google Vision OCR found no text.")

        lines = self._lines_from_annotation(annotation, cancel_event, self.language)
        text_lines = tuple(line for line in text.splitlines() if line.strip())
        # Paragraphs are not guaranteed to map one-to-one to visual lines.
        # Prefer the authoritative full text when the reconstructed count differs.
        if not lines:
            lines = tuple(OCRLine(line) for line in text_lines)
        elif len(lines) < len(text_lines):
            lines = tuple(lines) + tuple(
                OCRLine(line) for line in text_lines[len(lines) :]
            )
        elif len(lines) > len(text_lines):
            lines = tuple(OCRLine(line) for line in text_lines)
        return OCRResult(text=text, lines=tuple(lines))

    @staticmethod
    def _api_error(error: dict[str, Any]) -> OCRError:
        code = error.get("code")
        if code in (7, "7", 16, "16"):
            return OCRError(
                "Google Vision OCR authentication failed. "
                "Please check your API key and whether Cloud Vision API is enabled."
            )
        if code in (8, "8", 429, "429"):
            return OCRError("Google Vision OCR quota has been exceeded.")
        if code in (3, "3", 400, "400"):
            return OCRError("Google Vision OCR rejected the request.")
        return OCRError("Google Vision OCR service returned an error.")

    @classmethod
    def _lines_from_annotation(
        cls,
        annotation: dict[str, Any],
        cancel_event: threading.Event | None,
        language: str,
    ) -> tuple[OCRLine, ...]:
        separator = "" if _LANGUAGE_HINTS.get(str(language).strip().lower()) == "ja" else " "
        lines: list[OCRLine] = []
        pages = annotation.get("pages", [])
        if not isinstance(pages, list):
            return ()
        for page in pages:
            cls._check_cancel(cancel_event)
            if not isinstance(page, dict):
                continue
            blocks = page.get("blocks", [])
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                paragraphs = block.get("paragraphs", [])
                if not isinstance(paragraphs, list):
                    continue
                for paragraph in paragraphs:
                    cls._check_cancel(cancel_event)
                    if not isinstance(paragraph, dict):
                        continue
                    words = paragraph.get("words", [])
                    if not isinstance(words, list):
                        continue
                    word_texts: list[str] = []
                    confidences: list[float] = []
                    for word in words:
                        cls._check_cancel(cancel_event)
                        if not isinstance(word, dict):
                            continue
                        symbols = word.get("symbols", [])
                        word_text = "".join(
                            str(symbol.get("text", ""))
                            for symbol in symbols
                            if isinstance(symbol, dict)
                        )
                        if word_text:
                            word_texts.append(word_text)
                        confidence = word.get("confidence")
                        if isinstance(confidence, (int, float)):
                            confidences.append(float(confidence))
                    if not word_texts:
                        continue
                    # Vision's fullTextAnnotation.text remains authoritative. This
                    # line reconstruction is intentionally conservative.
                    line_text = separator.join(word_texts)
                    bounding_box = paragraph.get("boundingBox")
                    vertices = (
                        bounding_box.get("vertices", [])
                        if isinstance(bounding_box, dict)
                        else []
                    )
                    left, top = cls._top_left(vertices)
                    confidence = (
                        sum(confidences) / len(confidences) if confidences else None
                    )
                    lines.append(OCRLine(line_text, confidence, top=top, left=left))
        return tuple(lines)

    @staticmethod
    def _top_left(vertices: Any) -> tuple[float, float]:
        points = [
            vertex
            for vertex in vertices
            if isinstance(vertex, dict)
            and isinstance(vertex.get("x", 0), (int, float))
            and isinstance(vertex.get("y", 0), (int, float))
        ]
        if not points:
            return 0.0, 0.0
        return min(float(point.get("x", 0)) for point in points), min(
            float(point.get("y", 0)) for point in points
        )

    @staticmethod
    def _encode_png(image: Any) -> bytes:
        if isinstance(image, (str, Path)):
            try:
                return Path(image).read_bytes()
            except OSError as exc:
                raise OCRError("Unable to read the OCR image.") from exc
        if isinstance(image, QImage):
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not image.save(buffer, "PNG"):
                raise OCRError("Unable to encode the OCR image as PNG.")
            return bytes(buffer.data())
        save = getattr(image, "save", None)
        if callable(save):
            output = io.BytesIO()
            try:
                saved = save(output, format="PNG")
            except TypeError:
                saved = save(output)
            if saved is False:
                raise OCRError("Unable to encode the OCR image as PNG.")
            return output.getvalue()
        raise OCRError("Google Vision OCR requires an image or image path.")

    @staticmethod
    def _check_cancel(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise OCRCancelled("Google Vision OCR was cancelled.")
