# Floating Controller UI Unification Design

Status: **Draft for design review**  
Related Issue: **#25 — 统一 Auto Watch 与现有模式的 UI 设计**

## 1. Background / Current behavior

TellMeSensei 的浮动主控制器目前已经有一套较完整的视觉语言：柔和的蓝紫背景、圆角卡片、Text / OCR 与 Vision 两个大入口、右上角 Settings，以及底部状态区域。

但 Auto Watch 是后续加入的功能，目前主页面仍以一个普通 `QPushButton("Auto Watch")` 暂时承载入口，和 Text / OCR、Vision 两张 Mode card 在层级、尺寸、视觉语言和交互方式上不一致。

当前 `MainWindow` 中：

- Text / OCR 与 Vision 使用 `ModeButton` 卡片；
- Auto Watch 使用单独的普通按钮；
- 点击 Auto Watch 后，再通过 `Region Mode` 在 `Single Region` 与 `Context + Question` 间二次选择；
- 底部 `statusLabel` 只承载 `Ready / Capturing / Processing / Cancelling` 这类全局状态，但由于当前固定窗口和布局分配，它视觉上占据了明显大于信息量所需的空间。

因此，底部大框并不是一个尚未完成的“信息面板”。从当前实现看，它本质上只是一个全局状态指示器。现在的问题是它的视觉体量与实际职责不匹配。

## 2. Problem statement

当前 controller 存在三个直接的产品问题：

1. **入口风格不统一**：Text / OCR、Vision 是正式的主功能卡片，而 Auto Watch 像后来追加的临时按钮。
2. **Auto Watch 的两种实际使用模式隐藏得过深**：Single Region 与 Context + Question 已经是两种明确不同的用户工作流，但目前需要先进入 Auto Watch，再做 Region Mode 选择。
3. **状态区体量失衡**：`Ready` 等一行状态占用了一个大卡片区域，制造了明显的视觉空洞感。

这次 UI 优化应解决以上问题，而不是借机重做 AnswerWindow、Settings 或 Auto Watch 核心逻辑。

## 3. Goals

- 让 controller 的四个主要入口属于同一套视觉体系。
- 在主界面直接暴露两种 Auto Watch 工作流。
- 用简短、直观的名称表达两种 Watch 模式。
- 把底部状态区域缩成与其真实职责匹配的紧凑状态条。
- 尽量保持 controller 目前约 `340 × 330` logical px 的整体占用，不因为增加入口而显著变大。
- 保持现有 Text / OCR、Vision、Single Region Auto Watch、Context + Question Auto Watch 的底层行为不变。
- 复用现有 theme / ModeButton 视觉语言，不建立新的平行 UI framework。

## 4. Non-goals

本次不做：

- AnswerWindow 的 Context / Question / Answer 比例调整；
- Settings 全面改版；
- Watch mini controller 改版；
- Auto Watch detector、Latest-Wins、OCR cache、session lifecycle 或分析 pipeline 重构；
- 新增第三种 Watch 模式；
- 新增 Auto Watch 全局快捷键；
- 保存 Watch ROI 或改变现有配置持久化；
- 为未来可能出现的信息提前保留大型空白 panel。

如果后续要统一 AnswerWindow 或 Settings，应分别作为独立 UI 任务处理。

## 5. Existing architecture relevant to this change

主要相关文件：

```text
app/ui/main_window.py   # controller 布局、四个入口及 Auto Watch setup 路由
app/ui/theme.py         # controller stylesheet、ModeButton、图标与视觉 token

tests/...              # MainWindow / Auto Watch UI 行为相关测试
README.md               # 用户可见入口发生变化后，同实现 PR 同步更新
```

现有 Auto Watch 的底层 session 已经分开：

```text
AutoWatchSession                    # Single Region
ContextQuestionAutoWatchSession     # Context + Question
```

因此这次无需建立新的 Watch backend。UI 只需要把已有两条路径更直接地暴露出来。

## 6. Proposed information architecture

主页面从当前：

```text
┌──────────────────────────────┐
│ TellMeSensei              ⚙  │
│                              │
│  [ Text / OCR ] [ Vision ]   │
│                              │
│        [ Auto Watch ]        │
│                              │
│  ┌────────────────────────┐  │
│  │ ● Ready                │  │
│  │                        │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

调整为：

```text
┌──────────────────────────────┐
│ TellMeSensei              ⚙  │
│                              │
│  [ Text / OCR ] [ Vision ]   │
│                              │
│  [ Watch      ] [ Context ]  │
│                  [ Watch   ]  │
│                              │
│  ─ ● Ready ────────────────  │
└──────────────────────────────┘
```

实际实现仍使用规则的 **2 × 2 card grid**；上图只是结构示意。

推荐主入口名称冻结为：

- **Text / OCR**
- **Vision**
- **Watch**
- **Context Watch**

其中：

- `Watch` = 现有 Single Region Auto Watch；
- `Context Watch` = 现有 Context + Question Auto Watch。

这组名称比 `Single Region / Context + Question` 更偏用户语言，也比 `Single-region Auto Watch / Context-aware Auto Watch` 更短。

为了消除 `Context Watch` 是否“只监控 Context”的歧义，卡片底部使用短说明：

- Watch → `Single region`
- Context Watch → `Context + question`

因此用户不需要理解内部的 Region Mode 概念，也能在主页面直接选对入口。

## 7. Card visual design

四个入口使用同一种卡片结构：

```text
┌─────────────────────┐
│        icon         │
│       Title         │
│   [ footer chip ]   │
└─────────────────────┘
```

建议内容：

| Card | Title | Footer chip | Action |
| --- | --- | --- | --- |
| 1 | Text / OCR | 当前 Text shortcut | 直接框选并 OCR |
| 2 | Vision | 当前 Vision shortcut | 直接框选并 Vision |
| 3 | Watch | `Single region` | 进入 Single Region Watch setup |
| 4 | Context Watch | `Context + question` | 进入 Context + Question Watch setup |

### Visual rules

- 四张卡片保持相同宽度、相同高度、相同 radius、相同 hover / pressed / disabled 行为。
- Text / OCR 保留当前蓝色 accent。
- Vision 保留当前紫色 accent。
- 两张 Watch 卡片共享一种 Watch visual treatment，避免错误地用蓝/紫分别暗示它们固定绑定 Text 或 Vision。
- 优先在现有蓝紫主题内增加一个低饱和的 `WATCH_ACCENT`，建议为偏青蓝 / teal 的色相；两张 Watch 卡片使用同一 accent，通过 icon 和 footer 区分。
- 不为四张卡片设计四套完全不同的样式。

建议 icon 语义：

- Watch：scan / radar / tracking frame；
- Context Watch：两个关联区域、叠放矩形或 linked frames。

实现时优先复用 `theme.py` 现有绘制方式，不引入外部 icon dependency。

## 8. Layout sizing

目标不是把 controller 做得更大，而是重新分配现有空间。

建议：

- controller 宽度继续保持约 `340 logical px`；
- 优先继续保持当前整体高度约 `330 logical px`；
- 四张 card 改为更紧凑的高度，目标约 `84–92 logical px`；
- grid 水平 / 垂直间距约 `10 px`；
- header 和当前 margin 保持接近现状；
- 底部状态条高度固定在约 `36–40 logical px`，不得吸收布局的剩余高度。

如果 Windows 与 macOS 原生字体度量导致 `340 × 330` 出现真实裁切，可以小幅增加高度；不为了死守一个像素值压缩文字或控件。

## 9. Compact status strip

底部现有大框改为单行、固定高度的 compact status strip。

默认：

```text
● Ready
```

运行状态沿用现有语义：

```text
● Capturing…
● Processing…
● Cancelling…
```

原则：

- 这是 **global state indicator**，不是 activity dashboard；
- 默认不加第二行说明，不硬塞没有实际用途的信息；
- 不为未来可能的信息预留大空白；
- 如果未来真的需要展示多项 Watch telemetry，应另行设计，而不是重新膨胀这个 status strip。

实现层面应明确限制 vertical size policy / max height，避免 `QVBoxLayout` 再把剩余空间分配给它。

## 10. Auto Watch interaction redesign

### 10.1 Watch

点击 **Watch**：

```text
Main four-card view
    ↓
enter_auto_watch_setup(region_mode="single")
    ↓
Analysis Mode: Text / OCR | Vision
    ↓
Select Region
    ↓
Start Auto Watch
```

### 10.2 Context Watch

点击 **Context Watch**：

```text
Main four-card view
    ↓
enter_auto_watch_setup(region_mode="context_question")
    ↓
Analysis Mode: Text / OCR | Vision
    ↓
Select Context
    ↓
Select Question
    ↓
Start Auto Watch
```

### 10.3 Remove redundant Region Mode choice

既然主页面已经明确提供两个 Watch 入口，进入 setup 后不再显示：

```text
Region Mode
○ Single Region
○ Context + Question
```

这一步会变成重复选择，应删除。

同一个 setup widget 可以继续复用；入口只是在进入时预设 `_auto_watch_region_mode`。

`Back` 始终返回四卡片主页面。

## 11. State and lifecycle invariants

本次 UI 改动必须保持：

- Text / OCR 与 Vision direct capture 生命周期不变；
- Watch 仍使用现有 `AutoWatchSession`；
- Context Watch 仍使用现有 `ContextQuestionAutoWatchSession`；
- Text / Vision Analysis Mode 仍在 Watch setup 内选择；
- selection overlay、preview、Pause / Resume、Analyze Now、Stop 行为不变；
- controller 隐藏 / 恢复逻辑不变；
- 不改变现有 cancellation、generation guard、stale result rejection。

换句话说，这是 **entry-point and layout redesign**，不是 Watch architecture redesign。

## 12. Failure scenarios that matter

### A. 新入口路由错模式

失败：点击 Watch 实际进入 Context + Question，或反之。  
处理：阻塞实现 PR，修正入口到 `_auto_watch_region_mode` 的绑定。

### B. 移除 Region Mode radio 后 setup 状态残留

失败：先进入 Context Watch，Back，再进入 Watch，仍保留双区域 selection / preview。  
处理：明确在进入不同入口时执行现有 selection cleanup / mode transition，补 regression test。

### C. 2 × 2 布局在支持平台发生文字裁切

失败：Windows 或 macOS 正常 DPI 下 title / footer chip 被截断。  
处理：调整卡片高度或 controller 高度；不通过缩小到难读字体来规避。

### D. status strip 仍然垂直膨胀

失败：`Ready` 条在正常主页面继续吸收大量剩余高度。  
处理：修正 QLabel / container 的 size policy 和 layout constraint。

这些都是支持范围内真实可达的问题；不扩展到无关的 exotic DPI / theme corner cases。

## 13. Alternatives considered

### Alternative 1 — 保留一个 Auto Watch 按钮，进入后再选择模式

不采用。它保留了当前最大的问题：Auto Watch 仍然是二级、视觉上不一致的功能。

### Alternative 2 — 主页面显示 `Single Region` / `Context + Question`

可理解，但偏实现术语。对新用户而言，不如 `Watch` / `Context Watch` 自然。

### Alternative 3 — `Auto Watch` / `Watch + Context`

也足够直观，但两张卡片命名结构不平行。最终选择 `Watch` / `Context Watch`，并用 footer chip 补足语义。

### Alternative 4 — 保留大状态卡，并填入更多信息

不采用。当前没有足够高价值信息支撑这个区域，强行填充会把“布局问题”变成“信息噪声问题”。

## 14. Implementation scope

设计接受后，建议 **一个短生命周期实现 PR** 完成，不需要人为拆成多个 Phase。

预期主要修改：

```text
app/ui/main_window.py
  # 2×2 entry grid、Watch / Context Watch 路由、setup 简化、compact status sizing

app/ui/theme.py
  # Watch card icon/accent、统一 card visual、compact status style

tests/...
  # 两个 Watch entry routing、Back / mode reset、status/layout regression

README.md
  # 同步当前 controller 入口和 Auto Watch 使用说明 / 截图（若 README 有对应内容）
```

不要借此重构 Auto Watch core 或 AnswerWindow。

## 15. Test plan

每项检查都对应一个会改变结论的具体失败：

1. **Targeted controller UI tests**  
   检测四入口是否存在、按钮是否正确启用/禁用；失败则说明主界面 wiring 有 regression。

2. **Watch routing tests**  
   点击 Watch 必须进入 single；点击 Context Watch 必须进入 context_question；失败则阻塞 merge。

3. **Back / re-entry regression**  
   Context Watch → Back → Watch 不得残留 context/question selection；失败则说明 setup lifecycle 被 UI 重构破坏。

4. **Existing Auto Watch UI/session tests**  
   检测删除 Region Mode radio 是否意外改变现有 session 行为；失败则只修 UI adapter，不重构 backend。

5. **Core test suite + compile/smoke**  
   因 `MainWindow` 是共享入口，完整 Core regression 有价值；失败则判断是否为本次共享 UI 修改引入。

6. **Windows + macOS manual visual acceptance**  
   检查正常系统字体下的 2×2 对齐、hover、文字裁切、status strip 高度。视觉验收是本次 UI 改动的必要证据，自动测试不能替代。

## 16. Documentation

这是用户可见 UI / workflow 变化，因此实现 PR 必须遵循 `AGENTS.md` 的 README 规则：

- README 中若展示或描述当前 controller，应同步为四入口；
- Auto Watch 使用说明应从“进入 Auto Watch 后选择 Region Mode”改为“直接选择 Watch 或 Context Watch”；
- Release Notes 之后负责说明版本变化，但不能代替 README 的当前使用说明。

本 Design Doc 本身不改变产品行为，所以设计 PR 不需要为了形式修改 README。

## 17. Rollout / release

本次不单独要求新版本号。

正常流程：

```text
Design review
    ↓
Issue #25 scope accepted
    ↓
short-lived implementation branch
    ↓
implementation + tests + README
    ↓
PR + Windows/macOS visual acceptance
    ↓
merge to main
    ↓
随下一次正常 application release 发布
```

不需要 feature flag、migration 或 compatibility layer。

## 18. Open questions

设计层面只保留一个可在实现前快速确认的视觉问题：

- `WATCH_ACCENT` 最终具体色值是否采用 teal / cyan-blue，还是使用更中性的现有 palette 组合？

这不影响信息架构、命名或交互流程，不应阻塞当前 Design Doc 的结构性 review。

## 19. Definition of Done

- 主 controller 显示四个同风格主入口：Text / OCR、Vision、Watch、Context Watch；
- 原普通 `Auto Watch` 占位按钮消失；
- Watch 直接进入 Single Region setup；
- Context Watch 直接进入 Context + Question setup；
- setup 不再要求用户重复选择 Region Mode；
- 两种 Watch 仍可选择 Text / OCR 或 Vision Analysis Mode；
- 底部状态区变为紧凑单行 status strip，不再占据大面积空白；
- controller 在 Windows / macOS 正常 DPI 与系统字体下无明显裁切或失衡；
- 现有 capture / Auto Watch session 行为无 regression；
- README 与新的用户入口一致；
- 实现 PR 只包含本次 controller UI 范围，不顺手扩展到 AnswerWindow / Settings 重设计。
