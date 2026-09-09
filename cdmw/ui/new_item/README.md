# Create New Item

Owns the Create New Item tab: clone an equipment item into a brand-new one with
its own identity, model, icon, stats, shop placement and item groups, then write
it as a loose mod or install it.

Before planning, the worker checks the snapshot's archive/index revisions and
refreshes changed sources, including overlays removed by a mod manager or Steam
verification. The draft remains intact. Overlay output defaults to Auto; the
optional folder number selects a free four-digit group. Both disk folders and
PAPGT reservations are respected, including optional game archives absent on disk.
A stale ownership marker cannot take over a mount record replaced by a game update.
Large overlay payload checksums use the existing cancellable native helper so
building a mod does not occupy the UI's Python interpreter.

The archive snapshot reads StatusInfo and EquipTypeInfo from either their legacy
`gamedata/binary__/client/bin/*.pabgb` / `*.pabgh` pairs or the newer
`gamedata/binarystaticinfo__/bin/*.staticinfobody` / `*.staticinfoheader` pairs.
A complete legacy pair takes precedence when both layouts exist; payloads and
headers are never mixed between layouts. These two tables supply names only.

`state.py` is the editable draft and the pure helpers (stat grid, spec from
draft). `controller.py` keeps the public controller, signals, draft and snapshot
state; `controller_preview_mixin.py`, `controller_model_mixin.py` and
`controller_task_mixin.py` own preview, model-authoring and worker-lifecycle
behavior without changing that public class. Every plan is pinned to a draft revision: changing any plan input
invalidates it, and a worker result from an older revision is discarded. The
controller runs the snapshot, plan, export, install and model import through
`cdmw/workers/new_item_workers.py` on one owned task lane. The effect metadata
index has a separate cancellable lane with CPU decoding in an owned child process,
so initial indexing does not compete for the UI interpreter. Effect payloads are
spooled one at a time, cancelled children stop before temporary-file cleanup, and
only complete results enter the existing metadata cache. The resident placement workspace owns
its serialized latest-wins package lane. Changing the effect, item or reference rig
cancels obsolete preparation before the selection debounce runs. Already queued
launches also reject stale generations, while the displayed scene remains usable.
Mod-folder and icon-folder scans are part of that planning
worker, never UI callbacks. Shutdown requests cancellation and leaves live
threads discoverable to the shell close sweep; no New Item widget waits on its
own worker. The `panels_*.py` modules edit the draft and ask the
controller for facts; `tab.py` composes them, and forwards install to the shell.
Queued effect-toolbar resize and post-install refresh callbacks are tied to
their owning widgets, so destroying the workspace cancels pending delivery.
The Template panel searches internal IDs, every available localized item name, equipment types and
item keys with Archive Browser's normalized terms, phrases, alternatives and exclusions.
Its result table separates the internal name, English item name, numeric key and equipment
type into four labelled columns. Column edges are session-resizable, clicking a heading
sorts the complete match set (including numeric key order), and scrolling near the bottom
adds the next 60 rows until every match is visible. Startup and later panel growth distribute
all available width across the columns instead of leaving an empty strip. An explicit mouse click commits immediately,
while keyboard row navigation keeps its 180 ms latest-row settle so holding an arrow key
does not rebuild every dependent step along the way. It mounts the same resident item
viewport used by Model & Placement, so a selected helmet, armour piece or weapon can
be orbited and zoomed before the workflow inherits it. Template handoffs search the
catalogue once and select the requested row. Search and results stay in the
left column while the preview receives the wider right column and the full working
height. The workflow summary remains the one selected-template status authority, so
Template does not repeat it in another group; its camera help follows the viewport
instead of separating the viewport from its heading. Every shared preview keeps the
current orbit, pan and zoom controls in a footer outside the native viewport. Initial
package framing survives helper startup and progressive texture state replay, while
later explicit camera commands remain authoritative. Single-template geometry uses the
same replacement-only layout as its textured package so the initial camera stays centered
when host presentation arrives. Model and Effect Placement use
one neutral studio lighting setup without a lighting-mode selector. Imported glTF
emissive factors also work without an emissive texture, including explicit zero strength.
Declared and discovered emissive maps stay bound to their owning material through import
and the final preview package, so a masked glow cannot become a solid white surface.
External image preparation budgets the whole batch before encoding: preview copies keep
their aspect ratio, at most 2048 pixels per side, and share the existing 128 MiB budget
for uncompressed colour/material/glow maps (including mipmaps and headers). Larger sets
use a smaller common preview limit instead of switching later maps to slow BC7 encoding.
Normal maps retain their existing BC5 format. Downloaded images and export resolution
remain unchanged; old preview packages rebuild once to pick up the corrected bindings.
Large image batches can run through two native conversion workers when their estimated
combined scratch memory fits 512 MiB. Small batches, oversized sources and exports keep
one worker. Both workers receive cancellation, and a failed batch stops its sibling and
waits for owned process teardown before temporary images are removed. Scheduling does
not change texture dimensions, formats, colour policy or mipmap contents.
Imported glTF materials preserve their declared alpha mode and opacity, use
metallic/roughness factors as map multipliers, and draw blended surfaces in the
current camera's depth order. Imported previews open flat against their broad
plane with a matching grid; cache reuse preserves that framing choice.
Moving to step 3 reparents that
live viewport without rebuilding
its package or resetting its camera. Texture upgrades wait for an active drag or
orbit to finish and preserve the resulting placement. Snapshot creation
reuses Archive Browser's published path, basename and extension indexes. A valid durable
material-package hit is accepted before either preview builder, including packages
produced by native Preview Core. The cache identity includes the native helper,
rendering inputs, and archive-file revisions so borrowed textures also invalidate
correctly. With preview caching enabled, the snapshot worker also prepares the native
service and shared material indexes using one small character model while the remaining
archive tables load. It uses the template preview's cache and captured render settings;
unfinished warm-up is cancelled and drained before the snapshot returns. Warm-up failure
does not invalidate the table snapshot, and waiting for the native service is cancellable.
On a cold miss, bare
geometry and Archive Browser's native schema-8 Preview Core package prepare in parallel;
the native package reuses the shared DDS cache and bypasses New Item's former Python
OBJ/material recompilation. Geometry reaches the resident viewport first, then textures
replace it without restarting the host or resetting the camera. If Preview Core is
unavailable, the established Python preview remains the compatibility fallback.
Placement and character comparison scenes also consume that native template package.
They copy its textures and material bindings into the complete scene before temporary
native resources are removed, avoiding another full archive-index build during import.
The full material tier includes the reference, which comparison views can display textured.
Skeleton lookup filters out non-descriptor entries before normalizing archive paths,
while preserving exact descriptor priority and sibling skeleton/morph matching. The
template resolver follows every model dependency embedded in each part prefab and composes
the complete set in both preview stages; its cache identity includes the selected template,
all model components, and the prefab revisions. Right-clicking a template row can copy the
resolved primary model filename or open that exact model in Archive Browser. Shared Preview
Core material packages reconstruct PAC RGB selector-mask tints before grime and detail
layers, so templates that borrow another numbered model retain the archive-authored colour
regions instead of inheriting the raw texture colours. The selected template's logical prefab
is authoritative when several items share a physical PAC: its `_modelPropertyIndex` chooses
the matching material block for every composed model, and prefab order remains part of the
package cache identity. The part-prefab reader preserves both
the original record
layout and game 2.00.00's opaque per-record tag-prefix byte exactly. After a successful
snapshot, the shell records the current `CrimsonDesert.exe` hash as compatible with New
Item Studio; a later unsupported-layout error mentions a possible game update only when
the executable detector proves a direct transition from that last-known-good hash.
Hidden Combat stats tables keep their data current but defer
Qt's content sizing until that workflow step is actually opened.
The Identity panel keeps item keys and model stems automatic until **Manual** is
chosen; manual mode starts from the same collision-free allocation the planner
would make. Identifier editors enforce the domain's character and 64-character
limits, and per-field state icons point at the exact collision or format issue
reported in the existing Checks box.

Stats and gameplay perks are explicitly marked experimental. The Stats page uses
compact, alternating rows with columns that fill the enhancement card, alongside
a separate shop-price and stack card. The default view labels ItemInfo values as raw game data and compares a
selected cell with the template and shipped range; arbitrary stats, flat values,
extra levels and separate enhancement rows stay under an experimental fold. The
base-price table also owns draft-added money items: an empty decoded list can create
its first 1-Copper entry from Stats or Distribution, while a row whose all-empty stat
block has no safe anchor disables those controls and explains the format boundary.
StoreInfo placement never carries a second price. One
draft change on that step is one workflow-state refresh: every edit goes through the panel's
`_draft_changed` (refill the grid when its shape changed, then `invalidate_plan`),
the tab refreshes its summary from `plan_invalidated` alone, never from the tables'
own signals (Qt emits one per cell a refill writes), and the tables' signals are
blocked while they are filled. `build_context` is memoized per template on the
read-only snapshot, so a validation is set lookups, not a rebuild of the sets. The
horizontal seven-step header replaces the old summary rail. Only the current page uses
the accent; clean pages receive a neutral check after they have been visited, and
untouched future pages keep neutral numbers. Existing validation warnings and blocking
errors add an explicit attention badge to the current or visited owning step, including
price and stat-block issues on **Stats & Prices**. Per-step tooltips and accessibility
text include the exact validation reasons. The Effects preview and in-game verification
caveats stay in those details and the plan review; they do not mark applied effects
as unfinished. Unapplied changes and actionable validation issues still mark the step.
Its footer keeps Back, `Step N of 7` and Continue
stable. Output keeps Build plan and its review in the
left column, with every write and install action in the right. Existing-overlay
migration and removal are grouped under **Manage existing overlays**; opening that
fold never performs an action. Shared section cards and accent primary buttons keep
Continue, Build plan and Apply placement visually distinct, with palette-based
hover, pressed, focus and disabled states. Step 5 is a
non-scrolling full-height page with Perks and Effects tabs. The navigator is a
compact 46 px row; the outer pages do not
repeat numbered titles underneath it. Distribution measures the selected route tab,
so hidden reward controls do not add an outer scrollbar to Shops and groups at
1280x720. Longer active content remains scrollable. Perks & Effects keeps gameplay perks separate
from visual-only effects. Perks are chosen through searchable Available and Selected
lists that grow with the workspace rather than a popup catalogue. Perk search, labels
and tooltips share one lookup for the immutable English table; loading a different
table replaces it so descriptions stay current. Four perks is
the evidence-backed default cap and five to eight requires an explicit experimental
opt-in. Effect support is structural rather than equipment-name based: the service
dry-runs the real component graft against every prefab the item will own, accepts only
an all-target success, and never edits a shared borrowed prefab. The Effects tab uses
24 px virtualized table rows with neutral stem-derived names, separated numeric suffixes,
and compact Type and approximate Size columns; the exact stem stays searchable and
appears in selection details and tooltips instead of being repeated under every row. `No effect` is the
single empty-state row, so blank
compatibility and exact-stem labels do not repeat it. Search matches words in the
readable name, exact stem, emitter, texture, mesh and preset metadata. The background
index follows emitter and render/simulation preset dependencies once per definition;
schema 2 invalidates old caches and includes dependency paths and archive locations.
Missing definitions are shown in tooltips without hiding otherwise usable effects.
Labelled All / Loops / One-shot filters,
a result count and Reset filters make browsing explicit; the staged selection remains
visible even when it falls outside the filters. Library labels and facts are
prepared in short event-loop slices and reused across filtering and placement
changes. Unchanged rows retain their selection and layout, and metadata column
sizing samples a bounded number of rows even while the page is hidden. Returning
to Effects keeps the resident scene; changed inputs and failed updates still retry.
Favourites and Variants narrow the library. Variant families remove numeric and
letter suffixes in one scan, so long or malformed names cannot trigger regex
backtracking during filtering. **Thumbnail** captures the current preview
frame into the local library; **Large thumbnails** expands the rows, loading only the
visible cached images. Saved recipes contain references and settings, never game assets.
A replaced snapshot or catalogue cancels the previous preparation;
shutdown prevents late catalogue events from restarting it. The hidden legacy
selector mirrors only the committed choice. Item preview preparation starts when
Effects becomes visible, with one initial request, instead of decoding the item
while another step is open. `effect_item_source.py` captures the selected import,
placement, glow, snapshot and template key without decoding them. Item parsing and
baking then run in the existing placement package worker alongside effect preparation;
cancelled requests cannot publish their item mesh, and source leases last through
worker teardown. The inspector groups Placement,
Appearance and Preview, with Apply and Discard pinned below its scroll area. Its
Layers / Emitters / Saved tabs add up to 16 effect layers with independent placement,
visibility and appearance. Selecting another layer does not itself create a draft edit.
The inspector tabs size to their active contents and keep actions together at the top.
The compact preview toolbar and playback rows retain natural control widths and wrap
at narrow sizes; extra workspace width goes to the viewport, while the inspector remains
resizable. Apply and Discard remain pinned when the inspector needs to scroll.
Layer solo and emitter solo affect only the preview. **Create from this emitter** starts
a custom recipe from an existing emitter; duplicate/remove controls change its emitter
list, while the inspector exposes declared emission, lifetime, force, velocity, size,
rotation and atlas fields. Overrides are opt-in, show inherited values, and unavailable
fields are disabled. Colour, size and opacity curves use Start/Middle/End controls;
portable JSON recipes can retain up to 128 samples. Save, load, import and export retain
the complete composition. Playback speed, seek, seed, restart and preview
quality support repeatable comparisons; playback settings do not change exported files.
**Show effect** toggles only the particles for comparison with the item underneath;
it never changes the draft, placement or camera. Selection, placement and look are staged; Apply publishes one draft
change, while Continue stays disabled and direct navigation offers Apply, Discard or
Stay. The reusable `EffectPlacementWorkspace` keeps one renderer resident, rebuilds
effect/look packages without resetting the camera, and retains old package files until
the correlated renderer acknowledgement. Live placement and gizmo updates, including
restart replay, send only the mutable placement state; full effect definitions stay in
the loaded package so complex effects do not exceed the control-message size limit.
Effect, emitter, preset and spawn-mesh decoding
runs in that cancellable lane rather than in the selection callback; spawn meshes are
sampled across triangle area into 96 stable surface positions instead of clustering at
vertices. Curves retain 128 samples. The Rust renderer fades particles against completed
scene depth for soft intersections, including MSAA, and offers 64/256/1024/2048 particles
per emitter with a 32,768-instance scene limit. Reset actions clear the corresponding draft
authority, and the workflow summary reports effective changes rather than UI mode.

`effect_authoring.py` owns immutable layer/emitter recipes. `effect_recipe.py` resolves
editable inherited emitters and compiles the same bytes for preview and export.
`effect_writer.py` rebuilds typed graphs, presence masks, strings, collections and self
pointers, and decodes its output before accepting it. Unknown collection layouts and
incomplete graphs fail rather than producing speculative binary edits. The planner
clones edited definitions and grafts each enabled layer into the item's owned prefabs;
the legacy single-effect API and `.action.effect` references remain compatible. Recipe
creation and loose-package planning do not mutate game archives.

The preview remains an approximation of the game renderer: unknown spawn-volume enums,
vector fields, multi-texture shader graphs, distortion and injected lights are not fully
reproduced. Custom graphs use verified typed fields and existing emitter templates;
arbitrary game shader authoring is not provided. Binary readback and synthetic GPU tests
do not establish in-game appearance or acceptance of a newly authored composition.
For an imported item, Effects always derives its placed preview from the live import
source before and after **Apply placement**, so its PBR rows are the same authority that
Model & Placement displays. The rebuilt PAC remains output authority but its borrowed template
material wrappers never replace the import's source materials in the placement viewport.
Material synthesis follows each input's imported or archive provenance after scene
composition. Direct imported textures skip recomposition; archive-owned layers still
compile even when the editable role comes from glTF, OBJ or DAE.
Apply Placement captures the source snapshot and reads its existing archive indexes
on the build worker; it does not rescan the template family in the click handler.
Successful builds are recorded in the Output log. Conversion failures remain beside
**Apply placement** and in that log through preview refreshes, until the model is edited
or the build is retried. Build plan checks for unapplied variants before starting work.
When a template has fewer material slots than the import, automatic atlas allocation
reserves a separate existing slot for each tiled-UV material and combines compatible
materials in the remaining slots. This preserves texture repetition and the PAC draw
layout; insufficient slots or vertex capacity produce an explicit build error.
Character lookup filters relevant PAC, PAB and XML paths before normalization and
sorting, observes cancellation during the scan, and does not copy unused archive sizes.
The current per-part Glow colour and strength are copied into those same rows when the
Effects package is built, and returning to the step refreshes changes made in Model & Placement.
The character reference defaults to the template's player rig. Effects and Model & Placement
reuse Placement & Animations' bare-character choice: the playable rig's nude anatomy plus its
separate face, never the generic distance proxy that previously made Damian look like another
body and left Kliff on the bar mannequin. The Effects workspace's
**Character** control shares the compact character-visibility row in **Preview**,
so it does not reserve a separate band above the viewport. It can preview **Auto**, Kliff or
Damian without changing the template, item output or equip compatibility. `EquipTypeInfo`,
rather than the model folder's spelling, decides the frame. Hand-carried families reuse the selected
prefab's primary part and Placement & Animations' held body/child socket route; body-,
creature- and vehicle-mounted equipment stays in its upright authored bind frame. A folder
and the established right-hand/basic pair are only fallbacks when template metadata is
missing or malformed. The placed preview
bakes manual rotation and scale around the same fitted source origin that Model & Placement
and the final Builder use; for a wearable, neutral effect placement starts at that applied
origin so the gizmo opens on the helmet or armour rather than at the character's feet. A
feet-at-zero bind-space stand-in is used when the matching archive body is unavailable.

The Model & Placement step places two resizable inspectors around a tall resident preview.
Model selection and import actions stay on the left above compact Appearance, Dyes and Icon
tabs. Placement numbers, fit/reset actions and Apply placement stay on the right. The active
left tab uses its natural height, and captured icon thumbnails stay in the Icon tab so the
preview footer remains compact. Controls retain their values when switching tabs or resizing.
When the three columns cannot fit, Placement joins the left tabs; very narrow pages stack
that inspector above the preview. Both inspectors scroll locally, leaving the viewport fixed.
Full import notes, FBX setup and Quick turn expand on demand; Glow details collapse while off.
The default inspector pages fit a 1280 × 720 window without scrolling.
Quick turn buttons add −90°, +90° or 180° to the X, Y or Z placement rotation around the
fitted model pivot, retaining position and scale. **Reset rotation** restores the fitted
orientation; **Fit to template** restores the complete fit. These actions move only the
imported model, update the resident viewport, and invalidate an earlier applied mesh or plan.
Use **Apply placement** to prepare the resulting mesh for the item.
The Preview is the exact frame prepared under Template, retaining its camera and package.
The step imports a model file itself:
`model_import.py` reads it
the way the Model Library does (the scene import, the source's own textures),
and the same cancellable worker reads the template geometry, retains its bounds and
centroid for later re-fit, and prepares the fitted mesh before publishing the import.
The first UI read of the fitted bounds reuses that mesh. Weapon-family paths use the grip/heavy-end fit; armour,
accessories and other families keep a centred axis fit instead of being interpreted as
weapons. Import and **Fit to template** level the model's broad plane against the
placement grid while matching the template's direction within that plane and keeping
its grip or centre as the placement anchor. This removes authored and template-derived
tilt for elongated and broad shapes; shapes without a clear axis or plane retain the
bounding-box fit. The template stays fixed, and manual rotation remains available.
The level fit is baked into the mesh shared by the preview and **Apply placement**.
`item_preview.py` owns the resident frame and publishes fitted geometry, direct
DDS textures, and then the complete synthesized material tier without resetting
the resident camera;
`item_preview_materials.py` owns placement-scene composition and the copied-package
canonical-material upgrade, without restarting the renderer, re-exporting geometry or resetting
the camera. `panels_model.py` builds the three-column surface while
`panels_model_preview_mixin.py` owns its preview, placement, import and icon interactions.
FBX conversion relinks an explicitly referenced missing image by exact basename
from the extracted package's nearby texture folders; the shared preview then supplements an
embedded base with clearly named Normal, AO, Roughness and Metallic maps without treating a
Thickness map as colour. A textureless exported material still keeps its authored
`TEXCOORD_0` channel instead of triggering an unnecessary auto-unwrap. Generated material
synthesis is deduplicated across identical submesh inputs.
Apply runs through the controller's cancellable progress lane; its spinner, current phase,
percentage when available and Cancel action remain live while conflicting placement edits
are disabled. Preview-loading text stays in that pinned operation bar while errors and
ready/capture messages remain below the viewport. The fast-texture state explicitly says
that full quality is still loading, and the final state confirms whether that texture pass
completed or failed. Imported-material, Glow and
template-specific controls live with the model; alternate sheathed/holstered visuals
and inherited cloth/physics are hidden when the selected family cannot use them. The
viewport shows the model over the template with the grid and gizmo (`PlacementScene`).
Both the geometry-first and canonical-material stages declare a placement scene: Overlay keeps
the game's template fixed as a wire guide while the imported, textured model is the only editable
role. Side by side and Template only expose the full reference presentation, and changing among
the four view modes immediately frames the roles that are now visible. The grid stays anchored to
the scene frame and faces the template's broad plane; the opening camera looks straight at that
plane, so the template reads flat without changing any model coordinates. Move, Rotate and Scale
change only the imported model around its fitted source origin, so the template remains the in-game
placement authority. A glow
ticked on the step lights its parts in that
viewport live (`glow_preview_parameter_groups` in the materials service builds
the renderer's parameter groups from the same three values the plan will write,
re-sent whole after every package rebuild; un-ticking restores the import's own
emissive), and `ModelPlacement.build_transform()` plus the origin-aware preview bake turn the
placement into the static replacement's transform for the headless Builder import
(`build_placed_import`), whose result is what the plan writes. The fit's baked source
origin is the shared preview/build anchor, so the gizmo stays on a model whose template
location is away from world zero and manual rotation/scale happens around that origin.
**Show the character** adds that template's assembled body to the same resident scene as
non-editable reference geometry. A wearable keeps the upright bind frame; a held item expresses
the body in the item's authored frame so the exact relative fit is preserved without changing
the placement numbers, gizmo axes or Builder transform. Turning the character on or off rebuilds
through the existing latest-wins preview worker, and the character can never enter the item mesh,
Apply result, plan or output package.
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
never waits on filesystem cleanup in the UI thread.
Retired transient preview packages use the same tracked cleanup lane. Cleanup is
serialized, remains visible to the shutdown coordinator until drained, and cannot
remove the preview output root or paths outside it. Durable preview caches are retained.
Entry points: the tool tab
`new_item_studio` and the Item Finder's `Clone as new item...`; a ready Builder
result can still be handed in through the tab's `receive_imported_model`.

Related tests: `tests/test_new_item_studio_tab.py`,
`tests/test_new_item_workflow_header.py`, `tests/test_new_item_effect_workspace.py`,
`tests/test_effect_placement_dialog.py`, `tests/test_new_item_effect_targets.py`, and
`tests/test_new_item_effect_proof.py`. The explicitly invoked real-corpus gate is
`tools/new_item_effect_proof.py report`; it keeps evidence under system temp and is not
part of an ordinary automated check.

## Current game tables and extended authoring

The seven workflow steps support the current `binarystaticinfo__/bin` tables as
well as legacy `binary__/client/bin` tables. Current complete table pairs take
precedence as a generation; missing halves and parse errors cannot fall through
to an old mod. An unreadable archive index stops authoring rather than exposing
an incomplete catalogue. ItemInfo preserves its actual `0x11` or `0x12` stat marker.
Current StoreInfo retains the additional stock condition bytes and all opaque
fields. Every writable shape must round-trip without changes first.

Item text uses the current per-language `item.paloc` files, including Arabic,
or the legacy monolithic localization tables. Unspecified text falls back to
English using the existing derived keys. Arabic is an item-text option, not an
additional workbench UI language.

Template searches initially use the game's equipment category, with **All
equipment** and explicit subcategories available. A handoff reveals its requested
item regardless of the active filter. Ordinary category/equipment group memberships
are the default for new drafts; quest, special and collection memberships require
an explicit selection or **Advanced: inherit all template groups**.
The sortable **Authoring** column distinguishes templates with enhancement stats,
decoded prices/sockets and unsupported stat boundaries. Source archives remain in
the row tooltip and generation status.

**Perks & Effects** separates embedded perks, available socket capacity and
unlock costs, inherent bonuses, and visual effects. Bonus presets come from
shipped equipment. Parameters are the validated BuffInfo levels, without invented
percentage conversions. Bonus overrides can apply to one enhancement level or all
levels. Omitted overrides inherit; empty overrides clear. Reducing socket capacity
never silently removes perks. Normal limits remain four embedded perks and five
slots, with the existing eight-entry experimental limit visibly separate.

**Stats & Prices** also contains enhancement/crafting recipe authoring. A selected
recipe is copied with owned DropSet outputs and reconnected to the new item.
On the current generation, inheriting recipes automatically creates those owned
connections while preserving costs and requirements, even when the recipe editor
is never opened. The legacy format retains its explicit ownership choice.
Customizing one transition also creates owned copies of the remaining inherited
transitions, preserving their quantities and levels while reconnecting their item
references. Otherwise the game can report maximum refinement at an intermediate
level. An unsupported inherited transition blocks this operation before export.
Inputs, quantities, enhancement levels, tool and knowledge requirements can be
edited; item key zero in an ingredient means the new item. Source flags and
presentation/localization references remain unchanged, including elemental-status
requirements and variable-length refinement descriptions. Both primary and
additional output lists receive owned copies. Output quantity ranges are editable;
customizing another field preserves inherited ranges and zero-filled material
placeholders. The ingredient/output tables size to their rows, keep names readable
and leave recipe actions visible at compact workspace sizes. Unrelated crafting
presets stay editable while an output is selected.
Recipe connections require a unique list associated with the template through its
decoded inputs or outputs; an unrelated list containing recipe-looking keys is not
an editing boundary. Ingredient quantities are separate from item
purchase prices. Clearing connections removes the inherited recipe list.

**Distribution** saves multiple Add/Replace shop routes, including exact stock
indices when the same item appears more than once. Quantity and known unlock
requirements are separate controls. Existing item-use/container reward routes
clone both the reward definition and its ItemUse record, reconnecting only the
selected item consumer. Quantity ranges and raw weights are editable; weights are
not labelled probabilities because roll policy varies. Unrelated consumers keep
their original definitions. Supported conditional item entries preserve their four
stored condition/tag references, sub-weights and use conditions. Tooltips list the
actual indexed consumers and retained references; unknown condition scopes are not
offered as editable gameplay semantics.

**Model & Placement** identifies each variant by its exact prefab/model binding.
Imports, material routes, glow, placement and camera are retained independently.
Selected variants own their resources; unselected variants retain the template.
Variant allocation also reserves StringInfo and dye hashes, including orphaned
dye records carried by a compatible mod base.
Companion meshes are preserved, and held/sheathed bindings are individually visible.
On the current format, the legacy single-model service argument adapts to the
primary binding. Rigid attachments must retain their single slot. A rigid replacement
can also retain the selected prefab's exact model/socket binding when the original
weapon includes weighted accessories; those discarded accessories do not require a
character skeleton for the new rigid mesh. An unrigged source is bound to that exact
socket before conversion, so mapping its parts onto a flexible template accessory
does not transfer the accessory's skin weights. Unused runtime slots retain their
small placeholder draws but follow the same rigid attachment. Full replacement
records authored with up to six influences clear the donor's two additional weight
lanes before encoding, so discarded accessory influences cannot leak into the new
mesh. Authored source skin remains subject to rig validation.
Byte-identical models retain their existing
template binding. Changed skinned imports require a resolved target skeleton and matching
bone palette; an unresolved or ambiguous rig is blocked rather than borrowed from another
character.
Palette discovery follows the declared PAC metadata boundary, including palettes
beyond the former 4 KB scan window, and excludes the geometry sections.

**Dye assignments** starts unchecked and collapsed, with dyes disabled in the draft
and output. Enabling the checkbox explicitly requests template dye inheritance;
unchecking it clears the assignments. Exact RGB channel-to-slot mappings can then
replace the inherited setup. Replacing an import or changing the template resets
dyes to off. Switching variants restores only that variant's choices, and clears
the mask entry and dye-preview toggle. Moving or reapplying the same import retains
its explicit dye choices. Unselected template resources remain unchanged.
Imported renamed parts require an explicit mask fitted to their UVs. No fuzzy name
matching or inferred shader flags are used. If explicitly requested template dyes
are incompatible with imported materials, preview/export omit them and Build plan
records an actionable warning. Explicit mappings are still validated.
Material preview and export call the same preparation function. The preview is a
material inspection; it does not simulate a chosen in-game pigment or prove dye
station behavior. Mask revisions form part of the preview identity and immutable
worker request. A replaced mask invalidates cached previews and export plans;
changing it during preparation is rejected.

**Imported armour follow-up:** the existing components can support this, but this
weapon fix does not establish arbitrary armour import support. The next integration
should resolve the template's declared skeleton through
`cdmw/core/skeleton_resolver.py`, including descriptors outside the model folder;
the current variant validator only scans PABs under the character's model directory.
An unrigged garment needs fitting in the character's bind pose and transfer of
weights from the matching template armour/body surface using
`ensure_final_target_skin_weights`. An already rigged import needs bone-name mapping
into the target PAC palette before its numeric influences are accepted.
Rigid headgear should use its declared attachment when available; a helmet label
alone does not prove a rigid binding. Deforming pieces need the character rig.
Read-only checks resolved `cd_phm_00_hel_0001.pac` (12 palette entries) and
`cd_phm_00_lb_0002.pac` (40 entries) against `phm_01.pab`.
The animation and armour skinning in `tools/placement_studio/` provide reusable
playback for checking shoulders, elbows, knees and neck motion. Fit/clipping quality
can warn after a valid mesh is produced; missing usable weights or an unencodable
palette still needs an actionable correction. Body coverage, companion pieces and
cloth/physics require their own checks before claiming in-game support.

Optional bonus, recipe, dye and reward indexes load in the bounded worker lane.
Requests capture their variant and source state. Source leases cover all selected
imports until the worker thread exits. The resident viewport remains present while
its replacement is prepared. Output reviews variants, records, acquisition routes,
table provenance and changed files. Plans are tied to their draft revision and
source payload/file fingerprints, checked again before atomic publication.

Compatible mod bases carry every prior item and added dependency forward. Table
operations accumulate before encoding so recipes, rewards and multiple variants
cannot overwrite earlier additions. Mixed-generation bases are rejected with
affected paths/items and preserved for rebuilding; automatic migration is absent.

### Verification boundary

The September 2026 corpus check round-trips all 18,576 recipes, 13,045 item reward
sets (including 26 conditional sets), 166 ItemUse reward-reference records and all
1,626 dye records. The 1,699 other reward definitions include non-item and mixed
result variants; they remain unsupported for item reward editing. Nonempty
condition/elemental-material arrays not present in this recipe corpus remain
guarded. The 83 ItemInfo rows with empty-shaped but unproven stat boundaries remain
unsupported, rather than being treated as empty editable blocks. Templates without
a proven recipe-list boundary cannot receive new recipe connections.
The sampled `cd_phm_00_lb_0002.pac` garment now resolves its 40-entry palette against
`phm_01.pab`; a rebuilt garment passes target-rig validation. Existing item-use
containers are the supported reward consumer path. Generic world-object/quest
consumer rewiring and new world placement are not supported.

Synthetic fixtures cover edited round trips, ownership, empty/inherited overrides,
exact duplicate-shop selection, multiple imports, cancellation/leases and second-item
base preservation. The optional live-corpus tests fail on missing required tables.
Licensed payloads and local reports belong outside tracked fixtures. File-level,
headless and material-preview evidence do not close gameplay acceptance: bonuses,
unlock costs, recipes, dyes, animation/variant appearance and acquisition still need
recorded obtain/equip/use observations and restoration using a reviewed temporary
package. Installation/restoration continue through `ArchiveMutationService` with
the exact mutation confirmation and recovery checks.
