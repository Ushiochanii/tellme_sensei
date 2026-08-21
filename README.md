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
