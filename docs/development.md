# Development

## Supported targets

TellMeSensei supports:

- Windows x64
- macOS Intel x86_64
- macOS Apple Silicon arm64

The development baseline is Python 3.12.

## Core principle

Implement normal product features once in shared application code. Keep
platform-specific behavior only at real OS, native-runtime, or build
boundaries. A feature should work on all supported targets unless an actual
OS or runtime limitation requires a documented exception.

Current legitimate boundaries include native global hotkeys, macOS Screen
Recording and window/Spaces behavior, OS-specific credential/filesystem APIs,
Windows installer and macOS DMG packaging, and the platform-specific Local
OCR runtimes.

macOS Intel and Apple Silicon share the same Core application. Their Local
OCR components remain separate because their Paddle/PaddleOCR runtimes and
native binaries are different. Core consumes the same OCR interface,
persistent-worker protocol, and result types on every platform.

## Branching

Use short-lived, feature-based branches, for example:

- `feature/history`
- `feature/prompt-settings`
- `fix/capture-scaling`

Do not create long-lived platform branches such as `feature/windows-*`,
`feature/macos-*`, or `feature/macos-arm64-*` for normal product work.

## Core development

Create a Python 3.12 environment and install the Core/GUI development
dependencies:

```sh
python -m pip install -r requirements-dev.txt
pytest
```

The Core environment must not contain Paddle, PaddleOCR, or Local OCR worker
dependencies. Local OCR is developed and built in separate, platform-specific
environments using the committed scripts and requirements under
`packaging/` and `scripts/`.

For Apple Silicon Local OCR, use the committed PaddleOCR 3.x ARM64 dependency
set:

- `packaging/macos/local_ocr_arm64_requirements.txt`
- `packaging/macos/local_ocr_arm64_constraints.txt`
- `packaging/macos/local_ocr_arm64_build_requirements.txt`

Do not merge that environment with the PaddleOCR 2.x Windows/macOS Intel
worker environments.

## Builds

Use the existing platform-native scripts; no cross-platform wrapper is
required.

Windows Core and installer builds:

```powershell
pwsh -File scripts/build_windows.ps1
pwsh -File scripts/build_installer.ps1
```

macOS Core app and DMG builds:

```sh
bash scripts/build_macos.sh
bash scripts/package_macos_dmg.sh
```

Local OCR worker builds use the corresponding Windows or macOS worker scripts
and their platform-specific requirements. They are not part of the Core
development environment or the Core CI workflow.

## Release model from v0.7.0 onward

This is the intended future application release model; it does not change the
current version or create a release.

- one application version
- one Git tag
- one GitHub Release
- one shared product feature set
- one asset for each supported application target

For example, a future `v0.7.0` release may contain:

- `TellMeSensei-0.7.0-windows-x64-setup.exe`
- `TellMeSensei-0.7.0-macos-x64.dmg`
- `TellMeSensei-0.7.0-macos-arm64.dmg`

Local OCR component versions remain independently versioned by platform:
Windows 1.1.0, macOS Intel 1.2.0, and macOS Apple Silicon 1.3.0 at the
current release baseline.

## Feature parity

A normal product feature is complete only when it is available on all three
supported targets, unless a real OS, native-runtime, or packaging limitation
requires otherwise. Native hotkeys, macOS permissions and window behavior,
Windows installers, macOS DMGs, and the separate Local OCR runtimes are
intentional exceptions.

Do not implement separate copies of shared Settings, capture, OCR-provider
selection, cancellation, AnswerWindow, DeepSeek, or component-lifecycle
behavior merely because the host platform differs.

## Core CI

GitHub Actions runs the Core test suite on hosted Windows and macOS runners.
It installs only `requirements-dev.txt`, then runs pytest, compileall, and the
non-interactive `python gui.py --smoke-core` check.

The workflow does not build or download Local OCR components, build installers
or DMGs, publish releases, sign binaries, or require API secrets. Native
release acceptance remains on the corresponding physical platform.
