# TellMeSensei

<p align="center">
  <strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  A Windows and macOS desktop study assistant with explicit Text and Vision analysis modes.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-v0.7.0-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%2B%20macOS-lightgrey">
</p>

## Features

- Text Mode screenshot hotkey (`Ctrl+Shift+Q` by default)
- Vision Mode screenshot hotkey (`Ctrl+Shift+W` by default)
- Drag-to-select screen capture, including macOS fullscreen and Spaces
- Floating answer window with streaming DeepSeek output
- **Local OCR** with PaddleOCR, processed on-device
- **Google Cloud Vision** as an optional BYOK online OCR mode
- Configurable hotkey, persistent window geometry, system tray, and cancellation

## Downloads

All releases are published in the [canonical repository Releases](https://github.com/Ushiochanii/tellme_sensei/releases).

| Platform | TellMeSensei | Local OCR component |
|---|---|---|
| Windows x64 | [v0.5.0 — TellMeSensei-Setup-0.5.0.exe](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.5.0) | [Local OCR 1.1.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.1.0) |
| macOS Intel x86_64 | [v0.6.0 — TellMeSensei-0.6.0-macos-x64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.6.0) | [Local OCR 1.2.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.2.0-macos-x64) |
| macOS Apple Silicon arm64 | [v0.6.0 — TellMeSensei-0.6.0-macos-arm64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.6.0) | [Local OCR 1.3.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.3.0-macos-arm64) |

The current Windows binary is still v0.5.0; both macOS binaries are v0.6.0.

macOS builds are ad-hoc signed and not notarized. macOS may require **Open Anyway** in **Privacy & Security**, and Screen Recording permission is required for capture.

## Quick start

1. Install TellMeSensei.
2. Open **Settings** and enter your DeepSeek API key.
3. Choose an OCR mode:
   - **Local OCR:** click **Download Local OCR** in Settings.
   - **Google Cloud Vision:** enter your own Google Vision API key and test the connection.
4. Press `Ctrl+Shift+Q` for a text/OCR question or `Ctrl+Shift+W` for a diagram-heavy Vision question, drag over the question, and wait for the answer window.

## Analysis modes

| Mode | Shortcut | Pipeline | Best for |
|---|---|---|---|
| Text Mode | `Ctrl+Shift+Q` | Screenshot → configured OCR → DeepSeek text analysis | Text-heavy questions |
| Vision Mode | `Ctrl+Shift+W` | Screenshot → DeepSeek Vision | Diagrams, charts, geometry, flowcharts, and graphical questions |

Vision Mode always uses `deepseek-v4-flash-vision-exp` and sends the captured screenshot directly to DeepSeek. The user explicitly chooses the mode; TellMeSensei does not automatically switch or fall back between Text and Vision.

## OCR modes

| | Local OCR | Google Cloud Vision |
|---|---|---|
| Engine | PaddleOCR | Google Cloud Vision |
| Processing | On-device | Online |
| Screenshot upload | No | Yes |
| OCR API key | No | Yes |
| Extra download | Approximately 255–391 MB, depending on platform | No |

Local OCR is distributed as a separate, platform-specific component. TellMeSensei does **not** silently switch between OCR providers.

## Privacy

- With **Local OCR**, screenshots stay on the device during OCR.
- With **Google Cloud Vision**, screenshots are uploaded to Google for OCR only when that mode is selected.
- With **Vision Mode**, screenshots are sent directly to DeepSeek Vision for image analysis.
- Recognized question text is sent to **DeepSeek** to generate the answer.
- Logs avoid storing API keys, full question text, or screenshots.

## Development

Requirements: Windows or macOS, Python 3.12.

```sh
python -m venv .venv
python -m pip install -r requirements-dev.txt
python gui.py
```

See [development.md](./docs/development.md) for the cross-platform development contract and build commands.

The Core/GUI environment is intentionally separate from Local OCR worker dependencies. Use the platform-specific Local OCR build scripts and requirements only when working on the worker. Apple Silicon uses the committed PaddleOCR 3.x ARM64 dependency set in `packaging/macos/local_ocr_arm64_requirements.txt`, `packaging/macos/local_ocr_arm64_constraints.txt`, and `packaging/macos/local_ocr_arm64_build_requirements.txt`.

## Status

- **Application development target:** v0.7.0; published macOS binaries remain v0.6.0 and the Windows stable binary remains v0.5.0
- **Local OCR:** Windows 1.1.0 · macOS Intel 1.2.0 · macOS Apple Silicon 1.3.0
- **Auto updater:** not implemented yet

See the [v0.6.0 release notes](./docs/releases/v0.6.0.md) for details.
