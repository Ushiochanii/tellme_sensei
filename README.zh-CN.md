# TellMeSensei

<p align="center">
  <a href="./README.md">English</a> · <strong>简体中文</strong>
</p>

<p align="center">
  一个 Windows 桌面学习助手：框选屏幕上的题目，通过 OCR 识别文字，<br>
  再交给 DeepSeek 生成解释与答案。
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-v0.5.0-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey">
</p>

## 功能

- 全局截图快捷键（默认 `Ctrl+Shift+Q`）
- 鼠标拖拽框选屏幕区域
- 悬浮窗口流式显示 DeepSeek 回答
- **Local OCR**：PaddleOCR，本机处理
- **Google Cloud Vision**：可选的 BYOK 在线 OCR
- 支持快捷键配置、窗口位置记忆、系统托盘与任务取消

## 下载

**[下载 TellMeSensei v0.5.0](https://github.com/Ushiochanii/tellme-sensei-releases/releases/tag/v0.5.0)**

Windows 安装包为当前用户安装，不需要管理员权限。
目前尚未进行代码签名，因此 Windows SmartScreen 可能显示 **Unknown Publisher（未知发布者）**。

## 快速开始

1. 安装 TellMeSensei。
2. 打开 **Settings**，填写 DeepSeek API Key。
3. 选择 OCR 模式：
   - **Local OCR：** 在 Settings 中点击 **Download Local OCR**。
   - **Google Cloud Vision：** 填写自己的 Google Vision API Key 并测试连接。
4. 按 `Ctrl+Shift+Q`，框选题目，等待答案窗口出现。

## OCR 模式

| | Local OCR | Google Cloud Vision |
|---|---|---|
| 引擎 | PaddleOCR | Google Cloud Vision |
| 处理位置 | 本机 | 在线 |
| 上传截图 | 否 | 是 |
| OCR API Key | 不需要 | 需要 |
| 额外下载 | 约 255 MB | 不需要 |

默认使用 Local OCR。TellMeSensei **不会静默切换 OCR 服务**。

## 隐私

- 使用 **Local OCR** 时，截图只在本机进行 OCR。
- 使用 **Google Cloud Vision** 时，只有显式选择该模式后截图才会上传到 Google。
- OCR 得到的题目文字会发送给 **DeepSeek** 用于生成回答。
- 日志不会记录 API Key、完整题目文本或截图。

## 开发

环境要求：Windows 10/11、Python 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-local-ocr.txt
python gui.py
```

构建与测试：

```powershell
.\scripts\build_installer.ps1
pytest
```

Local OCR 以独立组件（`v1.1.0`）发布，因此 Core 安装包可以保持较小体积。

## 当前状态

- **当前版本：** `v0.5.0`
- **Local OCR 组件：** `v1.1.0`
- **Windows 10/11：** 已支持
- **macOS：** 计划支持
- **自动更新：** 尚未实现
- **代码签名：** 尚未实现

更多信息见 [v0.5.0 Release Notes](./docs/releases/v0.5.0.md)。
