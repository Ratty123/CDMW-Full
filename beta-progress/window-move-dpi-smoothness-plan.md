# CDMW window movement and DPI smoothness plan

- Plan ID: `WMDPI`
- Created: 2026-10-17 (Europe/Stockholm)
- Status: Planned. Implementation has not started.
- Project: `D:\CLAUDETEST\CDMW Full`
- Plan file: `beta-progress/window-move-dpi-smoothness-plan.md`
- Shared completion log: `beta-progress/progress.md`

## Goal

Make moving and resizing CDMW smooth, including moving between monitors with different scaling. Remove geometry-related settings-file updates during an active drag and prevent CDMW's custom screen-fitting logic from repositioning the window against the user's movement. Preserve readable controls, native DPI scaling, remembered window geometry, reachable dialogs, and embedded editor behavior.

This document prepares the work. Creating it does not start implementation, launch visible UI, authorize packaging, or claim the reported stall has been fixed. Follow authorization already provided in the active session when work starts.

## Current handoff

- Completed: WMDPI-DOC-01 only (planning).
- Active task: None.
- Working agent: Unassigned.
- Next task: WMDPI-01.
- Blockers: None identified for planning. Physical monitor validation remains to be performed.
- Required tasks: WMDPI-01 through WMDPI-07.
- Optional task: WMDPI-O1. This does not block completion if left deferred with a reason.

## Completed preparation

- [x] **WMDPI-DOC-01 complete:** Created this plan, recorded the investigation evidence and acceptance checks, and established matching task IDs and shared-progress rules.

Completion evidence: 2026-10-17. The saved plan was read back and checked for unique task IDs, pending implementation checkboxes, and valid Markdown structure. The matching planning entry is recorded in the shared `progress.md`. No implementation has started.

## Shared progress rules for every agent working on this plan

1. Before implementation, read the current project instructions, this plan, and `beta-progress/progress.md`. Create that exact shared progress file if it does not exist. If another agent has already created it, reuse it.
2. `progress.md` is shared by all plans and agents in this folder. Do not replace, clear, reorder, or reformat another agent's entries. Do not create a separate per-plan progress file.
3. Claim the active task and relevant source files in this plan's Current handoff section before editing. Coordinate overlapping source changes with other agents.
4. Use the stable task IDs below. Mark an item `[x]` only when its stated acceptance checks have passed and its completion evidence has been recorded in this plan.
5. At the same completion checkpoint, append one short completed-item bullet to the shared `progress.md`. Include the namespaced task ID, completed outcome, and concise verification; a plan link can be included in the description. Keep this as a simple list, not a second detailed plan.
6. Read both files immediately before updating them. With ThinkForge, use the latest read's SHA-256 and a targeted `apply_patch`. If the file changed, reread it and merge only the intended update. Never overwrite shared progress using a stale whole-file copy.
7. The plan and progress file are separate writes. After updating, reread both and verify the matching checkbox and progress entry exist. If interrupted between writes, reconcile the missing half on resume after checking the underlying completion evidence.
8. Check for an existing entry with this plan's namespaced task ID before appending, so retries do not create duplicate completions.
9. Keep unfinished work, blockers, ownership, and the next action in this plan. The shared progress list records completed work only. A completed investigation or a deferred optional change must not be described as an implemented fix.
10. Planning and earlier diagnostic results are not completed implementation tasks. Keep the implementation checkboxes below unchecked until their work is done.

Use the established shared-log format:

```text
- YYYY-MM-DD | WMDPI-02 | Deferred window geometry persistence until movement settles; verified <focused check and result>.
```

The line above is a format example, not a completed item. Once implementation starts, keep updating both this plan and the shared log throughout the work, not only at final handoff.

## Recorded investigation baseline

The review used the clean source tree at commit `afa050237092d1aa38ad0642ceabdd889da907da` on branch `RR/independent-item-packages`. The isolated checks used PySide6 and Qt 6.11.0. These are source-tree and offscreen results, not proof of physical monitor behavior or the identity of a packaged executable.

| Finding | Evidence | Meaning |
|---|---|---|
| Geometry persistence runs for every Move and Resize event | `UiLayoutPersistence.eventFilter()` calls `settings.setValue(..., watched.saveGeometry())` before the shared sync delay | Delaying the explicit `sync()` call does not defer the actual settings mutation |
| Automatic settings-file updates still occur during movement | An isolated QWidget with the real persistence policy and a temporary INI produced 20 file-content changes for 20 moves, while the CDMW sync timer fired 0 times and still had 636 ms remaining | The current 650 ms sync timer does not prevent geometry-related file updates during event processing |
| The small persistence probe had measurable processing cost | The 20 move-plus-event-processing steps took 201.421 ms in total; the largest step was 19.416 ms | A local observation, not a universal timing threshold or a full-application benchmark |
| Custom fitting can fire during continued movement | After a synthetic screen-change notification, 22 programmatic moves continued for 351.6 ms; fitting ran at 137.7 ms and changed frame X from 673 to 388 | The window was moved 285 logical pixels back inside a simulated screen boundary while movement continued |
| Relevant geometry tests already pass | `tests/test_display_scaling.py`: 13 passed in 1.55 seconds | Existing resize-burst coverage does not establish correct behavior during a native drag or move-only continuation |

### Existing behavior to retain

- The shell's ordinary resize path already skips application-wide theme/font reapplication, saved-splitter restoration, and column autofitting.
- The display policy already coalesces fitting with a 120 ms timer. The shell's screen-change path uses a 260 ms delay. The remaining problem is that those delays do not identify the end of a drag.
- Qt continues to own normal DPI handling and logical-to-device-pixel conversion.
- The Rust editor host already uses `SWP_ASYNCWINDOWPOS` and `ShowWindowAsync`.
- The Rust host's second, queued geometry synchronization addresses native parent sizing that may settle after Show or Resize.
- Overflow wrapping is meant to happen once and preserve the central widget and nested preview parents.

## Source ownership

Paths below are relative to `D:\CLAUDETEST\CDMW Full`. Read current source before editing; line numbers from the investigation may move.

| Area | Owning source |
|---|---|
| Per-window geometry persistence | `cdmw/ui/layout_persistence.py`: `UiLayoutPersistence.eventFilter()`, `watch_window()`, `flush()` |
| Shared explicit settings sync delay | `cdmw/ui/widgets.py`: `request_settings_sync()` and `_flush_requested_settings_syncs()` |
| Top-level fitting and display events | `cdmw/ui/display_scaling.py`: `fit_window_to_screen()`, `DisplayScalingPolicy` |
| Shell screen-change and resize policy | `cdmw/ui/shell/responsiveness_controller.py`: `_apply_responsive_resize_adjustments()`, `_handle_responsive_screen_changed()` |
| Policy installation | `cdmw/ui/shell/startup_restore.py`, `cdmw/ui/shell/app_startup.py` |
| Optional embedded child sizing | `cdmw/ui/mesh_editor/rust_host.py`: `_sync_child_geometry()`, `event()` |
| Existing geometry coverage | `tests/test_display_scaling.py` |
| Existing Rust host coverage | `tests/test_mesh_rust_embedding.py` |
| Documentation | `cdmw/ui/shell/README.md`, the relevant section of `docs/test-matrix.md`, and `CHANGELOG.md` |

## Required implementation tasks

### WMDPI-01: Confirm the starting state and ownership

- [ ] **WMDPI-01 complete:** Current source, prior evidence, task ownership, and the validation scope are recorded.

Work:

- Read current repository instructions and Git status. Preserve other agents' changes.
- Create or reuse the shared `progress.md` before implementation.
- Confirm that the owning code still matches the recorded findings. If it has changed, update the baseline and plan before implementing a stale proposal.
- Reuse passing evidence on unchanged code. Repeat checks only when the relevant source changed or a matched before/after comparison needs a new baseline.
- Identify the exact source revision and, for any later live check, the executable being exercised. Do not assume that the running executable matches the source tree.

Acceptance:

- The next edit and its owning files are clear.
- The two reproduced problems are still relevant, or any superseding change is documented.
- Earlier investigation results remain clearly separate from proof of a fix.

Completion evidence: Pending.

### WMDPI-02: Defer the actual geometry settings update

- [ ] **WMDPI-02 complete:** Geometry-driven settings updates are coalesced before `QSettings.setValue()`, with reliable final-state saving.

Work:

- Retain the latest pending geometry or a safe reference to the affected window in memory.
- Move the geometry `setValue()` operation out of each Move/Resize callback.
- Save the final geometry once movement settles. Integrate the active-drag state from WMDPI-03 so a pause with the drag still active does not trigger a geometry write.
- Flush pending geometry on the relevant close, hide, and orderly-shutdown paths before the window is destroyed.
- Preserve maximized/normal geometry and the existing minimized-window policy.
- Keep QSettings' normal synchronization and atomic-saving behavior intact. Apply the change at the window-geometry owner rather than suppressing settings events across the application.

Acceptance:

- The isolated 20-move scenario produces no geometry `setValue()` calls or geometry-driven INI changes during the burst.
- After settling, there is one final geometry persistence update rather than one update per movement event.
- A native drag that remains active beyond the timer delay still produces no geometry-driven file updates.
- Closing before the delay expires saves the latest valid geometry.
- Restore behavior, detached-window keys, and unrelated settings updates continue to work.

Completion evidence: Pending.

### WMDPI-03: Track active native move and resize operations

- [ ] **WMDPI-03 complete:** The relevant policies can distinguish an active user drag from a settled window.

Work:

- Observe Windows' native move/resize start and end notifications for the relevant top-level windows.
- Keep state per window so one dragged window does not unnecessarily suspend unrelated windows.
- Defer pending custom geometry fitting and geometry persistence while a native move or resize operation is active.
- Queue final work after native event processing has settled, using the final geometry.
- Handle cancellation, closing, and destroyed windows so no stale active-drag state survives.
- Continue normal Qt event processing. Do not consume or replace native DPI handling, discard the suggested DPI rectangle, or disable per-monitor scaling.
- Retain an appropriate settled-event path for programmatic resizing and platforms without these Windows messages.

Acceptance:

- Move-only continuation beyond both the 120 ms and 260 ms delays does not trigger custom repositioning.
- Holding a drag active beyond the timer delay does not trigger custom fitting or geometry persistence.
- Releasing or cancelling a drag clears the active state and allows the necessary final work.
- Later programmatic window changes still receive appropriate handling.
- Qt's DPI events continue through their normal path.

Completion evidence: Pending.

### WMDPI-04: Make screen fitting less aggressive and avoid duplicate corrections

- [ ] **WMDPI-04 complete:** A usable window can cross or span monitors without CDMW pulling it into one monitor during movement.

Work:

- Reconcile the display-policy and shell fitting paths so they do not apply competing or duplicate corrective moves.
- After movement ends, perform at most one necessary corrective fit for the settled state.
- Allow a usable window to span monitors. Do not require full-frame containment on every routine layout event.
- Keep recovery for inaccessible windows and monitor removal.
- Preserve small-screen overflow scrolling, reachable dialog actions, existing preview parents, and correct maximize/fullscreen/restore behavior.
- Keep the existing inexpensive shell resize path.

Acceptance:

- The straddling-window reproduction no longer produces the application-forced 285-pixel correction while movement continues.
- Ordinary movement and resizing do not cause a fight between native geometry and custom fitting.
- Windows that genuinely need recovery remain reachable.
- Existing oversized-dialog, text-readability, overflow, and parent-identity checks pass.
- No new application-wide theme, font, or splitter rebuild is introduced during a drag.

Completion evidence: Pending.

### WMDPI-05: Add focused behavioral regression coverage

- [ ] **WMDPI-05 complete:** Focused tests cover the corrected persistence and fitting behavior and preserve the affected contracts.

Work:

- Add targeted geometry-persistence coverage, for example in a new `tests/test_layout_persistence.py`. No dedicated test file for that owner was found during planning.
- Extend `tests/test_display_scaling.py` for move-only continuation, active drag duration, cancellation, final fitting, and window reachability.
- Verify settings-file behavior with a temporary INI and the actual Qt event loop. Counting only explicit `sync()` calls is insufficient.
- Keep test settings, captures, and caches isolated from the user's configuration and game data.
- If shared signals, callable contracts, or identifiers change, inspect their actual consumers and test those affected contracts.

Acceptance:

- Tests fail for the original behavior and pass for the implemented behavior.
- Coverage includes close-before-debounce, active-drag pauses, repeated monitor notifications, and safe final-state handling.
- Existing focused geometry checks pass.
- Tests exercise behavior rather than only matching source strings.
- Headless results are reported as headless results.

Completion evidence: Pending.

### WMDPI-06: Verify physical monitor movement

- [ ] **WMDPI-06 complete:** A live monitor check confirms the user-visible result on the recorded build and setup.

Run this task only within the visible-UI and renderer scope authorized in the active session. Planning alone does not authorize launching the application, starting native renderers, loading game data, or packaging a build. If required scope or hardware is unavailable, record the exact gap here and leave this item unchecked.

Record the executable/source identity, relevant monitor layout, scaling, and active tool. Compare equivalent workloads.

| Scenario | Required observation |
|---|---|
| Drag within one monitor | Smooth following, no geometry-driven settings updates during the active drag |
| Cross monitors with equal scaling | No custom pullback, snapping, or repeated corrections |
| Cross monitors with different scaling | Correct DPI response, readable text, and stable cursor/window relationship |
| Pause while holding the title bar, then continue | No delayed custom fitting or saving during the active operation |
| Resize, maximize, restore, and cancel movement | Correct final geometry and no stuck drag state |
| Reachable window spanning monitors | Position is respected |
| Oversized dialog or disconnected monitor | Controls and recovery remain usable |
| Mesh Editor closed and open | Main-window improvements hold; embedded sizing remains correct when the authorized editor check runs |

Acceptance:

- Repeated physical drags no longer show the reported resistance or avoidable stutter from these paths.
- Available timing/call-count evidence is recorded without presenting the isolated baseline as a full-application benchmark.
- Any remaining stall is recorded with its context and owning path, rather than hidden by a passing geometry test.
- No untested monitor or native-renderer scenario is described as verified.

Completion evidence: Pending.

### WMDPI-07: Update documentation and complete the handoff

- [ ] **WMDPI-07 complete:** Required work and verification are recorded consistently in this plan and the shared progress list.

Work:

- Update the nearest owning documentation for changed geometry and persistence behavior.
- Add a concise user-visible `Unreleased` fix entry in the existing changelog structure when the fix is implemented.
- Update the test matrix only if its relevant commands or coverage description changed.
- Inspect the task-scoped diff and preserve unrelated changes.
- Record the outcome, exact focused checks, live-check status, any remaining limitation, and the optional task's disposition.
- Verify that each completed required task has one matching shared-progress entry.
- Follow the repository's local commit rules for safely isolated changes. Do not push, package, release, or change versions without the required scope.

Acceptance:

- Required completed items have matching `[x]` checkboxes and progress entries.
- Unfinished or blocked items remain unchecked.
- The overall status is only `Complete` when every required task has passed. If implementation passes but live validation is outstanding, use `Implemented; live validation pending`.
- Other agents' progress entries and work remain intact.

Completion evidence: Pending.

## Optional improvement

### WMDPI-O1: Deduplicate embedded Rust child geometry requests

- [ ] **WMDPI-O1 implemented and verified.**

Disposition: Deferred until the two main issues are addressed and measurement shows useful remaining resize traffic. This item is not required for the main goal.

If pursued:

- Measure duplicate requests before changing behavior.
- Skip a request only when the effective native client dimensions and relevant child state are unchanged.
- Invalidate cached geometry on child replacement, reparenting, relevant DPI changes, and visibility transitions.
- Preserve asynchronous positioning and visibility calls.
- Preserve the post-layout correction for prewarmed hosts; do not remove the second synchronization solely because it appears redundant.
- Use the affected cases in `tests/test_mesh_rust_embedding.py`, including `test_host_resizes_hides_focuses_and_reparents_the_owned_child` and `test_prewarmed_host_uses_native_size_settled_after_show_and_resize`.
- Record a decision to defer as a decision, not as an implemented optimization.

Completion evidence: Pending.

## Validation routing and scope

Use the project virtual environment, current `docs/test-matrix.md`, and unique test directories under the system temporary directory. Reuse passing checks on an unchanged tree. Run the exact affected tests, not broad gates merely because UI files changed.

An existing focused command, using a unique temporary directory:

```powershell
$windowReviewTemp = Join-Path $env:TEMP ("cdmw-window-review-" + [guid]::NewGuid().ToString("N"))
.\.venv\Scripts\python.exe -m pytest tests/test_display_scaling.py -p no:cacheprovider --basetemp=$windowReviewTemp
```

Add the new persistence test target once it exists. Add the affected Rust-host cases only if that path changes. Tests and timings from the initial investigation do not certify a later edited tree.

The task does not require changes to mesh formats, archives, game files, model loading, application-wide DPI settings, or native rendering architecture. Do not expand into those areas unless evidence and user scope justify it. Do not disable QSettings safety, discard saved layouts, remove accessibility/overflow behavior, or replace the renderer to hide the symptom.

## Reference material

- [Qt 6.11: QSettings synchronization](https://doc.qt.io/qt-6.11/qsettings.html#sync)
- [Windows: WM_ENTERSIZEMOVE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-entersizemove)
- [Windows: WM_EXITSIZEMOVE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-exitsizemove)
- [Windows: High DPI desktop development and DPI-transition pitfalls](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)
