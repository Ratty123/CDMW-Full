# New Item Studio

Owns the New Item Studio tab: clone an equipment item into a brand-new one with
its own identity, model, icon, stats, shop placement and item groups, then write
it as a loose mod or install it.

`state.py` is the editable draft and the pure helpers (stat grid, spec from
draft). `controller.py` holds the draft, the read-only archive snapshot and the
last plan. Every plan is pinned to a draft revision: changing any plan input
invalidates it, and a worker result from an older revision is discarded. The
controller runs the snapshot, plan, export, install and model import through
`cdmw/workers/new_item_workers.py` on one owned task lane. The effect metadata
index has a separate cancellable lane, and the resident placement workspace owns
its serialized latest-wins package lane. Mod-folder and icon-folder scans are part of that planning
worker, never UI callbacks. Shutdown requests cancellation and leaves live
threads discoverable to the shell close sweep; no New Item widget waits on its
own worker. The `panels_*.py` modules edit the draft and ask the
controller for facts; `tab.py` composes them, and forwards install to the shell.
The Template panel commits an explicit mouse click immediately, while keyboard
row navigation keeps its 180 ms latest-row settle so holding an arrow key does
not rebuild every dependent step along the way. It mounts the same resident item
viewport used by Model & Placement, so a selected helmet, armour piece or weapon can
be orbited and zoomed before the workflow inherits it; moving to step 3 reparents that
live viewport without rebuilding its package or resetting its camera. Snapshot creation
reuses Archive Browser's published path, basename and extension indexes, and template
previews follow the existing bounded .NET/Vortice package-cache setting. A durable hit
is validated before archive decode or model preparation, so returning to a template does
not repeat either operation. Hidden Combat stats tables keep their data current but defer
Qt's content sizing until that workflow step is actually opened.
The Identity panel keeps item keys and model stems automatic until **Manual** is
chosen; manual mode starts from the same collision-free allocation the planner
would make. Identifier editors enforce the domain's character and 64-character
limits, and per-field state icons point at the exact collision or format issue
reported in the existing Checks box.

The default Stats view labels ItemInfo values as raw game data and compares a
selected cell with the template and shipped range; arbitrary stats, flat values,
extra levels and separate enhancement rows stay under an experimental fold. One
draft change on that step is one workflow-state refresh: every edit goes through the panel's
`_draft_changed` (refill the grid when its shape changed, then `invalidate_plan`),
the tab refreshes its summary from `plan_invalidated` alone, never from the tables'
own signals (Qt emits one per cell a refill writes), and the tables' signals are
blocked while they are filled. `build_context` is memoized per template on the
read-only snapshot, so a validation is set lookups, not a rebuild of the sets. The
horizontal seven-step header replaces the old summary rail while retaining that
calculated state in per-step tooltips and accessibility text. Its footer keeps Back,
`Step N of 7` and Continue stable. Output keeps Build plan and its review in the
left column, with every write and install action in the right. Step 5 is a
non-scrolling full-height page with Perks and Effects tabs. The navigator is a
compact 46 px row; the outer pages do not
repeat numbered titles underneath it. Perks & Effects keeps gameplay perks separate
from visual-only effects. Perks are chosen through searchable Available and Selected
lists that grow with the workspace rather than a popup catalogue. Four perks is
the evidence-backed default cap and five to eight requires an explicit experimental
opt-in. Effect support is structural rather than equipment-name based: the service
dry-runs the real component graft against every prefab the item will own, accepts only
an all-target success, and never edits a shared borrowed prefab. The Effects tab uses
24 px virtualized table rows with neutral stem-derived names, separated numeric suffixes,
and compact Type and approximate Size columns; the exact stem stays searchable and
appears in selection details and tooltips instead of being repeated under every row. `No effect` is the
single empty-state row, so blank
compatibility and exact-stem labels do not repeat it. Selection, placement and look are staged; Apply publishes one draft
change, while Continue stays disabled and direct navigation offers Apply, Discard or
Stay. The reusable `EffectPlacementWorkspace` keeps one renderer resident, rebuilds
effect/look packages without resetting the camera, and retains old package files until
the correlated renderer acknowledgement. Effect, emitter, preset and spawn-mesh decoding
runs in that cancellable lane rather than in the selection callback; spawn meshes are
sampled directly to the 96 points the viewport uses instead of copying their full vertex
arrays. Reset actions clear the corresponding draft
authority, and the workflow summary reports effective changes rather than UI mode.
For an imported item, Effects always derives its placed preview from the live import
source before and after **Apply placement**, so its PBR rows are the same authority that
Model & Placement displays. The rebuilt PAC remains output authority but its borrowed template
material wrappers never replace the import's source materials in the placement viewport.
The current per-part Glow colour and strength are copied into those same rows when the
Effects package is built, and returning to the step refreshes changes made in Model & Placement.

The Model & Placement step is a fixed three-column workspace. A top-packed Model scroller
and always-visible Icon choices share the left column, Placement controls and pinned operation
status occupy the middle column, and the resident Preview owns the full-height right column.
That Preview is the exact frame prepared under Template rather than a second renderer or
package load.
The repeated Model / Placement / Icon tab strip is gone, so all three surfaces stay mounted at once. It imports a model file itself:
`model_import.py` reads it
the way the Model Library does (the scene import, the source's own textures),
and the same cancellable worker reads the template geometry and retains its bounds and
centroid for later re-fit. Weapon-family paths use the grip/heavy-end fit; armour,
accessories and other families keep a centred axis fit instead of being interpreted as
weapons.
`item_preview.py` publishes fitted geometry first, then upgrades a copied package with
canonical materials without restarting the renderer, re-exporting geometry or resetting
the camera. FBX conversion relinks an explicitly referenced missing image by exact basename
from the extracted package's nearby texture folders; the shared preview then supplements an
embedded base with clearly named Normal, AO, Roughness and Metallic maps without treating a
Thickness map as colour. A textureless exported material still keeps its authored
`TEXCOORD_0` channel instead of triggering an unnecessary auto-unwrap. Generated material
synthesis is deduplicated across identical submesh inputs.
Apply runs through the controller's cancellable progress lane; its spinner, current phase,
percentage when available and Cancel action remain live while conflicting placement edits
are disabled. Preview-loading text stays in that pinned operation bar while errors and
ready/capture messages remain below the viewport. Imported-material, Glow and
template-specific controls live with the model; alternate sheathed/holstered visuals
and inherited cloth/physics are hidden when the selected family cannot use them. The
viewport shows the model over the template with the gizmo (`PlacementScene`), a glow
ticked on the step lights its parts in that
viewport live (`glow_preview_parameter_groups` in the materials service builds
the renderer's parameter groups from the same three values the plan will write,
re-sent whole after every package rebuild; un-ticking restores the import's own
emissive), and `ModelPlacement.build_transform()` turns the
placement into the static replacement's transform for the headless Builder import
(`build_placed_import`), whose result is what the plan writes. The fit's baked source
origin is the shared preview/build anchor, so the gizmo stays on a model whose template
location is away from world zero and manual rotation/scale happens around that origin.
The viewport's
rotation convention (the helper's yaw/pitch/roll) and the pipeline's x-then-y-
then-z are the same matrix re-expressed, proven in
`tests/test_new_item_item_preview.py` and the studio tab tests.

Distribution and Output keep their long lists and plan summary in local scrollable
controls. Their compact heights avoid an outer page scroll at 1280×720 in the graphite
theme, while both controls expand again at 1600×900.

An imported source can be opened in the resident Mesh Editor from this step without
starting a second authoring process. It opens with Faces as the target while retaining
the neutral camera tool. Faces selected there can be moved from one source part into a
uniquely named appended submesh with **Create Part from Selection** in the Selection
panel. **Use Mesh Editor changes** drains pending
selection authority, captures a stable resident revision in the controller's worker,
rebuilds the source's textured preview, and invalidates any placement build made from
the previous geometry. The Mesh Editor session remains open so another revision can be
accepted without losing its history. New Item exposes the generated submesh name beside
the source materials for per-part Glow. This is face separation, not a knife/cap tool.

UI code here never touches the archives: reading is the service's snapshot,
writing is `ArchiveMutationService` through the service's `install`, and the
loose export is built in a sibling staging directory and published only when
complete. DMM archive groups are readable as mod bases, so repeated exports
carry earlier items forward. Game overlays carry a CDMW ownership marker;
install, migration and removal ignore foreign numeric groups and roll back every
post-backup failure or cancellation. Temporary model extraction roots are retired when
their import is replaced, discarded, fails, or the studio closes. Model, Effects and
Mesh Editor-accept workers lease the source while they read it; recursive removal runs
on a tracked cleanup worker only after those usages finish, so Discard cancels first and
never waits on filesystem cleanup in the UI thread. Entry points: the tool tab
`new_item_studio` and the Item Finder's `Clone as new item...`; a ready Builder
result can still be handed in through the tab's `receive_imported_model`.

Related tests: `tests/test_new_item_studio_tab.py`,
`tests/test_new_item_workflow_header.py`, `tests/test_new_item_effect_workspace.py`,
`tests/test_effect_placement_dialog.py`, `tests/test_new_item_effect_targets.py`, and
`tests/test_new_item_effect_proof.py`. The explicitly invoked real-corpus gate is
`tools/new_item_effect_proof.py report`; it keeps evidence under system temp and is not
part of an ordinary automated check.
