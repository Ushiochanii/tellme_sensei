# TellMeSensei

<p align="center">
  <a href="./README.md">English</a> · <strong>简体中文</strong>
</p>

<p align="center">
  一个支持文字模式和视觉模式的 Windows、macOS 桌面学习助手。
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-v0.8.0-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%2B%20macOS-lightgrey">
</p>

## 功能

- 文字模式截图快捷键（默认 `Ctrl+Shift+A`）
- 视觉模式截图快捷键（默认 `Ctrl+Shift+S`）
- 鼠标拖拽框选屏幕区域，支持 macOS 全屏应用和多桌面
- 悬浮窗口流式显示 DeepSeek 回答
- 统一的悬浮控制器入口：**Text / OCR**、**Vision**、**Watch** 和 **Context Watch**
- **Watch** 监控一个选定区域；**Context Watch** 同时监控共享的上下文区域和题目区域
- **Local OCR**：PaddleOCR，本机处理
- **Google Cloud Vision**：可选的 BYOK 在线 OCR
- 支持快捷键配置、窗口位置记忆、系统托盘与任务取消

## 下载

所有版本都发布在[规范仓库的 Releases 页面](https://github.com/Ushiochanii/tellme_sensei/releases)。

| 平台 | TellMeSensei | Local OCR 组件 |
|---|---|---|
| Windows x64 | [v0.8.0 — TellMeSensei-Setup-0.8.0.exe](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.8.0) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |
| macOS Intel x86_64 | [v0.8.0 — TellMeSensei-0.8.0-macos-x64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.8.0) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |
| macOS Apple Silicon arm64 | [v0.8.0 — TellMeSensei-0.8.0-macos-arm64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.8.0) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |

macOS 版本为 ad-hoc 签名且未公证。macOS 可能需要在“隐私与安全性”中选择**仍要打开**，截图功能还需要授予屏幕录制权限。

## 快速开始

1. 安装 TellMeSensei。
2. 打开 **Settings**，填写 DeepSeek API Key。
3. 选择 OCR 模式：
   - **Local OCR：** 在 Settings 中点击 **Download Local OCR**。
   - **Google Cloud Vision：** 填写自己的 Google Vision API Key 并测试连接。
4. 文字题按 `Ctrl+Shift+A`，图形题按 `Ctrl+Shift+S`，框选题目后等待答案窗口出现。
5. 需要自动监控时，在悬浮控制器中选择 **Watch**（单个区域）或 **Context Watch**（上下文区域加题目区域），再选择 **Text / OCR** 或 **Vision** 作为分析模式。

## 分析模式

| 模式 | 快捷键 | 流程 | 适用场景 |
|---|---|---|---|
| 文字模式 | `Ctrl+Shift+A` | 截图 → 配置的 OCR → DeepSeek 文本分析 | 文字为主的题目 |
| 视觉模式 | `Ctrl+Shift+S` | 截图 → DeepSeek Vision | 图表、几何图形、流程图、网络拓扑等图形题 |

视觉模式固定使用 `deepseek-v4-flash-vision-exp`，会把截图直接发送给 DeepSeek。模式由用户明确选择；TellMeSensei 不会在文字模式和视觉模式之间自动切换或回退。

## OCR 模式

| | Local OCR | Google Cloud Vision |
|---|---|---|
| 引擎 | PaddleOCR | Google Cloud Vision |
| 处理位置 | 本机 | 在线 |
| 上传截图 | 否 | 是 |
| OCR API Key | 不需要 | 需要 |
| 额外下载 | 因平台而异，详见 Local OCR 1.4.0 Release 资产 | 不需要 |

Local OCR 按平台作为独立组件分发。TellMeSensei **不会静默切换 OCR 服务**。

## 隐私

- 使用 **Local OCR** 时，截图只在本机进行 OCR。
- 使用 **Google Cloud Vision** 时，只有显式选择该模式后截图才会上传到 Google。
- 使用 **视觉模式** 时，截图会直接发送给 DeepSeek Vision 进行图像分析。
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

- **当前应用版本：** v0.8.0
- **Local OCR：** 所有受支持平台均为 1.4.0
- **自动更新：** 未实现

更多信息见 [v0.8.0 Release Notes](./docs/releases/v0.8.0.md)。
