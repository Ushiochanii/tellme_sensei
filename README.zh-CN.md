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
  <img alt="local ocr" src="https://img.shields.io/badge/Local%20OCR-v1.1.0-green">
</p>

```text
Ctrl+Shift+Q
    ↓
框选屏幕区域
    ↓
OCR
    ↓
DeepSeek
    ↓
悬浮答案窗口
```

## 功能

- 全局截图快捷键（默认 `Ctrl+Shift+Q`）
- 鼠标拖拽框选屏幕区域
- 悬浮窗口流式显示 DeepSeek 回答
- 两种明确区分的 OCR 模式：
  - **Local OCR** — PaddleOCR，本地处理
  - **Google Cloud Vision** — 在线 OCR，使用你自己的 Google API Key
- 可直接在 Settings 中下载安装 Local OCR 组件
- Local OCR 常驻 worker 与后台预热
- 可自定义全局快捷键
- 自动保存答案窗口的位置与尺寸
- OCR 与 AI 请求均支持协作式取消
- 系统托盘运行
- Windows 用户级安装，不需要管理员权限

TellMeSensei **不会静默切换 OCR 服务**。你选择 Local OCR，就只使用 Local OCR；选择 Google Cloud Vision，就只使用 Google Cloud Vision。

## 下载

Windows 安装包发布在公开的二进制仓库：

**[下载 TellMeSensei v0.5.0](https://github.com/Ushiochanii/tellme-sensei-releases/releases/tag/v0.5.0)**

当前安装包：

```text
TellMeSensei-Setup-0.5.0.exe
```

目前安装包尚未进行代码签名，因此 Windows SmartScreen 可能会显示 **Unknown Publisher（未知发布者）** 提示。

## 快速开始

### 1. 安装 TellMeSensei

运行安装程序。默认安装位置为当前用户目录：

```text
%LOCALAPPDATA%\Programs\TellMeSensei
```

### 2. 配置 DeepSeek

打开 **Settings**，填写 DeepSeek API Key。

API Key 通过操作系统的凭据存储保存，不会写进 `settings.json`。

### 3. 选择 OCR 模式

#### Local OCR

在 Settings 中选择 **Local OCR**，点击 **Download Local OCR**。

Local OCR 组件：

- 使用 PaddleOCR
- 压缩下载约 **255 MB**
- 安装后大约占用 **700 MB**
- 与 Core 主程序分开安装
- OCR 过程中截图保留在本机处理

安装成功后，TellMeSensei 会在后台准备 OCR worker，并在多次识别之间复用 PaddleOCR 引擎。

#### Google Cloud Vision

选择 **Google Cloud Vision**，填写你自己的 Google Vision API Key，测试连接后保存。

需要：

- 在 Google Cloud 项目中启用 Cloud Vision API
- 自己的 API Key
- 按 Google Cloud 的要求配置相应 billing / quota

选择该模式时，截图会上传到 Google Cloud Vision 进行 OCR。

### 4. 截图识别

按下：

```text
Ctrl+Shift+Q
```

框选屏幕上的题目。TellMeSensei 会先识别文字，再将识别结果发送给 DeepSeek。

也可以从系统托盘菜单启动截图。

## OCR 模式对比

| | Local OCR | Google Cloud Vision |
|---|---|---|
| OCR 引擎 | PaddleOCR | Google Cloud Vision |
| 处理位置 | 本机 | 在线 |
| 上传截图 | 否 | 是 |
| OCR API Key | 不需要 | 需要 |
| 额外下载 | 约 255 MB | 不需要 |
| OCR 本地占用 | 约 700 MB | 无本地 OCR 组件 |
| 更适合 | 隐私 / 高频使用 | 轻量安装 / 在线识别 |

默认 OCR 模式为 **Local OCR**。

## 隐私

- **Local OCR：** 截图仅在本机由 PaddleOCR 处理，不上传到 OCR 服务。
- **Google Cloud Vision：** 只有显式选择该模式时，截图才会上传到 Google。
- **DeepSeek：** OCR 得到的题目文字会发送给 DeepSeek，用于生成回答。
- **日志：** 应用日志不会记录 API Key、完整题目文本或截图。

不存在 Local OCR 自动回退到 Online OCR 的行为。

## Local OCR 组件

PaddleOCR 被拆成独立组件，因此 Core 安装包可以保持较小体积。

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

当前 Local OCR 组件版本为 `v1.1.0`，安装位置：

```text
%LOCALAPPDATA%\TellMeSensei\components\local-ocr\1.1.0\
```

组件下载安装包含版本固定的 Release URL、SHA-256 校验、安全 ZIP 解压、smoke test、staging 与原子激活。

## 开发

### 环境要求

- Windows 10 / 11
- Python 3.12
- 可访问 DeepSeek API

创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-local-ocr.txt
```

运行开发版 GUI：

```powershell
python gui.py
```

`.env` 仅建议用于开发环境覆盖。普通安装用户应直接通过 Settings 配置应用。

## 构建

构建 Windows Core：

```powershell
.\scripts\build_windows.ps1
```

构建 Windows 安装包（需要 Inno Setup 6）：

```powershell
.\scripts\build_installer.ps1
```

构建 Local OCR worker：

```powershell
.\scripts\build_local_ocr.ps1
```

运行测试：

```powershell
pytest
```

## 发布文件

公开二进制发布仓库：

**[Ushiochanii/tellme-sensei-releases](https://github.com/Ushiochanii/tellme-sensei-releases)**

当前发布结构：

```text
v0.5.0
├── TellMeSensei-Setup-0.5.0.exe
└── TellMeSensei-Setup-0.5.0.exe.sha256

local-ocr-v1.1.0
├── TellMeSensei-LocalOCR-1.1.0-win-x64.zip
└── local-ocr-manifest.json
```

## 平台支持

- **Windows 10 / 11：** 已支持
- **macOS：** 计划支持

## 当前限制

- Windows 可执行文件与安装包目前尚未签名
- 暂无应用自动更新功能
- Local OCR 当前只提供 PaddleOCR
- macOS 尚未实现

---

TellMeSensei `v0.5.0` 是当前稳定的 Windows 版本。
