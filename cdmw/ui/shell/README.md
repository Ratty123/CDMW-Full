# UI Shell

Owns the main window shell, workspace layout, tab registry, actions, menus,
toolbar, status bar, settings/theme/language wiring, startup/close controllers,
activation handling, diagnostics, and app-level dialogs.

## Layout persistence

`cdmw.ui.layout_persistence` saves window/dialog geometry, splitter proportions
and interactive column widths through the shell's existing portable `.cfg`
settings. It covers late-created tools, detached windows, Placement & Animations,
and New Item's offscreen Qt workflow. Existing main/detached-window and
table-specific keys remain supported. New layouts use `ui/layout/v1`; splitter
directions have separate saved proportions. The existing **Remember splitter
sizes** preference applies to Qt panes and Rust Mesh Editor panel widths.

Splitter gestures and Rust resize actions save the chosen sizes; responsive
defaults and hiding a comparison pane do not replace them. Writes use the shared
settings debounce and flush at shutdown. Window geometry is constrained to the
current monitor's available area. Generic Qt dialogs need a stable `objectName`;
widget class/attribute names provide stable pane identities without translated
labels or runtime control IDs. Native New Item dialogs store logical client
coordinates, while its columns and splitters share the Qt workflow's settings.
Regression coverage lives in `test_ui_layout_persistence.py`,
`test_shell_layout_persistence.py`, `test_new_item_layout_persistence.py` and
`test_mesh_editor_layout_persistence.py` under `tests/`.

## Compact Workspace and navigation

`compact/` owns the restart-selected Compact Workspace presentation around the same
authoritative tool widgets. Compact is the first-run default; an existing Classic or
Compact choice remains authoritative. Compact mode hides the existing tab bars, routes
its rail through the shared activation path, reuses the existing actions and status
widgets, and never constructs a second tool/controller/worker tree. Its shared
application theme and category state are documented in
`docs/features/compact-workspace.md`. The shared Activity drawer checks tool-log content
without copying the complete document on tab activation or each appended line.

Repeated activation keeps its document connection; Copy still retrieves the full log,
and whitespace-only logs retain their empty-state and Copy/Clear behavior. Activity
history redraws are batched on a 40 ms timer while its page is visible; hidden drawers
and the Current Tool Log page do not rebuild the history text. Opening Activity
immediately catches up, Clear remains immediate, and Copy reads the current history even
before a scheduled redraw. All retained events and duplicate coalescing keep their
existing semantics.

Assets lists Browse Archives, Create New Item, Model Library, and Item Icons in that
order. The Compact navigation rail sizes to its labels, icons, and layout margins,
including room for a scrollbar, so it stays narrow without clipping larger fonts or
longer translations. Collapsing categories keeps that width stable. The shell navigation
arrow controls the app rail. Mesh Editor's own header chevrons independently collapse
its Tools and Inspector panels; floating and pinned tool settings are owned by the [Mesh
Editor](../mesh_editor/README.md).

### Lazy tool loading

Lazy tools reveal an indeterminate progress bar immediately, preload only Qt-free
data dependencies on a tracked low-priority thread, then import their UI module,
construct the widget, and apply presentation in separate GUI turns. Tool-specific
I/O remains in its owning workers, and shell shutdown retains both preload and
feature threads until native teardown completes. Translation and language-export
property inspection must not construct unopened lazy tools.
Navigation waits for a 75 ms settled selection before first-use preparation.
Leaving a tool pauses its queued GUI import, construction and presentation;
returning resumes the same preload and publishes once. Explicit hidden tool
handoffs still complete. This policy applies to both Classic and Compact
navigation and the shared lazy workflow containers.
Archive Browser's compact Select, Actions, and More Filters triggers retain their
existing routing while rendering normal, hover, pressed/open-menu, focus, and
disabled button states.

### Archive worker lifecycle

`archive_backend_client.py` owns the resident, bounded `QProcess` protocol and
nonblocking shutdown lifecycle for the independent full archive worker;
`archive_backend_resources.py` owns packaged and development worker discovery.
The standalone backend is the only scanner. The client validates protocol,
native ABI and index compatibility before dispatch. The catalogue service owns
one automatic retry per logical operation, including any session or query
reconstruction. Failure controls provide targeted Retry, Copy error report,
Details and Close. Background item-name failures leave archive rows usable.
See [Archive Browser recovery](../archive_browser/README.md#scanner-failures-and-recovery)
for timeout, cancellation and report limits.

## Shutdown and archive barriers

Shell close tracks `QThread` workers and parented `QProcess` helpers separately.
Windows startup requires a kill-on-close job before launching helpers. Closing
requests cooperative cancellation, stops remaining owned process trees after
eight seconds, and arms a separate 15-second process-exit watchdog. The watchdog
also covers interpreter teardown and is never rearmed by repeated close requests.
Archive patch, overlay, backup and restore transactions retain a shutdown barrier
through commit or rollback; new transactions are refused once closing starts.
The shell remains visible with a closing status while that barrier is held, then
closes normally or reaches the final cutoff. The game is explicitly allowed to
outlive CDMW. See `docs/runbooks/worker-lifecycle.md` for the ownership contract.

Shell startup also installs one application-owned cyclic garbage collector before
constructing tool widgets or starting their workers. Automatic Python collection
is disabled while Qt is alive: allocation in a worker must not destroy GUI-owned
Qt wrappers on that worker's thread. A GUI-thread timer checks allocation pressure
once per second, using generation thresholds or incremental collection on early
Python 3.14. Reference-count cleanup and explicit worker `deleteLater()` ownership are
unchanged. The previous automatic-GC state is restored when Qt destroys the
collector during application teardown, not at `aboutToQuit`.

## Ownership boundaries

Keep this package focused on application frame behavior. Feature tabs belong in
`cdmw/ui/<feature>/`; business coordination belongs in `cdmw/services/`; slow
work belongs in `cdmw/workers/`. `MainWindow` uses the shell-owned `WorkbenchWindow`;
shell and feature behavior uses ordinary methods on owning widgets and
controllers. There is no runtime provider registry or generated method manifest.

## In-app documentation

`Help > Documentation` is the app's wiki surface. It uses a hierarchical topic
tree, a generated all-topic index, multi-word relevance search with `Ctrl+K`,
article links, breadcrumbs, and back/forward history. English topic data in
`about_documentation_en.py` is the single source; all 14 built-in languages use
the shared localization catalog instead of maintaining separate translated
topic copies.

## Settings and display scaling

Settings font sizes are exact user preferences; responsive screen scaling may
compact spacing and control metrics, but it does not rewrite the chosen UI or
list font size. The five-page Settings navigation—Setup, General, Paths,
Performance, and Appearance—is a top-aligned, content-sized rail whose width
follows its translated labels instead of taking a fixed sidebar width and
full-window height.

`cdmw/ui/display_scaling.py` installs one application display policy for the shell,
late-created tools, and Qt dialogs. Text controls follow their font and translated
label metrics. The current tool has an overflow scroll area; inactive tools do
not impose their minimum size on it. Oversized separate windows fit the current
screen's available work area and retain reachable content in a scroll area.
Overflow wrapping happens once, preserving the central widget and nested preview
parents on subsequent resizes. Screen, work-area, and DPI changes refresh the
shell metrics once; ordinary resizing keeps the inexpensive path.

### Responsive feature layouts

Research and Textures action rows wrap, and Settings Performance cards switch
between one and two columns. Compact rail/status heights follow the font, and its
line icons rasterize at the requesting device pixel ratio. The Qt display matrix
and its scope are documented in `docs/test-matrix.md`.

## Themes and contrast

All 19 application themes use semantic palette roles for shared and feature-owned
chrome. Feature surfaces may retain intentional content colours only with an explicit
paired foreground; they must not pin buttons, fields, selection, warnings, editors, or
disabled text to a Graphite-era literal. Use `accent_text` on `accent`, and
`text_strong` on `accent_soft`; the two foregrounds are not interchangeable.

Shared Qt dropdowns use bounded, scrollable lists that open below the field when
space allows. Near the screen edge, the list can open above to keep choices visible.
This also applies to the reporting form's tool, action and setup menus.

Button text targets at least 4.5:1 contrast in normal, hover, pressed, checked, and
disabled states. `tests/test_theme_surface_coherence.py` applies every theme to real
Classic Placement, Mesh Editor, Archive Browser, New Item, and XML-editor surfaces and
guards new stylesheet/rich-text literals. It also checks painted button text in both
Classic and Compact. Compact's separate synthetic harness continues to cover the same
production widgets at its supported sizes.

## Focused checks

Related tests: `tests/test_shell_*.py`, architecture guards, and shell entries
under `tests/`.

`tests/test_shell_garbage_collection.py` checks native Qt cleanup under worker
allocation pressure, startup ownership, teardown and generation scheduling.
`tests/test_new_item_model_apply.py::test_apply_placement_collects_gui_cycles_without_stopping_worker`
covers the same ownership rule through Apply placement and its real Qt worker.
