"""Shared HTTPS primitives for services that run in packaged builds.

The application uses ``urllib`` for the small Google Vision and Local OCR
metadata requests.  A frozen Python runtime does not always have the
build-time OpenSSL CA path that CPython expects, especially on macOS.  The
``truststore`` package delegates certificate verification to the operating
system (Windows certificate store, macOS Keychain, or the host OpenSSL store)
and is therefore the preferred context.  ``certifi`` is retained as a portable
fallback for environments where the optional truststore import is unavailable.
"""

from __future__ import annotations

import ssl
import urllib.request
from typing import Any, Callable

try:  # truststore is a direct application dependency in release builds.
    import truststore
except ImportError:  # pragma: no cover - exercised by packaging fallback tests
    truststore = None  # type: ignore[assignment]

try:  # certifi is used only when native trust is unavailable.
    import certifi
except ImportError:  # pragma: no cover - exercised by packaging fallback tests
    certifi = None  # type: ignore[assignment]


Urlopen = Callable[..., Any]


def create_tls_context() -> ssl.SSLContext:
    """Create a verifying TLS context suitable for source and frozen builds.

    Native system trust is preferred so a packaged app follows the user's
    current root certificate store.  ``certifi`` provides a deterministic
    fallback when a host cannot load truststore (for example a minimal Python
    environment); the final stdlib fallback keeps development environments
    usable without either optional package.
    """

    if truststore is not None:
        try:
            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            return context
        except Exception:
            # A partially supported native store should not prevent a portable
            # CA bundle from being used for the request.
            pass

    if certifi is not None:
        try:
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass

    return ssl.create_default_context()


def urlopen_https(
    request: urllib.request.Request,
    *,
    timeout: float,
    opener: Urlopen | None = None,
) -> Any:
    """Open a URL with the shared verifying context.

    Test doubles and a few embedders expose the older ``urlopen(request,
    timeout=...)`` signature without a ``context`` keyword.  We retain that
    compatibility only after trying the secure context, while production
    stdlib ``urlopen`` always receives the trust-aware context.
    """

    open_function = opener or urllib.request.urlopen
    context = create_tls_context()
    try:
        return open_function(request, timeout=timeout, context=context)
    except TypeError as first_error:
        # Existing deterministic test doubles intentionally omit ``context``;
        # do not force callers to duplicate a fake network stack.
        try:
            return open_function(request, timeout=timeout)
        except TypeError:
            raise first_error


# Keep a concise alias for callers that prefer the operation-oriented name.
open_url = urlopen_https


__all__ = ["create_tls_context", "open_url", "urlopen_https"]
