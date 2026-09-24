# Create New Item

[Shader experiments](../mesh_editor/SHADER_CONTROLS.md) share
typed controls with Mesh Editor, including per-variant choices and worker-prepared
resources for Model, Effects and dye previews.
The experiment selector marks incompatible choices **Unavailable**, lists the
experiments supported by the selected part, and explains each unavailable option's
required source material in its tooltip.

**EyeCover blending (experimental)** is available here for plain Standard,
Emissive and Translucent materials with a base colour texture, and existing
EyeCover materials. Select a part under **Model & Placement → Appearance →
Shader experiments**. The initial overrides are colour mixing 0.5, surface alpha
1 and material red 0; roughness and metallic initially keep their source channels.
Unchecked fields retain the source; missing inputs use explicit neutral maps,
avoiding the shader's stock face textures. Restore removes the experiment.

Colour mixing is stored in the low byte of `_eyeCoverDiffuseParameter` (256
steps); the other bytes are preserved. The recovered colour weight is
`2 * packedColour / 255 - materialTexture.red`. It is not a whole-material
opacity percentage. `_alphaTexture.red` independently affects normals and
surface properties. The roughness/metallic overrides replace material G/B and
take precedence over the ordinary Surface controls for export. Colour and source
normal maps remain bound; colour, shine, reflection, depth and shadow behaviour
still require in-game testing. Glow and Translucency overrides must be restored
on the same part before choosing this experiment. Layered materials require a
Plain PBR import first; they are not silently converted.

EyeCover blending is **export only**: Model, Effects and dye viewports retain
source shading, and the panel visibly identifies this limitation. The preview
does not simulate EyeCover's character G-buffer pass. Choices persist per variant
and go through the regular build-plan/export workflow. Edited alpha/material
channels use private BC7 textures with full mip chains; shared source textures,
other parts and installed archives are untouched. BC7 is lossy and channel
values are quantized. Use the source application to test this addition until the
next explicitly requested executable build.

Owns the Create New Item tab: clone an equipment item into a brand-new one with
its own identity, model, icon, stats, shop placement and item groups, then write
it as a loose mod or install it.

## Rust interface

**Create New Item** always opens the Rust interface. The separate Rust entry and
the Rust/Classic presentation switch are removed. The Classic implementation is
retained in source as the offscreen workflow used by the Rust bridge, but cannot
be opened from the application. Both former saved tool keys resolve to the one
workspace, including Model Library and template handoffs, status, and detaching.

The Rust interface uses native egui controls and the existing native preview
windows. Python still owns the workflow, validations, workers, exports, archive
mutation service, and confirmations. File and colour pickers remain native
dialogs. Closing the Rust renderer or retrying it does not discard the draft or
plan. If the helper cannot start or stops responding, **Retry** reopens the Rust
interface for that same workflow without exposing Classic.

After the main window is visible and startup dialogs finish, the shell prepares
the Rust tab, its renderer and the archive tables in the background. The existing
cancellable snapshot worker loads the Template workspace automatically, without
requiring **Read the archives**. Opening the tab reuses that snapshot and process;
hidden renderer polling stops after the first acknowledgement. An early click or
restoring this tab after an app restart can still show loading until preparation
finishes. The archive read starts after startup even if the tab is already open.
An existing snapshot or read in progress is reused; a failed read keeps its error
and **Try again** action instead of retrying repeatedly in the background. The
worker and renderer remain owned by the tab for normal asynchronous shutdown.
The native window resizes after Qt settles its container geometry, so the first
opening fills the workspace even when preparation happened in a hidden tab.

The embedded child takes keyboard focus on clicks and supplies its actual Win32
focus state to egui. Field edits finish before navigation or dialog actions hide
their controls. Font size and button colors come from the current application
theme; hover changes color without expanding the controls.
Selecting a template and then moving focus to Find or another control keeps the
renderer responsive. If the renderer stops replying, its window is hidden
asynchronously so CDMW can stop it and retry with the same draft.
Buttons fit their labels and related actions stay together. Inspector lists fit
their contents, the navigation footer stays compact, and expanding Quick turn or
other inspector sections preserves the viewport size and splitter position.
Rust lists and table headings align left. Headings use plain text with sorting
indicators where supported, and draggable edges retain manually chosen widths.
Content-sized columns reserve room for their headings and values; stretch columns
take the remaining pane width without hiding the final price or parameter editor.
Material checklists keep long names within their pane and show the full label on
hover. Dropdown menus fit their option labels, including effect categories, up to
the window width. Colour indicators remain inset inside their buttons.
The Emitters property table expands into spare inspector height, keeping curve,
texture and reset controls below it and Apply placement outside the scrolling page.
The navigation footer fits one control row, and the shell status strip has a 30 px
minimum height that can grow for the active font. Model loading keeps its label,
percentage bar and Cancel adjacent; percentages use reported work counts, while
stages without a measurable total remain indeterminate.
Editable choices keep their text field and dropdown arrow on one row. Short
tables use their actual row and font heights, and narrow split panels scroll to
keep every inspector reachable. Context menus open beside the pointer; small
dialogs fit their fields and keep related actions together below the content.
Instructional detail is available on hover over the relevant control or section;
validation messages remain visible. Popup and tooltip rectangles mask the native
preview underneath so their complete contents remain visible and clickable.
Wheel zoom keeps the view-plane point under the cursor in place in both preview
and authoring viewports. The overlay folder field accepts digits; leave it blank
for Auto or enter a folder number from 0036 to 9999.
Projected dialogs retain their original results and block edits behind them in
the bridge without registering a second hidden Qt modal window, which would
disable the visible application. Template results fill the available height,
including a short final page, while inspector lists remain compact. Scrolling
requests more source rows only at the end of the loaded results, once per unchanged
model and page. Previous and Next navigate the projected pages.
Internal Name starts wider and header edges resize columns. Preview portals move
the complete native host, keeping its loading/status overlays in one stable slot
and retaining a layout placeholder while the renderer is restarted.

`rust_ui_document.py` projects the current controls, layouts, models and dialogs;
`rust_ui_actions.py` routes allowlisted input through their original handlers.
Checkable sections, including Glow and Translucency, preserve their checked state
and original toggle/click handlers when switched on or off from Rust.
`rust_ui_bridge.py` checks session, control revisions, enabled/visible state and
modal ownership. Large result lists and review text are paged; Copy retains the
complete source text. Editable descriptions support up to 1,048,576 characters.
`rust_ui_portals.py` retains preview window identity across renderer restarts.
Layout projection reads widgets and nested layouts in their layout-index order
without retaining Qt-owned `QWidgetItem` wrappers. Qt can delete those items when
moving a widget without invalidating their Python bindings, allowing a later
worker or control to reuse a stale address. Shared preview moves explicitly
remove their old layout items, and portal replacement retires both the returned
item and its binding before restoring or reattaching the viewport.
Captured icons use a native image-crop control with the original Reset and Use
Selection handlers. Dialog action buttons remain visible below scrolling content.

The helper's hashed control contract must advertise `cdmw_new_item_ui_v1`.
After changing the native UI, build the local pinned helper with
`./build_pyside6_app.ps1 -Mode onefile -BuildProfile release -NativeHelpersOnly`.
The owned headless layout and live transport probes are
`tools/new_item_rust_ui_harness.py` and `tools/new_item_rust_live_harness.py`;
neither uses an installed game. The layout probe's `--audit --material-controls`
options include optional editing states, material sections and owned dialogs.
The ignored Rust test `render_owned_ui_popups_and_scrolled_panels` reads captures
under `CDMW_UI_AUDIT_ROOT` and writes popup and scroll captures for inspection.
The live probe prewarms a hidden renderer, opens
the tab with the same process, and clicks and types through Win32 into the original
Name and Find fields. It also checks that page switches do not reject a finishing
edit. Its `--preview` option loads an owned
synthetic mesh into the pinned preview helper and checks camera captures, crop
dialog cancellation, renderer retry and process cleanup.
`--visible --interactive --preview` exposes the owned fixture with a second tool
in its sidebar for normal Windows typing, column dragging, dialog, navigation and
tool-switch checks. It asserts stable preview geometry from loading to ready.
See `docs/test-matrix.md`
for focused checks. Helper builds do not repack the main application executable;
use a source launch to try this workspace before the next application package.

Current Tool Log is available as soon as the tab opens. The same bounded document
keeps archive-read progress, template changes, preview status, effect indexing and
Output messages, including messages emitted before the workspace is built. These
stages also enter `diagnostics_current.jsonl` through the shell's persisted activity
recorder, with elapsed time and the selected template key. Optional tool loading
shows a loading label before construction; archive loading keeps its placeholder
until the workspace has been constructed.

Effects cache validation uses the snapshot's indexed effect-definition paths,
including emitter and preset dependencies. It never materializes unrelated model
or texture entries. Cancellation is checked while gathering and hashing definitions.
Background indexing reports progress and a bounded sample of incomplete metadata
with effect names and decoder reasons; incomplete metadata does not block template
selection. The Effects library retains the individual details.

Before planning, the worker checks the snapshot's archive/index revisions and
refreshes changed sources, including overlays removed by a mod manager or Steam
verification. The draft remains intact. Overlay output defaults to Auto; the
optional folder number selects a free four-digit group. Both disk folders and
PAPGT reservations are respected, including optional game archives absent on disk.
A stale ownership marker cannot take over a mount record replaced by a game update.
Large overlay payload checksums use the existing cancellable native helper so
building a mod does not occupy the UI's Python interpreter.

Native DDS encoding runs at below-normal process priority on Windows so its
parallel compression yields CPU time to the UI. Build plan reuses source-derived
translucent BC7 bytes within the session: the key includes the prepared image
(after factors, alpha and atlas baking), dimensions, mip count and encoder identity.
The cache retains at most 16 entries and 64 MiB. Waiting for an encode and the encode
itself are cancellable; failed or cancelled work is not cached. The first encode
still performs the full-quality conversion.

Layered template translucency also reuses completed material bakes in a separate
session cache, bounded to 16 materials and 64 MiB. Its key includes the authored XML,
model path, source DDS contents and encoder identity. Changing only thickness or
extinction updates the material parameters without baking its textures again.
Source dependencies are still read and registered for provenance on cache hits;
failed, incomplete or cancelled material bakes are not retained.

Output shows the current Build plan stage and elapsed time, including source reads,
layer combining, colour/normal/surface compression, cache reuse and table planning.
The bar counts completed materials during a template bake and remains indeterminate
for stages without measurable progress. It does not estimate an encoder percentage
or time remaining. Progress travels through the existing worker signal; cancellation
rejects late updates, and the elapsed timer stops when the operation finishes.

Overlay preparation checks source provenance once at the preparation boundary,
including recovery retries. Dependency analysis and composition share decoded
journals only within that call; composition still rechecks each reused journal's
hash. Backups, conflict checks and rollback remain required. Early preparation
stages appear in the operation log before composition begins. The post-install
archive refresh remains a separate background operation.

Perk search results use a prepared list model shared with the compatibility
selector. Refresh preserves selection by item key without clearing native list
items, and replaced models and selection models are released safely.

The archive snapshot reads StatusInfo and EquipTypeInfo from either their legacy
`gamedata/binary__/client/bin/*.pabgb` / `*.pabgh` pairs or the newer
`gamedata/binarystaticinfo__/bin/*.staticinfobody` / `*.staticinfoheader` pairs.
A complete legacy pair takes precedence when both layouts exist; payloads and
headers are never mixed between layouts. These two tables supply names only.

With a matching Full archive session, snapshot workers open its generation-bound,
read-only catalogue and materialize only relevant rows. Parsed tables are reused
within the service while source metadata remains unchanged; each snapshot has
separate planning caches, and planning/output still checks source provenance.
Older workers and standalone entry lists retain the existing archive-read path.
The shared preview, identity checks and output actions are available immediately;
Combat, Perks & Effects and Distribution are built when first requested. Workflow
summaries read the draft without constructing those pages. Optional preview warm-up
still cancels and drains before snapshot publication; debug logs report its drain time.

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
Effect manifests use compact JSON so dense item/character surfaces do not exceed
the viewport's 16 MiB manifest limit through formatting whitespace. Preparation
retains the full geometry without an extra deep copy and checks the serialized
size before publishing. Oversized packages fail on the worker without replacing
the current scene; rejected host loads retain their package and camera state for
Retry until a replacement is acknowledged or the workspace closes.
Mod-folder and icon-folder scans are part of that planning
worker, never UI callbacks. Shutdown requests cancellation and leaves live
threads discoverable to the shell close sweep; no New Item widget waits on its
own worker. The `panels_*.py` modules edit the draft and ask the
controller for facts; `tab.py` composes them, and forwards install to the shell.
Queued effect-toolbar resize and post-install refresh callbacks are tied to
their owning widgets, so destroying the workspace cancels pending delivery.

Secondary catalogue searches and effect compatibility checks use bounded,
cancellable lookup lanes. Each lane runs one request and retains only the newest
pending request; results return through queued signals and must still match the
current snapshot and selection. Hidden Effects pages defer filtering until shown.
Perk, group and recipe results retain their display limits, while large bonus,
reward and tool dropdowns and the output file list use virtual Qt models. Plan,
merge and update review text is prepared on workers and inserted in small batches.
Name validation reuses immutable collision indexes and runs once per name edit.

ZIP/FBX inspection, cold model bounds and Mesh Editor session cloning run on owned
workers. Accepting an edited import warms its baked geometry and preview caches
before publication; preview refresh never triggers a cold bake on the GUI thread.
Model/session results retain source, variant and revision checks, and rejected
sessions are disposed in the cleanup lane. Effect package retirement also uses
that lane, with exact package-root ownership checks. Closing either preview waits
for its owned renderer processes to exit before deleting their packages, while
the GUI continues processing input. Legacy recovery performs its read-only scan
on a worker before presenting the existing concrete mutation confirmation.

The Template panel searches internal IDs, every available localized item name, equipment types and
item keys with Archive Browser's normalized terms, phrases, alternatives and exclusions.
The snapshot worker prepares immutable equipment names and category membership once.
Find coalesces typing for 150 ms, then searches and sorts on one cancellable worker;
each edit immediately supersedes older work, and only the latest result for the current
snapshot can replace the list. Existing rows stay usable while searching. Search shutdown
returns immediately and keeps unfinished threads visible to the shell's close sweep.
Its result table separates the internal name, English item name, numeric key and equipment
type plus authoring capabilities into five labelled columns. Column edges are session-resizable, clicking a heading
sorts the complete match set (including numeric key order), and scrolling near the bottom
adds the next 60 rows until every match is visible. Startup and later panel growth distribute
all available width across the columns instead of leaving an empty strip. An explicit mouse click starts selection immediately,
while keyboard row navigation keeps its 180 ms latest-row settle so holding an arrow key
does not rebuild every dependent step along the way. A cancellable worker resolves the
selected family, material parts and validation facts before publishing it to the UI.
Only the latest selection can publish, and shared snapshot validation indexes are reused.
It mounts the same resident item
viewport used by Identity and Model & Placement, so a selected helmet, armour piece or weapon can
be orbited and zoomed before the workflow inherits it. Template handoffs search the
catalogue once and select the requested row. Search and results stay in the
left column, with search and category on one row and readable item names first. The
resizable list receives more width than the preview by default. The workflow summary remains the one selected-template status authority, so
Template does not repeat it in another group or add a second camera explanation.
Every shared preview keeps the
current orbit, pan and zoom controls in a footer outside the native viewport. Initial
package framing survives helper startup and progressive texture state replay, while
later explicit camera commands remain authoritative. Camera resets survive
superseded geometry and texture loads until the renderer acknowledges the new template.
Only selecting a different template frames automatically. Switching tabs, variants,
character references, display modes, imports, materials or effects keeps the live
camera, including gestures made while a package is loading. Frame and the camera
view controls remain explicit ways to reposition it.
Template, Identity and Model share a **Show gizmo**
checkbox next to the viewport; Effects and its placement dialog expose the same
preference. It updates open New Item views and survives application restarts. Hiding
the transform handles leaves the upper-right orientation control available.
Model handles follow the center of the visible editable geometry, including its
current transform and comparison layout. Authored placement pivots and exported
transforms retain their existing meaning; an effect's handles stay at its chosen anchor.
Single-template geometry uses the same replacement-only layout as its textured
package so the initial camera stays centered
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
current camera's depth order. New Item previews use a horizontal Y-up ground grid
for every equipment shape. The camera selects the model's broadside independently:
standing models keep Y upright and open slightly from above; horizontal models
open from above with their longest axis across the viewport. Frame restores that
view without changing model placement, grip/socket alignment or wearable fitting. A new template
resets the camera even when its textured package arrives without a geometry preview.
Texture upgrades for the same model preserve the user's orbit, pan and zoom. Older
cached New Item previews rebuild once to replace sideways grids.
Plain-PBR exports keep each source material's roughness/metalness and emissive
outputs separate even when the Builder shares a colour texture between parts.
After Mesh Editor deletes, reorders or separates parts, material bindings follow
the surviving materials so glass, glow and texture ownership stay with each part.
New Item disables the Builder's automatic brightness balancing so exported colour
textures retain the authored dark detail and highlights shown in the import preview.
Generated texture reuse includes the material's factors, normal scale and colour
controls, so sharing an image cannot transfer another material's appearance.
Textureless colours and opacity factors are applied once, including an explicitly
zero opacity. Normal strength is baked once; a material without a source normal
map does not inherit another part's map. Colliding glTF material names receive
distinct names based on their source indices before grouping.
Binding an unrigged weapon to its template's hand socket preserves those source
materials, including textureless gem colours, opacity and normal strength.
The exported roughness/metalness map includes the source's scalar multipliers;
separate OBJ/MTL roughness and metalness maps are packed into the same game layout.
Selected gem glow stays on those materials; a source emissive map is retained
even when the template has no emissive texture slot, with its authored colour
multiplier and intensity. When source materials share a baked atlas, their emissive
masks and relative strengths follow the same UV regions; non-emissive regions stay
dark. An explicit Glow colour on imported Plain PBR parts replaces both their
surface hue and emission colour. The surface recolour retains texture value detail
and alpha; atlas edits follow only the selected materials' cells. Shared textures
receive a separate output so unselected parts retain their colours. Unticking a part
restores its authored colours in preview and when rebuilding the plan. This does not
remove lighting, metallic reflections or the experimental glass approximation.

**Surface colour and reflections**, under Model & Placement → Appearance, edits
imported Plain PBR materials independently of Glow and Translucency. Choose a part,
enable **Surface colour** or use **Match glow colour**, then adjust **Roughness** and
**Metallic**. **Low-shine** sets roughness to 0.9 and metallic to 0.0. Surface colour
replaces hue while retaining texture brightness and alpha; explicit surface colour
takes precedence over Glow's surface recolour without changing its emission.
Unticked channels inherit the source or the selected Translucency surface settings.
**Restore source surface** clears the selected part; switching the group off clears
all active surface overrides. Edits follow the selected variant, Effects and dye
previews, and Build plan. Shared textures and atlas regions remain separate, so
unselected parts keep their appearance. The controls affect the exported textures;
game lighting, reflections and experimental glass can still differ from the viewport.

Source glow strength takes precedence over the template, faint emission keeps
its colour, and an unavailable declared emissive texture blocks export.
The default single-colour glow route reduces multicoloured emission to an
intensity map and tint. **Use RGB glow map**, described below, keeps the source RGB.
Blend and mask textures retain opacity precision in alpha-capable DDS output.
For imported Plain PBR parts using translucency, Build plan encodes base colour
directly from the source images as BC7 with full mipmaps. This reduces colour
compression errors amplified by glass absorption; it cannot remove variation
already present in the model's textures. Source colour/alpha factors and atlas
regions are preserved. Opaque parts sharing the same image keep their existing
texture, and standalone authored DDS inputs and prebuilt imports are retained.
Rebuild the plan from the imported source to obtain the higher-precision output;
converting an already compressed exported DDS cannot recover lost detail.
The plain-PBR route reports unsupported alpha mode/cutoff and double-sided shader
semantics explicitly: preserved alpha pixels do not establish matching game
transparency. Imported glTF materials with positive `KHR_materials_transmission`
use the experimental translucent route automatically, including glass shells
around emissive gems. This keeps those shells from exporting as opaque surfaces
when translucency is selected only on another part. Authored base colours and
emission remain unchanged unless the user explicitly selects a Glow override.
Source transmission uses the default thickness and extinction
below, not a conversion of the glTF transmission factor, alpha, or transmission
texture. The export reports this approximation. Ordinary BLEND/MASK materials
without transmission retain the unsupported-alpha warning. Existing exported or
installed items need to be rebuilt to pick up these material corrections.
Template models also support Move, Rotate, Scale, Glow and **Translucency (experimental)**
without importing a replacement. Template placement goes directly into Build plan;
Reset placement restores the authored geometry. Each selected variant receives its
own PAC/material copies, preserving UVs, skin weights and unselected materials.
Placement updates every stored LOD and its packed normal/tangent frame. Unsupported
or shared vertex layouts stop planning instead of publishing a partial transform.
Glow retains an existing emission mask or supplies a solid mask for the selected part;
the layered shader uses its emissive variant. Discard clears the imported appearance
and placement, and changing the preview source clears live material overrides before
the template is loaded.

Choosing **Template model** retains an existing import so it can be selected again.
Switching away from a variant and back preserves that choice without applying the
retained import to the plan. Effects captures the selected source and the draft's
template transform before starting its worker; inactive imports and their applied
results do not override the template or acquire a preview usage lease.

**Glow > Animation (experimental)** adds **Scroll U**, **Scroll V**, **Pulse speed**
and **Pulse floor** to templates and separate imported Plain PBR material parts.
Hover over a setting or its label for a short description, including the RGB
strength, reveal, softness and inversion controls.
The shared Rust renderer blurs visible HDR emission separately from surface colour
and adds a restrained coloured bloom halo to the viewport and captures. The halo
uses remaining display headroom rather than clipping an already lit surface to
white. Archive emission uses a conservative preview exposure instead of the old
brightness boost; imported glTF retains its authored radiance scale.
Strength 1 and 4 remain distinguishable; lower strengths retain more texture detail.
The emission pass respects depth, cutout, transparent coverage, animation and RGB masks; ordinary
bright surfaces do not bloom. **Preview > Dark mode** dims the background and
scene illumination while retaining emission strength and enough fill to read
surface textures at moderate glow strengths. This is a viewport lighting
simulation; it does not add game lights or change the exported material.
Focus a material number, then use the mouse wheel to adjust it. This also works for
translucency and shader experiment fields; scrolling over an unfocused control
continues to scroll the page without changing its value.
Zero speed is static. Scrolling changes only emission UVs, so it needs a patterned
glow map to be visible. Pulse speed is the shader's raw frequency, not calibrated Hz;
the preview uses `0.5 + 0.5 * sin(pi * speed * time)`. The floor is capped by each
pixel's emission before pulsing, so unlit pixels stay dark.

**Use RGB glow map** uses the existing source emission texture. RGB supplies colour,
alpha masks intensity, and its red channel acts as the reveal mask. **RGB strength**
uses the shader's 0..1 progress intensity instead of the ordinary Strength field;
the Colour button supplies a tint. **Reveal** 0 is off and 1 shows all glow.
**Reveal softness** and **Invert reveal mask** control the transition. Softness has
a 0.001 minimum to avoid undefined division in the game shader. This route preserves
authored DDS bytes and encodes other source images as BC7 with alpha and mipmaps.
It leaves the base surface hue unchanged. A part without a source glow texture
reports an error; split atlased materials before animating their emission.

Skin parts using `SkinnedMeshSkin` or `SkinnedMeshSkin_Ver2` support static and
animated Glow in both Create New Item and Mesh Editor. Their colour, normal and
surface inputs are baked into an Emissive material, with nonmetal skin surface
channels and textures up to 2048px. RGB glow still requires a source glow map.
This conversion fixes dye colours in the baked textures and does not retain the
skin shader's subsurface lighting or dynamic skin effects; its appearance needs
in-game verification. Restore/untick or Undo recovers the original skin material.
Unsupported-material errors name the shader; animation/translucency conflicts
are reported only for a translucent material or an overlapping translucency edit.

Both options follow the selected variant, Model & Placement, Perks & Effects and
Build plan. The export uses the matching `SkinnedMeshEmissive` variant and retains
other material inputs. Shader combinations that would drop wrinkle inputs, and
animated/RGB glow on the same part as translucency, are rejected. Switching to
ordinary static glow explicitly disables a donor's pulse, scroll and RGB progress;
unticking the part restores its authored material. Viewport timing and brightness
are approximations of decoded shader behavior; this feature has synthetic GPU and
export tests, not game calibration. Mesh Editor has the same controls in Parts.

The Appearance page offers **Underlying parts (experimental)** beside translucency.
**Keep underlying skin/head** and **Keep hair/beard** default off and follow the
current equipment variant. They affect all components using that variant's mesh,
across its materials. Whole-part hide conditions apply to the entire prefab, so
skin/hair choices from its mesh bindings are combined. Other equipped items can
still hide the restored parts. Helmet-owned item hair retains its template rules.

Build plan gives the item owned prefab copies and named shrink profiles in
`character/descriptors/partshrinkdesc.xml`. Profiles omit the requested receivers,
retain incoming relationships and copy relevant depth settings. Matching conditions
from `conditionalpartprefab_postfix.xml` are copied to isolated prefab names with
only the selected skin/hair Hide targets removed. Normal appearance copies also
preserve these filename-based conditions when their new names lose the original
suffix: leaving the options off retains the template's hiding rules for comparison.
Profile names retain each original tag's byte length, avoiding binary relocation
for visibility edits. Unknown or absent component tags produce a partial-support
warning; incomplete prefabs and unsupported descriptor forms fail planning instead
of guessing. Separately, the existing mesh-path cloner may reject a readable
prefab with ambiguous pointer lengths; the error identifies that prefab and cause.

These are export experiments, with **no simulation of game cut behavior in the
preview**. Metadata checks do not establish in-game visibility. For A/B testing,
export the same translucent item once with both options off and once with the
desired option on, then compare one version at a time with the same character,
hair, pose and other equipment. Test skin and hair separately before combining
them. Other cut volumes or absent body geometry may still prevent visibility.
The plan records each selected binding, component tag and generated profile in
`new-item.json`. Shared descriptor files travel through ordinary loose export,
overlay installation and recovery. Use the previous exported mod as the base when
combining items; separately exported descriptors can overwrite one another's rules.

The Appearance page offers **Translucency (experimental)** for both template and imported models.
Enable it and tick the material parts to change, or use **Select all** to check every
part with one preview update. **Clear selection** restores source materials with
one update. Both actions retain individual absorption and surface settings.
Highlight a checked part to edit
its own settings without changing the other checked parts. **Absorption preset**
offers Clear, Light, Medium and Dense absorption; the Clear-to-Dense slider adjusts
the exported parameters together, with finer adjustment near clear glass. **Advanced**
exposes **Thickness** and **Extinction** from 0 to 1. Defaults are 0.1 and 0.3 respectively; increasing
either generally reduces transmission. Texture colour, texture alpha and viewing
angle also matter, so these values are not percentages of opacity. Selecting parts
enables Plain PBR for imports and writes `SkinnedMeshTranslucent` with `_thickness` and
`_extinctionCoefficient`, preserving the chosen parts' texture bindings. These
settings override the source glass defaults on selected parts. Other parts retain
their source glass or ordinary Plain PBR route. Settings follow each model variant;
old shared-value choices remain supported. Parts combined into one atlas must use
the same absorption and surface settings or remain separate materials.

**Surface preset** offers **Source surface** and **Low-shine translucent**. Low-shine
sets roughness to 0.9 and metallic to 0 without changing absorption. Check **Roughness**
or **Metallic** to override that channel on the highlighted part; uncheck it to retain
the original texture channel. These are absolute values from 0 to 1. Higher roughness
softens highlights and lower metallic reduces metallic reflections. Source surface
restores both source channels while retaining translucency. The same controls are
available in Mesh Editor.

Surface overrides create a private `_materialTexture` DDS for each edited material,
replacing only green (roughness) and/or blue (metallic), with full mipmaps. Source DDS,
colour, normal and glow inputs remain intact, including maps shared with other parts.
Defaults do not decode or re-encode surface textures. Both Model & Placement and
Effects apply the same explicit channel overrides in the renderer. Some game reflections
can remain; this is not a guaranteed reflection-free shader. Independent reflection
strength and refraction sliders are not exposed: the inspected normal skinned shader
path ignores `_refractiveIndex` unless its hidden depth-thickness mode is enabled.

Python-decoded template previews prepare their texture slots and convert to the
shared mesh format before applying appearance edits, preserving texture bindings
and leaving the cached source unchanged.
Native template previews retain each PAC wrapper name by its material batch index.
Glow, translucency and surface overrides therefore target the selected part in
Model & Placement and Effects, even when several parts share a material name.
Imported resident previews update without rebuilding geometry; template previews
recompose their cached native material inputs. Both restore source defaults when the
manual override is disabled. Effects previews carry the
same settings. Switching to Builder clears the automatic glass preview.
Returning to Effects after changing appearance refreshes its resident item materials.
The refresh cancels obsolete preparation while retaining staged effects and the camera;
price and other unrelated draft changes do not rebuild the preview.
For templates without a usable base-colour map, Build plan bakes only the selected
parts into Plain PBR textures before applying translucency. This uses declared
material inputs across item types, including cloth and fur on helmets, armour and
shields, without a separate shader-name restriction. Direct diffuse/albedo inputs
and the shared material combiner's colour layers, masks, tints, normal and surface
maps are prepared up to 2048px, with complete DDS mipmaps and game normal
orientation. Base colours use BC7 and retain source alpha. Authored emission masks and colours
remain bound; explicit Glow overrides still apply. Unselected wrappers and source
archives are unchanged. The plan summary identifies the baked parts: their dye
colours become fixed in the textures. This conversion is approximate; in-game
appearance remains unverified. Missing textures and decode failures identify the
part and source path instead of exporting grey replacement textures.
Dye previews use the same translucency choices as export. For prebuilt imports,
manual translucency changes only the selected shaders, absorption values and explicitly
overridden surface channels; existing glow, other parameters and unselected materials are kept.
Surface-map and RGB glow encoding receive the request's cancellation event, including
prebuilt import and dye-preview routes.
The viewport applies absorption to the background separately from reflection and
glow, without painting the opaque diffuse texture over the glass. On adapters with
dual-source blending it preserves RGB transmission through sorted, overlapping
layers; other adapters use a mean-transmission approximation. Refraction distortion,
game lighting and shadow behaviour remain approximate. These presets describe
absorption strength, not opacity percentages. The glass shader can change apparent brightness and
tint compared with an opaque material; exact colour parity remains unverified.
Verify the result in-game. Glow and translucency
can share a part: the shipped translucent parameter group declares an emissive
map and colour. Export retains those inputs and the authored strength, but the
translucent shader may ignore the separate strength parameter, so brightness
needs in-game verification. A mixed opaque/translucent atlas must be separated or all its
materials selected, and missing material selections block export.
When Glow and Translucency select the same part, a warning below the scrolling
inspector names the overlapping parts. Static glow shows the brightness caveat;
animated or RGB glow shows an unsupported-combination warning with instructions
to disable those modes or deselect the shared parts. The warning updates immediately
and follows restored variant choices.
Moving to step 3 reparents that
live viewport without rebuilding
its package or resetting its camera. Texture upgrades wait for an active drag or
orbit to finish and preserve the resulting placement. Snapshot creation
reuses Archive Browser's published path, basename and extension indexes. A valid durable
material-package hit is accepted before either preview builder, including packages
produced by native Preview Core. This cache probe never waits for unfinished texture
dependencies. On a miss, the bare template mesh loads while native materials prepare
in parallel. Its canonical material package is cached for Model & Placement and
Perks & Effects, with texture resources leased until the consuming scene owns them.
Effects uses the same archive render settings as the shared template viewport.
New Item reads the cache root from the archive owner, just as Browse Archives does;
warm-up, Model & Placement and Effects share that native cache. The shell's cache
mode and viewport settings remain connected even though the shell and archive
owners are separate objects.
Native material failures are reported instead of silently switching material pipelines.
With a resident archive session, `template_preview_dependencies.py` uses Browse
Archives' bounded association/preparation provider for every selected model and
prefab. Prepared PAC, material and DDS inputs are marked complete only after the
whole selection succeeds. Preparation is shared across previews, cached by archive
session/revision, and cancelled on replacement or shutdown. Only workers wait for it;
the GUI never reads or searches the complete archive catalogue to load a template.
The cache identity includes the native helper,
rendering inputs, and archive-file revisions so borrowed textures also invalidate
correctly. With preview caching enabled, the snapshot worker also prepares the native
service and shared material indexes using one small character model while the remaining
archive tables load. It uses the template preview's cache and captured render settings;
unfinished warm-up is cancelled and drained before the snapshot returns. Warm-up failure
does not invalidate the table snapshot, and waiting for the native service is cancellable.
On a cold native template miss, the geometry-only builder gives the viewport an
interactive mesh before texture preparation finishes. Preview Core supplies the
textured packages without recompiling their materials in Python; upgrades preserve
the host and camera. Standalone callers without native context retain the Python
preview path; a configured native material failure remains visible as an error.
Rapid appearance edits are combined over 80 ms before starting a package worker.
Material changes retain the ready mesh and its camera while the replacement prepares;
they skip the bare-mesh rebuild. Template, variant, fitted geometry and character
changes still establish a new scene. Clearing the preview cancels pending texture
work and ignores late renderer readiness.
Placement and character comparison scenes also consume that native template package.
They retain its complete material graph, layer masks, DDS bytes and material parameters
in the combined scene, including Perks & Effects and template appearance edits. Rust
composes these same layers for archive and combined previews; Python does not synthesize
the template maps again. Native resources remain leased until the scene owns its copies.
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
Identity leads with the player-facing name and description, beside the same resident
item preview. **Technical identifiers** folds the internal name and manual controls;
its summary remains visible. Checks here show identity issues only; the workflow header
and Output retain cross-step validation. Item keys and model stems stay automatic until **Manual** is
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
Its footer keeps Back, `Step N of 7` and Continue stable. Output hides Continue and
keeps the file review on the left and destination settings in a right sidebar.
The sidebar groups the **Mod folder** / **Game overlay** choices, destination,
plan status and **Write mod folder** or **Install as an overlay** action. Its
settings scroll independently while the plan status and output actions stay visible.
Choose the destination and existing-mod base first, build the plan, then review its
file changes and full details. Destination, manager, overlay number and base changes
clear the plan, including an in-flight result. The **Mod management** menu below
the output action contains Merge mods, game-update checks, Installed overlays and
Archive recovery; opening the menu or recovery controls never performs a write.
Installed overlays pairs its selectable inventory with an item preview on the
right. Overlays containing multiple items expose an item selector. Folder,
file-count and build details appear on hover to leave room for readable names.
Preview work re-reads the installed overlay's index and metadata on the preview worker, so a
Studio snapshot taken before installation cannot substitute the old template.
Changing selection cancels obsolete preview work; closing retains the worker and
any reparented Rust viewport until shutdown finishes. Overlays without mounted
item models show an empty state. Remove selected uses the selected inventory row
and keeps its existing review, confirmation, backup and rollback flow; unmounted
history points to Check game updates or Start fresh instead.
**Build plan** stays beside the review heading, and the adjustable divider gives
the review most of the page width. **Activity log** expands below the review and
starts collapsed; collapsing it retains its messages, and an output error opens it.
The left review area scrolls independently, keeping progress and output actions visible.
An overlay installation failure also opens a warning and keeps the reason visible
on Output after the worker stops; the plan remains available for review or retry.
The confirmed install automatically handles a stale previous set whose folder is
no longer mounted: it prepares one retry using a fresh inventory and an unused
folder, preserving the old overlay files and journals. The archived inventory and
new install share one verified backup and rollback; a failed retry restores the
previous inventory and metadata. The install confirmation explains this recovery,
and the success report names the archived history. Mounted overlays, another
mounted CDMW group, an explicitly chosen occupied folder, and unrelated failures
remain blocked. The installer does not loop retries or overwrite the old folder.
If the saved texture registry or overlay files changed, **Installed overlays >
Check game updates...** compares the recorded set with the current game before
recovery. Refreshing the archive list or rebuilding a plan does not repair that
state. Saved overlays whose folder is absent from the game's mount list show
**Not mounted**, even though their files and installation dates remain in history.
For an unmounted set you no longer want to use, **Start fresh...** reviews all its
labels and the exact game folder, then requires confirmation. It verifies a backup
of `.cdmw/overlays.json` and archives that inventory under `.cdmw/retired-overlays/`.
The old overlay folder and journals remain on disk; current game archives, the
mount list and the texture registry are unchanged. Rebuild the item plan and use
**Auto** to install into a fresh inventory and an unused folder. Mounted overlays
still use normal removal. Starting fresh refuses changed inputs, a running game,
missing recovery data, or another mounted CDMW group. A failed retirement restores
its inventory backup; comparison and preparing the confirmation are read-only.
Shared section cards and accent primary buttons keep
Continue, Build plan and Apply placement visually distinct, with palette-based
hover, pressed, focus and disabled states. Step 5 is a
non-scrolling full-height page with **Effects** first and **Experimental Features
(Perks, Sockets, Bonuses)** second. Perk selection, socket capacity/costs and
inherent bonuses share that second tab with adjustable panes and growing lists;
available and selected perks have aligned headings and a shared compact action row.
Individual perk names omit experimental suffixes;
perk details and experimental limits are available on hover. The navigator is a
compact 46 px row; the outer pages do not
repeat numbered titles underneath it. Distribution fills the available height;
Shops scrolls independently, while recipe ingredients/outputs and reward routes
use the remaining workspace. Recipes and Loot and rewards are marked experimental.
Longer active content remains scrollable. Perks & Effects keeps gameplay perks separate
from visual-only effects. Perks are chosen through searchable Available and Selected
lists that grow with the workspace rather than a popup catalogue. Perk search, labels
and tooltips share one lookup for the immutable English table; loading a different
table replaces it so descriptions stay current. Four perks is
the evidence-backed default cap and five to eight requires an explicit experimental
opt-in. Effect support is structural rather than equipment-name based: the service
dry-runs the real component graft against every prefab the item will own, accepts only
an all-target success, and never edits a shared borrowed prefab. The Effects tab uses
24 px virtualized table rows with the specific variant before its source family,
reviewed word splits, preserved numeric suffixes and visible Category, Type and
approximate Size columns; the exact stem stays searchable and
appears in selection details and tooltips instead of being repeated under every row. `No effect` is the
empty-state row. The library starts open; **Browse effects** toggles it from the left end of the
Effects tab bar, above the library and alongside the selected effect name. Its larger,
bold button uses the active theme's accent colour so it is easy to find even when the
library is folded. Rust retains usable pane widths when it is reopened. Playback
controls are grouped at their natural widths and wrap at the rendered pane width.
Independent corner-label changes no longer invalidate tab navigation, and rejected
Rust inputs are recorded in Activity rather than a banner above the workflow.
The library keeps a short search field below
its heading and result count, with the category selector beside All / Loops / One-shot.
There is no separate search row above the viewport. A compact footer keeps the preview
notice and compatibility messages visible when the library is folded. Search matches words in the
readable name, category, exact stem, emitter, texture, mesh and preset metadata.
For example, `fx_aftertaa_a__lightning_att1` appears as **Lightning ATT 1 · Aftertaa A**.
Unknown artist/character names and ambiguous codes such as ATT and EXP remain intact.
Categories match complete words and reviewed compounds, so fireflies are Wildlife,
medicine is not Frost, and generic shock effects are Impact rather than Lightning.
The specific variant supplies the primary category, with other explicit family
traits retained as filter tags. Authoring, emitter and non-utility resource names
are fallbacks only when the effect's own name supplies no category. Tooltips make
this inference explicit; names do not prove appearance or game compatibility.
The background
index follows emitter and render/simulation preset dependencies once per definition;
schema 2 invalidates old caches and includes dependency paths and archive locations.
Missing definitions are shown in tooltips without hiding otherwise usable effects.
Effects with missing or incomplete timing metadata show **Unknown**, rather than
being assumed to be one-shot. Explicit loop flags or a loop-name hint remain usable.
Labelled All / Loops / One-shot filters,
a result count and Reset filters make browsing explicit; the staged selection remains
visible even when it falls outside the filters. Library labels and facts are
prepared in short event-loop slices and reused across filtering and placement
changes. Unchanged rows retain their selection and layout, and metadata column
sizing samples a bounded number of rows even while the page is hidden. Returning
to Effects keeps the resident scene; changed inputs and failed updates still retry.
Favourites and Variants narrow the library. The star, filters and Large thumbnails
show their selected state, and library buttons respond visibly to hovering and pressing.
Variant families use the source prefix before `__`, grouping named smoke, fire and
spark variants together. Names without that separator retain the bounded numeric
suffix grouping. Generated layer and emitter labels use the same readable names;
custom layer names and exact exported effect references stay unchanged.
**Capture thumbnail** saves the current preview
frame into the local library and reports capture progress, success or failure. A saved
capture immediately replaces the displayed image and enables **Large thumbnails**,
which expands the rows and loads only visible cached images. Failed captures retain
the previous thumbnail. Saved recipes contain references and settings, never game assets.
A replaced snapshot or catalogue cancels the previous preparation;
shutdown prevents late catalogue events from restarting it. The hidden legacy
selector mirrors only the committed choice. Item preview preparation starts when
Effects becomes visible, with one initial request, instead of decoding the item
while another step is open. `effect_item_source.py` captures the selected import,
placement, glow, snapshot and template key without decoding them. Item parsing and
baking then run in the existing placement package worker alongside effect preparation;
cancelled requests cannot publish their item mesh, and source leases last through
worker teardown. The preview thread is fully constructed before it is attached to the
resident widget, so child observers cannot resolve an incomplete Qt thread wrapper.
A single inspector has **Placement**, **Look**, **Layers**, **Emitters**
and **Saved** tabs, with Apply and Discard pinned below their local scroll areas.
Placement and Preview options are independently collapsible and start expanded.
Layers add up to 16 effects with independent placement,
visibility and appearance. Selecting another layer does not itself create a draft edit.
The inspector tabs size to their active contents and keep actions together at the top.
The preview tools, playback controls and Show gizmo share one compact toolbar;
Rust uses tool icons with hover labels. The toolbar wraps only when its controls
cannot fit the available width. Library actions also share a wrapping row rather
than separate rows for each group. Extra workspace width goes to the viewport, while the inspector remains
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
it never changes the draft, placement or camera. Move, Rotate and Scale use the thin
transform handles. The solid origin and axis helper meshes stay hidden, including
after scaling or restarting the renderer, so they cannot cover the effect. The reach
cage remains optional through **Show the reach**; toggling it does not move the camera.
Initial placement starts beside the combined item and character bounds with a small
gap, converted back to item coordinates for held weapons. Choosing another effect keeps
the current position, including a deliberate move to zero or browsing through
**No effect**. Saved positions and explicit layer changes retain their own placement;
changing the item or choosing Discard restores the draft's placement. Selection,
placement and look are staged; Apply publishes one draft
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
The standard simulation uses the authored force as acceleration without dividing by
particle mass. This keeps light fire and smoke particles from forming exaggerated
trails; placement, size and colour settings remain independent. The preview still
approximates game materials, lighting and environmental interactions.

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
Inherited curves and material parameters resolve by stable binary collection keys;
removed parent curves are not restored by preview or recipe compilation. The emitter
inspector exposes infinite particle life and repeated lifetime curves independently
of emitter looping. Scalar brightness, including a declared omitted unit default on
an unpreset emitter, is editable through the checked writer. Export resolves effect
namespaces from the active game registries and keeps that suffix on edited clones.
Mesh particles keep complete supported geometry; unavailable geometry no longer draws
an invented gray marker. Untextured particles use mesh coverage, and every reported
limitation remains visible through the approximation notice.
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
and the final Builder use. The Origin anchor targets that applied origin for wearables;
the initial effect position remains beside the subject. A
feet-at-zero bind-space stand-in is used when the matching archive body is unavailable.

The Model & Placement step puts a tall resident preview beside one resizable inspector.
Model selection, import actions, variant selection, preview controls, status and icon
capture share the right inspector with Placement, Appearance, Dyes and Icon. The viewport
uses the full left column; Apply placement stays fixed beneath the inspector's scroll area.
The active tab uses its natural height as sections expand or collapse, keeping spare
space below the controls. Captured icon thumbnails stay in Icon.
Controls retain their values when switching tabs or resizing.
When the two columns cannot fit, the inspector stacks below the preview. Neither widget
changes parent on resize, preserving the resident renderer and current control values.
Full import notes, FBX setup and Quick turn expand on demand; Glow details collapse while off.
Long or expanded inspector content scrolls locally while Apply placement remains visible.
Distribution's Item groups list fills its page and scrolls internally. Checkable section
headers such as Glow and Translucency use the theme's visible indicator states, including
OLED Black, consistently with ordinary checkboxes and radio buttons.
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
weapons. Import and **Fit to template** level held models against the template's broad plane,
retaining their heading and grip anchor. Wearables retain the template's authored
body orientation and centre, so a garment already aligned to the body stays aligned.
Shapes without a clear axis or plane retain the bounding-box fit. The template stays
fixed, and manual rotation remains available. The fit is baked into the mesh shared
by the preview and **Apply placement**.
Apply captures the import settings before its worker starts. A change to texture
flipping, source geometry, placement, variant or model choice prevents the old result
from becoming applied. Appearance-only changes retain that geometry build and use
the latest material choices when planning output.
`item_preview.py` owns the resident frame and publishes fitted geometry, direct
DDS textures, and then the complete synthesized material tier without resetting
the resident camera;
`item_preview_materials.py` owns placement-scene composition and the copied-package
canonical-material upgrade, without restarting the renderer, re-exporting geometry or resetting
the camera. `panels_model.py` builds the preview and tabbed inspector while
`panels_model_preview_mixin.py` owns its preview, placement, import and icon interactions.
FBX conversion relinks an explicitly referenced missing image by exact basename
from the extracted package's nearby texture folders; the shared preview then supplements an
embedded base with clearly named Normal, AO, Roughness and Metallic maps without treating a
Thickness map as colour. DirectX normal-map suffixes remain in the same material
group and retain their normal orientation. For converted FBX only, a newly matched
loose colour, roughness or metallic map replaces that channel's legacy conversion
factor with an identity multiplier. Explicitly linked channels and untextured
materials retain their source factors, including gem colours, opacity and glow.
The corrected factors follow the imported mesh into preview and output preparation.
The shared Rust preview package encodes separate roughness, metallic, occlusion and
specular images from material inputs as well as the top-level colour, normal and
packed maps. It retains source DDS priority, packed-channel ownership and image
deduplication. Imported preview caches rebuild when this material handoff changes.
A textureless exported material still keeps its authored
`TEXCOORD_0` channel instead of triggering an unnecessary auto-unwrap. Generated material
synthesis is deduplicated across identical submesh inputs.
In the compact shell, model import, Apply and preview loading appear beside Ready
and Cache Healthy in the bottom status bar. The controls
use one compact row, with full status text on hover, and take no space from the
right inspector. They hide when idle or when another tool is active. Standalone
and legacy-shell workspaces retain their loading bar above the placement actions.
Apply runs through the controller's cancellable progress lane; its spinner, current phase,
percentage when available and Cancel action remain live while conflicting placement edits
are disabled. Preview-loading text stays in that operation bar while errors and
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
plane, so the template reads flat without changing any model coordinates. Views looking straight
along Y keep positive Y pointing up when orbiting away from that flat view. Move, Rotate and Scale
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
Character visibility is part of the composed scene's cache identity for every texture
tier. Texture upgrades retain the selected comparison mode, and rapid on/off/on
changes restart cancelled work while rejecting its late results. Old appearance
packages rebuild once so cached scenes cannot restore an outdated character state.
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
installation is `ArchiveMutationService` through the service's `install_overlay`, and the
loose export is built in a sibling staging directory and published only when
complete. DMM archive groups are readable as mod bases, so repeated exports
carry earlier items forward. Select the same mod folder with **Add to the mod already in this folder**
enabled, then rebuild the plan for each additional item. Choosing that folder
invalidates the previous plan and reuses the loaded archive reader when rebuilding.
Separate New Item mod folders can replace the same shared tables, so enabling both
in DMM can hide items from the earlier mod even when their item keys differ.
**Merge mods** opens `mod_merge_dialog.py` without requiring a template or draft plan.
Choose at least two loose or DMM mod folders, the game folder that supplied their
baseline, a package name and a new or empty destination. **Check compatibility**
reports conflicts and the resulting file list; **Write merged mod** produces one
DMM package. Enable that package in place of the selected originals.
`mod_merge_workers.py` uses the controller's serialized `mod_merge` lane for scans
and export. Closing the dialog cancels its work without waiting and drops late
results. `mod_merge_service.py` checks recorded source hashes against the game or
selected base mods, then composes supported tables through the overlay merge rules.
Texture registrations require recorded CDMW ownership and matching DDS payloads.
Inputs are checked again before atomic publication. The source mods and game
archives are read-only throughout this workflow.
Duplicate item or generated recipe IDs, conflicting asset contents, missing baseline
history and unsupported shared changes block export. The merger does not reassign
identities or rewrite their references automatically. New Item's direct archive-install
button is removed; its compatibility service entry point refuses every call.

**Tools > Check mods for game updates...** compares an exported mod folder or all
installed CDMW overlays with the current game. The same action is available beside
**Read the archives** before the item catalogue loads. Disable an exported mod in its mod
manager before comparing it. Installed CDMW overlays are excluded from the current
game baseline and reviewed together using their recorded installation history.
Comparison resolves each archive table's location once for the whole lookup.
The progress bar shows measured percentages and completed/total work for the
current stage, including archive indexes, file lookup, overlay history and file
comparison. It restarts for each stage; these counts are not a time estimate.
Stages without a known work total show their activity without a percentage.
The review shows the original and current game builds, compared files, missing
originals, changed dependencies and merge conflicts. Supported independent table
changes can be carried forward; conflicting records, reused IDs and overlapping
opaque asset changes require review and block automatic output.
**Write updated mod** creates a separate DMM package in a new or empty folder.
Enable that package in place of the original. For installed overlays, review
**Archive recovery** before replacing the installed set. Comparison and export
never alter the source mod, installed overlays or game archives.

New exports record the full available game build and executable fingerprint, file
hashes and original payloads in `cdmw-compatibility.json` and `cdmw-baseline.zip`.
DMM exports keep these records and `new-item.json` under
`%LOCALAPPDATA%/CrimsonDesertModWorkbench/mod_export_history`. The exported
folder contains the archive group, `meta/0.pathc` when needed, `manifest.json`,
`modinfo.json` and `README.txt`. DMM rebuilds its own `meta/0.papgt`, so that file
is omitted too. This applies to New Item, merged and updated DMM packages.
History lookup verifies the exported contents; copied or renamed folders remain
usable on the same computer, while changed package contents cannot reuse stale
history. Extension, merge and update read local history automatically. A shared
DMM package does not carry that history to another computer; retain CDMW's local
history when moving authoring work. Other manager exports and older packages
keep their inline records, which remain readable.
Original payload storage is bounded to 256 MiB per file and 512 MiB total;
unavailable or larger originals remain explicitly unknown. New Item exports also
record the dependencies read while building the item. Installed overlays carry a
game stamp in their existing transaction history, and their list shows **Built for**
and **Game check**. A known game build change prompts a new comparison; a matching
build is not a gameplay compatibility guarantee.

Older mods without recoverable original data remain **Unknown baseline** and
cannot be updated automatically. Old source hashes can establish that existing
data is unchanged, but cannot reconstruct lost pre-update data. A successful
comparison covers recorded files and dependencies; gameplay still needs testing.
`mod_update_service.py` owns comparison and separate package publication.
`mod_update_workers.py` uses the controller's serialized `mod_update` lane;
closing the dialog cancels work without waiting, discards late results and leaves
an incomplete package unpublished. Both source inputs are checked again before
publication.

Game overlays carry a CDMW ownership marker;
install, migration and removal ignore foreign numeric groups and roll back every
post-backup failure or cancellation. Temporary model extraction roots are retired when
their import is replaced, discarded, fails, or the studio closes. Model, Effects and
Mesh Editor-accept workers lease the source while they read it; recursive removal runs
on a tracked cleanup worker only after those usages finish, so Discard cancels first and
never waits on filesystem cleanup in the UI thread.
Retired transient preview packages use the same tracked cleanup lane. Parallel
geometry/material preparation also owns its cleanup: cancellation joins the
material thread and removes completed packages that never reached the UI.
Successfully delivered stages and durable cache entries keep their ownership.
Cleanup is serialized, remains visible to the shutdown coordinator until drained, and cannot
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
or the legacy monolithic localization tables. Both raw tables and tables with
the 512-byte `paloc` LZ4 container are supported. New names preserve the source
container and its opaque header bytes; untouched tables rebuild byte for byte.
Unreadable encrypted tables retain the parser's reason and archive source in the
error message, including unsupported container versions, rather than collapsing
every failure into a ChaCha20 error. Unsupported data cannot produce an item plan.
Initial-load and refresh failures show contextual next steps and a **Copy error
report** button. **Details** previews the same report: error code, workbench and
runtime versions, UTC time, exact error and the last twelve loading messages.
Reports use existing progress only, do not read more archives, and replace configured
game-folder and user-profile prefixes with placeholders. Copying is local; users add
their game version, active mods and reproduction steps before sharing. Retrying
clears the previous report, and successful loading hides the panel.
Unspecified text falls back to English using the existing derived keys.
Arabic is an item-text option, not an
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

**Distribution → Recipes** owns enhancement/crafting recipe authoring, alongside
Shops, Loot and rewards, and Item groups. Stats & Prices stays on its own step;
its enhancement and shop-price tables fill the available height, with an adjustable
divider between them. Both presentations retain cell editing and table scrolling;
the panes stack in narrow windows, and expanded Advanced controls scroll separately
so they cannot collapse the stats table. Open recipes directly under Distribution,
retaining the editor's current selection and edits. A selected
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
Template dye previews first prepare current Glow, Translucency, shader and placement
edits. Explicit mappings on the same compatible material retain appearance edits and
change only the dye assignment or requested mask. A donor swap or incompatible shader
conversion that would replace an edited material is rejected; remove the dye mapping
or restore those appearance edits. Clear dyes retains an explicit empty override even
without other edits, and remains cleared when switching variants and building the plan.

**Imported armour:** complete wearable replacements transfer weights from the whole
compatible template surface, independently of its material sections. Partial edits
retain their selected part's donor. Build plan resolves the template's declared PAB
through `cdmw/core/skeleton_resolver.py`, including descriptors outside the model
folder, and checks the rebuilt palette and every weighted index. Rigid helmets keep
their prefab attachment; deforming headgear uses its character rig.

Some torso templates carry influences beyond their resolved character palette. For
an unrigged scene import with **Template cloth / physics** off, Build plan can rebuild
those weights from the matching, verified character body used by the existing
character preview. `cdmw/services/new_item_skinning.py` maps body bones into the
armour's own palette before transferring weights. Body triangles with no compatible
influences are excluded. The body and PAB are tracked snapshot inputs and stay
unchanged. The plan names the donor and warns to check fit and deformation; distant
surface matches also warn. Valid imported bindings stay intact. Authored source
weights, a changed palette, retained template physics, or a missing usable body do
not receive this automatic transfer.

The normal scene-import path supplies geometry for template/body weighting; this
does not add external bone-name or animation retargeting. New topology does not
rebuild cloth simulation. Body coverage, clipping and companion appearance still
need inspection. The existing animation/skinning tools can check the planned PAC
against PAB/PAA motion; headless deformation is not proof of in-game equipment or
physics behavior. Skin-transfer notes and fit/material warnings survive material
routing and appear in Build plan for their own variant.

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

The September 9 wearable import check combines template materials and changes mesh
topology before importing an unrigged OBJ. Nine variants pass Apply and Build plan:
weighted and rigid helmets, gloves, boots, lower body, a cloak and three torso
armours. Eight final planned PACs pass exact PAB binding and nine sampled frames of a PAA walking clip,
including deformation beyond root translation; the rigid helmet keeps its prefab
attachment and has no CPU socket-animation claim. The torso plans use the verified
body donor. These are read-only headless checks, with unchanged source archives.

Synthetic fixtures cover edited round trips, ownership, empty/inherited overrides,
exact duplicate-shop selection, multiple imports, cancellation/leases and second-item
base preservation. The optional live-corpus tests fail on missing required tables.
Licensed payloads and local reports belong outside tracked fixtures. File-level,
headless and material-preview evidence do not close gameplay acceptance: bonuses,
unlock costs, recipes, dyes, animation/variant appearance and acquisition still need
recorded obtain/equip/use observations and restoration using a reviewed temporary
package. Installation/restoration continue through `ArchiveMutationService` with
the exact mutation confirmation and recovery checks.
