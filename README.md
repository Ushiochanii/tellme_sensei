# TellMeSensei

A Windows desktop study assistant that turns a screen region into an AI-assisted explanation:

```text
Ctrl+Shift+Q
    ↓
Select a screen region
    ↓
OCR (Local PaddleOCR or Google Cloud Vision)
    ↓
DeepSeek
    ↓
Floating answer window
```

TellMeSensei is designed for quickly reading questions from screenshots, recognizing the text, and sending the recognized question to DeepSeek without interrupting the current workflow.

**Current release:** `v0.5.0`  
**Platform:** Windows 10 / 11  
**Local OCR component:** `v1.1.0`

[Download TellMeSensei v0.5.0](https://github.com/Ushiochanii/tellme-sensei-releases/releases/tag/v0.5.0)

---

## Features

- Global screenshot hotkey (`Ctrl+Shift+Q` by default)
- Drag-to-select screenshot capture
- Floating answer window with streaming DeepSeek output
- Two explicit OCR modes:
  - **Local OCR** — PaddleOCR, processed on-device
  - **Google Cloud Vision** — online OCR using your own Google API key
- Optional Local OCR component download from Settings
- Persistent Local OCR worker with engine reuse
- Background OCR prewarm for faster first use
- Configurable global hotkey
- Persistent answer-window position and size
- Cooperative cancellation for OCR and AI requests
- System tray operation
- Per-user Windows installer; no administrator privileges required

There is **no silent fallback** between Local OCR and Google Cloud Vision. The selected OCR provider is always used explicitly.

---

## Quick start

### 1. Install

Download the latest Windows installer from the public release repository:

[**TellMeSensei-Setup-0.5.0.exe**](https://github.com/Ushiochanii/tellme-sensei-releases/releases/tag/v0.5.0)

The application installs to:

```text
%LOCALAPPDATA%\Programs\TellMeSensei
```

The installer is currently unsigned, so Windows SmartScreen may show an **Unknown Publisher** warning.

### 2. Configure DeepSeek

Open **Settings** and enter your DeepSeek API key.

The key is stored through the operating-system secret store rather than in `settings.json`.

### 3. Choose an OCR mode

#### Local OCR

Choose **Local OCR** in Settings and click **Download Local OCR**.

The Local OCR component:

- uses PaddleOCR
- is approximately **255 MB** compressed
- occupies roughly **700 MB** after installation
- is installed separately from the Core application
- keeps screenshots on the device during OCR

After installation, TellMeSensei prepares the OCR worker in the background. The worker remains alive between recognition jobs so the Paddle engine can be reused.

#### Google Cloud Vision

Choose **Google Cloud Vision**, enter your own Google Vision API key, then use **Test Google Vision** before saving.

Requirements:

- Google Cloud Vision API enabled for your project
- your own API key
- any applicable Google Cloud billing/quota configuration

When this mode is selected, captured screenshots are uploaded to Google Cloud Vision for OCR.

### 4. Capture a question

Use:

```text
Ctrl+Shift+Q
```

Then drag over the question on screen.

You can also start capture from the tray menu.

---

## OCR modes

| | Local OCR | Google Cloud Vision |
|---|---|---|
| OCR engine | PaddleOCR | Google Cloud Vision |
| Processing | On-device | Online |
| Screenshot upload | No | Yes |
| API key required | No | Yes |
| Extra download | ~255 MB | No |
| Installed size | ~700 MB | No local OCR component |
| Best for | Privacy / repeated use | Lightweight setup / online OCR |

The default OCR mode is Local OCR.

---

## Local OCR performance

TellMeSensei uses a persistent Local OCR worker and background prewarm to avoid repeatedly initializing PaddleOCR.

Development measurements on the current Windows build typically showed:

- warm OCR: around **0.7 s**
- first OCR after successful prewarm: around **1 s**

These figures are development observations, not performance guarantees; actual timing depends on hardware, screenshot size, and OCR content.

---

## Privacy and storage

### Local OCR

Screenshots are processed locally by PaddleOCR and are not uploaded to an OCR service.

### Google Cloud Vision

Screenshots are uploaded to Google Cloud Vision only when that provider is explicitly selected.

### DeepSeek

Recognized question text is sent to DeepSeek to generate the answer.

### Logs

Application logs avoid storing API keys, full question text, or screenshots. Runtime logs are stored in the per-user TellMeSensei data directory, normally under:

```text
%LOCALAPPDATA%\TellMeSensei
```

---

## Local OCR component architecture

The Core application intentionally does not bundle PaddleOCR.

```text
TellMeSensei.exe
      │
      ├── GoogleVisionOCRProvider ──→ Google Cloud Vision
      │
      └── LocalOCRProvider
              │
              ↓
       TellMeSenseiOCR.exe
              │
              ↓
          PaddleOCR
```

The separately versioned component is installed under:

```text
%LOCALAPPDATA%\TellMeSensei\components\local-ocr\1.1.0\
```

Component downloads use:

- version-pinned public release URLs
- SHA-256 verification
- safe ZIP extraction
- staging installation
- worker smoke testing
- atomic activation

The published Local OCR `1.1.0` component is treated as immutable.

---

## Cancellation and shutdown

During OCR or DeepSeek processing, use **Stop** (or `Esc` in the answer window) to request cancellation.

The application uses cooperative cancellation and clean worker shutdown rather than forcibly terminating GUI threads. If a Local OCR job is cancelled, its persistent worker may be restarted on the next recognition request.

Exiting from the tray unregisters the Windows global hotkey and shuts down the Local OCR worker.

---

## User data and uninstall behavior

The Windows installer uses a fixed application identity so newer versions can upgrade the existing installation.

Uninstalling the Core application does not intentionally remove user-level data such as:

- settings
- stored API keys
- logs
- separately installed Local OCR component

This allows reinstalling the application without necessarily downloading the Local OCR component again.

---

## Development setup

### Requirements

- Windows 10 / 11
- Python 3.12
- DeepSeek API access

Create a virtual environment and install Core dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For development and Local OCR builds, also install:

```powershell
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-local-ocr.txt
```

Run the development GUI:

```powershell
python gui.py
```

The optional `.env` file remains available for development overrides, but normal installed users should configure the application through Settings.

---

## Build

### Core portable build

```powershell
.\scripts\build_windows.ps1
```

Output:

```text
dist\TellMeSensei\TellMeSensei.exe
```

Verify the frozen Core:

```powershell
dist\TellMeSensei\TellMeSensei.exe --smoke-core
```

The Core build must not include Paddle, PaddleOCR, or the Cython runtime used by the Local OCR worker.

### Windows installer

Requires Inno Setup 6:

```powershell
.\scripts\build_installer.ps1
```

Output:

```text
dist\installer\TellMeSensei-Setup-<version>.exe
dist\installer\TellMeSensei-Setup-<version>.exe.sha256
```

### Local OCR worker

```powershell
.\scripts\build_local_ocr.ps1
```

Developer-only local installation:

```powershell
.\scripts\install_local_ocr_dev.ps1
```

Package the component:

```powershell
.\scripts\package_local_ocr.ps1
```

Normal users should install Local OCR from **Settings**, not with the developer helper scripts.

---

## Testing

Run the test suite:

```powershell
pytest
```

Compile-check the Python sources:

```powershell
python -m compileall app tests
```

Local OCR profiling is available for development diagnostics:

```powershell
.\.venv\Scripts\python.exe scripts\profile_local_ocr.py `
  --input "C:\path\question.png" `
  --worker ".\dist\LocalOCR\TellMeSenseiOCR.exe"
```

Profiling is opt-in and is not part of the normal OCR path.

---

## Release artifacts

Public binary releases are hosted in:

[**Ushiochanii/tellme-sensei-releases**](https://github.com/Ushiochanii/tellme-sensei-releases)

Current artifacts:

```text
v0.5.0
├── TellMeSensei-Setup-0.5.0.exe
└── TellMeSensei-Setup-0.5.0.exe.sha256

local-ocr-v1.1.0
├── TellMeSensei-LocalOCR-1.1.0-win-x64.zip
└── local-ocr-manifest.json
```

Release notes for `v0.5.0` are also kept in:

```text
docs/releases/v0.5.0.md
```

---

## Platform support and known limitations

- **Windows:** supported
- **macOS:** planned; global hotkey and Screen Recording permission integration are not implemented yet
- The Windows executable and installer are currently unsigned
- There is no automatic application updater yet
- Local OCR is currently PaddleOCR-based; additional OCR engines are not included in `v0.5.0`

---

## Status

TellMeSensei `v0.5.0` is the current stable Windows release.
