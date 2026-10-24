# UI Shell

Owns the main window shell, workspace layout, tab registry, actions, menus,
toolbar, status bar, settings/theme/language wiring, startup/close controllers,
activation handling, diagnostics, and app-level dialogs.

## Layout persistence

`cdmw.ui.layout_persistence` saves window/dialog geometry, splitter proportions
and interactive column widths through the shell's existing portable `.cfg`
settings. Deferred column restoration is owned by its tree and is cancelled when
the tree is destroyed. It covers late-created tools, detached windows, Placement & Animations,
and New Item's offscreen Qt workflow. Existing main/detached-window and
table-specific keys remain supported. New layouts use `ui/layout/v1`; splitter
directions have separate saved proportions. The existing **Remember splitter
sizes** preference applies to Qt panes and Rust Mesh Editor panel widths.

Splitter gestures and Rust resize actions save the chosen sizes; responsive
defaults and hiding a comparison pane do not replace them. Writes use the shared
settings debounce and flush at shutdown. Window geometry has its own per-window
650 ms settle delay before calling `QSettings.setValue()`: delaying only
`sync()` would still allow Qt's event loop to rewrite the file during movement.
Native Windows move/resize operations suspend geometry saving even while the
user pauses with the title bar held. Each pending window keeps its latest valid
geometry in memory; another active window does not delay its save. Close, hide,
destruction, policy replacement, and orderly shutdown preserve pending geometry.
Minimizing retains the latest normal or maximized snapshot.

Generic Qt dialogs need a stable `objectName`;
widget class/attribute names provide stable pane identities without translated
labels or runtime control IDs. Native New Item dialogs store logical client
coordinates, while its columns and splitters share the Qt workflow's settings.
Saved-data coverage includes `test_settings_tab_flush_persistence.py` and
`test_profile_controller.py` under `tests/`. `test_layout_persistence.py`
exercises the actual Qt event loop and temporary INI file, including an active
drag, independent windows, final flushes, minimize/restore, and existing keys.

## Compact Workspace and navigation

`compact/` owns the restart-selected Compact Workspace presentation around the same
authoritative tool widgets. Compact is the first-run default; an existing Classic or
Compact choice remains authoritative. Compact mode hides the existing tab bars, routes
its rail through the shared activation path, reuses the existing actions and status
widgets, and never constructs a second tool/controller/worker tree. Its shared
application theme and category state are documented in
`docs/features/compact-workspace.md`. Current Tool Log has its own text layout so a
hidden writer or a differently sized Output pane cannot clip its final line. It
copies the source once when changing tools, then mirrors only changed text and
highlighting. Repeated activation keeps the existing binding.

New messages scroll to the bottom after layout settles, including messages written
while the drawer is closed. Reopening catches up immediately; older messages remain
readable between updates. Copy and Clear still use the original log, and whitespace-only
logs retain their empty-state and Copy/Clear behavior. Activity
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

`scripts/export_github_wiki.py --output <wiki-folder>` renders those same topics
and catalogues as 14 native-named GitHub Wiki manuals, a language index and
localized contents sidebars. Each manual opens with Home, keeps a folded contents
menu for narrow screens, and includes all 18 guides, stable section
anchors and labelled callouts. The exporter never pushes or changes repository
settings. `--check` compares the local
pages with their source. Keep generated Wiki pages in their separate checkout,
and review both documentation surfaces when a user-facing contract changes.
`--source-wiki <old-checkout> --replace-legacy` migrates the earlier per-guide layout
without regenerating prose. Obsolete generated filenames are removed only with
that explicit flag; unrelated files are retained. Do not add legacy redirect
pages, which would repopulate GitHub's global Pages list.
Translated manuals and their `_Sidebar.md` files share a locale folder so GitHub
selects the correct contents menu. Public manual URLs still use their native
page names. The Language link leads to the language index; sidebars list guides
instead of repeating the language choices.
The Wiki layout formats procedures as steps, emphasizes existing localized UI
controls, separates limitations into labelled callouts, and folds optional Mesh
Editor detail sections. It preserves the original translated sentences and
technical identifiers; incompatible source/translation block structures refuse
export. The in-app topics continue to own the wording.
Folded sections use localized blockquote labels because GitHub Wiki does not
process native alert markers inside HTML details blocks.

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
not impose their minimum size on it. Overflow wrapping happens once, preserving
the central widget and nested preview parents on subsequent resizes.

`cdmw/ui/window_interaction.py` tracks native Windows move/resize operations per
top-level window without consuming their messages or replacing Qt's DPI handling.
Custom fitting and geometry persistence stay deferred through pauses with the
mouse held. Queued completion handles cancellation and window/handle teardown
without letting an older callback release a newer interaction.

Shell and display events share one fitting scheduler with a 120 ms quiet interval
per window. Usable partial placements and spans over actual monitor work areas
remain where the user placed them. Missing captions, unusable positions, and
disconnected-screen geometry still recover to a reachable screen with scrolling
when needed. Monitor gaps are not counted as available screen space. Unchanged
geometry, constraints, window state, DPI, and work areas do not repeat a fit.
Screen and DPI notifications request this shared policy; ordinary shell resizing
keeps the inexpensive path without restoring splitters or reapplying the theme.

On Windows, the display policy enables `AA_DontCreateNativeWidgetSiblings` before
the shell constructs native hosts. Renderer hosts, their status/result surfaces,
and the theme overlay explicitly request native windows after disabling native
ancestor promotion. Ordinary controls and layout parents remain non-native.

`cdmw/ui/native_window_clipping.py` clips each native host to its ordinary and
scrolling ancestors with a host mask. A host-owned observer follows later layout,
scrolling, reparenting, handle and DPI changes; native-handle requests refresh
synchronously before embedding. Existing masks return when clipping is no longer
needed, and fully scrolled-out hosts retain their handles and visibility state.
The observer also corrects a stale Qt host position after an alien ancestor
moves, using the existing native parent's logical coordinates while preserving
QWidget geometry and ownership. Qt handles pixel conversion. Native layout
ancestors are unnecessary even after the root pane has overflowed, avoiding
repeated screen/DPR traversal through the tool stack. The renderer's existing
asynchronous child sizing and visibility paths remain with their owners.

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
disabled states. Theme appearance and layout across sizes require focused visual
inspection when those surfaces change; they are outside routine CI.

## Focused checks

Related tests: `tests/test_shell_app_startup.py`, `tests/test_shell_close_controller.py`
and `tests/test_workspace_ownership.py`.

`tests/test_new_item_model_apply.py::test_apply_placement_collects_gui_cycles_without_stopping_worker`
covers Qt ownership through Apply placement and its real worker.
