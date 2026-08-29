from __future__ import annotations

import ssl
import urllib.request

from app import network


def test_urlopen_https_passes_verifying_context() -> None:
    captured: dict[str, object] = {}

    def opener(request, *, timeout, context):
        captured.update(request=request, timeout=timeout, context=context)
        return object()

    request = urllib.request.Request("https://example.test/resource")
    result = network.urlopen_https(request, timeout=3.5, opener=opener)

    assert result is not None
    assert captured["request"] is request
    assert captured["timeout"] == 3.5
    context = captured["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_urlopen_https_supports_legacy_test_doubles_without_context() -> None:
    calls: list[tuple[object, float]] = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return "response"

    request = urllib.request.Request("https://example.test/resource")
    assert network.urlopen_https(request, timeout=2, opener=opener) == "response"
    assert calls == [(request, 2)]


def test_packaged_specs_collect_native_trust_and_portable_ca() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    windows_spec = (root / "packaging" / "tellme_sensei.spec").read_text(encoding="utf-8")
    mac_spec = (root / "packaging" / "macos" / "tellme_sensei.spec").read_text(encoding="utf-8")

    for spec in (windows_spec, mac_spec):
        assert "collect_submodules(\"truststore\")" in spec
        assert "collect_data_files(\"certifi\")" in spec
