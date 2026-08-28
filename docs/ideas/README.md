# TellMeSensei 想法池约定

这个目录只用于记录还没有进入正式开发流程的想法。

## 默认规则

当项目讨论中出现临时、模糊、天马行空的产品想法时：

1. 优先把它作为 GitHub Discussions 的 `Ideas` 类别内容记录下来。
2. 记录的目的只是防止遗忘，不代表已经承诺开发。
3. 不要因为记录了想法就自动创建 Issue、Design Doc、branch 或开始编码。
4. 只有当项目负责人明确决定“这个想法要做”以后，才进入：

```text
Idea
  ↓
Problem definition
  ↓
Design Doc（如果需要）
  ↓
Issue
  ↓
Branch / PR / Release
```

5. 如果当前使用的 GitHub 工具暂时不能创建 Discussion，不要擅自用 Issue 代替；可以先把 Discussion 草稿临时放在本文件的 `Pending discussion drafts` 中，等具备 Discussion 写入能力后再迁移。

---

## Pending discussion drafts

### Auto Watch UI 与现有模式 UI 统一

**状态：** Idea only / 暂不开发

**原始想法：**

目前 Auto Watch 的入口 UI 还比较简单，主要表现为一个单独的按钮；它和上方两个 Analysis Mode 的视觉结构、交互层级不太一致，因此整体看起来比较突兀。

以后可以考虑统一 Auto Watch 与现有模式选择区域的 UI 语言，让入口、模式选择、状态呈现和整体布局看起来像同一套产品设计，而不是后加进去的独立按钮。

**当前不决定的内容：**

- 不决定具体 UI 方案
- 不决定放在哪个版本
- 不创建实现 Issue
- 不开始编码

等未来真正准备处理 UI consistency 时，再把这个想法升级成正式需求并讨论具体方案。
