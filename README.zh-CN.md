# TellMeSensei

<p align="center">
  <a href="./README.md">English</a> · <strong>简体中文</strong>
</p>

<p align="center">
  一个 Windows 和 macOS 桌面学习助手：框选屏幕上的题目，通过 OCR 识别文字，<br>
  再交给 DeepSeek 生成解释与答案。
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-v0.6.0-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%2B%20macOS-lightgrey">
</p>

## 功能

- 全局截图快捷键（默认 `Ctrl+Shift+Q`）
- 鼠标拖拽框选屏幕区域，支持 macOS 全屏应用和多桌面
- 悬浮窗口流式显示 DeepSeek 回答
- **Local OCR**：PaddleOCR，本机处理
- **Google Cloud Vision**：可选的 BYOK 在线 OCR
- 支持快捷键配置、窗口位置记忆、系统托盘与任务取消

## 下载

所有版本都发布在[规范仓库的 Releases 页面](https://github.com/Ushiochanii/tellme_sensei/releases)。

| 平台 | TellMeSensei | Local OCR 组件 |
|---|---|---|
| Windows x64 | [v0.5.0 — TellMeSensei-Setup-0.5.0.exe](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.5.0) | [Local OCR 1.1.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.1.0) |
| macOS Intel x86_64 | [v0.6.0 — TellMeSensei-0.6.0-macos-x64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.6.0) | [Local OCR 1.2.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.2.0-macos-x64) |
| macOS Apple Silicon arm64 | [v0.6.0 — TellMeSensei-0.6.0-macos-arm64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.6.0) | [Local OCR 1.3.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.3.0-macos-arm64) |

当前 Windows 二进制仍为 v0.5.0；两个 macOS 二进制均为 v0.6.0。

macOS 版本为 ad-hoc 签名且未公证。macOS 可能需要在“隐私与安全性”中选择**仍要打开**，截图功能还需要授予屏幕录制权限。

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
| 额外下载 | 约 255–391 MB，因平台而异 | 不需要 |

Local OCR 按平台作为独立组件分发。TellMeSensei **不会静默切换 OCR 服务**。

## 隐私

- 使用 **Local OCR** 时，截图只在本机进行 OCR。
- 使用 **Google Cloud Vision** 时，只有显式选择该模式后截图才会上传到 Google。
- OCR 得到的题目文字会发送给 **DeepSeek** 用于生成回答。
- 日志不会记录 API Key、完整题目文本或截图。

## 开发

环境要求：Windows 或 macOS、Python 3.12。

```sh
python -m venv .venv
python -m pip install -r requirements-dev.txt
python gui.py
```

跨平台开发约定和构建命令见 [development.md](./docs/development.md)。

Core/GUI 环境与 Local OCR worker 依赖刻意分开。只有开发 worker 时，才使用对应平台的 Local OCR 构建脚本和依赖文件。Apple Silicon 使用 `packaging/macos/local_ocr_arm64_requirements.txt`、`packaging/macos/local_ocr_arm64_constraints.txt` 和 `packaging/macos/local_ocr_arm64_build_requirements.txt` 中提交的 PaddleOCR 3.x ARM64 依赖集。

## 当前状态

- **应用版本：** macOS v0.6.0；Windows 稳定版本 v0.5.0
- **Local OCR：** Windows 1.1.0 · macOS Intel 1.2.0 · macOS Apple Silicon 1.3.0
- **自动更新：** 尚未实现

更多信息见 [v0.6.0 Release Notes](./docs/releases/v0.6.0.md)。
