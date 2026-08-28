# AGENTS.md — TellMeSensei 工程开发规范

本文档定义本仓库中 AI coding agent 与贡献者默认遵循的工作约定。

项目负责人正在通过开发 TellMeSensei 学习专业的软件工程实践。因此，Agent 不仅要正确完成实现，也应尽量让工程过程可见，并用简洁、实用的方式解释重要决策。

这是仓库级的全局规范。`docs/plans/` 下更具体的 Design Doc 可以为某个功能增加额外要求。若两者发生冲突，应优先遵循该功能已经接受的更具体设计，同时继续遵守本文中的安全、流程和范围控制规则。

---

## 1. 项目基线

TellMeSensei 是一个基于 Python 3.12 的桌面应用。

Core 当前支持：

- Windows x64
- macOS Intel x86_64
- macOS Apple Silicon arm64

普通产品功能应尽量只在共享应用代码中实现一次。只有真正位于 OS / native runtime / build 边界的行为才应做平台特化，例如：

- 原生全局快捷键
- macOS Screen Recording / window / Spaces 行为
- 操作系统凭据或文件系统 API
- Windows installer 打包
- macOS DMG 打包
- 各平台独立的 Local OCR native runtime

不要仅仅因为项目支持多个平台，就为共享功能分别写一套 Windows/macOS 实现。

Local OCR 拥有独立的 native component 生命周期。除非当前任务明确与 Local OCR 有关，否则不要把 Paddle/PaddleOCR 依赖引入 Core 开发环境。

平台、构建、CI、打包和发布的既定模型见 `docs/development.md`。

---

## 2. 标准开发生命周期

对于非琐碎的产品功能，默认遵循以下流程：

```text
Idea / Problem
    ↓
Problem definition
    ↓
Design Doc / Technical Plan
    ↓
Design review / scope freeze
    ↓
Umbrella Issue / implementation tracker
    ↓
Short-lived feature branch
    ↓
Implementation phase
    ↓
Targeted tests
    ↓
Pull Request
    ↓
Code review
    ↓
Merge to main
    ↓
Next phase, if any
    ↓
RC / release validation
    ↓
Stable release
```

如果架构、用户交互、数据模型、生命周期或兼容性行为仍未确定，不要从一个较大的想法直接跳到编码。

小型、明确的 bug fix 不要求完整 Design Doc，应根据实际情况判断。若修复涉及架构、用户可见行为、持久化数据、跨平台行为或多个子系统，则应先形成书面计划。

---

## 3. Design Doc

非琐碎功能的设计文档放在：

```text
docs/plans/
```

一份合格的 Design Doc 通常应包含：

1. Background / 当前行为
2. Problem statement
3. Goals
4. Non-goals
5. 与本次修改相关的现有架构
6. Proposed architecture
7. 必要时的数据模型 / API / 状态机变化
8. 必要时的用户交互 / 生命周期
9. 在项目支持范围内真实可达的重要失败场景
10. 存在真实技术取舍时的 Alternatives considered
11. Test plan
12. Rollout / release plan
13. Open questions
14. Definition of Done

Design Doc 是技术层面的 source of truth。不要在 Issue 或 PR 描述中重复整份设计。

一旦设计经过 review 并被接受，在当前实现 Phase 内，应把核心架构和 scope 视为已经冻结。不要在编码过程中顺手重新设计；只有当实现证据暴露了真实问题时，才说明原因并先更新设计，再扩大 scope。

---

## 4. Issue、Phase、Branch 与 Pull Request

### 4.1 Umbrella Issue

如果一个版本化功能会跨多个 Phase，应在 Design Doc 被接受后创建一个 umbrella Issue。

Issue 用于追踪进度，而不是复制设计。通常包含：

- Design Doc 链接
- 各 Phase checklist
- 简洁的 Definition of Done
- 各 Phase PR 链接

### 4.2 Phase 划分

优先把工作拆成可以独立 review、边界清晰的 Phase。每个 Phase 应主要回答一个明确的工程问题。

例如：

```text
Phase 1 — Core model / algorithm
Phase 2 — Pipeline integration
Phase 3 — Product UI
Phase 4 — Hardening / regression / release
```

如果用户采用分阶段开发流程，在当前 Phase 尚未 review 并 ACCEPT 之前，不要开始下一个 Phase。

### 4.3 Branch

基于最新已经接受的 `main` 创建短生命周期 feature/fix branch，例如：

```text
feature/v0.8.1-phase1-dual-region-core
fix/capture-scaling
```

普通共享功能不要建立长期 platform branch。

开始修改前：

- 确认当前 branch
- 检查 `git status`
- 识别与当前任务无关的用户修改
- 原样保留这些用户修改

绝对不要为了获得“干净 working tree”而 reset、覆盖、丢弃、stage 或 commit 与当前任务无关的用户修改。

如果同一个文件同时包含当前任务修改和用户自己的修改，只 stage 当前任务相关的 hunks。

### 4.4 Pull Request

PR 应解释“本次实现实际改变了什么”，而不是重新讲一遍整个 Design Doc。

建议结构：

```text
## Summary
这次 PR 改了什么。

## Design
链接到对应 Design Doc / section。

## Scope
本 PR / Phase 明确包含什么、排除什么。

## Key implementation notes
只写 review 当前 patch 所需的重要技术决策。

## Tests
运行的命令和结果。

## Known limitations
只列本 Phase 完成后仍然真实存在、且属于有意保留的限制。
```

---

## 5. 写代码之前

实现前，应根据仓库真实代码回答这些问题，而不是凭假设：

- 当前行为由哪个现有模块负责？
- 应扩展哪个已有 public/internal interface，而不是另写一套？
- 哪些行为必须保持不变？
- 满足已接受设计的最小、完整修改是什么？
- 哪些测试能证明新行为？
- 哪些现有测试能防止 regression？

先读实际代码。

不要为本项目不存在的场景添加 wrapper、兼容层、feature flag、migration framework、hash、defensive scaffolding 或过度泛化的 abstraction。

如果现有抽象已经清楚拥有某个职责，应优先扩展它，而不是建立平行子系统。

---

## 6. Scope 控制

真实存在的问题要报告；只要某个少见问题通过项目支持的正常用法可达，也应报告。

不要制造问题。

修复范围应与项目实际需求成比例：

- 除非任务明确涉及安全，否则这不是一篇 security paper。
- 除非功能明确存在 adversary，否则默认操作员是在自己的机器上正常使用。
- 不要添加 hash/checksum/fingerprint，除非它确实替代了明显更昂贵的操作，并且 hash 结果会改变程序后续行为。
- 不要为项目里不存在的兼容或迁移场景增加 defensive scaffolding。
- 不要优化 exotic encoding、symlink race、RTL text、毫秒级 race 等角落问题，除非它们能通过项目支持的输入、接口或真实数据到达。
- 已经 review 并解决的问题，不要反复重新审查到影响实现进度。

运行任何检查前，都应该能够回答：

> 这个检查具体能发现什么失败？如果失败，我们接下来会做出什么不同的决定？

如果没有明确答案，就不要运行这个检查。

---

## 7. 代码架构原则

优先保持清晰的职责边界。

一个模块应回答一个容易识别的工程问题。例如：

```text
capture/        # 如何获取屏幕内容
ocr/            # 如何把图像内容转换成文字
services/       # 如何调用外部服务
workers/        # 如何在 GUI 线程之外执行/取消长任务
ui/             # 用户如何与应用交互
auto_watch/     # 如何把屏幕变化转换成 analysis generation
platform/       # 真正的 OS-specific 行为
```

不要因为 UI 会触发某个功能，就把 domain/state-machine logic 塞进大型 QWidget/UI class。

如果已有共享路径已经负责 cancellation、job lifecycle、OCR provider selection、DeepSeek access、AnswerWindow、settings 或 Local OCR lifecycle，不要为新功能再复制一套。

平台特化代码应留在真实的平台边界。

---

## 8. 注释与教学说明

项目负责人正在学习软件工程实践。开发流程应承担一定教学作用，但不要把生产代码变成教程。

### 8.1 报告 / 文档中的带注释文件树

如果一个任务新增或大幅修改多个文件，在有帮助时，应在报告中给出带职责注释的文件树。

例如：

```text
app/auto_watch/
├── pair_coordinator.py   # 把 Context / Question revision 合并成一个 pair generation
├── sampler.py            # 抓取屏幕并裁切一个或多个 monitored ROI
└── dispatcher.py         # Latest-Wins 分发与 stale-result 保护

tests/
└── test_pair_coordinator.py  # 确定性的 pair 状态转换测试
```

这些 `# ...` 是文档/报告中的解释注释。不要真的把注释写进文件名或目录名。

### 8.2 生产代码中的注释

以下情况适合加入简洁代码注释：

- 不明显的 invariant
- lifecycle ownership
- 容易误解的状态机转换
- coordinate / DPI mapping 假设
- cancellation / generation / stale-result 规则
- 看起来不寻常但有明确理由的实现选择

不要给显而易见的语法或每一行代码写注释。优先使用好命名、小函数和清晰结构。

不好的例子：

```python
count += 1  # count 加 1
```

有价值的例子：

```python
# 在 dispatch 之前更新 accepted baseline，避免分析仍在运行时，
# 后续 tick 再次把同一个稳定题目识别为新题。
baseline = current
```

### 8.3 报告中的学习说明

有意义的实现工作结束后，应加入简短的 `What this demonstrates` 部分，解释 1–3 个与刚完成任务直接相关的软件工程概念，例如：

- 为什么某段逻辑应该放在 coordinator，而不是 QWidget
- 为什么先拆 Core Phase，再做 UI integration
- 为什么某个测试属于 unit / integration / regression
- 为什么多个 ROI 应共享一次 screen capture
- 为什么已经有 cancellation 仍然需要 generation guard

只解释和本次工作直接相关的概念，不要泛泛写教程。

---

## 9. 测试策略

先运行能发现当前修改可能引入故障的最小测试集；当修改会影响共享行为时，再逐步扩大覆盖范围。

典型顺序：

1. 新增/修改的 unit tests
2. focused subsystem tests
3. 相关 integration/UI tests
4. 修改共享行为时运行完整 Core test suite
5. 视情况运行 compile/import/static sanity checks
6. 行为依赖真实 OS API 时进行 platform-native/manual validation

Core 开发基线：

```sh
python -m pip install -r requirements-dev.txt
pytest
```

常用仓库检查（在确实相关时）：

```sh
python -m compileall app gui.py
git diff --check
python gui.py --smoke-core
```

不要每次小修改后无条件跑所有昂贵检查。只有当检查结果会改变下一步工程动作时才运行。

测试在可行时应是 deterministic 的。如果状态可以直接驱动，就不要在 unit test 中加入真实时间 sleep。

不要为了让 suite 变绿而 skip、弱化或修改一个无关的既有失败。必须明确区分已知 environment failure 与当前修改引入的 regression。

Release-critical validation 优先使用 clean checkout / clean worktree，避免未提交的本地文件意外满足 import、dependency 或 runtime 行为。

---

## 10. Review 标准

在宣布一个 Phase 完成之前：

- 对比 branch 与预期 base
- 确认只有预期文件发生修改
- 看实际 implementation，而不是只看 Agent 自己的报告
- 确认实现符合已经接受的 Design Doc
- 确认测试覆盖重要状态转换和真实失败模式
- 确认没有提交无关用户修改
- 确认没有把后续 Phase 工作提前塞进当前 Phase

如果实现正确，要明确说“正确”。

不要为了显得严格而制造 blocker。

如果确实存在 blocker，应明确说明：

1. 具体 failure 是什么
2. 为什么它会影响项目支持范围内的真实使用
3. 最小的 in-scope 修复是什么
4. 它是否真的阻塞当前 Phase，还是可以以后再做

---

## 11. Git 与 commit 规范

优先保持 commit 小而完整，每个 commit 应代表一个清晰的工程修改。

例如：

```text
feat: add dual-region auto-watch core
fix: preserve latest auto-watch generation
refactor: share screen capture across watched regions
test: cover context-question pair transitions
docs: add v0.8.1 implementation plan
```

不要把无关 cleanup、formatting、refactoring、feature work 和用户自己的修改混在同一个 commit。

除非用户明确要求，并且仓库状态确实适合，否则不要 rewrite published history 或 force-push。

不要擅自 merge 到 `main`、创建 tag、发布 release 或删除 branch，除非这些动作明确属于当前已经批准的步骤。

---

## 12. Release 流程

对于较大的版本化功能：

```text
feature phases
    ↓
all accepted on main
    ↓
release preparation
    ↓
RC build/tag/release
    ↓
real platform validation
    ↓
fix only release blockers
    ↓
stable tag/release
```

TellMeSensei 当前既定 application release model：

- 一个 application version
- 一个 Git tag
- 一个 GitHub Release
- 一套共享 product feature set
- 每个支持的 application target 一个发布 asset

Local OCR 继续作为独立版本的 component，使用各平台 native package。

没有实际完成 platform/manual acceptance，就不要声称已经通过。

---

## 13. 实现报告格式

对于有意义的 coding work，除非某个 feature-specific prompt 要求更严格格式，否则按以下顺序汇报：

```text
## Result
一句话说明结论/状态。

## What changed
从行为层面简洁说明发生了什么变化。

## File map
带简短职责注释的文件路径。

## Design notes
只写真正重要的实现决策，以及为什么这样做。

## Tests
运行了什么；每个检查打算发现什么失败；结果是什么。

## Git
Branch、commit、push/PR 状态，以及无关本地修改是否原样保留。

## What this demonstrates
1–3 个与本次修改直接相关的软件工程知识点。

## Next step
下一步已批准的流程动作。不要未经允许自动开始。
```

如果是 review-only 任务，把 `What changed` 替换成 `Findings`；在适用时明确给出：

- `ACCEPT`
- `ACCEPT WITH FOLLOW-UP`
- `NOT ACCEPT`

---

## 14. 不只解释代码，也解释开发流程

开始一个有意义的任务时，应简短说明当前项目处于软件开发生命周期的哪个阶段，以及为什么下一步属于这个阶段。

例如：

- “我们还处于 design 阶段，所以现在不修改 production code。”
- “Design Doc 已接受；下一步正规流程是建立 umbrella Issue 和 Phase 1 branch。”
- “Phase 1 implementation 已完成；当前 review 用来判断是否可以 merge 后再进入 Phase 2。”
- “代码已经 merge；现在处于 release validation，而不是 feature development。”

解释 Git 或工程操作时，优先使用实际术语，并结合仓库当前状态说明。目标是让项目负责人理解专业团队如何组织开发，而不仅仅是拿到最终代码。

---

## 15. 避免 process theater

专业流程存在的目的，是减少歧义并捕获真实故障，而不是制造文书工作。

不要仅仅因为大公司有某种流程，就额外创建没有实际价值的 artifact。

应使用工程判断：

- 一份好的 Design Doc，比内容重复的 RFC + ADR + spec 更有价值
- 如果拆 sub-Issue 不会改善协调，一个 umbrella Issue 就够了
- 如果进一步拆分会让 review 更困难，一个 Phase PR 就够了
- 小型 bug fix 可以直接 branch + PR，不需要 Design Doc
- 只有真正长期有价值的架构决策，才值得单独建立 ADR

标准是：让 intent、ownership、review 状态和 release 状态足够清楚即可，不多做无价值流程。

---

## 16. 最终原则

首先保护已经正常工作的软件。

做满足已接受需求的最小、完整修改；清楚解释架构与开发流程；测试项目真实可能失败的行为；并在当前已经批准的 Phase 边界停止。