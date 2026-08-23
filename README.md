# Windows OCR 学习助手（Phase 1～3）

这是一个尚未包含 GUI 的 MVP 核心流水线：

```text
图片 → PaddleOCR → 规范化文本 → DeepSeek → Console 输出
```

## 环境要求

- Windows 10/11
- Python 3.11（推荐；项目代码也兼容 Python 3.12）
- 可访问 DeepSeek API 的网络

## 安装

```powershell
uv venv --python 3.11
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如果本机已有 Python 3.11，也可以使用：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

首次运行 PaddleOCR 时可能会自动下载 OCR 模型，请保持网络可用。

## API Key 配置

```powershell
Copy-Item .env.example .env
notepad .env
```

在 `.env` 中填写：

```text
DEEPSEEK_API_KEY=你的密钥
```

API Key 只从环境变量读取，不会写入源码，也不会写入日志。若之前提供的密钥是真实密钥，建议在 DeepSeek 控制台测试完成后立即轮换。

## Phase 1：DeepSeek

```powershell
python test_deepseek.py
python test_deepseek.py "RAM 和 ROM 有什么区别？"
```

## Phase 2：OCR

```powershell
python test_ocr.py .\test.png
```

默认 OCR 语言为 `japan`，可在 `.env` 中修改 `OCR_LANGUAGE`。PaddleOCR 的日文模型也可识别常见中英文题目；需要时可尝试 `ch` 或 `en`。

## Phase 3：完整 pipeline

```powershell
python test_pipeline.py .\test.png
```

也可以使用：

```powershell
python main.py .\test.png
```

## 自动化测试

自动化测试不调用网络和 OCR 模型，使用假服务验证文本解析及模块连接：

```powershell
pytest
```

## Phase 4～6：GUI 截图与悬浮结果窗口

```powershell
python gui.py
```

点击“截图识别”后，在当前鼠标所在显示器上拖动框选题目；按 `Esc` 或鼠标右键取消。截图完成后会立即显示悬浮结果窗口，状态依次更新为“正在识别题目”“正在请求 AI”“完成”。

如需确认实际截取区域，可显式开启调试截图：

```powershell
python gui.py --debug-capture .\temp\debug_capture.png
```

调试截图是可选的；默认流程不会把截图永久写入磁盘。结果窗口支持拖动、调整大小、滚动、复制答案、重新分析和关闭。重新分析只使用已有 OCR 文本，不会重新截图或 OCR。

GUI 的 OCR 与 DeepSeek 请求运行在 `QThread` 中，主线程只负责界面更新。当前版本尚未实现全局快捷键、系统托盘、设置窗口和 PyInstaller 打包。

## 日志和隐私

运行日志写入 `logs/app.log`，只记录阶段、状态和文本长度，不记录 API Key 或完整题目。当前阶段不会上传截图，只会把本地 OCR 文本发送到 DeepSeek；截图不会由程序永久保存。

## Phase 7: tray mode and global hotkey

The default GUI entry point runs as a Windows tray application:

```powershell
python gui.py
```

Use `Ctrl+Shift+Q`, the tray menu, or a double-click on the tray icon to
start screenshot recognition. `Esc` and right-click cancel capture. The
development launcher remains available with `python gui.py --show-window`.
The tray exit action unregisters the Win32 hotkey and stops the application.

## Platform Support

- Windows: supported.
- macOS: planned; macOS global hotkey support is not implemented yet.

Future macOS work will require Screen Recording permission handling and a
platform-specific global hotkey implementation. The application and service
layers remain independent of those platform details.

## Online OCR backend

Google Cloud Vision is an optional, BYOK OCR backend for development and
future Settings integration. It requires the Cloud Vision API to be enabled
for the Google project. When `google_vision` is explicitly selected, the
captured screenshot is uploaded to Google Cloud Vision; the default remains
the local OCR component. The provider uses the REST API directly and does not
require the Google Cloud SDK.

## Windows installer

The installer build requires Windows, Python 3.12, the project `.venv`, and
Inno Setup 6. Build the portable application and per-user installer with:

```powershell
.\scripts\build_installer.ps1
```

The portable output is `dist\TellMeSensei\`; the installer is written to
`dist\installer\TellMeSensei-Setup-<version>.exe`. The installer uses a
per-user location under `%LOCALAPPDATA%\Programs\TellMeSensei`, creates a
Start Menu shortcut, and does not remove Settings, Credential Manager data,
logs, or OCR model caches when uninstalled.

The executable and installer are currently unsigned. Windows SmartScreen may
therefore show an unknown-publisher warning.

## OCR modes and the external Local OCR component

TellMeSensei supports two OCR modes:

- **Local OCR** uses PaddleOCR on this device. The optional component is
  downloaded from the public distribution release by opening Settings > Local
  OCR > Download Local OCR. The download is approximately 240 MB compressed
  and is larger after installation; screenshots remain on the device.
- **Google Cloud Vision** is an optional BYOK online backend. When selected,
  screenshots are uploaded to Google Cloud Vision for recognition.

The default remains Local OCR. The Core application does not bundle PaddleOCR.
If the Local OCR component is missing, Settings can install it without
installing anything into the Core application directory.

The Core application no longer bundles PaddleOCR. Core development dependencies
are installed with `requirements.txt`; a complete development environment also
needs `requirements-local-ocr.txt` and `requirements-dev.txt`. Build and install
the separate worker for development with:

```powershell
.\scripts\build_local_ocr.ps1
.\scripts\install_local_ocr_dev.ps1
```

The worker is copied to the versioned per-user component directory under
`%LOCALAPPDATA%\TellMeSensei\components\local-ocr\`. The Core installer does
not include or download this component; if it is missing, the application shows
a local OCR component error. PaddleOCR and its model cache remain outside the
Core installation.

For a developer-only component build or archive, run:

```powershell
.\scripts\build_local_ocr.ps1
.\scripts\package_local_ocr.ps1
```

The archive and `local-ocr-manifest.json` are written to `dist\components`
with immutable public GitHub Release URLs. The developer-only
`scripts\install_local_ocr_dev.ps1` helper remains available for local builds;
normal users should use Settings. `LOCAL_OCR_MANIFEST_URL` can still override
the production URL for development and tests. Downloads are checked with
SHA-256, safely extracted, smoke-tested, and installed atomically. Removing
the component does not remove settings, API keys, logs, or model caches.

For developer-only Local OCR performance diagnostics, use the packaged worker
with `scripts/profile_local_ocr.py`. This is opt-in instrumentation; normal OCR
does not create profile files or change the worker JSON protocol:

```powershell
.\.venv\Scripts\python.exe scripts\profile_local_ocr.py `
  --input "C:\path\question.png" `
  --worker ".\dist\LocalOCR\TellMeSenseiOCR.exe"
```

## Windows portable build

Build prerequisites: Windows, Python 3.12, and the project `.venv` with
`requirements-dev.txt` installed. From the repository root, run:

```powershell
.\scripts\build_windows.ps1
```

The onedir output is `dist\TellMeSensei\TellMeSensei.exe`. The portable build
does not require Python, a virtual environment, the repository, or a `.env`
file at runtime. Save the DeepSeek API key from Settings; it remains in the
Windows Credential Manager and is never placed in `settings.json`.

On first OCR use, PaddleOCR may download its model files to Paddle's normal
per-user cache. The packaged application does not bundle those models and does
not depend on the current working directory. Runtime logs are stored in the
Qt user data directory, normally `%LOCALAPPDATA%\TellMeSensei\logs\app.log`.

During OCR or AI processing, use `停止` or press `Esc` in the answer window to
request a cooperative cancellation. After the worker exits, `重新分析` keeps
the existing OCR text, while `重新截图` starts a fresh capture job.
