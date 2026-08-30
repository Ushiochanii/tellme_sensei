# Auto Watch Direct Selection Workflow Design

Status: **Draft for design review**  
Related Issue: **#53 — 简化 Auto Watch 入口与连续框选流程**  
Date: **2026-08-30**

This document is the technical source of truth for the Issue #53 workflow
change. It builds on the accepted controller design in
`docs/plans/controller-ui-unification-design.md` and supersedes only that
document's Auto Watch setup interaction. The Auto Watch session/core design
accepted for v0.8.0/v0.8.1 remains in force.

## 1. Background and problem statement

The controller already exposes four entry cards: `Text / OCR`, `Vision`,
`Watch`, and `Context Watch`. The two Watch cards are visually separate, but
their actual workflow still enters a second setup screen.

The current implementation has two different interaction paths:

- Single Region is effectively “select once, then start”. The user first
  enters the setup screen, clicks `Select Region`, and the selection callback
  immediately creates an `AutoWatchSession`.
- Context + Question is “select, select, then confirm”. The user first enters
  the setup screen, clicks `Select Context`, clicks `Select Question`, and then
  clicks `Start Auto Watch`.

Analysis mode is also selected in that setup screen, even though Text / OCR vs
Vision is a reusable preference that can be decided before a Watch workflow.

Issue #53 therefore changes the entry and selection workflow, not the Watch
analysis pipeline:

```text
Watch card / Watch shortcut
    → immediately select one region
    → automatically start Single Region Auto Watch

Context Watch card / Context Watch shortcut
    → immediately select Context
    → automatically select Question
    → automatically start Context + Question Auto Watch
```

The user must not see a redundant Region Mode choice, a per-session Analysis
Mode choice, or a manual `Start Auto Watch` action.

## 2. Goals

- Make the Watch and Context Watch card clicks enter the first selection
  overlay directly.
- Make the Watch and Context Watch global shortcuts enter the exact same
  public workflow methods as their cards.
- Preserve the already intuitive Single Region behavior: one successful
  selection starts monitoring without another button.
- Make Context Watch a continuous two-stage selection chain: Context success
  immediately opens Question selection; Question success immediately starts
  monitoring.
- Move Text / OCR vs Vision to one shared, persistent Auto Watch setting.
- Preserve the current default analysis path (`Text / OCR`) for settings files
  that predate this setting.
- Make cancellation, failed selection, shutdown, and busy-state cleanup
  deterministic and leave the controller ready for a later attempt.
- Keep the existing `AutoWatchSession`,
  `ContextQuestionAutoWatchSession`, detector/coordinator semantics,
  dispatcher, OCR cache, AnswerWindow, and mini controller behavior unchanged.

## 3. Non-goals

This change does not:

- rewrite `AutoWatchCoordinator` or `PairCoordinator`;
- change detector thresholds, stability, Latest-Wins dispatch, generation
  guards, OCR caching, or analysis request formats;
- change `AutoWatchSession` or `ContextQuestionAutoWatchSession` monitoring
  semantics, except for receiving the mode snapshot selected at workflow
  entry;
- change AnswerWindow placement, the Watch overlay used during an active
  session, or the Watch mini controller;
- persist Context or Question ROIs;
- introduce per-workflow or per-region Analysis Mode settings;
- add an environment variable or a third analysis mode;
- redesign the Settings shell or add a new settings subsystem;
- add platform-specific selection logic;
- preserve hidden UI controls solely for old tests or for a removed setup
  screen.

## 4. Existing architecture and verified current behavior

### 4.1 Controller entry and hotkey routing

`MainWindow` creates the four cards in a 2 × 2 grid. The current Watch card
signals call lambdas that invoke:

```python
enter_auto_watch_setup("single")
enter_auto_watch_setup("context_question")
```

The setup method clears pending Context/Question data, sets the hidden
Region Mode radio state, marks `_auto_watch_in_setup`, hides the main card
view, and shows `auto_watch_setup`.

`ApplicationController` already connects the two native hotkey managers to the
public methods `MainWindow.start_watch()` and
`MainWindow.start_context_watch()` using a queued Qt connection. Those methods
currently call `_start_watch_from_hotkey()`, which first shows the controller
and then enters the same setup screen. They do not start a selection overlay.

The four native registrations are already independent and shared by Windows
and macOS through `GlobalHotkeyManager`. Issue #53 does not require changing
the hotkey IDs, parser, defaults, registration, or rollback contract.

### 4.2 Single Region selection path

The actual Single Region path in `MainWindow` is:

```text
Watch card
  → enter_auto_watch_setup("single")
  → user clicks auto_watch_select_button
  → start_auto_watch_selection()
  → CaptureOverlay()
  → overlay.begin()
  → captured(QImage)
  → _on_auto_watch_capture()
  → WatchRegion.create(screen, roi)
  → _start_single_region_session(region)
  → AutoWatchSession(region, mode)
  → _activate_auto_watch_session()
  → session.start()
```

`CaptureOverlay.selection_metadata` exposes the selected `QScreen` and a
screen-local logical `QRect`. `WatchRegion.create()` validates that the ROI is
non-empty and contained by the same screen-local geometry snapshot, and stores
screen geometry, device-pixel ratio, and a session ID.

The mode is currently read from the setup radio at the moment
`_start_single_region_session()` is called. The successful selection therefore
starts the session automatically; only entering the setup and pressing
`Select Region` are redundant under the new workflow.

### 4.3 Context + Question selection path

The current Context path is:

```text
Context Watch card
  → enter_auto_watch_setup("context_question")
  → hidden Context + Question adapter radio is checked
  → user clicks Select Context
  → start_auto_watch_selection("context")
  → CaptureOverlay()
  → captured(QImage)
  → _on_auto_watch_capture()
  → _on_context_question_capture(..., role="context")
  → store _auto_watch_context_region
  → show ContextQuestionWatchOverlay preview with one ROI
  → setup button changes to Select Question
  → user clicks Select Question
  → start_auto_watch_selection("question")
  → CaptureOverlay()
  → captured(QImage)
  → _on_context_question_capture(..., role="question")
  → validate same screen
  → store _auto_watch_question_region
  → create ContextQuestionRegions
  → update the same preview with two ROIs
  → enable Start Auto Watch
  → user clicks Start Auto Watch
  → start_context_question_auto_watch()
  → ContextQuestionAutoWatchSession(regions, mode, overlay=preview)
  → _activate_auto_watch_session()
  → session.start()
```

`ContextQuestionRegions.create()` requires both `WatchRegion` values to share
the same screen, screen geometry, device-pixel ratio, session ID, and valid
non-empty ROIs. The Question region reuses the Context session ID. A different
screen is rejected before it can replace the existing Context.

The current selection cancellation callback clears the active selection
overlay and role but leaves a previously selected Context and its preview in
setup. That is safe only because the old setup still has an explicit Start
button. It is not an appropriate state for the new no-confirmation workflow.

### 4.4 Overlay ownership

There are three distinct overlay roles and they must not be conflated:

| Overlay | Current owner | Purpose |
| --- | --- | --- |
| `CaptureOverlay` | `MainWindow` during selection | Interactive full-screen drag; emits `captured` or `cancelled` |
| `ContextQuestionWatchOverlay` preview | `MainWindow` during old setup | Click-through preview of pending Context/Question ROIs |
| `WatchOverlay` / `ContextQuestionWatchOverlay` active overlay | Auto Watch session | Persistent click-through border while monitoring |

The new chain removes the setup preview. The active session remains the owner
of the monitoring overlay. A `CaptureOverlay` is the only selection UI and at
most one may exist at a time.

## 5. Proposed user workflow

### 5.1 Canonical public entry methods

`MainWindow.start_watch()` and `MainWindow.start_context_watch()` become the
canonical public entry methods for both cards and global shortcuts.

The card signals should connect directly to these methods. The
`ApplicationController` hotkey connections already target these methods and
remain queued on the GUI thread. The methods must therefore perform the same
guards, mode snapshot, controller visibility handling, and overlay creation
regardless of whether the caller was a card or a native hotkey.

The current `_start_watch_from_hotkey()` distinction is removed or reduced to
an internal common helper. There must not be a “hotkey opens setup” path that
differs from a “card opens setup” path.

### 5.2 Watch

```text
IDLE controller
  → start_watch()
  → snapshot shared Auto Watch Analysis Mode
  → create and begin CaptureOverlay
  → user selects a valid ROI or cancels
  → valid ROI creates WatchRegion
  → AutoWatchSession starts immediately
```

No setup widget, Analysis Mode radio, Select button, or Start button is shown.

### 5.3 Context Watch

```text
IDLE controller
  → start_context_watch()
  → snapshot shared Auto Watch Analysis Mode
  → create and begin CaptureOverlay for Context
  → valid Context creates WatchRegion
  → immediately create and begin CaptureOverlay for Question
  → valid same-screen Question creates ContextQuestionRegions
  → ContextQuestionAutoWatchSession starts immediately
```

The second `CaptureOverlay` is created from the Context capture callback after
the first overlay has delivered its metadata. No manual intermediate action is
required. The Context and Question capture overlays may be separate instances;
the active monitor overlay remains one session-owned
`ContextQuestionWatchOverlay` after the pair is complete.

### 5.4 Controller visibility during selection

Before constructing a selection overlay, the common entry helper records
whether the floating controller was visible and hides it. This matches direct
capture behavior and prevents the controller from being included in the
screen image, which matters because `CaptureOverlay` grabs the screen during
construction on macOS and after a short settle delay on Windows.

On selection cancellation or setup failure, the controller is restored only if
it was visible when the workflow began. On successful session activation it
remains hidden using the existing Auto Watch lifecycle; on session Stop the
existing `_auto_watch_restore_visible` behavior restores it only when
appropriate for tray/non-tray mode.

This visibility detail is not a new session behavior: it makes the direct
selection overlay equivalent for card and shortcut entry and preserves the
existing hidden-controller contract during active Auto Watch.

## 6. Shared Auto Watch Analysis Mode setting

### 6.1 Persistence contract

Persist one allow-listed top-level setting in the existing settings JSON:

```json
{
  "auto_watch_analysis_mode": "text"
}
```

The canonical values are the existing `AnalysisMode` values:

- `"text"` for Text / OCR;
- `"vision"` for Vision.

The recommended API is a narrow `SettingsRepository.auto_watch_analysis_mode()`
accessor returning `AnalysisMode`, plus validation in `load()`/`update()`.
`AutoWatchSettings` should remain the detector/timing settings object; Analysis
Mode is a launch preference and is not consumed by the sampler or coordinator.

Missing or invalid persisted values fall back to `AnalysisMode.TEXT`. This
preserves the current behavior of existing settings files and fresh installs.
An invalid value must not make application startup fail. An explicit update
with an invalid value should raise `ValueError`, consistent with the existing
allow-listed Auto Watch settings validation.

No environment variable is introduced. `ConfigManager` remains the owner of
the shared `SettingsRepository` passed to `MainWindow` and `SettingsWindow`,
but `AppConfig` does not need a new field merely to carry this UI/session
preference. The session constructor continues to receive an explicit
`AnalysisMode` enum.

### 6.2 Settings UI

The existing **Settings → Auto Watch** page adds one Analysis Mode radio group
alongside the existing detector/timing controls:

```text
Analysis Mode
● Text / OCR
○ Vision
```

The page loads the repository value, saves it in the same atomic settings save
operation as the other Auto Watch fields, and restores `Text / OCR` when the
user chooses Restore Defaults. Existing shortcut controls and their four-way
uniqueness/rebind behavior are unchanged.

### 6.3 Runtime snapshot and active-session invariant

At `start_watch()` or `start_context_watch()`, before the first selection
overlay is created, `MainWindow` reads the repository setting and stores a
workflow-local mode snapshot. The completed session is constructed from that
snapshot; it never reads the repository again for its mode.

Saving Settings while a selection overlay or an active Auto Watch session is
present must not mutate:

- the pending workflow mode snapshot;
- `AutoWatchSession.mode`;
- `ContextQuestionAutoWatchSession.mode`;
- any active dispatcher request.

The saved value is used by the next workflow entry. If a user changes Settings
while a selection chain is in progress, the current chain keeps its snapshot;
canceling and starting a new chain is the deterministic way to use the new
value. This prevents an analysis mode from changing between Context and
Question selection.

## 7. Selection-chain state machine

The current combination of `_auto_watch_in_setup`, hidden radio buttons,
`_auto_watch_selection_role`, and setup-widget visibility should be replaced by
one explicit private selection phase and a small set of pending data. This is
UI workflow state, not a new Auto Watch core state machine.

Recommended phases:

```python
class AutoWatchSelectionPhase(Enum):
    IDLE = "idle"
    SELECTING_SINGLE = "selecting_single"
    SELECTING_CONTEXT = "selecting_context"
    SELECTING_QUESTION = "selecting_question"
    ACTIVE = "active"
```

`MainWindow` owns this phase because it also owns the controller, selection
overlay, and session handoff. No separate general-purpose workflow framework is
needed. The transition helpers should be small and deterministic so they can
be exercised without real screen drags.

### 7.1 State invariants

- `IDLE`: no selection overlay, no pending Context/Question/regions, and no
  active Auto Watch session. The main controller card view is available unless
  the application is hidden by tray policy.
- `SELECTING_SINGLE`: exactly one active `CaptureOverlay`; no pending Context
  or Question.
- `SELECTING_CONTEXT`: exactly one active Context `CaptureOverlay`; no pending
  Context has been accepted yet.
- `SELECTING_QUESTION`: exactly one active Question `CaptureOverlay`; exactly
  one valid pending Context `WatchRegion`; no `ContextQuestionRegions` session
  object exists yet.
- `ACTIVE`: no selection overlay; an accepted session object is the sole owner
  of monitoring timers, active watch overlay, mini controller, and dispatcher
  lifecycle.
- A pending Context or Question is never sufficient to start a session. Only a
  fully validated `WatchRegion` or `ContextQuestionRegions` reaches the
  corresponding session constructor.
- A selection overlay callback is accepted only when it belongs to the current
  phase/current overlay. A late callback from a canceled or replaced overlay
  cannot commit a region or start a session.
- The workflow mode snapshot is immutable for all phases until the workflow
  returns to `IDLE` or reaches `ACTIVE`.

### 7.2 Transition table

| From | Event | Guard | Action | To |
| --- | --- | --- | --- | --- |
| `IDLE` | `start_watch()` | not shutting down, not busy, no direct-capture overlay, no active session | Snapshot mode, record visibility, create/begin single selection overlay | `SELECTING_SINGLE` |
| `IDLE` | `start_context_watch()` | same guard | Snapshot mode, clear old pending data, create/begin Context selection overlay | `SELECTING_CONTEXT` |
| any selection phase | new Watch entry | selection/session/busy guard fails | Do nothing; do not replace current overlay or pending data | unchanged |
| `SELECTING_SINGLE` | valid capture | current overlay and metadata valid | Build `WatchRegion`, hand it to `AutoWatchSession`, start immediately | `ACTIVE` |
| `SELECTING_CONTEXT` | valid capture | current overlay and metadata valid | Store Context region; start Question selection immediately | `SELECTING_QUESTION` |
| `SELECTING_QUESTION` | valid same-screen capture | current overlay, Context, ROI, geometry, and DPR valid | Build Question region with Context session ID, build `ContextQuestionRegions`, start session immediately | `ACTIVE` |
| `SELECTING_QUESTION` | rejected Question display/ROI | Context remains valid | Report a concise error and reopen Question selection; do not build pair/session | `SELECTING_QUESTION` |
| any selection phase | Esc/right-click/too-small selection | cancellation belongs to current overlay | Close/clear overlay and all pending data; restore controller | `IDLE` |
| any selection phase | overlay creation/begin failure | exception before capture | Close any partial overlay, clear all pending data, restore controller, report error | `IDLE` |
| `SELECTING_SINGLE` | region/session construction or start failure | exception/false return | Clean any created session using existing stop/shutdown contract; clear selection | `IDLE` |
| `SELECTING_QUESTION` | pair/session construction or start failure | exception/false return | Clean any created session; clear Context/Question and selection state | `IDLE` |
| `ACTIVE` | session stopped | current session identity matches callback | Reuse existing `_on_auto_watch_stopped()` cleanup and controller restoration | `IDLE` |
| any phase | application shutdown | `_shutting_down` set | Abort selection or stop active session, then continue existing shutdown chain | shutdown path |

The same-screen rejection is the one intentionally recoverable selection
failure: the in-memory Context remains only long enough to retry Question
selection immediately. It is never exposed as a startable partial session. An
Esc/cancel, overlay creation failure, metadata failure, or session failure
clears the entire chain and returns to `IDLE`.

## 8. Ownership and minimal coordination

The coordination boundary is deliberately narrow:

```text
MainWindow
  owns entry guards, phase, pending regions, mode snapshot, and CaptureOverlay
       │
       ├── WatchRegion / ContextQuestionRegions validation
       │
       ├── AutoWatchSession(region, mode)
       └── ContextQuestionAutoWatchSession(regions, mode)
               │
               └── existing sampler/coordinator/dispatcher/overlay/mini lifecycle
```

`MainWindow` should not duplicate detector, polling, cancellation, or result
handling logic. The two existing session classes remain the only owners after
the handoff.

The selection callback should be structured as three focused operations:

1. `begin_auto_watch_workflow(workflow)` performs guards, mode snapshot,
   visibility bookkeeping, and first overlay creation.
2. `handle_selection_capture(overlay, metadata)` validates and commits only
   the current stage. Context success calls `begin_question_selection()`;
   Question success calls the existing session activation path.
3. `abort_auto_watch_workflow(reason)` closes selection UI, clears all pending
   fields, restores the controller when appropriate, and leaves no partial
   session.

No new `app/auto_watch` coordinator is necessary: this state machine controls
only UI selection and session construction.

## 9. Failure, cancellation, and cleanup behavior

### 9.1 Guard failures and already-busy state

Both public entry methods must return `False` without changing state when any
of these are true:

- `_shutting_down` is true;
- an Auto Watch session is active or stopping;
- a direct-capture overlay is active;
- a selection overlay is already active;
- `_busy` or a normal processing job is active;
- the controller is not in an idle/re-enterable selection state.

No second overlay, session, timer, or mode snapshot may be created in these
cases. Existing direct capture and Auto Watch active-session guards remain the
source of truth for shared busy behavior.

### 9.2 Screen permission and overlay creation

The common entry helper calls the existing
`_ensure_screen_recording_permission()` before creating or changing selection
state. If permission is unavailable, the existing permission warning is shown,
the phase remains `IDLE`, and no overlay/session is allocated.

If `CaptureOverlay()` or `begin()` raises (no screen, native window setup
failure, or another supported capture error), the helper must:

- close a partially constructed overlay when possible;
- clear the current overlay reference, phase, role, and pending regions;
- restore the controller only if it was visible at workflow entry;
- report a concise error through the existing controller status/logging path;
- avoid constructing either Auto Watch session.

### 9.3 Esc, right-click, and too-small selection

`CaptureOverlay` emits `cancelled` for Esc, right-click, and a selection below
the existing minimum dimensions. The cancellation handler is accepted only for
the current overlay. It then clears the complete selection chain, including a
pending Context when Question selection was active. It does not create a
session and does not leave a preview or `Start Auto Watch` affordance.

External `close()` calls during shutdown must not be treated as a user
selection success or as a new workflow. Shutdown explicitly clears the current
selection reference before continuing its existing cleanup sequence.

### 9.4 Capture and selection validation failures

The callback reads the current overlay's `selection_metadata`, not only the
emitted image. `WatchRegion.create()` remains responsible for non-empty,
screen-local, fully contained ROI validation.

- Invalid first-stage metadata aborts the complete workflow and returns to
  `IDLE`.
- Invalid Question metadata or a Question on a different display leaves the
  valid Context only as transient retry state, reports the existing same-screen
  error, and immediately reopens Question selection.
- A failed retry overlay creation aborts the complete workflow and clears the
  transient Context.
- No invalid `ContextQuestionRegions` object is passed to the session.

### 9.5 Session construction/start failure

After a valid region/pair exists, session construction and `session.start()` are
still fallible. If construction or start raises, or returns `False`, reuse the
existing `_cleanup_failed_auto_watch_session()` contract for any created
session, close selection resources, clear pending data, restore the controller,
and return to `IDLE`. A failed start must not leave `_auto_watch_active` true or
retain a session identity that can accept later callbacks.

### 9.6 Active-session errors and Stop

Once the handoff reaches `ACTIVE`, Issue #53 does not alter session semantics:

- sampler/capture faults pause the existing session and leave Stop usable;
- one OCR/AI failure does not terminate monitoring;
- dispatcher cancellation, generation guards, and stale-result rejection stay
  unchanged;
- Stop remains idempotent and closes session-owned overlay/mini/controller
  resources through the existing session lifecycle;
- `_on_auto_watch_stopped()` clears region/session references and restores the
  main controller according to the recorded visibility policy.

### 9.7 Application shutdown

`request_shutdown()` sets `_shutting_down` and disables new entry controls.

- During a selection phase, close the current `CaptureOverlay`, clear all
  pending Context/Question/mode state, and proceed directly to the existing
  `_continue_shutdown_after_watch()` path. There is no session stop signal to
  await.
- During `ACTIVE`, retain the existing session `stop()`/`session_stopped`
  handshake, then continue the existing processing, Settings, Local OCR, and
  `shutdown_ready` sequence.
- Repeated shutdown requests remain idempotent.

### 9.8 Selection cleanup invariant

After every abort, failed start, cancel, or session stop, the following must
hold before the controller is re-enterable:

```text
selection phase = IDLE
selection overlay = None
pending context = None
pending question = None
pending pair = None
selection role = None
workflow mode snapshot = None
active session = None (unless the state is ACTIVE)
```

The only exception is the recoverable same-screen Question validation failure,
which remains in `SELECTING_QUESTION` with one pending Context and a new active
Question overlay. It cannot start a session until a valid Question completes.

## 10. Setup widget and compatibility decision

The existing `auto_watch_setup` is no longer needed. The implementation should
remove the user-facing widget and its controls rather than hide them:

- Analysis Mode radios in `MainWindow`;
- hidden Region Mode radios and their `QButtonGroup`;
- Context/Question selection status labels;
- Reselect Context and Reselect Question buttons;
- Select Region/Context/Question button;
- Start Auto Watch button;
- Back button and setup-only status label;
- setup visibility/state helpers whose only consumer was that widget;
- the old ContextQuestionWatchOverlay preview path.

The following remain real consumers and must be retained:

- `start_watch()` and `start_context_watch()` as the public card/hotkey entry
  methods;
- `CaptureOverlay` as the selection primitive;
- `WatchRegion` and `ContextQuestionRegions` validation;
- `_auto_watch_session`, session identity/generation guards, and active-session
  cleanup;
- `WatchOverlay` / `ContextQuestionWatchOverlay` when owned by active sessions;
- `auto_watch_main_view` (or a clearly renamed equivalent) as the main card
  grid and status strip.

The old `auto_watch_button` / `context_watch_button` aliases, hidden radio
adapters, and setup-specific method aliases should not be kept after focused
tests and real callers are updated. There is no production consumer for those
aliases; retaining them would preserve a dead second workflow and make future
state cleanup ambiguous.

## 11. Core/session invariants that must not change

The new selection chain ends at the same constructors and activation boundary
as the current implementation:

- Single Region uses `AutoWatchSession(region, mode)`;
- Context + Question uses
  `ContextQuestionAutoWatchSession(regions, mode)`;
- the mode is an explicit `AnalysisMode` snapshot, not a mutable repository
  reference;
- `AutoWatchSession.start()` still creates `ScreenSampler`,
  `AutoWatchCoordinator`, timer, session-owned `WatchOverlay`, and
  `WatchMiniController` with existing semantics;
- `ContextQuestionAutoWatchSession.start()` still creates
  `ContextQuestionSampler`, `PairCoordinator`, timer, dual-region overlay, and
  mini controller with existing semantics;
- first stable generation, Context/Question revisions, Context OCR cache,
  Vision image composition, dispatcher Latest-Wins, cancellation, and stale
  result guards are unchanged;
- AnswerWindow and mini-controller presentation are unchanged;
- screen geometry/device-pixel-ratio snapshots continue to be enforced by
  `WatchRegion` and `ContextQuestionRegions`.

The workflow change must not move detector or session state into the card
widgets. `MainWindow` only coordinates selection and hands validated values to
the existing session owners.

## 12. Minimal implementation file map

```text
app/ui/main_window.py
  # Canonical card/hotkey entry methods, selection phase, direct overlay chain,
  # cleanup, mode snapshot, and session handoff.

app/settings/repository.py
  # Persist and validate auto_watch_analysis_mode; keep detector settings API.

app/ui/settings_window.py
  # Auto Watch Analysis Mode radio group, load/save/default behavior.

app/ui/application_controller.py
  # Expected to need no routing change; verify both hotkeys still target the
  # same public MainWindow entry methods.

app/config.py
  # Expected to remain unchanged; ConfigManager continues to provide the
  # shared SettingsRepository and service configuration.

app/platform/hotkey.py
  # Expected to remain unchanged; existing four native shortcut contracts are
  # reused.

README.md
README.zh-CN.md
  # Describe direct card/shortcut selection and the Settings mode preference.

tests/test_controller_ui_unification.py
tests/test_context_question_ui.py
tests/test_gui.py
  # Replace setup-screen assumptions with direct selection-chain assertions.

tests/test_settings.py
  # Repository and SettingsWindow mode persistence/default tests.

tests/test_phase7.py
tests/test_shutdown.py
  # Verify hotkey route and shutdown behavior where existing coverage overlaps.
```

No `app/auto_watch` detector, sampler, dispatcher, coordinator, OCR cache,
AnswerWindow, or mini-controller file should change for this UI workflow unless
implementation evidence exposes a direct contract bug.

## 13. Deterministic test plan

Tests should inject fake screens, overlays, sessions, and repositories. They
must not use wall-clock sleeps or real native hotkey registration to prove the
selection state machine.

### 13.1 Settings and compatibility

1. A fresh repository returns `AnalysisMode.TEXT`.
2. A settings file without `auto_watch_analysis_mode` still returns Text.
3. Persisted `"vision"` round-trips as Vision.
4. Invalid persisted values fall back to Text without discarding unrelated
   settings.
5. Explicit invalid updates are rejected.
6. SettingsWindow loads, saves, cancels, and restores the mode together with
   existing Auto Watch tuning fields.
7. Saving the mode while a fake active session exists does not mutate that
   session's mode; the next entry reads the new value.

### 13.2 Entry and phase transitions

1. Clicking Watch calls the same public `start_watch()` method used by the
   ApplicationController Watch shortcut.
2. Clicking Context Watch calls the same public `start_context_watch()` method
   used by the Context Watch shortcut.
3. A successful Watch entry creates the first `CaptureOverlay` immediately;
   no `auto_watch_setup` widget or Start button is required.
4. A successful Context Watch entry creates the Context `CaptureOverlay`
   immediately; a valid Context capture creates a Question overlay immediately.
5. A valid Single Region capture constructs/starts exactly one
   `AutoWatchSession` without a manual start action.
6. A valid Context + Question pair constructs/starts exactly one
   `ContextQuestionAutoWatchSession` without a manual start action.
7. The mode passed to either session equals the mode snapshot read at workflow
   entry.

### 13.3 Cancellation and failure cleanup

1. Esc/right-click/too-small selection at the first stage returns to `IDLE`
   with no session or pending region.
2. Esc during Question selection clears the pending Context as well and
   returns to `IDLE`.
3. Overlay constructor or `begin()` failure leaves no overlay reference,
   session, pending pair, or stale mode snapshot.
4. Invalid first-stage metadata leaves no pending region.
5. A different-screen Question is rejected without replacing Context and
   reopens Question selection; canceling that retry clears the chain.
6. Session constructor/start exception or false return invokes cleanup and
   leaves the controller re-enterable.
7. Entry attempts while direct capture, processing, selection, active Watch,
   or shutdown is in progress are no-ops.
8. A late callback from an old overlay cannot commit a region or start a
   session after cancellation/re-entry.
9. Shutdown during selection closes the overlay and reaches the existing
   shutdown path without waiting for a nonexistent session signal.
10. Active-session Stop and shutdown regression tests continue to pass.

### 13.4 Regression coverage

Run the existing focused Context + Question UI/session tests and the relevant
controller, cancellation, shutdown, settings, and core suites. The existing
detector, pair-coordinator, dispatcher, OCR cache, AnswerWindow placement, and
session tests remain authoritative for the non-goals explicitly preserved by
this document.

## 14. Native validation

After automated tests pass, validate on the supported native targets:

- Windows x64;
- macOS Intel x86_64;
- macOS Apple Silicon arm64.

For each target, verify:

1. Clicking Watch opens the screen selection overlay immediately.
2. The Watch shortcut opens the same overlay without first showing setup.
3. A successful Watch selection starts monitoring and exposes the normal mini
   controller/AnswerWindow behavior.
4. Clicking Context Watch and using its shortcut both perform Context then
   Question selection without a manual intermediate button.
5. Esc/cancel at both stages returns to a usable controller and does not start
   monitoring.
6. A different-display Question is rejected and can be retried without a
   stale or startable partial session.
7. Settings mode changes persist across restart, apply to the next workflow,
   and do not change an active session.
8. Screen Recording permission denial, normal DPI/Retina scaling, display
   geometry changes, Stop, and application shutdown preserve the existing
   cleanup behavior.

Visual validation is limited to the direct selection transition and native
window lifecycle. It does not reopen the already accepted controller card
visual review unless the implementation changes that UI.

## 15. Documentation and rollout

Because this changes user-visible behavior, the implementation PR must update
both READMEs in the same change:

- replace “open Watch setup, choose Analysis Mode, then select” with direct
  Watch/Context Watch selection instructions;
- document that Context Watch automatically advances from Context to Question
  and starts after the second selection;
- state that Text / OCR vs Vision is configured under Settings → Auto Watch;
- keep the four global shortcut descriptions, but describe Watch shortcuts as
  starting their matching selection workflow rather than opening setup.

Recommended delivery sequence:

```text
Design review and Issue #53 scope acceptance
    ↓
short-lived implementation branch
    ↓
implementation + deterministic tests + README updates
    ↓
PR review and Core CI
    ↓
Windows/macOS native workflow validation
    ↓
merge to main
```

No feature flag, ROI migration, release-specific data migration, or version
bump is required. A missing setting key is the compatibility migration: it
means Text / OCR.

## 16. Open questions and recommended decisions

There is one behavior difference from the accepted v0.8.1 Context + Question
design: that design required an explicit `Start Auto Watch` confirmation. Issue
#53 explicitly supersedes that interaction. The recommendation in this
document is to remove the confirmation and clear the whole chain on Question
cancel, while allowing only a same-screen validation failure to retry Question
immediately.

The following implementation details are considered resolved for scope review:

- one shared persisted mode, not separate Single/Context preferences;
- default Text / OCR for fresh and legacy settings;
- mode snapshot at workflow entry, not live mutation;
- no setup preview or hidden compatibility radios;
- card and shortcut reuse `start_watch()` / `start_context_watch()`;
- active session classes and Auto Watch core remain unchanged.

Native validation may adjust the concise status-strip wording for selection
errors, but it must not add a second setup screen or alter the state machine.

## 17. Definition of Done

- Watch card and Watch shortcut immediately enter Single Region selection.
- A valid Single Region selection starts Auto Watch automatically.
- Context Watch card and Context Watch shortcut immediately enter Context
  selection.
- A valid Context selection immediately enters Question selection.
- A valid Question selection automatically starts Context + Question Auto Watch.
- The controller no longer displays an Auto Watch setup/Region Mode menu.
- Analysis Mode is configurable once in Settings → Auto Watch and persisted.
- Missing/invalid legacy mode values preserve the current Text / OCR default.
- Saving Settings affects the next workflow and never mutates an active session
  or an in-progress selection chain.
- Any selection cancel, overlay failure, invalid first-stage capture, second
  stage cancellation, session start failure, or shutdown leaves no stale
  selection/session state.
- Same-screen validation remains enforced for Context and Question.
- Existing Auto Watch sessions, Stop, cancellation, Latest-Wins, OCR cache,
  AnswerWindow, mini controller, and core detector/coordinator tests remain
  green.
- README.md and README.zh-CN.md describe the actual direct-selection workflow.
- Deterministic controller/settings tests and supported-target native workflow
  validation are complete.

