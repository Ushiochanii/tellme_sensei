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
  <img alt="local ocr" src="https://img.shields.io/badge/Local%20OCR-v1.1.0-green">
</p>

```text
Ctrl+Shift+Q
    ↓
Select a screen region
    ↓
OCR
    ↓
DeepSeek
    ↓
Floating answer window
```

## Features

- Global screenshot hotkey (`Ctrl+Shift+Q` by default)
- Drag-to-select screen capture
- Streaming DeepSeek answers in a floating window
- Two explicit OCR modes:
  - **Local OCR** — PaddleOCR, processed on-device
  - **Google Cloud Vision** — online OCR with your own Google API key
- Optional Local OCR component download from Settings
- Persistent Local OCR worker with background prewarm
- Configurable global hotkey
- Persistent answer-window position and size
- Cooperative cancellation for OCR and AI requests
- System tray operation
- Per-user Windows installer with no administrator privileges required

TellMeSensei never silently switches between Local OCR and Google Cloud Vision. The provider you select is the provider it uses.

## Download

Download the latest Windows installer from the public binary release repository:

**[TellMeSensei v0.5.0](https://github.com/Ushiochanii/tellme-sensei-releases/releases/tag/v0.5.0)**

Current installer:

```text
TellMeSensei-Setup-0.5.0.exe
```

The installer is currently unsigned, so Windows SmartScreen may show an **Unknown Publisher** warning.

## Quick start

### 1. Install TellMeSensei

Run the installer. TellMeSensei is installed per-user under:

```text
%LOCALAPPDATA%\Programs\TellMeSensei
```

### 2. Configure DeepSeek

Open **Settings** and enter your DeepSeek API key.

API keys are stored through the operating-system secret store rather than in `settings.json`.

### 3. Choose an OCR mode

#### Local OCR

Choose **Local OCR** and click **Download Local OCR**.

The Local OCR component:

- uses PaddleOCR
- is approximately **255 MB** compressed
- occupies roughly **700 MB** after installation
- is installed separately from the Core application
- keeps screenshots on the device during OCR

After installation, TellMeSensei prepares the OCR worker in the background and reuses it between recognition jobs.

#### Google Cloud Vision

Choose **Google Cloud Vision**, enter your own Google Vision API key, test the connection, and save Settings.

You need:

- Google Cloud Vision API enabled for your project
- your own API key
- any applicable Google Cloud billing/quota configuration

When this mode is selected, captured screenshots are uploaded to Google Cloud Vision for OCR.

### 4. Capture a question

Press:

```text
Ctrl+Shift+Q
```

Drag over the question on screen. TellMeSensei recognizes the text and sends the recognized question to DeepSeek.

You can also start capture from the system tray menu.

## OCR modes

| | Local OCR | Google Cloud Vision |
|---|---|---|
| OCR engine | PaddleOCR | Google Cloud Vision |
| Processing | On-device | Online |
| Screenshot upload | No | Yes |
| OCR API key required | No | Yes |
| Extra download | ~255 MB | No |
| Installed OCR size | ~700 MB | No local OCR component |
| Best for | Privacy / repeated use | Lightweight setup / online OCR |

The default OCR mode is **Local OCR**.

## Privacy

- **Local OCR:** screenshots are processed locally and are not uploaded to an OCR service.
- **Google Cloud Vision:** screenshots are uploaded to Google only when this provider is explicitly selected.
- **DeepSeek:** recognized question text is sent to DeepSeek to generate the answer.
- **Logs:** application logs avoid storing API keys, full question text, or screenshots.

There is no automatic Local-to-Online OCR fallback.

## Local OCR component

PaddleOCR is distributed separately so the Core installer stays small.

```text
TellMeSensei.exe
      │
      ├── Google Cloud Vision
      │
      └── Local OCR Provider
              │
              ↓
       TellMeSenseiOCR.exe
              │
              ↓
          PaddleOCR
```

The current Local OCR component is `v1.1.0` and is installed under:

```text
%LOCALAPPDATA%\TellMeSensei\components\local-ocr\1.1.0\
```

Component installation uses version-pinned release URLs, SHA-256 verification, safe ZIP extraction, smoke testing, staging, and atomic activation.

## Development

### Requirements

- Windows 10 / 11
- Python 3.12
- DeepSeek API access

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-local-ocr.txt
```

Run the development GUI:

```powershell
python gui.py
```

The optional `.env` file is intended for development overrides. Normal installed users should configure the application through Settings.

## Build

Build the Windows Core application:

```powershell
.\scripts\build_windows.ps1
```

Build the installer (requires Inno Setup 6):

```powershell
.\scripts\build_installer.ps1
```

Build the Local OCR worker:

```powershell
.\scripts\build_local_ocr.ps1
```

Run the test suite:

```powershell
pytest
```

## Release artifacts

Public binaries are hosted in:

**[Ushiochanii/tellme-sensei-releases](https://github.com/Ushiochanii/tellme-sensei-releases)**

Current releases:

```text
v0.5.0
├── TellMeSensei-Setup-0.5.0.exe
└── TellMeSensei-Setup-0.5.0.exe.sha256

local-ocr-v1.1.0
├── TellMeSensei-LocalOCR-1.1.0-win-x64.zip
└── local-ocr-manifest.json
```

## Platform support

- **Windows 10 / 11:** supported
- **macOS:** planned

## Known limitations

- Windows executable and installer are currently unsigned
- No automatic application updater yet
- Local OCR currently uses PaddleOCR only
- macOS support is not implemented yet

---

TellMeSensei `v0.5.0` is the current stable Windows release.
