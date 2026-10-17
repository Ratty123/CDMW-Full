# CDMW window movement and DPI smoothness plan

- Plan ID: `WMDPI`
- Created: 2026-10-17 (Europe/Stockholm)
- Status: Implemented; live validation pending.
- Project: `D:\CLAUDETEST\CDMW Full`
- Plan file: `beta-progress/window-move-dpi-smoothness-plan.md`
- Shared completion log: `beta-progress/progress.md`

## Goal

Make moving and resizing CDMW smooth, including moving between monitors with different scaling. Remove geometry-related settings-file updates during an active drag and prevent CDMW's custom screen-fitting logic from repositioning the window against the user's movement. Preserve readable controls, native DPI scaling, remembered window geometry, reachable dialogs, and embedded editor behavior.

The user authorized implementing this full plan and finishing the interrupted session. Source implementation and available isolated live Windows checks passed. Packaging, release/version changes, and unrelated native builds remain outside this task.

## Current handoff

- Completed: WMDPI-DOC-01, WMDPI-01 through WMDPI-05, WMDPI-08 and WMDPI-07.
- Current status: Native-widget isolation, focused checks, available 100%/150% physical-monitor scenarios, final review and documentation are complete. The scoped local WMDPI commit contains this checkpoint; implementation needs no further work for the accepted scope.
- Required validation gap: WMDPI-06 remains unchecked solely because the available displays have different scaling. A physical crossing between two equal-scaling monitors has not been verified. Do not change display settings or treat same-monitor movement as that missing case.
- Next action: When an equal-scaling display pair is available, repeat the required physical crossing with Mesh closed and open, record the actual source/helper identity, and then reassess WMDPI-06. No further implementation or optional optimization is queued by this handoff.
- Ownership: This session's root owns source edits, live input, validation, paired tracking updates and Git operations. Delegates provide read-only review. Other plans' source, localization, changelog and progress changes remain outside this commit.
- Resume identity: The interrupted work resumed on 2026-10-17 at the user's request from HEAD `622758398594b90484f0abce2126dccb9b2f8fb0` plus the preserved working changes. Final reports record that HEAD and the exact owner hashes below.
- Required tasks: WMDPI-01 through WMDPI-08. WMDPI-08 was added from live evidence within the authorized smoothness goal.
- Optional task: WMDPI-O1 remains deferred. The measured improvement does not require child-geometry request deduplication, and the existing asynchronous and post-layout sizing behavior remains intact.

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

- [x] **WMDPI-01 complete:** Current source, prior evidence, task ownership, and the validation scope are recorded.

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

Completion evidence: 2026-10-17. Clean starting worktree at `b99e5c267f74e135410b9a627df8abc9a05d920d`, branch `RR/independent-item-packages`. Current persistence, display fitting, and shared-sync source hashes match the recorded investigation; the 20-move settings-write and mid-move correction findings remain applicable. Root and global AGENTS, the close-flush caller, focused tests, test matrix, and local `cdmw-async-ui-work` skill were read. File ownership is claimed above. Existing unchanged baseline tests were reused. The user authorized implementation of this full plan; live executable and monitor identity will be recorded separately by WMDPI-06.

### WMDPI-02: Defer the actual geometry settings update

- [x] **WMDPI-02 complete:** Geometry-driven settings updates are coalesced before `QSettings.setValue()`, with reliable final-state saving.

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

Completion evidence: 2026-10-17. Added per-window in-memory snapshots and a 650 ms settle delay before the actual geometry settings mutation. Active native-interaction holds suspend the save; other windows can settle independently. Close/hide, immediate and deferred destruction, policy replacement, and orderly shutdown preserve the final state, including the latest pre-minimize snapshot. The new 20-move test first failed against the original source with 20 geometry writes. After the fix, `tests/test_layout_persistence.py` passed all 13 cases, including zero geometry writes and zero INI changes during the burst, one settled save, retained existing keys, and unrelated settings updates. Combined with the tracker cases after its handle-lifecycle update: 29 passed in 2.51 seconds, offscreen Qt 6.11.0. Live monitor proof remains WMDPI-06.

### WMDPI-03: Track active native move and resize operations

- [x] **WMDPI-03 complete:** The relevant policies can distinguish an active user drag from a settled window.

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

Completion evidence: 2026-10-17. Added the shared per-window Windows interaction tracker. It observes enter/exit/cancel messages without consuming native or DPI messages, keeps the hold through queued completion, and handles restarted operations, hidden/recreated handles, ignored close events, destruction, and application reuse. Persistence and fitting both defer while the hold is active. All 16 tracker cases pass, including real ctypes MSG layouts and Shiboken pointer decoding. The integrated three-file suite passes 59 cases in 3.65 seconds with offscreen Qt 6.11.0. Physical input evidence is recorded separately under WMDPI-06.

### WMDPI-04: Make screen fitting less aggressive and avoid duplicate corrections

- [x] **WMDPI-04 complete:** A usable window can cross or span monitors without CDMW pulling it into one monitor during movement.

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

Completion evidence: 2026-10-17. Display fitting now owns the shared per-window 120 ms scheduler; shell callbacks request it instead of applying competing geometry corrections. Ordinary move events postpone pending fits and native holds prevent direct and scheduled fitting. Reachable partial placements and spans over the actual monitor work-area union are preserved, while missing captions, tiny visible slivers, disconnected positions, and substantial screen gaps still trigger recovery. DPI, constraints, window state, geometry, and work-area signatures suppress unchanged repeats. No theme/font/splitter rebuild was added. A fresh red check against the original fitting helper pulled an actively held window 262 logical pixels sideways; the new hold, continuation, span, overflow/parent, text, and recovery cases all pass. All 30 display cases pass in the 59-case integrated suite.

### WMDPI-05: Add focused behavioral regression coverage

- [x] **WMDPI-05 complete:** Focused tests cover the corrected persistence and fitting behavior and preserve the affected contracts.

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

Completion evidence: 2026-10-17. Added tests/test_layout_persistence.py (13 cases) and tests/test_window_interaction.py (16 cases), and extended tests/test_display_scaling.py from 13 to 30 cases. The actual temporary INI/event-loop test first failed with 20 geometry writes on the original persistence path and now produces zero burst writes/file changes and one settled update. Original direct fitting also failed the active-hold red check. The final combined run on the implemented files passed 59 tests in 3.65 seconds, exit 0, using the project virtual environment, QT_QPA_PLATFORM=offscreen, disabled pytest cache, and a unique system-temporary basetemp. These are behavioral headless checks, not physical monitor or packaged-build certification.

### WMDPI-08: Prevent redundant DPI traversal through incidental native widgets

- [x] **WMDPI-08 complete:** Only intended native surfaces and overlays acquire native child windows, without promoting ordinary sibling widgets.

This required follow-up was discovered during live validation after the original geometry fixes passed. It addresses the same reported window-movement stall.

Investigation evidence: the two measured 525.594/533.306 ms DPI gaps each consumed 484.375 ms of UI-thread CPU. A transparent event observer recorded 18,738 DevicePixelRatioChange and 18,450 ScreenChangeInternal deliveries, while the shell contained 1,003 widgets, only 96 visible. Non-forcing inspection found 72 native child widgets. Qt 6.11 source confirms recursive screen/DPI delivery from each QWidgetWindow and automatic native-sibling promotion when WA_NativeWindow is requested. This duplicated traversal through native ancestors and their descendants.

An isolated constructor-order change alone retained 72 native children and a 549.335 ms peak. Setting AA_DontCreateNativeWidgetSiblings reduced that to two intended preview native widgets, 2,040 DPR/2,028 screen deliveries, and an 88.125 ms peak in the combined experiment. The attribute-only control also passed native functional gates with a 95.610 ms peak. These experiments identify the smallest effective policy; they are not yet a shipped-source or clipping/stacking pass.

Work:

- Enable native-sibling isolation on Windows before the shell creates embedded surfaces. Keep Qt's normal per-monitor DPI handling and suggested geometry.
- Set DontCreateNativeAncestors before requesting each native host, including construction under already-created parents.
- Preserve native renderer surfaces, stable QWidget parent ownership, and asynchronous geometry/visibility handling.
- Explicitly retain native stacking for preview status/resident overlays and the theme-change overlay where they previously relied on incidental sibling promotion.
- Add focused behavior checks for native host creation, ordinary sibling/ancestor isolation, hide/show, and reparenting.
- Verify actual native clipping/overlay behavior and repeat the unprofiled main-window movement comparison. Report renderer-preflight and hardware gaps separately.

Acceptance:

- Ordinary siblings and intermediate parents remain non-native when a preview or Mesh host is created and shown.
- Intended host/overlay windows remain available, properly positioned, and owned by the same widget hierarchy.
- Native event amplification and the measured half-second closed-shell pause are materially reduced in the final source-tree run.
- The existing native-child sizing/cleanup checks and the affected geometry tests pass.
- No renderer replacement, DPI-awareness override, event suppression, or settings safety reduction is introduced.

Completion evidence: 2026-10-17. The final source enables Windows native-sibling isolation before embedded surfaces are created and requests DontCreateNativeAncestors before each intended native host. Preview status/resident layers, Mesh pages/surface, and the theme overlay explicitly retain the native stacking they need.

The final `ensure_native_host_clipping()` observer keeps ordinary and scrolling ancestors non-native. It intersects the host's original mask with ancestor bounds, follows scroll/layout/reparent/handle/DPI changes, reapplies native masks after pixel-scale changes, and restores the original mask when clipping is no longer needed. A nonempty region outside the host clips fully scrolled-out content without changing visibility or child ownership. If alien scrolling content moves without moving its native descendant, only the Qt host window's position is refreshed in the existing native parent's logical coordinates. QWidget geometry, renderer child sizing, asynchronous visibility and ownership remain with their existing owners. Position transitions are masked before moving to avoid exposed edges.

The interrupted full-ancestor approach and a later three-boundary approach were rejected. Promoting only the viewport lost scroll position and leaked content after hide/show. Retaining a native scroll frame, viewport and content after real overflow restored a 405.824 ms Mesh DPI heartbeat gap even though clipping passed. The final masks/position implementation retained eight native child widgets before and after a genuine 180 px root overflow and measured a 156.979 ms maximum gap in that scenario. It does not leave a native ancestor chain behind after scrolling.

All 21 isolation cases are verified: 20 offscreen and one native-detach lifecycle case on Windows. The affected existing Mesh embedding/reparent suite adds 24 passing cases. Coverage includes nested/late overflow, fully clipped edges and recovery, preserved original masks, top-level detach, reparenting, stable handles and QWidget geometry, and handle/DPR mask reapplication. The remaining 60 geometry/tracker/persistence cases also pass; exact routing and run results are below.

Final source-tree physical runs reduced the observed maximum heartbeat gaps to 80.926 ms with Mesh closed and 123.987 ms with Mesh open. Non-forcing inventory found five and eight native child widgets respectively, compared with the original 72-child shell inventory. Actual native clipping, overlay stacking, hide/show, child dimensions and shutdown passed on the available 100%/150% displays. These are local observations of the recorded workloads, not an FPS measurement or a universal latency bound. The exact final-source evidence and remaining hardware gap are recorded under WMDPI-06.

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

Historical live checkpoint before native-widget isolation: 2026-10-17 (Europe/Stockholm). At this checkpoint WMDPI-06 remained unchecked because functional passes still showed a real DPI-transition freeze. The final-source result below supersedes that stall/helper blocker.

- Source-tree executable: `D:\CLAUDETEST\CDMW Full\.venv\Scripts\python.exe`, PySide6/Qt 6.11.0, HEAD `d4b38e5082d4f9b4b4cce14f9ee2ecdb37994aaf` plus the recorded working changes. The four implemented owner hashes were unchanged throughout these runs and are recorded in each machine-local report. This does not certify a packaged build.
- Actual monitors: left XV240YP, 1920 x 1080 physical at 100%; primary MAG341COLED, 3440 x 1440 physical at 150%. Qt logical work areas were `[-1920, 0, 1920, 1032]` and `[0, 0, 2293, 912]`. No display settings were changed.
- Native movement, held-titlebar pauses, resize, and Escape cancellation passed in the owned real shell. Three interaction starts and three queued finishes were observed; active holds produced zero geometry settings mutations and zero custom fitting calls. The temporary INI stayed unchanged during the held operations. Maximize/restore and a reachable spanning position behaved correctly.
- Closed-editor reports `%TEMP%\cdmw-window-dpi-live-paj7l7jq\native-window-report.json` and `%TEMP%\cdmw-window-dpi-live-qu1zht1m\native-window-report.json` passed native functional gates. The latter observed a maximum UI heartbeat gap of 509.205 ms. An earlier unprofiled closed-editor run observed 490.694 ms. The physical trajectory independently showed unchanged HWND rectangles while cursor input continued, with stall lower bounds of approximately 334 ms and 483 ms in the profiled run. These are real frame stalls, not an FPS measurement.
- A minimal Qt window using the same theme and new policies crossed the same monitors with a maximum heartbeat gap of 38.994 ms and no gap above 60 ms. The full-shell pause is therefore still being investigated.
- The full-shell text protection work totaled 22.324 ms over 1,045 calls, with a maximum individual call of 0.139 ms. A corrected MainWindow event subclass observed 70 relevant native-phase events, with none lasting 5 ms. These measurements do not attribute the remaining pause to a specific native Qt function; broader event and UI-thread sampling is the next check.
- Mesh Editor native report `%TEMP%\cdmw-window-dpi-live-zauovxzv\native-window-report.json` passed production renderer preflight, accepted hello/ready, native hold and placement checks, and physical embedded host/child sizing. The synthetic quad used no game or archive data. Matched dimensions were 1353 x 980 initially, 1422 x 1025 after movement/resize, and 954 x 700 on the 100% screen. Its maximum heartbeat gap was 918.551 ms, so this is functional embedding evidence, not a smoothness pass or a general editor-layout certification.
- The successful Mesh run used `native\rust_mesh_editor\build\Release\cdmw_mesh_lab.exe`, 18,064,384 bytes, renderer `wgpu_d3d12_rust`, SHA-256 `ec9710cbedbcd4949a593374ccda749d4e862ca95031b1ab716d93a70b52e6a8`. A later run stopped at the changed production contract before input because that helper lacks the newly required binary mesh document capabilities. The preflight was not bypassed and no native rebuild was performed.
- Completed native runs confirmed released synthetic buttons, an inactive native hold, a joined input worker, and normal shell shutdown with no owned worker threads or renderer processes remaining. Owned-window captures were reviewed; embedded dimensions are established separately from editor content/layout behavior.

### Final-source live checkpoint, 2026-10-17

The measured native-widget amplification is fixed in the source under review. The available physical and native-layer scenarios below passed; WMDPI-06 remains unchecked only for the required equal-scaling monitor crossing.

- Source-tree executable: `D:\CLAUDETEST\CDMW Full\.venv\Scripts\python.exe`, PySide6/Qt 6.11.0, HEAD `622758398594b90484f0abce2126dccb9b2f8fb0` plus the final owner changes; each report records it and the owner SHA-256 values in the table below. This certifies the exercised source tree, not a packaged build.
- Actual monitors: left XV240Y P, 1920 x 1080 physical at 100%, Qt geometry `[-1920, 0, 1920, 1080]`, work area `[-1920, 0, 1920, 1032]`; primary MAG 341C OLED, 3440 x 1440 physical at 150%, Qt geometry `[0, 0, 2293, 960]`, work area `[0, 0, 2293, 912]`. No display settings changed.
- Production Mesh helper: `native\rust_mesh_editor\build\Release\cdmw_mesh_lab.exe`, 18,234,880 bytes, SHA-256 `b9772dfc50a4a4d59ef9e0bdac96bdff95e07351260ce132e81993112007db04`, renderer `wgpu_d3d12_rust`, authoring `cdmw_rust_mesh_0.1`. Production package/preflight, accepted hello and ready passed. The helper mismatch from the historical checkpoint is resolved. The fixture uses a synthetic quad and no game/archive data.
- Both physical runs observed three native enter/exit pairs and three tracker starts/finishes, with DPI transitions to 96 and 144. Same-monitor movement, crossing to the secondary display and back, 0.85-second held pauses, resize and Escape cancellation passed. Active dragging produced zero application geometry writes and zero custom fitting calls. The temporary INI hash stayed unchanged through held operations, then changed with the settled final geometry save.
- Maximize/restore returned to the same normal geometry. A reachable spanning placement `[-330, 100, 1166, 780]` was respected. Mesh host/child dimensions matched at both scales, including 1353 x 980 initially, 1422 x 1025 after movement/resize, 3113 x 1233 maximized, and 954 x 700 at the later 100% placement. Native handles and renderer ownership stayed stable.
- The final Mesh programmatic supplement exercised nine real-monitor placements after 180 px root ToolContentStack overflow and recovery to zero scrollbar maximum. It retained eight native children before and after overflow. Native theme-overlay hit tests above the actual renderer and host hide/show passed at both scales.
- Preview clipping, status and resident-banner stacking, scrolling, fully scrolled-out hit-test exclusion, hide/show, late overflow and recovery passed at both scales using the real Preview host and an owned Win32 STATIC child test surface. This is a native-host clipping check, not a second production renderer or general editor-layout certification. All scrolling ancestors stayed non-native, and the host QWidget geometry remained `[36, 40, 820, 540]` while the native position mapped to its correct parent.
- A disconnected synthetic dialog sized 3400 x 2100 recovered to `[8, 8, 2277, 896]` with scrolling, retained original content and a reachable control. This tests recovery without disconnecting hardware.
- All four final reports have no errors and show normal close finalization with no owned running threads or renderer processes. Physical runs also show joined input workers, cleared native-interaction state, and released owned button/Escape input. Final Mesh/Preview clipping and overlay captures and the physical 100% capture were reviewed.

| Final-source scenario | Maximum UI heartbeat gap | Machine-local report under `%TEMP%` |
|---|---:|---|
| Physical movement, Mesh closed | 80.926100 ms | `cdmw-window-dpi-live-dwi6h284\native-window-report.json` |
| Physical movement, Mesh open | 123.986700 ms | `cdmw-window-dpi-live-8448u5r_\native-window-report.json` |
| Mesh monitor placements and native layers after real root overflow | 156.979000 ms | `cdmw-window-dpi-live-j5k58ofa\programmatic-window-report.json` |
| Closed-Mesh monitor placements and Preview native layers | 109.424200 ms | `cdmw-window-dpi-live-wbgo430z\programmatic-window-report.json` |

The historical physical maxima of 509.205 ms closed and 918.551 ms open provide context for the earlier symptom. They used an earlier source/helper state; this is not a controlled cross-version benchmark or a guarantee that no pause can occur. The final programmatic results are separate from physical drag measurements.

The local runners are `workspace/tmp/wmdpi-completion-20261017/run_native_shell_probe.py` (without arguments and with `--mesh`) and `run_programmatic_shell_probe.py` (with `--layers`, and with `--mesh --layers --after-overflow`). Inputs, fixtures, captures and reports remain machine-local and are not committed. The Mesh supplement's old `late_overflow.promoted_after_layout` field name means that clipping refreshed; its actual native-boundary fields are null. The final closed supplement uses the corrected `clipping_refreshed_after_layout` name.

| Final owner | SHA-256 recorded in final reports |
|---|---|
| `cdmw/ui/window_interaction.py` | `9080214cf5cf0e9b98019e785520e0367cbba8be40eca405e45254f3c2f01bac` |
| `cdmw/ui/layout_persistence.py` | `0590dcdf7ea73984d9bc71d5023b8bcb8e849c467554fc45c6590f60d8ecebea` |
| `cdmw/ui/display_scaling.py` | `a900384279aac09b87e9232ad9b1e1145633ea232f1630cd908c71364777a601` |
| `cdmw/ui/shell/responsiveness_controller.py` | `9a9334f0c2d2fca5a0ff83715155b765c839dab437328efcb8a1c4b7142dac21` |
| `cdmw/ui/preview/dotnet_host.py` | `66c3803ecccc571f213086f3820ee8fbcf68da3b21af868c9eb73abec0089725` |
| `cdmw/ui/mesh_editor/rust_host.py` | `1f8cd2407dc663daf9b44f9b1338e630236f8e213d8862f14b6d44a28062ab0f` |
| `cdmw/ui/native_window_clipping.py` | `95edc0e1c19f6b44609faeffb43361a6414caff77ad4dc1ddfcf922bc581740a` |
| `cdmw/ui/preview/dotnet_host_lifecycle.py` | `178ccbcf001c64f398dbcbbc0d1a244d6fb1f86ffada12157ceadcf2710d0dc8` |
| `cdmw/ui/mesh_editor/tab_dotnet_lifecycle.py` | `850065d33a676c6102f47b466c3cdc40f9e036b2b5b774b9721e42de83fa4b30` |
| `cdmw/ui/shell/theme_overlay.py` | `debdb709d010e63dcfd91014d7f3b097b445c5e30df46fca08c349e87491a6b8` |

Post-run review removed exactly one trailing blank line from `cdmw/ui/display_scaling.py` and `tests/test_display_scaling.py`. Their parsed Python syntax trees are unchanged, and appending that one line reconstructs each tested SHA-256 exactly. The final display owner hash is `7de5c35409f57fc50f5f66ea769f3150c3940e9980ab71022135c9c23813d878`; the final display-test hash is `9d78e731b5c708bb05c6f349cf1f9490f1af4c16b47485ec30d4cc33a7e9da7a`. The other nine production owner hashes still match every final report. This whitespace cleanup does not require repeating the physical runs.

Remaining required validation: a physical crossing between two monitors at the same scaling, with Mesh closed and open. The present setup has only 100% and 150% displays. Same-monitor dragging and the passing focused tests do not substitute for that crossing. No remaining helper mismatch or reproduced half-second DPI stall blocks this source checkpoint.

### WMDPI-07: Update documentation and complete the handoff

- [x] **WMDPI-07 complete:** Required work and verification are recorded consistently in this plan and the shared progress list.

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

Completion evidence: 2026-10-17. Root reviewed the changed geometry, interaction, persistence, native-host clipping/stacking and lifecycle contracts, the affected regression checks, the final report-to-source identities, and the owned-window captures. Read-only delegates reviewed lifecycle safeguards and the validation-status boundary; root owns the final source and evidence review.

The shell README now documents geometry saving, shared fitting, native interaction holds, explicit native surfaces and mask-based clipping. The Unreleased fix describes the user-visible window/preview behavior. The relevant local test matrix is updated, with exact durable commands and the Qt offscreen lifecycle limitation also recorded in this plan. All 105 distinct focused cases and the available physical/native-layer outcomes are recorded above. The only post-run source/test edits remove two trailing blank lines, with exact-byte and parsed-syntax equivalence verified.

The plan and shared progress were reread and reconciled at the WMDPI-08 and WMDPI-07 checkpoints. Completed items have one matching progress entry. WMDPI-06 remains unchecked for the equal-scaling monitor pair; WMDPI-O1 remains deferred. Overall status is `Implemented; live validation pending`.

The task-scoped diff passed whitespace checks. The local WMDPI commit containing this checkpoint includes only the reviewed window/DPI source, tests, owning README, this plan, the WMDPI progress entries and the matching changelog fix. Shared files are staged by owned hunks; CDISO, localization and machine-local evidence are excluded. No push, packaging, release/version change or native build is part of this closure.

## Optional improvement

### WMDPI-O1: Deduplicate embedded Rust child geometry requests

- [ ] **WMDPI-O1 implemented and verified.**

Disposition: Deferred. Final-source movement and post-overflow evidence passed without deduplicating Rust child geometry requests. Further changes need evidence of useful remaining duplicate traffic; the current asynchronous positioning/visibility and queued post-layout size correction remain intact. This optional decision is not an implemented optimization and does not close the required equal-scaling hardware gap.

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

Final focused evidence covers 105 distinct tests: 104 passed offscreen and the remaining native-detach lifecycle test passed with the Windows Qt backend.

| Focused file | Distinct cases |
|---|---:|
| `tests/test_display_scaling.py` | 31 |
| `tests/test_window_interaction.py` | 16 |
| `tests/test_layout_persistence.py` | 13 |
| `tests/test_native_widget_isolation.py` | 21 |
| `tests/test_mesh_rust_embedding.py` | 13 |
| `tests/test_mesh_editor_host_window_reparent.py` | 11 |

Executed evidence: the five-file geometry/tracker/persistence/embedding/reparent run passed 84 cases in 5.55 seconds. Its 60 geometry/tracker/persistence cases have no behavior changes; the trailing-blank-line cleanup is documented above. After the final clipping changes, the isolation/embedding/reparent run passed 44 cases with one skip in 1.43 seconds. The skipped isolation test, `test_existing_host_mask_survives_clipping_recovery_and_top_level_detach`, separately passed on Windows in 0.42 seconds. This is 105 distinct passing cases, with overlapping host reruns counted once.

Qt 6.11's offscreen backend crashes during native-child detachment/teardown even in a standalone QWidget reproduction without CDMW imports. The one affected lifecycle test is explicitly skipped only on offscreen and is routed to Windows; the production lifecycle passed there. This does not claim that the Qt offscreen issue was fixed.

Repeat the exact targets using fresh temporary directories and restore the caller's Qt backend setting:

```powershell
$windowReviewQt = $env:QT_QPA_PLATFORM
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    $windowReviewTemp = Join-Path $env:TEMP ("cdmw-window-review-" + [guid]::NewGuid().ToString("N"))
    .\.venv\Scripts\python.exe -m pytest tests/test_display_scaling.py tests/test_window_interaction.py tests/test_layout_persistence.py tests/test_native_widget_isolation.py tests/test_mesh_rust_embedding.py tests/test_mesh_editor_host_window_reparent.py -q -p no:cacheprovider --basetemp=$windowReviewTemp
    if ($LASTEXITCODE -ne 0) { throw "Window/DPI focused checks failed" }

    $env:QT_QPA_PLATFORM = "windows"
    $windowReviewNativeTemp = Join-Path $env:TEMP ("cdmw-window-native-review-" + [guid]::NewGuid().ToString("N"))
    .\.venv\Scripts\python.exe -m pytest tests/test_native_widget_isolation.py::test_existing_host_mask_survives_clipping_recovery_and_top_level_detach -q -p no:cacheprovider --basetemp=$windowReviewNativeTemp
    if ($LASTEXITCODE -ne 0) { throw "Window/DPI native lifecycle check failed" }
}
finally {
    $env:QT_QPA_PLATFORM = $windowReviewQt
}
```

The relevant local `docs/test-matrix.md` commands and coverage were updated. That existing guide is ignored by `/docs/` and is not force-added to the task commit; the exact commands and evidence are preserved here. Automated widget checks do not certify physical DPI crossings or GPU behavior; use the separately recorded live evidence for those claims.

The task does not require changes to mesh formats, archives, game files, model loading, application-wide DPI settings, or native rendering architecture. Do not expand into those areas unless evidence and user scope justify it. Do not disable QSettings safety, discard saved layouts, remove accessibility/overflow behavior, or replace the renderer to hide the symptom.

## Reference material

- [Qt 6.11: QSettings synchronization](https://doc.qt.io/qt-6.11/qsettings.html#sync)
- [Windows: WM_ENTERSIZEMOVE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-entersizemove)
- [Windows: WM_EXITSIZEMOVE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-exitsizemove)
- [Windows: High DPI desktop development and DPI-transition pitfalls](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)
