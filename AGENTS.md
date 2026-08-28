# AGENTS.md — TellMeSensei Engineering Workflow

This file defines the default working agreement for AI coding agents and contributors in this repository.

The project owner is learning professional software-development practice while building TellMeSensei. Therefore, agents must not only implement correctly; they should also make the engineering process visible and explain important decisions in concise, practical terms.

This is a repository-wide instruction file. More specific design documents under `docs/plans/` may add feature-specific requirements. When instructions conflict, follow the more specific accepted design for that feature, while preserving the safety and workflow rules below.

---

## 1. Project baseline

TellMeSensei is a Python 3.12 desktop application.

Supported Core targets:

- Windows x64
- macOS Intel x86_64
- macOS Apple Silicon arm64

Normal product features should be implemented once in shared application code. Platform-specific implementations are appropriate only at real OS/native/build boundaries such as:

- native global hotkeys
- macOS Screen Recording / window / Spaces behavior
- OS credential or filesystem APIs
- Windows installer packaging
- macOS DMG packaging
- platform-specific Local OCR native runtimes

Do not create separate Windows/macOS copies of shared application behavior merely because multiple platforms are supported.

Local OCR is a separate native component lifecycle. Do not pull Paddle/PaddleOCR dependencies into the Core development environment unless the task is specifically about Local OCR.

See `docs/development.md` for the established platform, build, CI, packaging, and release model.

---

## 2. Standard development lifecycle

For non-trivial product work, use this sequence:

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

Do not skip directly from a large idea to implementation when the architecture, user interaction, data model, lifecycle, or compatibility behavior is still undecided.

Small, obvious bug fixes do not require a full Design Doc. Use judgment. A fix that changes architecture, public behavior, persisted data, cross-platform behavior, or several subsystems does require a written plan.

---

## 3. Design Docs

Non-trivial feature plans belong under:

```text
docs/plans/
```

A useful Design Doc should normally contain:

1. Background / current behavior
2. Problem statement
3. Goals
4. Non-goals
5. Existing architecture relevant to the change
6. Proposed architecture
7. Data model / API / state-machine changes where relevant
8. User interaction / lifecycle where relevant
9. Important failure cases that are reachable in supported use
10. Alternatives considered when there is a meaningful choice
11. Test plan
12. Rollout / release plan
13. Open questions
14. Definition of Done

The Design Doc is the technical source of truth. Do not duplicate the full design into Issues or PR descriptions.

Once a design has been reviewed and accepted, treat its major architectural decisions and scope as frozen for that implementation phase. Do not redesign opportunistically while coding unless implementation evidence reveals a real problem. If that happens, explain the problem and update the design before widening scope.

---

## 4. Issues, phases, branches, and PRs

### 4.1 Umbrella Issue

For a versioned feature spanning multiple phases, create one umbrella Issue after the Design Doc is accepted.

The Issue should track progress, not duplicate the design. Typical contents:

- link to the Design Doc
- implementation phases as a checklist
- concise Definition of Done
- links to phase PRs

### 4.2 Phase sizing

Prefer independently reviewable phases with clear boundaries. Each phase should have one primary engineering question to answer.

Example:

```text
Phase 1 — Core model / algorithm
Phase 2 — Pipeline integration
Phase 3 — Product UI
Phase 4 — Hardening / regression / release
```

Do not start the next phase until the current phase has been reviewed and accepted when the user is following a phased plan.

### 4.3 Branches

Use short-lived feature/fix branches based on the latest accepted `main`, for example:

```text
feature/v0.8.1-phase1-dual-region-core
fix/capture-scaling
```

Do not create long-lived platform branches for normal shared product work.

Before editing:

- confirm the current branch
- inspect `git status`
- identify unrelated user changes
- preserve those changes exactly

Never reset, overwrite, discard, stage, or commit unrelated user modifications just to obtain a clean working tree.

If a file contains both task changes and unrelated user changes, stage only the task-specific hunks.

### 4.4 Pull Requests

A PR should explain the implementation delta, not restate the whole Design Doc.

Use a structure similar to:

```text
## Summary
What this PR changes.

## Design
Link to the relevant Design Doc section.

## Scope
What is intentionally included and excluded in this PR/phase.

## Key implementation notes
Only the important technical decisions needed to review the patch.

## Tests
Commands and results.

## Known limitations
Only real, intentional limitations that remain after this phase.
```

---

## 5. Before writing code

Before implementation, answer these questions from the repository, not from assumptions:

- What existing module owns this behavior today?
- What public or internal interface should be extended instead of duplicated?
- What must remain unchanged?
- What is the smallest coherent change that satisfies the accepted design?
- Which tests prove the new behavior?
- Which existing tests protect regressions?

Inspect the actual code first.

Do not introduce wrappers, compatibility layers, feature flags, migration frameworks, hashes, defensive scaffolding, or generalized abstractions for cases that do not occur in this project.

Prefer extending an existing well-owned abstraction over introducing a parallel subsystem.

---

## 6. Scope discipline

Report real problems, including uncommon ones when they are reachable through supported project use.

Do not manufacture findings.

Keep fixes proportional to the actual project:

- This is not a security paper unless a task explicitly makes security the subject.
- Assume a cooperating local operator unless the feature explicitly defines an adversary.
- Do not add hashes/checksums/fingerprints unless they replace a materially more expensive operation and the result changes behavior.
- Do not add defensive scaffolding for hypothetical compatibility or migration cases that do not exist.
- Do not optimize exotic encodings, symlink races, RTL text, millisecond races, or other corner cases unless they are reachable through supported inputs or real data.
- Do not re-review the same settled point repeatedly while blocking implementation progress.

Before running a check, be able to state:

> What specific failure could this check detect, and what would we do differently if it failed?

If there is no meaningful answer, do not run the check.

---

## 7. Code architecture principles

Prefer clear ownership boundaries.

A module should answer one recognizable engineering question. For example:

```text
capture/        # How screen content is acquired
ocr/            # How image content becomes text
services/       # How external services are called
workers/        # How long-running work is executed/cancelled off the GUI thread
ui/             # How users interact with the application
auto_watch/     # How monitored screen changes become analysis generations
platform/       # Real OS-specific behavior
```

Do not put domain/state-machine logic into large UI classes merely because the UI triggers it.

Do not duplicate cancellation, job lifecycle, OCR provider selection, DeepSeek access, AnswerWindow behavior, settings behavior, or Local OCR lifecycle across feature implementations when an existing shared path already owns it.

Keep platform-specific code at the actual platform boundary.

---

## 8. Comments and educational annotations

The project owner is learning software-engineering practice. Make explanations part of the workflow without turning production code into a tutorial.

### 8.1 Annotated file trees in reports/docs

Whenever a task adds or substantially changes multiple files, show an annotated file tree in the report when useful.

Use comments after the paths, for example:

```text
app/auto_watch/
├── pair_coordinator.py   # Combines Context and Question revisions into one pair generation
├── sampler.py            # Captures the screen and crops monitored ROI(s)
└── dispatcher.py         # Latest-Wins analysis dispatch and stale-result protection

tests/
└── test_pair_coordinator.py  # Deterministic pair-transition tests
```

These are explanatory comments in documentation/report output. Do **not** rename files or directories to include comments.

### 8.2 Code comments

Add concise code comments for:

- non-obvious invariants
- lifecycle ownership
- state-machine transitions that are easy to misunderstand
- coordinate/DPI mapping assumptions
- cancellation / generation / stale-result rules
- intentionally unusual implementation choices

Do not comment obvious syntax or every line. Prefer good names and small functions over excessive commentary.

Bad:

```python
count += 1  # Add one to count
```

Useful:

```python
# Update the accepted baseline before dispatch so later ticks cannot
# rediscover the same stable question while analysis is still running.
baseline = current
```

### 8.3 Learning notes in reports

At the end of meaningful implementation work, include a short `What this demonstrates` section explaining 1–3 relevant engineering concepts, such as:

- why this logic belongs in a coordinator instead of a QWidget
- why a phase is separated before UI integration
- why a test is unit vs integration vs regression
- why one screen capture is shared across multiple ROI crops
- why generation guards are needed even when cancellation exists

Keep it practical and tied to the work just completed.

---

## 9. Testing strategy

Use the smallest test set that can detect the failures introduced by the change, then widen coverage where shared behavior could regress.

Typical order:

1. new/changed unit tests
2. focused subsystem tests
3. relevant integration/UI tests
4. full Core test suite when the change touches shared behavior
5. compile/import/static sanity checks as appropriate
6. platform-native/manual validation when the behavior depends on real OS APIs

Core development baseline:

```sh
python -m pip install -r requirements-dev.txt
pytest
```

Common repository checks when relevant:

```sh
python -m compileall app gui.py
git diff --check
python gui.py --smoke-core
```

Do not run every expensive check automatically after every small edit. Run it when its result could change the next engineering action.

Tests must be deterministic where practical. Avoid real-time sleeps in unit tests when state can be driven directly.

Do not make the suite green by skipping or weakening an unrelated existing failure. Clearly distinguish known environment failures from regressions introduced by the current change.

For release-critical validation, prefer a clean checkout/worktree so uncommitted local files cannot accidentally satisfy imports, dependencies, or runtime behavior.

---

## 10. Review standard

Before declaring a phase complete:

- compare the branch against its intended base
- verify only expected files changed
- inspect the actual implementation, not only the agent's own report
- confirm the implementation matches the accepted design
- confirm tests exercise the important state transitions and failure modes
- confirm unrelated user changes were not included
- confirm no later-phase work leaked into the current phase

If the implementation is correct, say plainly that it is correct.

Do not invent blockers to make a review look rigorous.

When there is a real blocker, identify:

1. the concrete failure
2. why it matters in supported use
3. the smallest in-scope fix
4. whether it blocks the phase or can wait

---

## 11. Git and commit hygiene

Prefer small, coherent commits whose message describes the engineering change.

Examples:

```text
feat: add dual-region auto-watch core
fix: preserve latest auto-watch generation
refactor: share screen capture across watched regions
test: cover context-question pair transitions
docs: add v0.8.1 implementation plan
```

Do not mix unrelated cleanup, formatting, refactoring, feature work, and user changes into one commit.

Do not rewrite published history or force-push unless the user explicitly asks and the repository state makes it appropriate.

Do not merge to `main`, tag a release, publish a release, or delete branches unless that action is explicitly part of the current approved step.

---

## 12. Release workflow

For a significant versioned feature:

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

TellMeSensei's established application release model is:

- one application version
- one Git tag
- one GitHub Release
- one shared product feature set
- one asset for each supported application target

Local OCR remains an independently versioned component with platform-specific native packages.

Do not claim platform/manual acceptance that was not actually performed.

---

## 13. Required implementation report format

For meaningful coding work, report in this order unless a feature-specific prompt requires a stricter format:

```text
## Result
One-sentence verdict/status.

## What changed
Concise behavior-level summary.

## File map
Annotated paths with short comments.

## Design notes
Only important implementation decisions and why they were made.

## Tests
What was run, what failure each check was meant to detect, and the result.

## Git
Branch, commits, push/PR status, and whether unrelated local changes remain untouched.

## What this demonstrates
1–3 short software-engineering lessons tied to this change.

## Next step
The next approved workflow step. Do not silently start it.
```

For review-only tasks, replace `What changed` with `Findings` and give a clear `ACCEPT`, `ACCEPT WITH FOLLOW-UP`, or `NOT ACCEPT` verdict when appropriate.

---

## 14. Explain process as well as code

When beginning a meaningful task, briefly state which development stage the project is currently in and why the next action belongs there.

Examples:

- “We are still in design, so I am not editing production code yet.”
- “The Design Doc is accepted; the next professional step is to create the umbrella Issue and Phase 1 branch.”
- “Phase 1 is implementation-complete; this review checks whether it is safe to merge before Phase 2.”
- “The code is merged; now we are in release validation rather than feature development.”

When explaining a Git or engineering operation, prefer practical terminology and relate it to the repository state. The goal is for the owner to learn how professional teams structure work, not merely to receive finished code.

---

## 15. Avoid process theater

Professional process exists to reduce ambiguity and catch meaningful failures, not to create paperwork.

Do not create extra artifacts merely because large companies sometimes have them.

Use judgment:

- one good Design Doc is better than duplicate RFC + ADR + spec documents saying the same thing
- one umbrella Issue is enough when sub-Issues would add no coordination value
- one phase PR is enough when splitting it further would make review harder
- a small bug fix can be a direct branch + PR without a Design Doc
- do not create an ADR unless a durable architectural decision genuinely benefits from a standalone record

The standard is: enough structure to make intent, ownership, review, and release state clear — no more.

---

## 16. Final rule

Preserve working software first.

Make the smallest coherent change that satisfies the accepted requirement, explain the architecture and workflow clearly, test the behaviors that can actually fail, and stop at the approved phase boundary.
