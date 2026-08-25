# TellMeSensei

<p align="center">
  <strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  A Windows desktop study assistant that captures a question from your screen,<br>
  recognizes it with OCR, and asks DeepSeek for an explanation.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-v0.5.0-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey">
</p>

## Features

- Global screenshot hotkey (`Ctrl+Shift+Q` by default)
- Drag-to-select screen capture
- Floating answer window with streaming DeepSeek output
- **Local OCR** with PaddleOCR, processed on-device
- **Google Cloud Vision** as an optional BYOK online OCR mode
- Configurable hotkey, persistent window geometry, system tray, and cancellation

## Download

**[Download TellMeSensei v0.5.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.5.0)**

The Windows installer is per-user and does not require administrator privileges.
It is currently unsigned, so Windows SmartScreen may show an **Unknown Publisher** warning.

## Quick start

1. Install TellMeSensei.
2. Open **Settings** and enter your DeepSeek API key.
3. Choose an OCR mode:
   - **Local OCR:** click **Download Local OCR** in Settings.
   - **Google Cloud Vision:** enter your own Google Vision API key and test the connection.
4. Press `Ctrl+Shift+Q`, drag over a question, and wait for the answer window.

## OCR modes

| | Local OCR | Google Cloud Vision |
|---|---|---|
| Engine | PaddleOCR | Google Cloud Vision |
| Processing | On-device | Online |
| Screenshot upload | No | Yes |
| OCR API key | No | Yes |
| Extra download | ~255 MB | No |

Local OCR is the default. TellMeSensei does **not** silently switch between OCR providers.

## Privacy

- With **Local OCR**, screenshots stay on the device during OCR.
- With **Google Cloud Vision**, screenshots are uploaded to Google for OCR only when that mode is selected.
- Recognized question text is sent to **DeepSeek** to generate the answer.
- Logs avoid storing API keys, full question text, or screenshots.

## Development

Requirements: Windows 10/11, Python 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-local-ocr.txt
python gui.py
```

Build and test:

```powershell
.\scripts\build_installer.ps1
pytest
```

Local OCR is distributed as a separate component (`v1.1.0`) so the Core installer stays lightweight.

## Status

- **Current release:** `v0.5.0`
- **Local OCR component:** `v1.1.0`
- **Windows 10/11:** supported
- **macOS:** planned
- **Auto updater:** not implemented yet
- **Code signing:** not implemented yet

See the [v0.5.0 release notes](./docs/releases/v0.5.0.md) for details.
