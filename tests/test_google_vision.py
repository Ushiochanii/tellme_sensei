from __future__ import annotations

import io
import json
import threading
import urllib.error

import pytest
from PySide6.QtGui import QImage

from app.config import AppConfig, ConfigError
from app.ocr.factory import create_ocr_provider
from app.ocr.providers.google_vision import GoogleVisionOCRProvider
from app.ocr.providers.local_worker import LocalOCRProvider
from app.ocr.types import OCRCancelled, OCRError


class _Response:
    def __init__(self, payload: object, on_read=None) -> None:
        self.data = json.dumps(payload).encode("utf-8")
        self.on_read = on_read
        self.closed = False

    def read(self) -> bytes:
        if self.on_read:
            self.on_read()
        return self.data

    def close(self) -> None:
        self.closed = True


def _image() -> QImage:
    image = QImage(3, 3, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    return image


def _success_payload() -> dict:
    return {
        "responses": [
            {
                "fullTextAnnotation": {
                    "text": "第一行\n第二行\n",
                    "pages": [
                        {
                            "blocks": [
                                {
                                    "paragraphs": [
                                        {
                                            "boundingBox": {
                                                "vertices": [
                                                    {"x": 20, "y": 12},
                                                    {"x": 100, "y": 12},
                                                ]
                                            },
                                            "words": [
                                                {
                                                    "confidence": 0.96,
                                                    "symbols": [
                                                        {"text": "第一"},
                                                        {"text": "行"},
                                                    ],
                                                }
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            }
        ]
    }


def test_factory_defaults_to_local_and_can_create_google() -> None:
    assert isinstance(create_ocr_provider(AppConfig(api_key="x")), LocalOCRProvider)
    provider = create_ocr_provider(
        AppConfig(
            api_key="x",
            ocr_provider="google_vision",
            google_vision_api_key="google-key",
        )
    )
    assert isinstance(provider, GoogleVisionOCRProvider)


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ConfigError, match="Unsupported OCR provider"):
        create_ocr_provider(AppConfig(api_key="x", ocr_provider="unknown"))


def test_request_uses_header_and_document_detection(qt_app) -> None:
    captured: dict[str, object] = {}

    def urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(_success_payload())

    result = GoogleVisionOCRProvider(
        "secret-google-key", language="japan", urlopen=urlopen
    ).recognize(_image())

    request = captured["request"]
    assert request.full_url == "https://vision.googleapis.com/v1/images:annotate"
    assert request.headers["X-goog-api-key"] == "secret-google-key"
    body = json.loads(request.data)
    vision_request = body["requests"][0]
    assert vision_request["features"] == [{"type": "DOCUMENT_TEXT_DETECTION"}]
    assert vision_request["imageContext"] == {"languageHints": ["ja"]}
    assert "secret-google-key" not in request.full_url
    assert result.text == "第一行\n第二行\n"
    assert [line.text for line in result.lines] == ["第一行", "第二行"]
    assert result.lines[0].confidence == 0.96
    assert result.lines[0].left == 20.0
    assert result.lines[0].top == 12.0


def test_unknown_language_omits_google_language_hint(qt_app) -> None:
    provider = GoogleVisionOCRProvider("key", language="paddle-unknown")
    payload = provider._request_payload(b"png")
    assert "imageContext" not in payload["requests"][0]


def test_empty_response_is_an_ocr_error(qt_app) -> None:
    provider = GoogleVisionOCRProvider("key", urlopen=lambda *_args, **_kwargs: _Response({"responses": [{}]}))
    with pytest.raises(OCRError, match="found no text"):
        provider.recognize(_image())


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "rejected the request"),
        (403, "authentication failed"),
        (429, "quota has been exceeded"),
    ],
)
def test_http_errors_are_user_facing(qt_app, status: int, message: str) -> None:
    def urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://vision.googleapis.com/v1/images:annotate",
            status,
            "failure",
            {},
            io.BytesIO(b"secret response details"),
        )

    with pytest.raises(OCRError, match=message):
        GoogleVisionOCRProvider("secret-key", urlopen=urlopen).recognize(_image())


def test_network_timeout_and_malformed_json(qt_app) -> None:
    def timeout(*_args, **_kwargs):
        raise TimeoutError()

    with pytest.raises(OCRError, match="Unable to reach"):
        GoogleVisionOCRProvider("key", urlopen=timeout).recognize(_image())

    malformed = GoogleVisionOCRProvider("key", urlopen=lambda *_args, **_kwargs: type(
        "Response", (), {"read": lambda self: b"not-json", "close": lambda self: None}
    )())
    with pytest.raises(OCRError, match="malformed JSON"):
        malformed.recognize(_image())


def test_api_level_error_is_not_raw_response(qt_app) -> None:
    provider = GoogleVisionOCRProvider(
        "secret-key",
        urlopen=lambda *_args, **_kwargs: _Response(
            {"error": {"code": 7, "message": "secret internal detail"}}
        ),
    )
    with pytest.raises(OCRError, match="authentication failed") as error:
        provider.recognize(_image())
    assert "secret internal detail" not in str(error.value)


def test_cancellation_before_and_after_request(qt_app) -> None:
    event = threading.Event()
    event.set()
    calls = 0

    def should_not_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response(_success_payload())

    with pytest.raises(OCRCancelled):
        GoogleVisionOCRProvider("key", urlopen=should_not_call).recognize(
            _image(), cancel_event=event
        )
    assert calls == 0

    event.clear()

    def cancel_after_read() -> _Response:
        return _Response(_success_payload(), on_read=event.set)

    with pytest.raises(OCRCancelled):
        GoogleVisionOCRProvider("key", urlopen=lambda *_args, **_kwargs: cancel_after_read()).recognize(
            _image(), cancel_event=event
        )


def test_missing_api_key_is_clear(qt_app) -> None:
    with pytest.raises(OCRError, match="API key is not configured"):
        GoogleVisionOCRProvider("").recognize(_image())


def test_logs_do_not_contain_key_or_image_payload(qt_app, caplog) -> None:
    key = "google-secret-value"
    provider = GoogleVisionOCRProvider(
        key,
        urlopen=lambda *_args, **_kwargs: _Response(_success_payload()),
    )
    provider.recognize(_image())
    assert key not in caplog.text


def test_diagnostic_image_does_not_require_qt_gui(monkeypatch) -> None:
    provider = GoogleVisionOCRProvider("key")
    captured: list[QImage] = []

    def fake_recognize(image, cancel_event=None):
        captured.append(image)
        return type("Result", (), {"text": "TEST"})()

    monkeypatch.setattr(provider, "recognize", fake_recognize)
    result = provider.test_connection()

    assert result.text == "TEST"
    assert captured and not captured[0].isNull()
