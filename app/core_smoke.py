"""Deterministic, non-interactive smoke checks for the packaged Core app."""

from __future__ import annotations

import importlib
import sys


class CoreSmokeError(RuntimeError):
    """A smoke check failed in a known, reportable category."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def run_core_smoke() -> int:
    """Run package-integrity checks without starting the GUI lifecycle."""

    try:
        _run_checks()
    except CoreSmokeError as exc:
        _report(exc.category, str(exc))
        return 1
    except ModuleNotFoundError as exc:
        _report("CORE_SMOKE_IMPORT_FAILED", f"missing module: {exc.name}")
        return 1
    except ImportError as exc:
        _report("CORE_SMOKE_IMPORT_FAILED", str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - smoke must report, not fake success.
        _report("CORE_SMOKE_FAILED", f"{type(exc).__name__}: {exc}")
        return 1
    return 0


def _run_checks() -> None:
    """Import and construct safe Core services, without side effects."""

    from app.config import ConfigManager
    from app.local_ocr.platform import current_spec
    from app.ocr.factory import create_ocr_provider
    from app.ocr.providers.google_vision import GoogleVisionOCRProvider
    from app.platform import factory as platform_factory
    from app.services.deepseek_service import DeepSeekService
    from app.version import __version__

    if not isinstance(__version__, str) or not __version__.strip():
        raise CoreSmokeError("CORE_SMOKE_RESOURCE_FAILED", "version metadata is empty")

    try:
        config = ConfigManager().load(require_api_key=False)
    except Exception as exc:  # noqa: BLE001 - normalize config failures for the CLI.
        raise CoreSmokeError(
            "CORE_SMOKE_CONFIG_FAILED",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    create_ocr_provider(config)
    GoogleVisionOCRProvider(api_key="core-smoke-placeholder")
    DeepSeekService(config)

    # Importing the factory validates that the packaged platform boundary is
    # present. Instantiating it would register a real global hotkey, which is
    # deliberately outside this non-interactive smoke contract.
    if not callable(platform_factory.create_global_hotkey_manager):
        raise CoreSmokeError(
            "CORE_SMOKE_PLATFORM_FAILED",
            "global hotkey factory is unavailable",
        )
    if sys.platform == "darwin":
        spec = current_spec()
        if spec.platform_id != "macos-x64" or not spec.supported:
            raise CoreSmokeError(
                "CORE_SMOKE_PLATFORM_FAILED",
                f"unsupported packaged macOS platform: {spec.platform_id}",
            )

    if getattr(sys, "frozen", False):
        for module_name in ("paddle", "paddleocr"):
            try:
                importlib.import_module(module_name)
            except ModuleNotFoundError:
                continue
            raise CoreSmokeError(
                "CORE_SMOKE_RESOURCE_FAILED",
                f"forbidden Core dependency was bundled: {module_name}",
            )


def _report(category: str, message: str) -> None:
    print(f"{category}: {message}", file=sys.stderr)


__all__ = ["CoreSmokeError", "run_core_smoke"]
