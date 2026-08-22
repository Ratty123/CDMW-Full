# New Item Studio

Owns the New Item Studio tab: clone an equipment item into a brand-new one with
its own identity, model, icon, stats, shop placement and item groups, then write
it as a loose mod or install it.

`state.py` is the editable draft and the pure helpers (stat grid, spec from
draft). `controller.py` holds the draft, the read-only archive snapshot and the
last plan. Every plan is pinned to a draft revision: changing any plan input
invalidates it, and a worker result from an older revision is discarded. The
controller runs the snapshot, plan, export, install, the model import and
the placement build through `cdmw/workers/new_item_workers.py` on one owned
thread at a time. Mod-folder and icon-folder scans are part of that planning
worker, never UI callbacks. Shutdown requests cancellation and leaves live
threads discoverable to the shell close sweep; no New Item widget waits on its
own worker. The `panels_*.py` modules edit the draft and ask the
controller for facts; `tab.py` composes them, and forwards install to the shell.

The default Stats view labels ItemInfo values as raw game data and compares a
selected cell with the template and shipped range; arbitrary stats, flat values,
extra levels and separate enhancement rows stay under an experimental fold. One
draft change on that step is one rail refresh: every edit goes through the panel's
`_draft_changed` (refill the grid when its shape changed, then `invalidate_plan`),
the tab refreshes its summary from `plan_invalidated` alone, never from the tables'
own signals (Qt emits one per cell a refill writes), and the tables' signals are
blocked while they are filled. `build_context` is memoized per template on the
read-only snapshot, so a validation is set lookups, not a rebuild of the sets. The
Perks & Effects step keeps gameplay perks separate from visual-only
weapon effects. Four perks is the evidence-backed default cap, five to eight requires
an explicit experimental opt-in, and raw effect browsing, placement numbers, colour
and particle factors stay under Advanced. Reset actions clear the corresponding draft
authority, and the rail summarizes effective changes rather than UI mode.

The Model and icon step imports a model file itself: `model_import.py` reads it
the way the Model Library does (the scene import, the source's own textures),
`item_preview.py` shows it over the template in the resident viewport with the
gizmo (`PlacementScene`), a glow ticked on the step lights its parts in that
viewport live (`glow_preview_parameter_groups` in the materials service builds
the renderer's parameter groups from the same three values the plan will write,
re-sent whole after every package rebuild; un-ticking restores the import's own
emissive), and `ModelPlacement.build_transform()` turns the
placement into the static replacement's transform for the headless Builder import
(`build_placed_import`), whose result is what the plan writes. The viewport's
rotation convention (the helper's yaw/pitch/roll) and the pipeline's x-then-y-
then-z are the same matrix re-expressed, proven in
`tests/test_new_item_item_preview.py` and the studio tab tests.

UI code here never touches the archives: reading is the service's snapshot,
writing is `ArchiveMutationService` through the service's `install`, and the
loose export is built in a sibling staging directory and published only when
complete. DMM archive groups are readable as mod bases, so repeated exports
carry earlier items forward. Game overlays carry a CDMW ownership marker;
install, migration and removal ignore foreign numeric groups and roll back every
post-backup failure or cancellation. Temporary model extraction roots are
removed when their
import is replaced, discarded, fails, or the studio closes. Entry points: the tool tab
`new_item_studio` and the Item Finder's `Clone as new item...`; a ready Builder
result can still be handed in through the tab's `receive_imported_model`.

Related tests: `tests/test_new_item_studio_tab.py`.
