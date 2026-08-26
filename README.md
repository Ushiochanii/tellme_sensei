# TellMeSensei

<p align="center">
  <strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  A Windows and macOS desktop study assistant with explicit Text and Vision analysis modes.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-v0.7.0-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%2B%20macOS-lightgrey">
</p>

## Features

- Text Mode screenshot hotkey (`Ctrl+Shift+A` by default)
- Vision Mode screenshot hotkey (`Ctrl+Shift+S` by default)
- Drag-to-select screen capture, including macOS fullscreen and Spaces
- Floating answer window with streaming DeepSeek output
- **Local OCR** with PaddleOCR, processed on-device
- **Google Cloud Vision** as an optional BYOK online OCR mode
- Configurable hotkey, persistent window geometry, system tray, and cancellation

## Downloads

All releases are published in the [canonical repository Releases](https://github.com/Ushiochanii/tellme_sensei/releases).

| Platform | TellMeSensei | Local OCR component |
|---|---|---|
| Windows x64 | [v0.7.0 — TellMeSensei-Setup-0.7.0.exe](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.7.0) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |
| macOS Intel x86_64 | [v0.7.0 — TellMeSensei-0.7.0-macos-x64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.7.0) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |
| macOS Apple Silicon arm64 | [v0.7.0 — TellMeSensei-0.7.0-macos-arm64.dmg](https://github.com/Ushiochanii/tellme_sensei/releases/tag/v0.7.0) | [Local OCR 1.4.0](https://github.com/Ushiochanii/tellme_sensei/releases/tag/local-ocr-v1.4.0) |

macOS builds are ad-hoc signed and not notarized. macOS may require **Open Anyway** in **Privacy & Security**, and Screen Recording permission is required for capture.

## Quick start

1. Install TellMeSensei.
2. Open **Settings** and enter your DeepSeek API key.
3. Choose an OCR mode:
   - **Local OCR:** click **Download Local OCR** in Settings.
   - **Google Cloud Vision:** enter your own Google Vision API key and test the connection.
4. Press `Ctrl+Shift+A` for a text/OCR question or `Ctrl+Shift+S` for a diagram-heavy Vision question, drag over the question, and wait for the answer window.

## Analysis modes

| Mode | Shortcut | Pipeline | Best for |
|---|---|---|---|
| Text Mode | `Ctrl+Shift+A` | Screenshot → configured OCR → DeepSeek text analysis | Text-heavy questions |
| Vision Mode | `Ctrl+Shift+S` | Screenshot → DeepSeek Vision | Diagrams, charts, geometry, flowcharts, and graphical questions |

Vision Mode always uses `deepseek-v4-flash-vision-exp` and sends the captured screenshot directly to DeepSeek. The user explicitly chooses the mode; TellMeSensei does not automatically switch or fall back between Text and Vision.

## FE benchmark: Text/OCR vs Vision

A local benchmark was run on 40 official Japanese IPA Fundamental Information Technology Engineer Examination (FE) Subject A questions: 20 public questions from 2024 and 20 from 2025. Each question was evaluated once through both TellMeSensei paths using the same source PNG. The Text/OCR path used persistent Local OCR followed by `deepseek-v4-flash`; the Vision path sent the original PNG directly to `deepseek-v4-flash-vision-exp`. All 80 requests completed successfully and all answers were parsed as `ア` / `イ` / `ウ` / `エ`.

| Metric | Text/OCR | Vision |
|---|---:|---:|
| Accuracy | 38/40 (95.0%) | **39/40 (97.5%)** |
| 2024 accuracy | 19/20 | 19/20 |
| 2025 accuracy | 19/20 | **20/20** |
| Mean prompt tokens | 306.4 | 516.4 |
| Mean completion tokens | 2349.8 | **943.5** |
| Mean reasoning tokens | 2170.1 | **713.2** |
| Mean total tokens | 2656.2 | **1459.9** |
| Median total tokens | **871** | 1107 |
| Median first visible token | **4.223 s** | 4.422 s |
| Median API time | **5.899 s** | 6.581 s |
| Median end-to-end time | 15.636 s | **6.583 s** |

Paired outcomes were 38 both correct, 1 Vision-only correct, 0 Text-only correct, and 1 both wrong. The Vision-only win was `fe-2025-a-14`; both modes missed `fe-2024-a-13`.

The benchmark suggests that, on this small FE sample, Vision preserved essentially the same high accuracy while avoiding the Local OCR latency and using substantially fewer tokens on average. The accuracy difference is only one question out of 40, so it should not be treated as evidence that Vision is universally more accurate. Text also had a lower median total-token count, while its much higher mean was driven by large completion/reasoning outliers. On the benchmark machine, steady-state Local OCR itself took about 8.7 seconds median, which explains most of the end-to-end latency gap; this timing is machine- and OCR-runtime-dependent rather than a general performance guarantee.

The benchmark harness is in `tools/benchmark_text_vs_vision.py`. The source question images and raw benchmark outputs are intentionally kept outside Git. The question set was prepared from [IPA's publicly released FE questions](https://www.ipa.go.jp/shiken/mondai-kaiotu/sg_fe/koukai/index.html).

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

- **Current application release:** v0.7.0
- **Local OCR:** 1.4.0 on all supported platforms
- **Auto updater:** not implemented

See the [v0.7.0 release notes](./docs/releases/v0.7.0.md) for details.
