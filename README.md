# TellMeSensei

<p align="center">
  <strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  A Windows and macOS desktop study assistant with explicit Text and Vision analysis modes.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-v0.8.2-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%2B%20macOS-lightgrey">
</p>

## Features

- Text Mode screenshot hotkey (`Ctrl+Shift+A` by default)
- Vision Mode screenshot hotkey (`Ctrl+Shift+S` by default)
- Watch selection hotkey (`Ctrl+Shift+W` by default)
- Context Watch selection hotkey (`Ctrl+Shift+C` by default)
- Drag-to-select screen capture, including macOS fullscreen and Spaces
- Floating answer window with streaming DeepSeek output
- Unified floating controller with **Text / OCR**, **Vision**, **Watch**, and **Context Watch** entry cards
- **Watch** monitors one selected region; **Context Watch** monitors a shared context region plus a question region
- **Local OCR** with PaddleOCR, processed on-device
- **Google Cloud Vision** as an optional BYOK online OCR mode
- Configurable global shortcuts, persistent window geometry, system tray, and cancellation

## Downloads

All releases are published in the [canonical repository Releases](https://github.com/Ushiochanii/tellme_sensei/releases).

| Platform | TellMeSensei | Local OCR component |
|---|---|---|
| Windows x64 | [v0.8.2 — TellMeSensei-Setup-0.8.2.exe](https://github.com/Ushiochanii/tellme_sensei/releases/download/v0.8.2/TellMeSensei-Setup-0.8.2.exe) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |
| macOS Intel x86_64 | [v0.8.2 — TellMeSensei-0.8.2-macos-x64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/download/v0.8.2/TellMeSensei-0.8.2-macos-x64.dmg) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |
| macOS Apple Silicon arm64 | [v0.8.2 — TellMeSensei-0.8.2-macos-arm64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/download/v0.8.2/TellMeSensei-0.8.2-macos-arm64.dmg) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |

macOS builds are ad-hoc signed and not notarized. macOS may require **Open Anyway** in **Privacy & Security**, and Screen Recording permission is required for capture.

## Quick start

1. Install TellMeSensei.
2. Open **Settings** and enter your DeepSeek API key.
3. Choose an OCR mode:
   - **Local OCR:** click **Download Local OCR** in Settings.
   - **Google Cloud Vision:** enter your own Google Vision API key and test the connection.
4. Press `Ctrl+Shift+A` for a text/OCR question or `Ctrl+Shift+S` for a diagram-heavy Vision question, drag over the question, and wait for the answer window.
5. For automatic monitoring, choose **Watch** for one region or **Context Watch** for a context region plus a question region in the floating controller. Watch starts screen selection immediately; Context Watch automatically advances from Context to Question and starts monitoring after the second selection. Choose **Text / OCR** or **Vision** once in **Settings → Auto Watch**. `Ctrl+Shift+W` and `Ctrl+Shift+C` start the matching selection workflow directly.
6. To change any global shortcut, open **Settings → Shortcuts** and save the four entries together.

## Analysis modes

| Mode | Shortcut | Pipeline | Best for |
|---|---|---|---|
| Text Mode | `Ctrl+Shift+A` | Screenshot → configured OCR → DeepSeek text analysis | Text-heavy questions |
| Vision Mode | `Ctrl+Shift+S` | Screenshot → DeepSeek Vision | Diagrams, charts, geometry, flowcharts, and graphical questions |
| Watch | `Ctrl+Shift+W` | Select one region, then start monitoring automatically | Repeated questions in one region |
| Context Watch | `Ctrl+Shift+C` | Select Context, then Question, then start monitoring automatically | Repeated questions with shared context |

Vision Mode always uses `deepseek-v4-flash-vision-exp` and sends the captured screenshot directly to DeepSeek. The user explicitly chooses the mode; TellMeSensei does not automatically switch or fall back between Text and Vision.

Watch shortcuts start the matching screen-selection workflow directly. There is no separate setup or manual Start action; configure the shared Text / OCR vs Vision preference under **Settings → Auto Watch**.

## OCR modes

| | Local OCR | Google Cloud Vision |
|---|---|---|
| Engine | PaddleOCR | Google Cloud Vision |
| Processing | On-device | Online |
| Screenshot upload | No | Yes |
| OCR API key | No | Yes |
| Extra download | Platform-dependent; see the Local OCR 1.4.0 release assets | No |

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

- **Current application release:** v0.8.2
- **Local OCR:** 1.4.0 on all supported platforms
- **Application updates:** manual check/download in Settings; automatic background updates are not implemented

See the [v0.8.2 release notes](./docs/releases/v0.8.2.md) for details.
