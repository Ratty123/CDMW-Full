# Mesh Editor

## Contents

- [Layout and shared controls](#layout-and-shared-controls)
- [Feature ownership and scope](#feature-ownership-and-scope)
- [Edit, export, and reopen](#edit-export-and-reopen)
- [Parts and appearance](#parts-and-appearance)
- [Opening meshes and preparing sessions](#opening-meshes-and-preparing-sessions)
- [Collapsible panels and tool icons](#collapsible-panels-and-tool-icons)
- [Hair creation](#hair-creation)
- [Replacement workflow](#replacement-workflow)
- [Cloth influence](#cloth-influence)
- [Vertex Parameters](#vertex-parameters)
- [Existing editing controls](#existing-editing-controls)
- [Preview compatibility and output](#preview-compatibility-and-output)

## Layout and shared controls

### Editable mesh exchange

Editable packages include GLB, FBX and OBJ versions, portable texture files and
CDMW companions. Use GLB when keeping PBR materials, multiple UV sets, vertex
colors, a resolved rig or morph targets. It embeds textures and retains existing
animation clips; animation editing is not supported.

Keep the companion beside the edited mesh. It retains source hashes, LODs,
unknown game data and protected channels. Re-import checks vertex and joint
identity before rebuilding the original mesh. Enable **Data > Mesh > Attributes**
in Blender's glTF export options to keep `_CDMW_VERTEX_ID` when returning GLB,
or keep the `CDMW_VERTEX_ID` UV layer when returning FBX.
Unproven identity, changed topology and unsupported game channels are rejected.

For GLB or separate-file glTF returns, set **Use Vertex Color > Active** and
enable **Include All Bone Influences**. Select the model meshes and armature,
then export selected objects only; exclude the rig's bone-display shapes. Disable
modifiers that change topology. Keep the matching companion when switching
formats: it recovers omitted UV sets, texture bindings and protected channels,
and restores static OBJ geometry to the original local coordinates. Imported
UVs, existing texture bindings and material values retain their edits.

FBX import uses the Blender executable selected on Create New Item's Model step.
Conversion runs in the background, supports cancellation and publishes only a
completed result. OBJ/FBX texture copies include material factors that Blender's
legacy readers otherwise ignore; original images remain in the package.
Companion reports list missing inputs and format limitations. OBJ retains rigs,
morphs and extra UV/color data in the companion. Exact material extensions,
samplers and animation clips require GLB for exchange.
Split OBJ exports retain each part's source identity, rig, scene graph and existing
clips in its companion. A single split part cannot rebuild an entire game mesh.

Tools, Inspector and pinned tool panel widths, plus floating tool positions,
are saved in CDMW's user `.cfg` and restored for new editor sessions. The helper
receives them in the initial theme's `layout` field and publishes bounded,
session/generation-correlated `layout_changed` events. These presentation events
bypass authoring workers, mesh revisions and Undo/Redo. The shared
[layout persistence policy](../shell/README.md) also covers the Qt character
context pane and detached editor window.

[Shader experiments](SHADER_CONTROLS.md) extend
the selected-parts workflow with captured material dependencies, Undo/Redo and
replacement draft version 12. Static Dissolve stays object-only.

### Precise numeric controls

Click a number to type an exact value and press Enter to apply it. While the
number is focused, hover it and use the mouse wheel or Up/Down to adjust it.
The **⋮** menu beside each number selects its increment, including **0.1**,
**0.5**, **1**, smaller steps and a custom increment. Number dragging and sliders
use the selected increment; typing remains independent of it. Each control
remembers its increment for the editor session. Count fields use whole numbers
and all existing limits still apply. Scrolling an unfocused control scrolls
the panel without changing its value.

Sliders use a full-width track below the number, increment menu and label.
Tracks within a section have the same alignment, width and theme styling,
independent of label length or numeric precision. Disabled controls retain
their disabled appearance.

This applies to Cloth preview and profile settings, transforms, brushes,
topology, UVs, Morph & Refit, rigging, Hair Tools and material settings.
Colour swatches also have **RGB** or **RGBA** channel menus for numeric editing.
Vertex Parameters also supports stepping while retaining its staged Apply
workflow and blank **Unchanged** fields.

## Feature ownership and scope

Owns the direct, mesh-only Mesh Editor tab shell, typed archive-session requests,
resident authoring workspace, and output orchestration. Archive internals and
destructive writes stay outside this UI package. Static-replacement builder
hosting remains compatibility-only in this tab. Archive Browser's separate
**Replace Mesh from File...** workflow is temporarily disabled for release review;
its retained implementation does not replace the active Mesh Editor session.
Use the editor's **Import Replacement...** workflow for supported replacement edits.

The current product boundary is geometry authoring: selection, topology,
transforms, normals/tangents, rigging, Morph & Refit, UV-coordinate editing,
history, original-vs-edited review, validation, and read-only textured display.
Replacement imports, reversible output inclusion, experimental translucency and glow
extend that foundation through the Inspector's Parts and material controls.
General material assignment, recolouring and in-game swaps remain separate
workflows. Hair Appearance has a scoped DDS handoff.

## Edit, export, and reopen

Choose the reopening route by what you need to recover or verify:

| Action | State it reads | Persistence and proof boundary |
|---|---|---|
| **Resume current edit** after Finish | The accepted mesh in the existing `MeshService` session. | Keeps the original source reference and accepted state; the reopened editor starts a new per-action history. It does not read a package from disk. |
| **Start next edit pass** | Validated rebuilt game bytes and retained source dependencies. | Makes the edited bytes the next baseline and clears the previous pass's edit state. This is an in-app continuation, not restart recovery. |
| **Add to Archive Browser**, then open **Edited results** | Prepared entries with source identity, rebuilt-byte hashes and dependency context. | Results survive closing the editor, but remain local to the current CDMW app session. |
| Resume a matching saved draft | The source-bound workspace and newest valid saved generation, or its previous valid generation. | Recovers authoring state, not the last exported mod. Source-fingerprint mismatch refuses recovery without deleting the draft. |
| Open the exported mesh/package payload | The file at the completed output path, with its required companions. | Establishes output readback only when those exact bytes and dependencies are used. Opening the original archive entry does not establish this. |
| Preview an installed overlay | The currently mounted overlay and its metadata. | Checks installed content, which can differ from both the live edit and an uninstalled export. |

For an existing game mesh, start from the exact archive entry through **Modify
Original**. Retain its archive path and source hash: the same filename can occur
in stock archives, prepared edited results and mounted overlays. `ArchiveEntry.identity`
identifies the source location; `prepared_sha256` identifies prepared bytes when
present. Neither a filename nor a session revision alone identifies a portable result.

**Finish Edit Mesh** accepts one validated revision into CDMW. Its successful
validation remains usable by **Build Mod** until a later edit invalidates it.
Finish does not write the mod folder, install an overlay, or by itself prove that
a recoverable draft was saved. Draft autosave applies only to sessions with an
associated project path; it records mesh/layer revisions separately from output
validation. If saving fails on close, retry saving or explicitly choose to close
without saving. Keep the workspace manifest, project descriptor and generation
files together; copying only `mesh_layer_project.json` is insufficient.

Choose the output appropriate to the session. Archive-bound sessions can **Build
Mod** with all generated companions. **Export Mesh File** is a separate rebuilt
asset route and is unavailable when required replacement companions cannot travel
with it. Free Edit uses **Export Free Edit Package**; Finish only accepts its
geometry after checking the chosen destination. Editable GLB/FBX/OBJ exchange
packages retain their own [companion contract](#editable-mesh-exchange).

To verify a finished export, record the accepted revision, source hash, final
output path and hashes of the mesh and generated companions. Read the published
files, then compare a known edit and the relevant materials/LOD data against the
accepted result. Keep the original archive and any earlier package distinguishable;
a matching preview with no file provenance is insufficient. Unchanged dependencies
may still come from the original game data, so a mod package is not automatically
a self-contained editing project. See [validation and export](#validation-and-export)
for package layouts and the separate installation boundary.

After an uncertain export outcome, inspect the final folder and optional ZIP
before retrying. These mesh-package routes refuse existing destinations; use a
new destination after identifying the completed output rather than deleting it
to make a retry succeed. Keep rejected draft generations for diagnosis. A recovered
generation may be older than the newest save attempt; identify the loaded generation
in any verification record.

The owning code is [Finish publication](tab_rust_process.py),
[output orchestration](tab_direct_output.py),
[draft persistence](../../services/mesh_layer_project_service.py),
[source-bound draft discovery](../../services/modify_original_workspace_service.py),
and [edited-result preparation](../../services/mesh_archive_results.py).

## Parts and appearance

Click **Parts** in the Inspector to open a resizable panel using the full editor
height, with separate **Parts** and **Mesh islands** tabs. Each tab has one
scrolling area; switching tabs or reopening the panel retains its scroll position.
Use **Back to Inspector** for **Translucency (experimental)**, **Glow (experimental)**,
**Shader experiments**, **Geometry Layers** and **Action History**. Part selection
is retained when navigating between these tools.

Parts use compact single-line rows with aligned **View** and **Include** columns.
**View** only affects the viewport; **Include** controls exported output. Physics
badges occupy a separate column. Long names and badges truncate; hover for the
full name, material and physics evidence. Selection, visibility, Duplicate, Delete
and output-policy controls stay above the scrolling area. Replacement import,
comparison, placement and mapping controls remain available in the Parts tab.

### Mesh islands

Open **Parts**, select a part, then switch to **Mesh islands** to address disconnected
pieces inside that part. Selecting an island selects its faces for the existing
move, rotate, scale and Free Edit tools; it does not create a new material or part.
The island list is separate from the Parts list and groups islands by their source
part. Each compact row contains its selectable name, **Isolate**, **View** and
**Include**. **Show all islands** stays above the list. Long names retain their
full text on hover. Hover over the tab for selection and seam grouping guidance.
Coincident UV-seam vertices are grouped at 1e-5 model-unit precision without
welding or moving the model. Existing **Linked** selection still follows vertex
indices when that stricter connectivity is wanted.

- **View** hides only that island in the viewport and picking. **Isolate** shows
  only that island within its part; **Show all islands** restores viewport masks.
- **Include** includes or excludes the island from the exported PAC, independently
  of View. **Preview output** shows the export result. Undo/Redo and saved drafts
  retain exclusions; re-enabling an island restores its source triangles.

Island inclusion requires an original PAC at LOD0 with unchanged topology. Disabled
controls show the reason beside the island list. After Morph & Refit, replacement
import or supported topology edits, use **Finish Mesh > Continue editing modified
mesh** to start from the rebuilt PAC before changing island inclusion. **Reopen
Edit** resumes the existing editing state and does not establish that new source.
Free Edit publishes OBJ; its island selection, View and Delete controls remain
available, while game-format inclusion is unavailable. Lower
LODs can use exact source positions or safely separated component bounds, including
pieces that split or disappear as detail decreases. The simplified component must
fit wholly within one source island's bounds, expanded by at most 10% of the bounds
diagonal and one third of the gap to its nearest neighbour. Overlapping source bounds,
including interlocking accessories, can also use exactly retained UV and skin
records, including palette-resolved bones and weights when guide/mask data varies
between LODs. Every vertex in a lower-LOD component must have an unambiguous source
inclusion. Movement must stay within one incident-edge length of its matching vertex
or one of that vertex's directly connected neighbours in the preceding LOD. This also
supports simplified corners that move beyond the matching vertex's own edge radius;
distant vertices of the same component do not extend that local allowance, nor do a
neighbour's longer edges. Every vertex of the preceding component must also have a
consistent, proven inclusion. Changed normals do not invalidate retained records.
Reused records spanning included and excluded islands, conflicting positions,
components crossing inclusion boundaries and unproven movement remain rejected
before changing the session.
Excluding the last island automatically uses the same hidden-part output as the
whole part's **Include** checkbox across stored LODs. The island controls stay available
to restore individual islands, and Undo/Redo retains the choices. Partial exclusion
suppresses only selected triangle indices across LODs and retains vertex data,
materials and bindings. If every surviving island at one lower LOD is excluded,
that LOD retains a tiny valid triangle with identical donor skin/guide records at
its corners, preserving the part slot without stretching under animation. Output is
rejected if the stored position precision cannot represent an invisible triangle.
Other parts and retained vertices remain unchanged. Drafts containing these masks
use replacement version 13; older drafts remain readable. View masks are temporary
presentation state.

Overlapping translucent islands can still expose shader limits. See the
[EyeCover overlap investigation](EYECOVER_OVERLAP.md).

### Glow on parts

Select parts and expand **Glow (experimental)** for colour, strength, emission UV
scrolling and pulsing. **Apply glow** stages an undoable edit; **Restore glow**
returns to the captured source material. **Use RGB glow map** retains source RGB
and alpha, with red-channel reveal, softness, inversion and a separate RGB strength.
See [Create New Item's glow controls](../new_item/README.md) for the shared semantics
and shader limitations. RGB glow needs a source glow map. Animated/RGB glow and
translucency cannot share a part; unsupported shader switches report a reason.

These edits work on original PAC parts and replacement parts with their captured
material sidecar. Edits resolve the PAC part's exact material wrapper before its
fallback material label; sharing a texture label does not tie independent parts
together. Parts bound to the same wrapper require matching settings. Glow, translucency
and shader experiment numbers have sliders and editable values. The viewport reuses
loaded textures; only material parameters change. Edits survive Undo/Redo, Finish, Build
Mod and saved drafts (replacement draft version 11 when glow is present).

Material-only output keeps PAC geometry bytes unchanged and patches only selected
material wrappers plus a solid glow DDS if needed. Restore uses the original inputs
rather than attempting to invert an already modified XML.

### Translucency on parts

Select one or more parts, expand **Translucency (experimental)**, set **Thickness**
and **Extinction** (0–1), and click **Apply translucency**. This works on original
PAC parts and imported replacements in an eligible item session at LOD0. There
is no New Item requirement. **Restore material**, Undo and Redo recover the
previous material; Finish and saved drafts retain the choices. Restoring an
imported part keeps its imported materials. Drafts with captured dependencies
can be edited without the archive mounted.

**Source surface** retains authored roughness and metallic textures. **Low-shine
translucent** sets roughness to 0.9 and metallic to 0, keeping absorption unchanged.
The **Roughness** and **Metallic** checkboxes enable independent absolute channel
overrides from 0 to 1. Uncheck a channel to retain its source texture. Higher roughness
softens highlights; lower metallic reduces metallic reflections. These controls
match Create New Item and are retained through Undo/Redo, Finish and saved drafts
(replacement draft version 10 when a surface override is present).

The viewport reuses its prepared textures for absorption and surface changes and keeps
emission. Export changes the selected PAC XML material to `SkinnedMeshTranslucent` with
the two absorption parameters. Explicit surface overrides export a private
`_materialTexture` DDS with roughness in green and metallic in blue, preserving unedited
channels and complete mipmaps. Other parameters, colour, normal and glow paths stay
intact; shared source DDS are never overwritten. Material-only edits keep the PAC bytes
unchanged.

Layered materials without a usable base map use New Item's shared texture preparation,
baking colour and surface maps up to 2048px. Baked dye colours become fixed; missing
declared textures or unusable colour inputs stop the edit before it is committed.
Prepared maps are reused for absorption adjustments. Shared wrappers require the same
settings on all their parts; missing sidecars and unmatched wrappers report an error
before applying. Free Edit meshes without the original PAC binding are outside this
export route. Authored `SkinnedMeshTranslucent` sidecars also supply absorption on
reopening.

Existing renderer packages rebuild once to pick up this interpretation; source DDS
caches remain reusable.

This is an experimental approximation: the viewport does not reproduce game
refraction or coloured background transmission. The shipped translucent shader
declares emissive map and colour inputs; it may ignore the separate glow strength.
Verify appearance and brightness in game.
Some game reflections may remain even at high roughness and zero metallic. There
is no verified independent reflection-strength control for this path; its declared
refractive-index parameter is ignored in the normal non-depth-thickness path, so
the UI does not expose a misleading refraction slider.

## Opening meshes and preparing sessions

The resident editor defers hidden Qt compatibility panels until an explicit widget
or action lookup needs them. Output controls keep their identity, and the latest
panel state and fonts are replayed when the panels are constructed. Embedded
replacement controls retain their existing construction path. Initial authoring
packages read the worker-owned shadow directly; authoritative, editable shadow
and immutable base geometry remain separate.

PAC opening covers archive bytes, appearance and skeleton, material context, the
isolated authoring package, and the Rust host. Preparation reports geometry, material,
texture and final validation stages. Load failures replace the loading overlay with the
error and a Retry action for the same archive entry or local file, preserving draft
selection. Close cancels the load and rejects late results. A replacement request waits
for retiring loaders and Rust workers, retaining only the latest requested file.
Unpublished sessions and failed preparation folders are disposed.

Sparse preview batches retain their original PAC part indices, and repeated layer
parameter tables share snapshot storage without losing owners or relaxing the depth and
size bounds. Texture composition skips inactive normal mask pixels while retaining the
original output bytes.

### Prepared textures and material context

**Open Mesh** can lease the prepared texture package and its matching material
context while Archive Browser is hidden. It does not wait for the archive
viewport to render the package; stale requests and mismatched entries are rejected.
Once the editor owns the texture lease, clearing Archive Preview retires its pending
texture acknowledgement. Each subsequent PAC starts its own request through either
**Open in Mesh Editor** or the preview's editor button, including after closing a
session before the archive viewport rendered its textures.
Large command responses, including dense jiggle data returned after part selection,
use an atomic session-owned file with verified size and SHA-256. The control pipe
keeps its 256 KiB limit; referenced response state is bounded to 16 MiB.

The archive session loader retains the exact PAC XML under `modelproperty`, the PBD
catalogue and referenced profile documents with archive identities and content hashes.
This also runs when archive textures are already prepared. Physics bindings keep their
part names, variants and explicit empty assignments, including inherited empty
assignments. The editing context owns these immutable sources; ordinary preview models
and their serialized form stay unchanged. Cancellation, stale load results and closing
the session release the context. Missing or ambiguous paths remain unresolved, and
same-name files elsewhere are not used.

The active game variant is not inferred. These captured sources support explicit profile
selection for cloth preview and reversible companion-file output through the [Authored
physics profiles](#authored-physics-profiles) workflow below.

## Collapsible panels and tool icons

Use the arrow in each panel header to collapse it independently. **Tools** becomes
a narrow icon rail; **Inspector** leaves a slim edge handle. Their expand arrows
stay available, including while an operation is busy. These controls work in
Classic, Compact, and detached Mesh Editor windows. Hair mode uses Inspector.
Hair Tools and Close share a compact row above the editor. Close retains its
unsaved-changes confirmation; the embedded workspace fills the remaining height
without a separate Close row or outer padding below the viewport.

Click a tool icon to select it and open its settings. Several floating tool
panels can stay open together, including while you edit in the viewport. Drag a
panel by its header to place it anywhere within the editor's content area; its
position is remembered when you close and reopen it. Hover an icon for its name.
**Viewport** has its own icon for display settings.

Clicking an already-open tool's icon activates that tool and brings its panel
forward. Clicking again while that tool and panel are current closes just that
panel. Each panel also has its own close button. Closing or moving settings keeps
the selected tool active; focusing another panel does not change the tool.
Escape closes the front floating panel after any focused control or active
gesture has handled cancellation. **Orbit** exits the active tool.

The pin button docks that panel beside the rail and reserves viewport space. One panel
can be docked at a time; pinning another returns the previous one to a floating window.
Unpin returns to floating settings; closing affects only that panel. Short windows
scroll the icons and settings while keeping their header controls available. Panels stay
within the available content area after resizing. Expanded tools use compact tabs that
size to their labels and wrap into rows. Each group's settings appear below all its
tabs, keeping related tools together.

**Selection** opens its controls and activates viewport selection directly from the
section heading. Collapse it to return to Orbit; the selection settings and selected
mesh elements are retained. The compact rail still provides its **Select** shortcut.

Clicking the active tab retains the existing toggle-to-Orbit behavior. Floating panels
grow with their contents up to the available editor height and use the full panel width.
Expanded and pinned panels start narrower; tool rows wrap at larger font sizes, and
action buttons size to their labels. Topology keeps its numeric options in labeled rows
above the actions.

Collapsing panels preserves their widths and open sections, tool settings, mesh
selection, history, and output inclusion. Layout choices last for the current
editor window; a new editor process starts with both panels expanded.
The app navigation has a separate arrow button that remains visible when its
navigation is hidden.

## Hair creation

Use **Hair Tools (Experimental)** above the viewport. Hairstyles have not been tested in
game and may not work correctly. One setup dialog contains Character (Kliff, Damiane or
Oongka) and Create/Edit. **Create starts with an empty scalp**; the first verified
compatible base supplies skinning and materials only. Create does not load a thumbnail
gallery. Edit shows registered hairstyles with thumbnails and preselects the active
compatible hairstyle. **Start** stays disabled until the catalogue and donor checks are
ready. Browsing choices does not replace the scene. Finder Create/Edit Hair uses this
same dialog.

Setup, loading, and catalogue errors use a compact form with one action row; Edit
expands for the hairstyle gallery once the catalogue is available. Mounted barber
documents using `Hair` and older/modded documents using `hairShape` are both supported
without changing their slot names or existing choices.

### Character references and hairstyle catalogue

Mounted appearance and customization documents supply the head, facial details, scalp,
neck and shoulders. References share one skeleton pose: the body's authored transforms
with the head's explicit PABC bone overrides applied to both the face and skull. Bones
absent from the head PABC retain the body's neck and shoulder adjustments. Each PAC
keeps its own skin palette, including separate eye references. Face and body then use
the same skin-weighted head scale around the shared head joint. Applying the two PABCs
independently separates their matching jaw and temple edges. The complete upper body
surface supplies the temples and sides of the skull before the face seam is joined.
The common character scale cancels in the donor's authoring coordinates. Oongka uses his `5_pom`
references even though his registered hair belongs to `1_phm`. The clean, untextured
mannequin uses the head's fitted eye-cover surfaces as smooth eyes, excluding separate
shader-dependent iris/lens meshes, lashes and brows. Heads without fitted covers retain
their separate eye reference.

Reference loading parses fitting geometry and authored transforms directly, without
opening editable sessions or decoding DDS. Eyes follow the head but remain outside the
scalp planting and collision surface. **Advanced > Show character bust** only controls
reference visibility. It can be turned off before any hair is created; the empty
viewport remains usable, and turning it back on restores the reference without changing
the hairstyle. Compatible single-mesh PAC registrations at LOD0 are supported, including
registered variants without a `_player` suffix.

Entries with multiple PAC references, additional LODs, unsupported layouts or incomplete
dependencies explain their restriction before Start. Unavailable choices remain
selectable for preview and for reading the exact reason, while Start stays disabled.
Styles with a separate tail mesh require multiple PACs and cannot currently be edited
together in Hair Tools. Ordinary hair PACs retain the general mesh tools.

The hairstyle chooser shows each registered mesh once, keeps the first slot's
number and icon, and searches both that number and the asset name. It loads 24
choices per page with at most four detail requests in flight. Opening a hairstyle
from Finder starts on its page. Mounted barber DDS icons supply the grid images;
missing or unreadable icons use the existing rendered thumbnails. The selected
style still gets its full 3D preview. Page changes cancel obsolete icon and
compatibility work, and unavailable styles keep their explanation.
Mouse and keyboard selections stay selected while other compatibility checks
finish. Start waits for the selected hairstyle's own check.

### Starting an isolated replacement

Start prepares a complete replacement in isolation before the existing unsaved
work confirmation and scene switch. Cancellation and failed preparation preserve
the current scene; **Retry loading choices** restarts preparation. An active
generated hairstyle can start empty as one undoable edit without reopening its
archive target. Procedural hairstyle presets have been removed; existing saved
hair keeps its geometry. Repeated Create requests use the same route.

### Selection and grooming

Select a visible lock and use **Move** to drag it. Ctrl-click toggles selection; drag
empty space for a marquee. **Move reach** sets how much of the lock follows the grabbed
point, with a smooth falloff and fixed roots. **Draw** offers **Freehand**,
**Straight**, **Arc** and **Circle**. Drag the endpoints of a line or arc, or the
diameter of a circle. **Bend** adjusts an arc's direction and depth; **Stroke
smoothing** reduces freehand jitter without trailing behind the pointer. It uses the
same physical smoothing distance at different mouse sampling rates. Slow, small pointer
movements accumulate into a continuous stroke instead of repeatedly being discarded.

**Draw width** and **Draw cards** set the width and follower count before a stroke.
They affect new locks; **Appearance > Apply to selected locks** changes existing ones.
Narrower locks reduce both card width and follower spread. Use fewer cards for flatter
locks and more for volume, with several smaller strokes to control the silhouette.

Drawn cards follow smooth curves with up to three sections per guide segment and
continuous shading through bends, including during grooming and motion. Extra card
detail does not add physics points and stays within the existing vertex budget. Older
drawn hair gains this detail on its next grooming edit or geometry rebuild; imported
hair keeps its original topology. Drafts and output retain the refined geometry.

#### Scalp following and shape tools

**Follow scalp** starts enabled for Freehand; the shape tools start in the view
plane. Toggle it to choose surface following, or hold **Ctrl** temporarily to draw
away from the scalp. Contacts remain active in either mode, including card width.
Cards start narrow and follow the scalp before widening into the lock. Long
strokes retain evenly spaced guides; cached scalp data keeps live preview work
local to the active locks. Older strokes with a baked-in straight root retain
their saved shape and need redrawing.

#### Erasing and cutting

**Erase** removes only brushed, visible triangles from imported hair by default, so a
connected scalp section is not deleted from one small hit at the neck. Its boundary
follows the source triangles. Drawn locks still erase as a whole. Enable **Whole locks**
to remove complete connected sections; Delete removes the selected locks. Hidden faces
stay protected, Escape cancels the stroke, and a completed erase is one Undo step.
**Cut** trims every visible lock inside the brush at the point nearest the brush centre.
Click for one cut or drag across several locks; the completed stroke is one Undo step.
**Lengthen** extends the tips of every brushed lock without moving roots, spreading the
extension gradually through the tail instead of stretching one final segment. **Smooth**
rounds jagged bends while keeping both the root and tip in place. **Curl** wraps around
each lock's direction. Grooming falloff follows distance along the lock, so closely
spaced root points do not introduce abrupt changes. Comb, Smooth,
Curl and Clump also affect every visible lock inside the brush, even when another lock
is selected. **Move** continues to act on selected locks. Grooming works with hair drawn
with **Follow scalp** either on or off.

Short and thin locks anywhere inside the brush circle can be groomed, including between
pointer events during fast strokes. Entering another lock does not reset the strength
already applied to covered locks. The character reference and nearer hair still block
edits to hidden locks. **Physics** paints regions
along locks with **Static** or **Physical**. Blue marks fixed rows and orange marks
moving rows. Roots always remain fixed. The brush affects visible hair without needing a
selection, even when other locks are selected. Enable **Selected locks only** to
restrict painting to the selection; with that option enabled, an empty selection paints
nothing. The brush uses explicit symmetry pairs.

Paint is retained in drafts and Undo/Redo and follows cuts and grooming. Static rows and
their follower cards stay attached to the head during preview. Output disables retained
PAC cloth bindings at static rows, including lower LODs through nearest-vertex transfer
from LOD0. Physical restores the template's cloth bindings on rebuild; it does not
create a game physics rig or change skeletal weights. Original sections need grooming
roots before painting. Appearance controls width and generated follower cards. Symmetry
uses explicit pairs created while drawing. Escape cancels a stroke;

Ctrl-Z/Ctrl-Y undo or redo one completed action. Alt-drag orbits, Shift-drag pans, and
the wheel zooms.

### Existing hair and source preservation

Existing hair retains its original geometry, UVs, skinning and material sections.
Sections without editor guides are not broken: unchanged sections can be exported
without preparation. To groom them or preview their motion, expand preparation, select a
group or visible locks, choose **Set root / group selected sections**, then click the
scalp. This explicitly combines selected sections sharing a material. Changed sections
without valid guides remain blocked. Mark rigid scalp pieces as rigid.

Preparation controls remain available after every section has been assigned, so roots
and rigid attachments can be corrected without resetting the hairstyle. Draw and
follower density are available for generated hair; unsupported controls explain that
limitation. Existing locks support grooming, cutting and deletion once bound.

### Setup and references

Setup contains the readable hairstyle name and **Change references**. Alternatives
show compatible heads or base bodies, filtered in the resident catalogue before
pagination. There is no fallback to an unrestricted archive list. Changed heads
invalidate bindings until explicit rebinding. Setup, Appearance and Advanced are
collapsed; unrelated topology, rigging and UV controls stay hidden in Hair mode.
Switching choices cancels the previous preparation; its late results and errors
cannot replace the current selection. Failed reference choices remain retryable.
Cancelled reference loads release their unpublished assets.

### Motion preview

**Play** becomes available when roots, geometry ownership and required textures are
ready. **Head and shoulders** is the default test; Turn, Nod, Body sway and Wind are
also available. Existing sections spanning too far from their guide cannot simulate
safely: assign roots to smaller selections, or mark scalp sections rigid. Static editing
remains available. The Rust XPBD solver drives the rendered cards and uses matching
reference/root/collision transforms. Cached scalp-surface contacts check guide segments
and card width.

New reference setups retain the complete body surface for shoulder, chest and back
contacts, independently of bust visibility; the neck uses the same blended pose for
rendering and collisions. Older drafts use their saved bust until **Change references**
loads the full body. Local contact searches avoid scanning distant surfaces during soft
motion. Head contacts use the actual scalp surface, so starting Play does not push
fitted hair outward to the head's larger bounding capsule.

A rest-shape force preserves the groom while allowing softer tip movement; adjust
**Shape softness** to change it. This is an editor preview, not a simulation of the
donor's in-game rig or physics. A stroke pauses playback and resumes from the edited
rest shape at the current pose. Reset is deterministic. Simulation frames never modify
drafts, output or history. **Use settled shape** explicitly accepts the
neutral-coordinate result as one undoable edit after motion has played. Losing focus or
resizing cancels an unfinished stroke and clears its busy state.

While a topology edit is finishing, another click reports that preparation is still
running; completed edits remain ordered and bounded.

### Texture editing

**Appearance > Background color** changes the viewport backdrop. **Hair color > Apply
hair color** recolors every original base-color DDS together as one undoable edit. It
starts from the captured originals each time, so repeated color changes retain strand
detail and can recover from black. This replaces in-session edits to those color maps;
Undo restores them. Recoloring retains the DDS headers, compression, dimensions and
authored mip levels. BC2/BC3 transparency blocks stay byte-for-byte identical; other
supported formats pass the original alpha through DDS encoding. Flow, normal and
surface-response maps are retained.
Unknown or conflicting color slots require explicit editing in Texture Editor.

**Texture to edit** selects one DDS for editing, not the only texture used by the hair.
All DDS files referenced by the donor material remain bound and travel with the output.
The selected file shows its authored slot and missing-file status. Numeric names such
as `0003`, and suffixes such as `_f` or `_sp`, do not by themselves define a material
role; the material's parameter binding is authoritative.

**Open in Texture Editor** and **Apply edited DDS** retain the template's verified
material slots, dimensions, compression and mip counts. Edits follow the selected
texture's identity; separate DDS bindings remain independent even when their bytes
match. Repeated edits and Undo preserve the same preview and export bindings.
Missing required DDS files block game-ready validation. Guides are an optional
overlay. **Convert to ordinary
mesh** is an explicit undoable action under Advanced. Once the host accepts the
conversion, Undo and Finish are available without waiting for another edit.

### Drafts and geometry ownership

Hair state v2 records stable locks, geometry ownership and retained source vertices.
Drafts use `mesh_layer_project_v5`/`mesh_layer_generation_v5`, with reads of v1-4.
Legacy generated bindings recover lock ownership without regenerating geometry; legacy
existing hair needs explicit preparation for grooming or motion. Hair, geometry,
materials and output inclusion are saved atomically. The helper advertises
`hair_authoring_v2`. Small grooming updates publish only changed positions and authored
normals; unchanged UVs, materials and skin records remain resident. Each completed
action keeps its own Undo step. Pending Undo/Redo and Finish wait for ordered
publication.

Parts, action history, guides/roots and collision overlays remain available in collapsed
panels; visibility never removes hair from the exported result. Hair section names and
texture choices shorten to fit the Inspector, with full names on hover. Texture and
movement selectors place their labels above the choice so larger fonts keep the
surrounding controls clickable. Drawing and rebuilding populated sections preserve their
**Include in Mod** setting. The first hair drawn into an empty section starts included.
Incremental candidates reuse immutable references; acknowledgements preserve the camera,
selection and newer local edits.

Finish drains pending actions first. Acknowledgements read the validated revision
without decoding the complete hair document again.

### Package output

Packages retain the additional-choice contract, automatically allocate distinct internal
identities and use the readable name in their manifest. Existing barber slots, including
mod-added duplicates, remain byte-for-byte unchanged; the new choice inherits the first
matching donor slot's settings and icon. Retained PAC vertices preserve their original
skeletal and cloth-guide records when reshaped, cut or deleted. Generated geometry
always transfers skinning from an immutable original PAC donor matched by stable part
identity, including after consecutive Draw strokes, Undo/Redo and reopening.

Generated vertices needing five or six bone weights use ordinary skin records;
compatible cloth bindings remain intact. The 40-byte PAC layout guard remains in force.
Drafts can be reopened and saved repeatedly without losing part identities. A multi-LOD
donor is blocked until its writer is verified. Installed archives stay read-only.
In-game barber selection, save/load, headgear and motion remain unverified.

## Replacement workflow

Open an archive mesh, choose **Import Replacement…**, and select **Entire Mesh**
or **Selected Parts**. OBJ, DAE, glTF and GLB use the retained import pipeline.
Review the source-to-target mapping before **Apply Replacement**. Selected-part
replacement preserves every untouched part and its material binding, including
the original PAC vertex and index records at every LOD. Multiple
source parts can map to a target with original materials; imported-material mode
requires one source material part per target.

The import panel names the replacement scope and labels each mapping as **Imported
part** and **Replaces game part**. Entire Mesh includes all original parts; originals
without a mapped import are excluded from output. Selected Parts keeps originals
outside that scope unchanged and excludes unmapped parts within it. The mapping
dropdowns choose destinations for imported geometry.

**Import Replacement** requires an original game PAC, PAM or PAMLOD target at LOD0.
**Free Edit** creates a new OBJ package for geometry editing; OBJ does not retain a
rig or skin weights. An eligible original mesh can return to **Exact** under
**Output**. For an external import, open its game target from Archive Browser in
Mesh Editor first. The disabled replacement control shows this guidance directly.
Switching output workflows is explicit and does not apply a replacement by itself.

Mapping rows stay within the Inspector width; hover a shortened source or target
name to read it in full. Apply and Cancel wrap when the panel is narrow.

OBJ face regions with different materials appear as separate source parts even
when they belong to the same object. Material assignments continue across OBJ
object/group boundaries until the file specifies another material.

### Coordinates and source validation

Unskinned imports preserve decoded coordinates: no automatic scaling, alignment or
centering. Scale starts at 1, rotation and translation at 0. Use the existing
transform tools for placement. **Fit to Original** explicitly fits the imported
parts; **Reset Placement** restores their imported positions and normals. Both
restore the imported normal orientation and invalidate outdated tangents, and
both are undoable.
New Item fitting defaults are unchanged.

Replacement and geometry updates refresh the camera clipping range without moving
the camera, so larger or offset imports are not sliced by the original asset's far plane.

Source positions, UVs, normals and tangents must contain finite values within
the supported float range. Invalid values stop import before automatic UV
generation or preview conversion, preserving the current edit for a valid retry.
OBJ faces must also reference existing vertices, UVs and normals. Invalid indices
stop import instead of substituting geometry or regenerating authored channels.

### Imported GLB skin weights

Skinned GLB/glTF replacements retain their authored influences when the original
PAC target has a resolved matching skeleton and bone palette. Used joint names
must each match one target palette entry. Matching known joints must retain their
hierarchy and prove a common conversion into the target's bind space. Blender
armatures with different local bone axes are supported when their noncollinear
rest-joint positions prove one rotation, positive uniform scale and translation.
Coincident or collinear joints cannot establish this alternative conversion.
Import uses bind geometry rather than baking the current pose. Unused foreign
joints do not require palette entries; unused matching game joints still take part
in the compatibility check.

Authored weights survive replacement, texture UV seam splits and vertex reordering,
Undo/Redo and PAC output. PAC stores byte weights, so export includes its normal
quantization. The authored mapper refuses more than six influences per vertex,
incompatible bind frames, unknown used bones, unresolved target rigs and unsupported
layouts with an explanation. A retained cloth-bound record has four skeletal lanes.
The full topology rebuild can instead convert a donor record to an ordinary
six-lane skeletal record, clearing its cloth-guide lanes when the imported weights
need more than four. This is not rebuilt cloth simulation. New Item's explicit
per-part policy exposes reduction and requires physics off for five/six influences;
the shared byte writer refuses excess influences instead of trimming them. This does not retarget
a foreign rig or add bones to a game palette. Skinned and unskinned source parts
must map to separate game parts so that merging cannot discard authored weights.

Check weights before exporting from Blender. A GLB exported with four bone
influences can discard and renormalize weights from a mesh that has more; CDMW
cannot reconstruct those discarded influences. Reduce and normalize weights
deliberately for the chosen target layout, then set Blender's export influence
limit accordingly. A matching skeleton alone also does not guarantee that an
equipment PAC's palette contains every bone used by a complete imported outfit.
Replacement edits the selected PAC, not every PAC referenced by an item's prefab.
A split must verify each piece's actual palette, ownership, materials and retained
companions; dividing an outfit alone does not make unsupported bones available.

Unskinned replacements retain the existing transfer from original game geometry.
This authored-weight path belongs to **Import Replacement** on PAC targets;
Create New Item now reuses the same compatibility proof before static conversion, and
Free Edit's OBJ output does not retain a rig. Owned GLB/glTF and PAC fixtures
verify the replacement writer. The supplied Rosa Cassius Blender/GLB pair was
also inspected: geometry and named hierarchy agree, while the GLB reduces the
source's weights to four influences. Its rest-joint layout matches the PHW game
skeleton, including different local bone axes. The reported Elegant Carmine
Leather Armor resolves to five PACs. Its primary `cd_phw_00_ub_00_0170.pac`
palette lacks two bones used by the complete GLB (`Bip01 L Thigh_Side` and
`Bip01 Neck`), so importing that complete outfit is correctly refused. This is
file and preparation evidence; packaged appearance and game animation remain
unverified. The five existing item PAC palettes together still lack Neck. That
bone carries the entire 337-vertex `Main_submesh3.001` source part, so removing it
would change an authored rigid attachment rather than clean up a minor weight.

A subsequent read-only investigation and owned temporary-copy experiment extended
the primary palette from 93 to 95 entries with those two existing PHW bones.
Sequential metadata framing, cloth-guide data, embedded volumes, all four geometry
sections and the original parsed LOD influences survived the eight-byte insertion.
The later semantic palette writer and captured `PacPaletteExtension` contract also
passed complete seven-part Rosa output with imported materials and physics off.
Independent record decoding verified the two new slots and source weight sets at
every stored LOD (within measured byte quantization). Undo/Redo and versioned drafts
retain the explicit contract. Original archive bytes stay the provenance witness;
the writer derives the expanded metadata separately and validates final output.
Malformed framing, unknown flag combinations, ambiguous PAB identities, reordered
old slots and changed source/PAB inputs refuse. The small per-LOD
`SubMesh.source_bone_palette` guard remains unchanged.

A separate six-influence Blender/GLB review copy and loss-hotspot CSV are available.
Direct Blender export avoids coincident-position ambiguity, and the original GLB's
embedded material/image graph is retained. The six-influence 95-slot primary passed
four-LOD record checks (maximum byte-weight change 1.892 percentage points). Reduction
removes up to 12.93% on one original vertex, with 61 over 5%. The authorized follow-up
rendered 60 Rust D3D12 captures of the exact four/six-weight LOD0 outputs and original
nine-weight reference: seven controlled poses and three decoded PHW PAA samples, with
two views of each. Six weights follows the reference more closely in the sampled
walking/crouching and shoulder/chest/hip poses. Original surface-vertex measurements
still find a 10.5 mm maximum displacement from reduction in the raised-arm stress
pose, so this does not approve the 61 high-loss vertices. Common camera, framing and
generated DDS base/normal textures isolate the comparison; the material presentation
does not qualify selected PABC appearance, body masks, auxiliaries or simulation.

Static analysis of build 1.0.0.2976 confirms the counted hash reader and
count-sized CPU remapping, including explicit 1,024-entry/index bounds. Remap
resource preparation also receives the captured count. Final matrix/upload/draw
and special-physics consumers still need qualification. This remains an internal
experiment and is not exposed by the normal replacement
controls. New Item keeps strict equality for ordinary imports; experimental callers
must supply the exact captured contract. Appearance, companion ownership, full motion
playback, lower-LOD deformation, packaged behavior and game acceptance remain unverified.

### Materials and diagnostics

**Keep Original Materials** is the default. Missing or stale imported MTL and
texture references do not block this geometry-only mode. Source geometry and
external geometry buffers in both glTF and GLB must still exist and remain
unchanged while reviewing the mapping. **Imported Materials & Textures**
prepares the required DDS and material sidecars before publishing the import.
Missing textures, ambiguous material wrappers, shared selected/untouched material
ownership, incompatible skinning, or invalid coordinate/layout conversion block
preparation or Apply with a specific reason. This mode also rejects material
dependencies that changed after import preparation and never silently uses original
materials.

Imported materials follow the selected part's exact sidecar binding, even when its
embedded material label differs from the part name or uses different letter case.
Separate bindings can retain the same embedded label. Repeating part bindings in
different model-property variants are matched by their property index; each variant
keeps the untouched parts. Truly shared bindings and ambiguous variants remain blocked.

Hover over the bottom status message to read the full text, or choose **Details**
for a scrollable, selectable view. **Copy** copies the complete message, including
any part that does not fit in the status bar.

### Mod inclusion and preview modes

The **Include** checkbox controls exported output and is independent of viewport
visibility. Excluding a part retains all its editable geometry; re-enabling is
lossless, and every part may be excluded. Only export creates the existing tiny
triangle placeholders, retaining required target sections and their existing
index convention. Output Preview ignores temporary viewport/layer hiding.
Use **Output Preview** to see excluded parts or islands removed; **Edit** keeps
their geometry available for restoration. The Parts list states this distinction.
Inclusion-only changes retain the original PAC skin records, including seventh
and eighth influences. Re-enabling every unchanged part restores the original
mesh bytes. The textured editor retains the exact native-selected hair base DDS
and its alpha even when its material wrapper differs from the geometry part index.

**Edit**, **Original**, and **Output Preview** share the current viewport.
Comparison views are read-only. Finish the edit, validate its current revision,
then **Build Mod**. Preview, validation and packaging consume the same immutable
rebuilt mesh/sidecar/texture/paired-LOD bundle. Single-file export is disabled
when companions are required. Original archive bytes are never modified by
preparation or package creation.

### Eligibility and limitations

This workflow handles one eligible PAC/PAM/PAMLOD at LOD0. Finish active Morph &
Refit work and choose **Start next edit pass** to change inclusion on
the rebuilt source. Direct replacement remains unavailable while its profile or
archive bindings are active.
Unsupported target layouts remain blocked. Existing sessions without replacement
state retain Exact Game Asset/Free Edit behavior. Replacement uses its own
`replacement_game_asset` policy, not weakened Exact validation.

Neutral-appearance meshes show an **Experimental** warning above the import controls.
Imports and **Include** are available immediately for eligible meshes, with no
extra enable button. Positioning, scale or animation may be wrong in game. Imports still
preserve their bind-space placement. Unskinned imports transfer weights from the
displayed original part; compatible skinned imports retain their mapped weights.
Export uses the final weights to invert the neutral display transform. Output Preview
reparses the actual written mesh and displays it in the same neutral frame. Singular
transforms, unsupported skin layouts, invalid geometry and missing dependencies still
block the operation.

The left part checkbox controls viewport visibility; the right **Include** checkbox controls
output inclusion. Opening the editor alone does not change geometry or output;
cancelling the editor discards its edits.

Clicking **Delete** for selected whole Parts in Exact output opens guidance:
untick **Include** to exclude them from game output, or choose **Free Edit** for
structural editing to OBJ. Supported vertex/face deletion stays available in
Exact output. The Delete key follows the same selection rules, leaves text
editing and hair controls in charge of their own input, and does not delete
through a modal or comparison view. Rejected Delete commands show their actual
error in a popup without changing the retained mesh or selection.

### History and drafts

Imports, inclusion and placement changes participate in normal Undo/Redo and
Finish/cancel. Replacement-bearing drafts use version 2 and keep captured dependencies
and output intent together; older apps reject them. Existing version-1 drafts still load
unchanged. Source files are unnecessary after Apply. Reopened replacement drafts use
their captured original DDS and material data to restore untouched parts and the
**Original** comparison after preview caches or source files disappear. Saved
material-owner and layer metadata is retained, and readable authoritative preview
textures keep their existing bindings.

Recovery handles texture roles separately, so a surviving normal map does not block
restoration of a missing colour texture. Native-selected hair and base textures keep
their saved binding identity and cutout transparency after their captured DDS files are
relocated. Empty, malformed or truncated cached DDS files can be replaced by validated
saved copies. Damaged DDS inputs are rejected if neither a valid cached binding nor a
valid saved copy is available. New replacement payloads also retain import normals.

Older replacement drafts still reopen and export, but require reimporting before Reset
Placement or Fit to Original because their original normal orientation was not saved.
Older applications reject the new replacement payload version. No bulk migration is
performed. Experimental replacement drafts use project and payload version 3, retaining
the exact neutral transform and coordinate frame. Older apps reject this format before
attempting generation recovery. Ordinary replacement drafts remain v2.

Repeated unskinned imports transfer weights from the retained original target in the
active coordinate frame, so earlier imports do not become skin donors. Skinned imports
use their own authored influences. Draft restoration is staged for every format;
a rejected generation leaves the loaded geometry unchanged
before recovery tries a previous generation. Malformed replacement fields, duplicate
part identities and invalid target mappings reject the generation and allow recovery of
the previous valid save. PAC replacement also rejects non-finite UVs or values that
overflow its half-float storage before committing the import.

Python rebuilds and native rebuild handoffs use the same check; valid negative and tiled
UV coordinates remain supported.

### Implementation and checks

`mesh_replacement_import.py`, `mesh_replacement_skinning.py`,
`mesh_replacement_materials.py`, and `mesh_replacement_output.py` own detached
preparation and complete output.
`mesh_rust_replacement.py` and `mesh_rust_replacement_materials.py` publish through
the existing shadow-session/control/material contracts. Task cancellation,
revision checks and import tokens prevent stale candidates from taking over.

Synthetic verification covers format round-trips and the packaged editor. It
does not establish real-game rendering or animation compatibility.

## Cloth influence

For an original PAC at LOD0, open **Mesh Data > Cloth**. Choose all included
cloth parts or **Selected parts only**. **Cloth amount** scales their existing
influence; **Disable cloth** makes them follow skeletal animation. Enable
**Fix vertices above height** to set where movement begins, with an optional
fade below that height. Height uses displayed model Y, including the neutral
appearance transform when present, and is evaluated separately at every stored
LOD. Previously rigid vertices remain rigid.

### Applying and restoring influence

**Apply cloth settings**, **Restore cloth**, Undo/Redo, Finish/cancel and drafts use the
existing replacement output transaction. PAC output retains the source bindings and
reapplies the rule on every rebuild, including after replacement. Restore removes the
rule and recovers those retained bindings. An exported PAC whose bindings have been
disabled cannot recover them without its source/draft. Unproven or shared vertex
layouts, missing bindings and active hair/refit workflows are rejected before committing
output. Incomplete or undecoded lower LODs disable cloth controls without blocking an
otherwise readable mesh from opening.

Replacements reject non-finite or out-of-range retained cloth-guide indices before
committing the imported mesh. Skin-weight edits made before applying cloth settings
remain in PAC output, including after inclusion changes, replacement of other parts and
draft recovery. Parts whose geometry is unchanged keep their original lower LOD weights;
authored LOD0 weights are patched at their final output offsets. Weight commands reject
a fifth skeletal influence on cloth vertices and removal of a vertex's last bone before
changing the mesh or Undo/Redo history.

Position, UV and normal edits on original parts with unchanged vertex counts and faces
patch their LOD0 channels while retaining lower LOD topology and packed fields,
including when another part is replaced, parts are reordered or Mod inclusion changes.
Moves within the original bounds preserve lower LOD records exactly. Moves outside those
bounds expand them and re-encode lower LOD positions within the new quantization
precision. Draft recovery uses the same exact record-map checks before accepting these
edits.

### Detected physics

The **Parts** list marks parts with cloth, spline or jiggle influence. Select a
part and expand **Detected physics** below the list in the **Parts** tab.
It starts collapsed, with each selected part's evidence grouped under its name.
The Cloth page keeps its physics details expanded initially. The details show
retained source vertex counts, the guide mesh and its fixed anchors, exact
profile assignments by variant, and current disabled contributions where the
editor can still prove vertex ownership. Hover over a part for the same evidence.

Detection combines render bindings with validated guide indices and resources.
Part names, fabric appearance and a shared physics profile alone do not identify
cloth. Exact profile modes take precedence over the PAC default; a default is
identified as such, and unresolved, mixed, absent or unsupported data stays
explicit. An empty variant assignment is retained. Detection works without a
preview skeleton and does not change the mesh or its output.

Free Edit still inspects an eligible original PAC's LOD0 bindings and exact source
profile assignments. Badges mark these as **source** data, separately report
whether current geometry retains the source binding layout, and explain that
edited physics remains unverified. Surviving parts are matched by their original
descriptor ownership after whole-Part deletion; current row numbers and display
names are not source identity. Unmatched parts stay unknown. Cloth/Jiggle
authoring and physics output remain unavailable: Free Edit publishes OBJ, which
does not retain the game rig, cloth, jiggle or physics profiles.

An active Morph & Refit profile or archive binding pauses physics inspection.
Parts show **Blocked by Morph & Refit**, and Jiggle and Cloth explain that existing
physics data is unchanged. The jiggle region overlay pauses instead of colouring
the model as unknown. The previous overlay setting and normal detection return when the
blocking Morph & Refit state is cleared or undone.

For example, a weapon ribbon can use **Spline** physics through its retained
guides. Supported ordered chains can play in a controlled spline preview, with
stretch, bend and angular spring-back. This approximates game motion; it does
not reproduce the game's spline solver. Detected source bindings and profiles describe
authored data; they do not establish active in-game simulation, ordinary bone
animation or runtime overrides. **No guide or jiggle bindings** therefore does
not claim that a part can never move.

### Influence and profile boundaries

These influence controls edit render-vertex cloth influence. Profile authoring
uses the separate **Edit profile for mod** section described below; simulation
anchors and collision shapes remain source-owned.
Cloth-only drafts use project/generation v6 and replacement payload v4 so older apps
reject them before attempting recovery that could lose the settings. Drafts
without cloth settings retain their existing formats unless jiggle settings are present.

`mesh_rust_cloth.py` owns the command/state handoff, `domain/mesh/cloth.py` the
height rule, and `modding/pac_cloth.py` the validated byte patch. In cloth mode,
only four packed slots are skeletal; the other four influences address cloth
guides. Disabling cloth clears the guide fields that the ordinary six-bone
shader branch would otherwise reinterpret. Original skeletal weights, mesh
geometry, materials, physics sections and companion files are preserved.

### Motion preview

**Motion preview** in **Mesh Data > Cloth** now applies those saved influence
edits to an experimental native guide simulation. Choose **Up / down**,
**Start / stop**, **Turning** or **Freehand**, then **Play preview**. Freehand
moves the whole model with a left-mouse drag in the viewport; release to let the
cloth settle. **Current flags** uses
the saved cloth amount/height/fade rule; **Original flags** uses retained source
weights; **All disabled** shows rigid motion. Height rules use the original neutral
display coordinates, matching PAC output even after sculpting. Jiggle flags are
not required. **Pause preview**, **Resume preview** and **Reset preview** share
the existing Jiggle controller; changing between Cloth and Jiggle resets playback.

#### Preview settings

**Cloth preview settings** supplies gravity, stretch/bend response, damping, iteration
count, optional authored vertex-alpha blending and a floor with an adjustable Y height.
**Guide rotation correction** optionally turns the cloth surface with its guide
particles, using decoded orientation neighbors. It is available only when those
neighbors are known. **Single-edge rotation** selects the decoded alternative that
follows one neighbor; leave it off for two-edge frame alignment. Short single edges
preserve the animated orientation. The active game material is not selected
automatically. These settings affect only the preview.

Saved cloth influence rules remain separate. Smaller internal simulation steps reduce
excessive stretch on dense guide meshes while retaining the damping control's effect
over time. Preparation runs on the bounded background loader; failed comparisons keep
the last usable frame paused, and Reset/source changes reject late results. Preview
frames never change authored geometry, drafts or exports.

#### Body collisions

**Body collisions** optionally projects moving cloth guides against authored sphere,
cylinder and capsule volumes. By default, a decoded, nonempty model PAC volume set takes precedence;
a confirmed empty set uses the matched PAB rig's primary defaults. The panel identifies
which source is used. Model volumes bind through stored bone hashes, independently of
palette order. Colliders use the same neutral pose and up/down or turning motion as the
model. **Collision margin** adds preview clearance. Fixed guides and zero-contribution
render vertices retain their existing behavior.

Undecoded model metadata, missing or ambiguous bone bindings, and unsupported volumes
disable this option while leaving ordinary cloth playback available. They do not
silently substitute rig defaults. **Collision sources** accepts body/head PABV inputs
from **External file…** or **Game archives…** for the current preview. Archive search
shows only the requested file type and loads only the selected file. The body input replaces
model or rig defaults and the head input replaces the first matching head volume in that
set. Both inputs can be selected together, including an external body and an archive head.
Standalone inputs must use bone hashes; unsupported shapes or bindings are rejected.
**Clear collision inputs** restores the model or rig defaults.

Failed or cancelled loads preserve the previous inputs. Inputs are held for this session
only and do not change mesh Undo, drafts or exported PACs. Outfit files are not selected
automatically and game collision activation remains unverified.

#### Weapon collisions

In **Cloth**, click **Experimental features** below the influence controls to show
**Weapon colliders**, **Collision sources** and **Create cloth guides** inline.
Click it again to hide them. Cloth settings and motion preview remain in the same
panel. The weapon PAC picker appears once, in **Collision sources**.

**Weapon colliders > Weapon collisions** is a preview switch for supported single-root weapon
PACs. Capsules are fitted around included rigid parts; guide-bound ribbons are excluded.
It can run together with **Body collisions**. **Show collision shapes**, directly below
the preview settings and profile headings, draws body shapes
in blue and weapon shapes in gold, through the mesh, following **Keep model centred**.
It prepares a paused view before playback, so volumes inside a cloak can be inspected
without starting the simulation. The panel shows how many shapes are available; Reset
clears the inspection view.

For character cloth, **Collision sources**, directly below **Weapon colliders**, offers
**Choose weapon PAC…** to load a separate weapon
reference from **External file…** or **Game archives…**, such as Rhett's Longsword
(`cd_phm_02_sword_0009.pac`). A cloak does not provide its own rigid weapon parts: load a
weapon reference to enable **Weapon collisions**. Loading it automatically displays its
rigid parts as an untextured solid reference, fits collision capsules and shows their gold
outlines. Enable **Weapon collisions** under **Weapon colliders** to use those contacts
during playback; no separate creation step is needed for a reference. **Show collision
shapes** hides the outlines independently of the reference mesh. **Move weapon** and
**Rotate weapon** show a separate gizmo at the weapon's origin. Drag an axis or the
centre to place the weapon without editing the cloak; Escape cancels the drag.
Position and rotation each use one horizontal XYZ row that keeps its height as values
change. Gizmo and numeric placement move the mesh and contacts together and resume a
stationary-body cloth test. With **Weapon collisions** enabled, moving contacts push
the cloth guides; fast crossings retain the entering side. Fixed guides and disabled cloth
influence remain fixed. Placement is retained on release without resetting the simulation.
The other motion tests still move the body and reference together; game sockets and
weapon animation are not loaded. Loading and placing
it changes only the current preview. Clear, failed-load and cancellation behavior match
the body/head inputs above.

Mesh Editor keeps control labels, live status and actionable errors visible. Instructions
and preview limitations are available by hovering the relevant control or section heading.
Collision inputs show filenames in the panel and the complete source path on hover.

**Weapon colliders > Create weapon colliders** experimentally adds capsules to the
weapon's exported PAC through the normal Undo, draft and Build PAC/Mod workflow.
This export action appears when the currently edited model is a supported weapon;
a sword loaded as a cloak's preview reference does not become part of that cloak's mod.
**Restore source colliders** removes this authoring choice and retains original volumes.
The writer currently supports verified, rigid, single weapon roots and preserves all
render LOD geometry. Unsupported layouts or attachments are rejected with a reason.

For a weapon's own ribbon, **Authored physics profile > Edit profile for mod > Collision
and attachment overrides > Skip own model collisions** exposes the stored
`SkipSelfMeshCollidable` flag. Explicitly overriding it to disabled exports `0` to that
weapon's cloned profile. This does not change the shared source profile. These exported
shapes and flags are experimental: live collider registration and collision eligibility
remain unverified, so preview contact does not establish in-game contact.

#### Required decoded inputs

Cloth playback requires decoded PAC guide data, a matching fixed-layout PAB rig, and
verified original LOD0 render mappings within the existing 100,000-vertex /
200,000-triangle preview limit. Unsupported inputs keep their saved cloth controls and
explain why playback is unavailable. The controlled solver uses decoded stretch/bend
kernels and authored fixed vertices with unit dynamic masses; it does not reproduce
runtime profiles or layer/world collisions. Body contacts use an explicit preview
admission rule and frictionless response. Area records are retained but inactive in the
decoded normal-step path.

Spline playback additionally requires complete, disjoint ordered guide chains,
fixed roots and retained pair constraints on every chain edge. When every guide
and render vertex across every stored LOD uses one rigid skeletal attachment,
the editor can preview the spline without a PAB. **Standalone rigid attachment**
means controlled model-root motion, not identification of an in-game socket.
Edited or multiple skeletal attachments retain the matching-rig requirement.
Body/appearance collision inputs and decoded bone jiggle require a matching rig;
the standalone spline still offers an optional preview floor and weapon contacts.

**Spline preview settings** provides gravity, damping, stretch, bend, iterations,
vertex-alpha blending and guide rotation. **Spring-back response** pulls the chain
toward its animated source directions; zero disables that angular restoration.
Spline rotation follows adjacent chain guides rather than cloth triangles.
Entering spline mode or resetting its settings starts with free bending, zero
spring-back, authored vertex-alpha blending and guide rotation. Tune those
preview values or explicitly load an authored profile for different starting
settings. Spline bend and spring-back account for the duration of each small
simulation step, so substeps do not artificially hold a ribbon straight.
These controls are temporary preview settings. The chain projection, fixed preview
clock, absent wind/water and runtime overrides are not game-equivalent physics.

Initial overlap is corrected without adding launch velocity; moving bodies still
transfer normal contact speed. Optional cloth guide rotation uses its two-edge branch; this
does not establish which branch the game selects. Headless controls and synthetic
playback are tested. Packaged visual checks have exercised a Damiane body and two
garments; game behavior and complete material fidelity remain unverified.

### Experimental jiggle contribution

Open **Mesh Data > Jiggle**, separately from Cloth. Compatible original body and
clothing PAC meshes are supported; cloth bindings are not required. Select
the intended part, keep **Selected parts** enabled, and use
**Only below height > Below Y** to limit the edit to the lower body. The boundary
uses displayed model coordinates and applies strictly below that height at every
stored LOD. Its initial midpoint is not an anatomical waist detector. Unchecking
the height limit applies the edit to the whole selected part.

#### Region overlay and eligibility

**Show jiggle regions** is an optional viewport overlay, off by default. Blue to
orange shows increasing vertex contribution, gray marks zero contribution, and
purple marks unknown data. It covers all visible parts, independent of part
selection and motion comparisons, and remains usable on an entirely disabled PAC.
Disable/restore, Undo/Redo, and visibility changes refresh the colors. The toggle
works during playback without restarting it; turning it off restores the normal
viewport display. It does not change vertex colors, materials, drafts, or exports.
Region colours retain directional surface shading so bends remain visible.
**Region tint** adjusts the colour strength without restarting playback.

Only verified source PAC LOD0 vertex mappings are classified. Other formats,
imported or unverified geometry, other LODs, and Original/Output comparison views
show unknown instead of being treated as disabled. These colors identify the
decoded vertex contribution, not confirmed in-game activation. The overlay and
preview use byte 38's low four bits, matching the traced game's skinned-mesh
setup. Runtime bone overrides remain unresolved and can change the final motion.

#### Contribution and disable controls

**Retain original % > Apply contribution** scales each source vertex's contribution
instead of replacing the authored gradient with one value. It supports every
source byte while preserving its upper four bits:
`new = (original & 0xF0) | (15 - floor((15 - (original & 15)) * retained + 0.5))`.
For example, 249 becomes 252 at 50%, and `0x89` becomes `0x8C`.
Values are quantized; a weak source may have only one useful step.
100% retains the source and 0% removes the byte-derived contribution. This cannot
create bindings, amplify motion, or override runtime bone masks.

With a matching source skeleton, the region selector lists its named bones. Choose
a bone and use the same **Retain original %**, **Apply contribution** and
**Disable jiggle** controls to change that region independently. All PAC palette
slots belonging to that bone are handled together. Each vertex blends the regional
amounts through its exported skin weights, including any weight reduction required
by generated cloth guides. Mixed vertices can still receive contribution from
other bones when one region is set to zero.

**Use whole-part contribution** removes only the selected region's override. Existing
whole-part height limits still apply to regional edits. Selecting **Whole selected
parts** and applying an amount replaces the selected parts' regional overrides;
**Restore original jiggle** there clears every contribution rule on those parts.
Regional editing needs a matching skeleton to resolve bone names, while saved
regional amounts can still export after draft recovery without that skeleton.
Recovered drafts can also use the whole-part controls and restore their source
contribution without reopening the original archive.

**Disable jiggle** sets only the low four bits of zero-based byte 38 (`0x26`) to 15 in
validated 40-byte PAC records. The upper four bits, colours, the separate cloth gate at
byte 39, skinning, geometry and other bytes are retained. **Restore original jiggle**
removes the rule and restores the retained source values. Undo/Redo, Finish and saved
drafts use the existing replacement output transaction. Restore cannot recover values
lost before the source PAC was opened. Layouts without proven record ownership at every
LOD are rejected.

Jiggle drafts use project/generation v7 and replacement payload v5 for disable-only
rules, v6 for relative contributions or v15 for independent regional contributions;
older drafts remain readable. Repeated adjustments start from the source, not the
last result.

#### Reported game evidence

The disable value `255` is externally reported as tested on a modified Damiane
body. The current shipped shader additionally decodes byte 38 as either
`(255-byte)/255` or `(15-(byte&15))/15`. These are render-blend weights, not damping
or stiffness, and bone overrides can supersede them. CDMW has not independently
validated the result in-game. The source waist threshold `Y < 1.2` applies only to
the reporter's model.

#### Jiggle motion preview

**Motion preview** in the same section provides experimental inertial deformation of the
rendered mesh. **Up / down** is the default: it repeatedly raises and lowers the model
along its displayed Y axis, making vertical lag and bounce easier to compare. **Start /
stop** and **Turning** remain available. Choose a motion, then **Play preview**. **Keep
model centred** is enabled by default. It removes the test's whole-body translation and
rotation from the displayed frame while the solver still receives the full motion.

This keeps the body steady so small jiggles are easier to see. Uncheck it to see the
full moving-model preview. It also works while paused and does not change camera orbit
or pan. **Freehand** lets you shake the preview with the left mouse button in the
viewport. The affected regions react to that motion; releasing lets physics settle.
Dragging follows the camera's screen plane and is limited to one model extent from the
starting position. Right mouse orbits, middle mouse pans, and Reset returns the model to
its starting position.

Freehand works with approximate jiggle, decoded bones and guide cloth. It changes only
the motion preview, leaving mesh transforms, history, drafts and exports unchanged.
**Current flags**, **Original flags** and **All disabled** compare the saved jiggle
rule, the retained source weights, and rigid motion using the same geometry. Changing
comparison or motion restarts a playing test for a repeatable comparison.

Motion and comparison buttons keep the same size on hover and selection; narrow panels
wrap the choices without moving them under the pointer. **Pause preview** retains the
frame; **Reset preview** returns to the editable rest shape. Camera orbit and framing
remain available during playback.

#### Decoded bones

**Decoded bones** is the default and requires a matching fixed-layout PAB rig. It drives
the recovered bone solver through the original hierarchy and retained PAC skinning
records. **Bone solver settings** exposes linear/angular response, damping, speed limits
and offset limits. Hover a setting for an explanation and a simple example.
Higher decoded damping values retain more velocity
(less braking); speed and offset limits only affect motion that reaches the limit.
Angular settings are easiest to compare with Turning.

The same region selector also scopes these eight settings. With a named bone
selected, changes affect that bone while other bones keep their settings; **Reset
bone settings** returns the selected bone to the shared preview values. With
**Whole selected parts** selected, the controls change the shared defaults for the
rig, keeping regional overrides. Reset there restores the decoded initialization
values and clears all regional preview overrides. Changing the selected parts still
controls which mesh parts are drawn; it does not remove bones from the solver.

All eight settings take effect on the next simulation step, without reloading the rig.
These are preview-only parameters, separate from byte 38. Rig reading and vertex
preparation run on the existing background loader; cancellation and source changes
reject late results, and a failed replacement keeps the previous frame paused.

#### Approximate vertices

**Approximate vertices** remains available for meshes without a resolved rig,
with its existing editor-only softness/damping controls. Both modes use a repeatable
60 Hz procedural pose test, rather than game animation or a verified live profile.
They do not simulate inter-part collisions or guide cloth. Decoded per-vertex weights
blend simulated and ordinary motion, preserving the source gradient. Byte-255
vertices follow the controlled model motion without added deformation. Existing
custom normals are rotated with the deforming surface.

The initial preview supports LOD0 with verified, unchanged source vertex ownership
and up to 100,000 visible vertices / 200,000 triangles. Imported replacements and
topology-changed meshes remain editable but cannot use this preview. The decoded
rig snapshot is also limited to 100,000 retained source vertices across its parts.
Preview frames
never modify mesh data, drafts, Undo/Redo or exported PACs. Surface picking waits
for Reset; source edits, selection changes and host state updates discard playback.
`cdmw_jiggle.rs` owns playback and viewport snapshots; its `native` module binds the
decoded `cdmw_mesh::jiggle_rig` solver, while `cdmw_mesh::jiggle` owns the approximate
mode. Compatibility with game motion still needs reporter comparison.

#### Reporter testing and implementation

Reporter test: retain the original PAC and export 50%, disabled and restored variants
using **Build PAC**. On the same game build, compare walking, sprinting and
stopping, then change camera distance to exercise LODs. Check that chest, hair,
accessory and cloth movement and normal animation remain intact. Repeat with
0145 and 0166 clothing, recording whether any returning jiggle belongs to the
clothing or the visible underlying body. Include the game build, exact input and
output hashes, selected part and height with any regression report.

`mesh_rust_jiggle.py` owns the command/state handoff, `domain/mesh/jiggle.py` the
height and weighted region rules, and `modding/pac_jiggle.py` the byte patch. The
shared PAC LOD reader validates record ownership without requiring cloth bindings.

### Creating cloth guides on existing bones

In **Mesh Data > Cloth**, click **Experimental features**, then expand **Create cloth guides**. This
requires a guide-free PAC with a decoded 2-, 3- or 4-LOD layout and a matching
skeleton. Select the parts to affect and enable **Create guides for selected
parts only** when appropriate. Choose a **Source LOD** and **Pin guides at or
above Y**, then **Create / update guides**. Pin height uses displayed neutral
coordinates; generated positions remain in the PAC source frame.

#### Generation and skinning limits

The generator welds identical positions with identical bone weights, builds
distance/bend/area constraints and fixed-root chains, and binds the visible
vertices at every stored LOD to up to four nearby guides in their own part.
The total is limited to 1,024 guides. Degenerate or non-manifold source geometry,
pieces without anchors, all-fixed selections and undecoded metadata are rejected.
Choose a lower source LOD, a different height or fewer parts when needed.

**Reduce skinning to four bones** is off by default. Enable it only when the
conversion is wanted: it merges duplicate influences, keeps the four strongest
existing bones and normalizes their weights at every LOD of each selected part.
Without it, sources that need weight conversion are rejected. Other parts retain
their original records. No bones are created or added to a skeleton.

The generated guide data feeds the existing decoded motion preview. Cloth amount,
Disable cloth and Restore cloth continue to work on these new bindings. **Restore
source guides** removes the creation recipe and dependent cloth-influence rule for
the chosen parts. Undo/Redo, Finish, saved drafts and Build Mod retain creation
settings and the captured bone palette. Draft version 9 reopens without an archive
or skeleton for output; decoded motion still needs the matching rig.

The first version generates from PAC LOD geometry; importing or hand-editing a
separate guide mesh and changing existing authored guide topology are not included.
Offline decoder, deformation-reference and retained-asset checks establish
structure and preservation, not in-game activation, appearance or solver parity.

### Authored physics profiles

In **Mesh Data > Cloth**, expand **Authored physics profile** and choose a variant.
Assignments come from the exact captured PAC sidecar and profile catalogue,
including explicit empty variants. The active in-game variant is not inferred.
**Use profile in preview** loads supported settings after decoded stiffness
conversion. Motion tests and preview sliders remain preview-only.
Explicit spline profiles also load their simulation mode and converted
`RestoreAngleStiffness`. Applying or restoring a saved edit refreshes a loaded
profile for the same selected parts and variant. Changing selection or variant
restores the previous manual preview values. Profile edits reset playback; press
**Play preview** again to run with the updated values.
Both the preview gravity control and raw profile gravity use negative values for
downward acceleration and positive values for upward acceleration, from -100 to
100. Loading a profile preserves that direction; restoring manual settings
restores the previous gravity as well.

#### Assignments and guide information

The profile panel reports the current model's cloth-guide count and fixed guides,
including generated guides in Edit comparison and source guides in Original.
A model without guides is labelled explicitly; an unsupported or damaged guide
layout is reported as unknown instead. Profile metadata remains editable where
its source assignment is available, but editing it does not add cloth or bone
jiggle to a model without those bindings.

#### Editing profile output

Expand **Edit profile for mod**, choose the shared assignment group if there is
more than one, and choose a captured source profile. Each group lists every
affected part; a shared owner changes as one unit. Empty variants can receive
an explicit assignment through their existing owner. Tick the raw XML values to
override: stretching/bending stiffness, spring-back stiffness (`RestoreAngleStiffness`), damping, gravity, iteration count,
vertex-alpha blending or guide rotation. Unticked values retain the source.
Models whose variants are all empty do not provide a captured source template;
profile authoring remains unavailable for those models.
Invalid source numbers are labelled; explicit overrides use finite bounded
values. Preview stiffness coefficients are never copied into raw XML overrides.

#### Collision and attachment overrides

**Collision and attachment overrides** exposes cloak behavior, backstop
collisions, input-position collisions, shrinking around a sheathed shield and
long-range attachments. Tick **Override** to replace the captured value, then
use **Enabled** to choose on or off. Unselected switches retain their original
XML. Closing this section keeps selected overrides. These switches use the same
Apply/Restore, history, draft and mod-output path as the other profile values.
They do not change the manual preview's collision controls. Runtime globals,
collider availability and scene conditions still gate the game's behavior;
the preview does not reproduce every branch.

#### History and source preservation

**Apply profile edit** and **Restore profile assignment** each use Undo/Redo in
the isolated edit session. **Finish Edit Mesh** accepts the edits into the main
session. Save/Open Draft retains exact source bytes, archive locations and
rules, so profile editing can continue without the original archive context.
**Build Mod** includes the cloned profile, catalogue and selected sidecar
assignments. Profile-only edits keep the PAC byte-identical. Single-file PAC
export cannot contain the required companions.

Original shared profiles, unknown XML, encoding and unrelated variants are
preserved. Catalogue edits compose with existing entries, but packages that
override the same catalogue must be merged. This does not create guide geometry
or physics/bone bindings. A generated profile changing Canta Plate Cloak's gravity
from -10 to +20 was verified in game: the user observed upward cloth movement and
supplied a screenshot, with the PAC unchanged. This verifies that assignment and
gravity override on that cloak; it does not establish every setting, other
models' activation or game-equivalent preview motion.

## Vertex Parameters

Open **Mesh Data > Vertex Parameters** in Tools. It is a dedicated tool tab,
with its own icon when Tools is collapsed, and can float or pin like other tool
pages. Inspector contains Parts, Geometry Layers, and Action History; Vertex
Parameters is no longer duplicated there. Opening the page follows the current
selection without changing the viewport tool. Select vertices,
edges, faces or whole parts; an empty selection has no target. Edges and faces contribute their
unique vertices.

### Editable groups and Apply behaviour

**Position**, **UV Coordinates**, **Normals**, and **Skin Weights** group the
selection's values with their editing controls. Component rows show the axis,
current value, and new input. Displayed numbers are rounded for readability;
hover a current value for its full precision or the exact **Mixed** selection
range. **Inspect one vertex** contains the row picker and pages (at most 128
vertices), letting you inspect a member without changing the batch target. Rows
show current part/vertex indices and original or donor indices only when source
provenance proves them. Generated
and unmapped vertices are identified explicitly. Coordinates are **model editing
space**, including neutral appearance when active, rather than animated or
camera positions.

Expand an edit group and enter only the components to change. Position and UV0
offer **Set** and **Offset**, defaulting to Set for one vertex and Offset for a
batch. **Apply to N vertices** commits the complete batch as one Undo step;
**Discard** clears inputs. Selection, topology or mesh changes discard pending
inputs with an explanation. Inspecting another row or page keeps the batch.
Skin Weights shows only the fields needed for its selected operation; unavailable
weight editing shows its reason. **Cloth & other data** groups read-only summaries,
unsupported-channel information, and **Open Cloth Controls**.

### Channel support

| Channel | Current support and remaining boundary |
| --- | --- |
| Position | Set or offset individual XYZ components. PAC output expands shared bounds when needed and retains lower LOD positions within quantization precision. |
| UV0 | Set or offset U/V. Tiled UVs outside 0 to 1 are preserved. PAC/PAM/PAMLOD half-float limits apply where those writers are used. |
| Normals | Set a direction; all three components are required. Valid vectors are normalized; zero-length and nonfinite input is rejected. PAM/PAMLOD normal writeback is unavailable. |
| Skin weights | Resolved bone names, influences, totals and batch ranges. Set/offset a chosen influence, remove it, or normalize. Other influences redistribute proportionally. Exact PAC LOD0 layout and a resolved palette are required. Cloth vertices support four skeletal slots; ordinary supported rows support six. Removing the last influence or exceeding capacity rejects the batch. The separate Rig & Weights tool remains hidden. |
| Cloth | Read-only original/effective influence, fixed/moving status and proven guide bindings. Height rules use the existing quantized PAC output path, including the saved neutral frame. Unproven mappings report unavailable. **Open Cloth Controls** opens the existing controls. |
| Tangent frame | Generate Tangents computes editing data. The current PAC writer retains or clears donor tangent bits; it does not encode an arbitrary authored tangent frame. More writeback validation is needed before promising saved tangent edits. |
| Packed colour fields | Original record bytes are retained through replacement donors. There is no editable per-vertex colour channel in the current mesh model. Shader-specific interpretation and a complete preview/save path are needed before adding painting controls. |

Viewport selection, weight and deformation colours are overlays, not saved vertex
colour data. Unidentified tail bits remain source-owned; they should not be shown
as named editable parameters until their consumers are proven.

UV1, vertex colours and undecoded fields explicitly report unavailable or unsupported.
Renderer placeholder UVs/normals are never used as stored values. Editing is limited by
the active format, LOD, workflow and proven output path; a missing source map keeps
exact channel edits read-only. Skin weights are also read-only when neutral appearance
uses different bone transforms: the current inverse conversion would otherwise move
saved vertices during a weight edit. A mixed-capability batch is rejected in full.
Unedited channels, materials, topology and cloth bindings are retained. Geometry-channel
edits invalidate derived tangents.

Channel operations, Undo/Redo and drafts use the existing operation types. Ordinary
draft generations keep their current format and now retain channel-operation metadata
and original PAC bounds. Ordinary neutral edits return to source coordinates at Finish;
replacement drafts retain their existing explicit neutral-coordinate state.

### Implementation ownership

`cdmw/domain/mesh/vertex_parameters.py` owns selection/numeric rules and
`cdmw/services/mesh_vertex_parameters.py` owns authoritative inspection and
candidate validation. `cdmw_vertex_inspector.rs` owns the Rust UI. The additive
`vertex_parameters_v1` capability enables the read-only `vertex_inspect` event
and atomic `vertex_edit` command. Older combinations leave the feature
unavailable. Requests bind session, mesh revision, selection revision and
topology generation. Inspection is debounced, cancellable background work with
one active request and only the newest pending query. It stops when closed and
does not publish a mesh document, advance history/revisions or rebuild materials.
Inspection errors remain local. Edits validate the entire candidate before the
existing prepared-mesh commit, preserving an existing Redo branch on rejection.

## Existing editing controls

Rust's **Visible** selection compares projected depth with a floating-point
rounding allowance, so fitted human meshes do not select the hidden back surface
through the front. **X-Ray** explicitly selects through occluders. A brush stroke
accumulates its painted path and commits one undo step.
Recording a completed selection keeps the side panels visually stable; new edits
still wait for the host acknowledgement, without briefly dimming the whole UI.
Selected controls pair the muted accent background with the theme's strong text
colour. Disabled labels stay readable; their fill, border, and interaction still
distinguish unavailable controls.

### Parts and status presentation

Parts use compact, single-line names with the full name and material on hover. Geometry
Layer names also shorten to fit, reserving room for the visibility button; hover a
shortened name to read it in full. The Inspector scrollbar has its own space, keeping
button edges clickable. The checkboxes and Visibility menu hide/show parts in the
viewport; hidden parts remain in the output, and a hidden Geometry Layer still controls
its own parts. All and Invert operate on visible parts, and selection changes update the
viewport immediately.

Duplicate and Delete target only the explicitly selected whole parts. They wait for
pending selection updates and require Free Edit; **Enable part edits…** opens the output
controls directly. Delete keeps at least one part, and successful structural edits
refresh the list through the same shadow history used by Undo/Redo.
Whole-Part Delete uses the current document size as a conservative capacity
bound, avoiding a disposable clone before the native transaction. Capacity
refusal leaves the current mesh and history intact. Other operations that need
a native clone retain the failing snapshot stage and native error when refused;
Python fallback stays blocked while the native core is available.

### Shell and workspace owners

`tab.py` is the stable public Qt class. Bounded `tab_*.py` owners hold shell,
Rust process/protocol, package, report, session, state, interaction, and action
behavior. Retained `.NET`/`d3d11` module names are compatibility imports and
persisted-setting adapters only; every production preview and editor process is
Rust.

`workspace.py` is the stable standalone Blender-style workspace class. Bounded
`workspace_*.py` owners hold state synchronization, skeleton presentation,
shell/panel construction, reports, interaction, and the UV canvas/helpers. Its
widgets emit action descriptors; mesh edits still execute through
`MeshEditorController` and `MeshService`. Its Validator tab renders
service/domain export validation findings; it does not inspect mesh geometry
itself. Outliner, material, UV, and skeleton panel rows are populated from the
service-backed workspace summary. Its Compare tab renders the service-backed
source-vs-edited summary and emits preview-mode requests for edited, source,
and ghost overlay views.

### Archive sessions and neutral appearance

`MeshEditorTab.open_archive_session()` is the normal entry point. A correlated,
cancellable `MeshArchiveSessionLoadWorker` reads and round-trip-validates the
exact archive bytes, creates the authoritative `MeshService` edit session, and
publishes only the current completion. Matching source-hash drafts open against
the current source and produce the non-modal Resume/Start Fresh banner; starting
fresh never deletes a draft. `MeshEditorTab.open_session()` remains a compatibility
wrapper over this direct contract.

Archive PAC sessions resolve the same head-specific PABC neutral appearance as Archive
Browser. The embedded editor labels these meshes **neutral appearance** and uses the
reconstructed face for selection, move/sculpt operations, comparison, and Undo/Redo. The
authoritative mesh keeps the original PAC coordinates. Finish inverts each vertex's
blended skin transform before exact-writer validation and committing edits, so the game
does not apply the face correction twice. Opening and finishing without a geometry edit
preserves the source bytes.

Unreadable or non-invertible resolved appearance data reports a load/preparation error
rather than opening a falsely corrected face; meshes with no linked variation retain
their source shape. Finish or cancel this edit before importing an unrelated source
mesh. Archive Refit has its own per-asset neutral mappings, so it can load body and
armor together without applying the body's appearance transform to the armor. Free Edit
OBJ output retains the displayed neutral shape; game-asset output retains the reversible
source-coordinate mapping.

Body and armor may use different PAC slot ranges. Free Edit combines their
geometry for OBJ output without requiring a shared rig, retaining up to eight
original influence lanes in the session. Exact PAC output preserves each
asset's original skin bytes, including references beyond its attached PAB's
bone count; changed weights still require the explicit safe weight operation.
Rigid accessories need no character appearance mapping. When no complete PAC
palette resolves, archive loading retains source geometry and reports that
character appearance and named weight editing are unavailable. Other appearance
decode errors still stop loading. Rejections include the available zero-based
mesh/vertex coordinates and expected/actual values in Activity and Log.

### Scripted edit sessions

`MeshEditorTab.open_mesh_session()` opens a scripted in-tab edit session for a
`ParsedMesh` without starting Archive Browser UI. It creates the same authoritative
service session and embedded Rust shadow workflow as an archive open; it does not build
a Vortice authoring package. `MeshEditorController.native_update_for_result()` is
native-payload-only; Python mesh-based preview packing is explicit archive-only code
behind `legacy_python_update_for_result(...,
allow_archive_legacy_preview_rebuild=True)`. `MeshEditorTab.open_mesh_file_session()`
opens a supported PAC/PAM/PAMLOD file through `MeshService.load_mesh_file()` before
entering the same standalone edit session path for scripted callers.

UI callers should use `MeshEditorTab.open_mesh_file_session_async()`, which runs file
IO, parsing, and service session creation in `MeshFileSessionLoadWorker`, then attaches
the controller and already-loaded mesh on the UI thread. `tab_rust_editor.py` owns the
only production editor route, with process startup, protocol handling, diagnostics, and
shutdown in `tab_rust_process.py`. `tab_archive_material_context.py` owns correlated
archive material requests; `tab_direct_output.py` owns the direct output actions. The
retired `mesh_editor_backend` preference is ignored and no engine selector is built.

Before loading a mesh, CDMW validates the bundled `cdmw_mesh_lab.exe`; a missing or
incompatible package blocks the open with a visible reason and never falls back to
Vortice.

### Rust startup and shadow session

After the authoritative archive `MeshService` exists, CDMW starts `cdmw_mesh_lab.exe
--cdmw-session <manifest> --embedded-parent-hwnd <decimal>`. Rust creates one
undecorated winit/wgpu child containing the complete editor UI. `rust_host.py` verifies
the reported HWND belongs to the launched process, attaches it to the native Qt host,
and synchronizes resize, show/hide, focus, DPI/screen changes, and Qt `WinIdChange`
re-parenting. Failure terminates the owned process, leaves no detached window, and
offers Retry from a fresh shadow.

The child uses a dedicated native surface beneath the loading/result pages, so GPU
initialization cannot cover the loading page with a blank window. The New Item and Mod
Management hosts retain that page until their first rendered state; an asynchronous
paint request lets the covered child produce that first frame. The compiled Rust UI
emits the merged `cdmw_rust_mesh_editor_control_contract_v2`; every enabled row has a
compiled UI and dispatch anchor, while every disabled row carries a reason. It has no
Vortice contract input or build-time Vortice probe.

Standalone Rust Lab modes remain independent. The five direct output buttons use
explicit normal, hover, pressed, and disabled states. Validation-gated outputs and
receipt-gated restore stay visibly unavailable until their prerequisites exist. The
session-state bridge carries one explicit output policy: **Exact Game Asset**, **Free
Edit/Rebuild**, or **Read Only**. Exact PAC/PAM/PAMLOD LOD0 sessions show only
writer-safe actions, disable operations whose result cannot preserve protected records,
expose the exact reason in help, and still defer the final decision to the writer and
validator. Higher unproven LODs do not silently enter the exact policy;

Free Edit may author the active higher LOD only to a new validated OBJ/MTL destination.
Imported OBJ/FBX/DAE/glTF sessions likewise require the user to choose a new output
folder before proven non-exact topology tools appear. MeshInfo and unknown formats
remain read-only for selection, inspection, comparison, and safe export. The Python host
and resident forms reject the same unavailable command before mutation.

In **Viewport > Output**, active Free Edit sessions show **Choose output folder...**
until a destination is configured, then **Change output folder...** with the chosen
path. This also works for imported meshes opened from Create New Item, which already
start in Free Edit. The picker chooses the parent of a new package folder; existing
destination validation still applies. Cancelling the picker keeps the current
destination. Selecting a folder does not export the mesh.

Integrated Rust authoring owns a disposable shadow `MeshService` under a single session
directory. The preparation worker creates that isolated mesh once and the shadow service
adopts it directly; it no longer performs two additional full-mesh clones before the
helper can start. Protected channels, Geometry Layers, object transform, output state,
provenance, and the native Morph & Refit runtime remain isolated from the authoritative
session. The initial channel file references geometry already stored in `document.bin`
instead of writing a second positions/normals/UV/index copy.

Revisioned local gestures and typed asynchronous service commands update only that
shadow. Candidate payloads are consumed, superseded state files are pruned after safe
replacement, generated layer and morph-profile trees are independently bounded, and the
complete owned tree has an aggregate limit. Path escape, hash, length, unexpected-entry,
stale-generation, replay, and out-of-order checks fail closed.

Runtime snapshot restore and cleanup support Windows temporary folders redirected
through directory junctions, including Finish Edit Mesh. Snapshot location, length,
and checksum validation remain mandatory.

### Authoring geometry transport and derived state

New authoring packages publish geometry as `mesh_document_binary_v1` and require the helper capability with that name. The first document is `document.bin`; acknowledged updates use `state-<revision>-<10 lowercase hex>.bin`. The reader also accepts the existing JSON document contract. Archive Preview retains its explicit JSON/Preview Core paths. An unsupported binary version or incompatible helper is rejected before loading the document.

#### Binary document version 1

The 16-byte little-endian header is `<8sHHI>`: magic `CDMWMSH1`, version `1`, flags `0`, and the UTF-8 metadata length. Metadata is bounded to 16 MiB and uses schema `cdmw_mesh_document_binary_v1`. It retains format, source SHA-256, parser, LODs, part names/materials, source ranges, layouts, warnings, and reported LOD count. Each numeric channel has a descriptor containing `dtype`, `components`, `count`, `offset`, and `byte_length`.

| Channel | Wire scalar | Components |
| --- | --- | --- |
| Positions, normals, shader masks | Little-endian float64 | 3 |
| UV0 | Little-endian float64 | 2 |
| Triangle indices | Little-endian uint32 | 1 |
| Current source vertex indices | Little-endian int32 | 1 |

Array order within each part is positions, normals, UV0, triangle indices, source vertex indices, and shader masks. Offsets are relative to the first byte after metadata. Spans must be contiguous and consume the file exactly; size multiplication, offsets, counts, scalar widths, and schema fields are checked before allocating decoded arrays. Existing native geometry validation remains authoritative, including finite float32 values, valid triangle indices, and shader mask bounds. Partial/empty normal and UV arrays and signed source mappings retain the existing native admission rules.

Float64 transport preserves the Python values until the existing Rust float32 rendering boundary. Fractional shader masks and negative source mappings retain their values. Original-relative PAC provenance, skin weights, tangents, and UV1 continue through `channels.json`, whose geometry reference points to the matching document.

The structural fingerprint is versioned with the transport. SHA-256 starts with `cdmw_mesh_document_binary_v1` plus a zero byte and the uint32 LOD count. For each LOD it includes uint32 level and part count; for each part it includes uint64 position/index counts followed by raw position and index bytes. The consumer verifies it before float32 conversion. The outer file reference independently verifies SHA-256 over the entire document, including metadata and every channel.

#### Publication and caching

Documents retain the owned-session path, root identity, exact byte length, SHA-256, and total submesh-count checks. The payload limit remains 512 MiB and the aggregate session limit remains 768 MiB. A complete replacement is installed atomically before obsolete state documents are pruned, preserving the last usable recovery document if preparation, capacity checks, or publication fail.

Each authoring session retains one immutable prepared geometry encoding. Capacity preflight and publication reuse those exact bytes only after the same prepared mesh successfully commits against its captured revision and unchanged channel identities. Cancellation, stale revisions, malformed candidates, and failed admission discard pending bytes. State-only changes can retain the current geometry encoding; unknown service revisions invalidate conservatively. Closing the session releases its derived caches.

Inspector caches track geometry and weight revisions separately. Selection, layer presentation, and active-bone changes refresh their small response fields while reusing verified static skinning summaries and bounded influence rows. Immutable original PAC row/palette checks are keyed to their source and rig identity. Weight, topology, rig, provenance, and policy changes invalidate the affected results. Island discovery also follows position changes, since coincident seam positions affect connectivity; it does not hash entire position/index arrays on every inspector update.

#### Native working meshes and textures

Smooth uses the working mesh's immutable, sorted vertex adjacency. Topology changes rebuild
that graph; compatible authoritative attribute updates reuse it. The initial authoring
load constructs the selected LOD's editing graph while retaining all authoritative LOD
geometry. An uncached LOD is constructed on the bounded loader with shared immutable
source data. The current scene remains usable until a result with the matching source
and generation is accepted; cancellation and newer requests discard stale results.
Parked LODs retain their own history, and an authoritative document replacement invalidates
inactive graphs when required.

Decoded DDS payloads have shared immutable ownership. Material mappings and role-specific
interpretation remain separate, while remapping and document refresh avoid copying the same
CPU texture data. Queued loaders and installed scenes retain only their own live references.


### Theme and input handling

The embedded child receives CDMW's active semantic palette, explicit light or
dark variant, UI and data font sizes, scale, and density before reveal and after
every live appearance change. Rust maps those roles to its panels, fields,
buttons, selections, warnings, and disabled states instead of inheriting the OS
theme. The session bar, camera strip, left tools, Parts, Layers, and History are
split into named compact groups so controls remain scannable at constrained
sizes.

### Local gestures and history

**Inspector > Action History** lists confirmed actions in order. Click a row to
select it without changing the model, then right-click **Undo from here** to undo
that action and every later action. Undone entries remain in the list with hollow
markers and dimmed labels. Right-click **Restore through here** on an undone entry
to restore the intervening actions, including that entry. Numbers distinguish
repeated action names. A new edit after undoing replaces the redo branch, just as
with the existing Undo/Redo buttons.

History navigation waits for each confirmed Undo/Redo result before continuing.
Controls are disabled while edits are pending, and a failed restore or expired
history entry stops at the last confirmed state. These controls use the current
editing session's retained history; they do not replay or remove isolated edits
out of order. `cdmw_history.rs` owns the list and traversal; the existing host
history still restores geometry, selection, profiles and other editor state.
Morph & Refit snapshots retain the earlier native actions needed to cross between
body controls, fitting and ordinary mesh edits in both directions. Their retained
native data counts toward the existing history memory budget; a new edit after
Undo still discards the previous Redo branch.

Select, Move, Rotate, Scale, Grab, Smooth, Inflate, and Pinch execute locally in Rust.
Completed viewport drags submit only changed vertex attributes, including the normal
one-ring, instead of copying and serializing every Part's geometry. Revision, payload,
topology, capacity, export validation and one-entry shadow history remain enforced.
The v1 candidate accepts sorted, unique per-Part `vertex_indices` for sparse updates;
position and supplied normal/UV rows follow that index order. Such updates cannot
create missing attribute channels or carry topology/source-vertex changes. Every Part
still has a candidate slot, and unchanged slots contain empty updates. Legacy full
candidates remain accepted. The existing base revision identifies the geometry to
which each delta applies.
Selection is acknowledged with a selection-only command; it never sends geometry
channels. Geometry candidates preserve original channel values when their Rust `f32`
representation is unchanged, including fractional PAC values. Whole-part translation
preserves authored normals; rotation and nonuniform scaling transform them without
replacing custom shading with face averages. Partial-part deformation still updates
affected geometry normals. Selection, bone choice, output policy, and layer presentation
changes leave resident geometry loaded.

**Sculpt > Bend** holds point **1** while you drag point **2**. Select the whole rope
Part or island, click the fixed end, then drag farther along that section. For a
vertex-region selection, use X-Ray to include its back side. **Reset anchor** lets you
choose another fixed point. The first click creates no history entry; release commits
one Bend entry, and Esc, focus loss or viewport resize cancels an unfinished drag.

Bend follows only the selected connected component in the anchored Part. Exact
coincident seams in that Part connect; nearby or other Parts never enlarge the scope.
The fixed side stays in place, while circular bending rotates cross-sections without
scaling and retains the centreline's arc length. The endpoint follows a constrained
curve and may stop short of the cursor. Tight bends are limited to avoid collapsing
the inside. This is intended for elongated sections, with enough lengthwise segments;
it does not add geometry or solve collisions, knots or arbitrary branching shapes.
Undo and Redo use the existing validated Mesh Editor history.

Geometry updates reuse successfully uploaded textures when their ownership is unchanged
and retain the Bones overlay preference. Numeric transform steps use the same revisioned
transaction lane. Inflate uses signed strength, where positive values inflate and
negative values deflate, and face Extrude sends an explicit world-X, Y, or Z offset.
Cleanup, mirror, normals/tangents, UV0, bone selection and skin-weight editing are
strict typed `MeshService` commands with explicit selection, allowlisted arguments,
output-policy checks, disposable candidate preflight, and shadow history.
Adjust/Normalize require explicitly selected Vertex elements;

Transfer from Original may restore the immutable source skin channels into an unskinned
working mesh from selected vertices or Parts. Loop Cut count/factor, Refine Smooth
strength/passes, and Weld distance are carried with typed topology commands. Successful
no-op results and host diagnostics are shown instead of claiming that an edit completed.

Deleting the last vertices in a Part retains its empty slot in the editing session.
Other Parts keep their source and material identities, and Undo/Redo restores the
deleted geometry, including after Finish. Exact PAC output suppresses a fully deleted
source Part at every stored LOD, retaining its descriptor and material slot as a tiny
valid draw with matching source skin/cloth bindings. Other Parts' LOD records remain
unchanged unless explicitly edited. This output representation never populates the
empty editor slot. Missing deletion provenance, unsupported layouts and bounds that
cannot represent the tiny draw still block export without closing the session or
discarding edits.

Morph & Refit hydrates the selected bound garment's saved
enabled/mode/intensity/clearance values before applying a change; profile creation
exposes its rule, axis, amount, feather, falloff, and mirror inputs instead of creating
a hard-coded deformation.

Geometry Layer Copy/Paste names the required selection and Free Edit policy, and layer
visibility removes hidden Parts from both rendering and picking. Cleanup and other
topology-changing tools remain visibly locked by Exact output with a direct instruction
to choose Free Edit. Bevel/chamfer, UV1 and a 2D UV workspace, true weight paint, posed
skeleton deformation, normal-direction or edge extrusion, sculpt symmetry, and full
layered/dye material composition remain open rather than being presented as functional
controls.

### Skeleton lookup and Rig and Weights

Archive PAC sessions resolve a matching PAB automatically from the same archive index,
using the original PAC's bone references as well as descriptor and family matches,
before attaching it to the shadow service. The current Archive Browser passes its
prepared per-asset dependency snapshot into the session instead of relying on legacy
global indexes. Queued opens and draft resumes retain that snapshot for both skeleton
and material lookup until the session closes. The PAB is a separate skeleton dependency;
the PAC's vertex weights alone do not contain the named bone hierarchy.

The Rust window has no manual PAB picker. Rig & Skin Weights reports the actual
automatic-resolution failure (including missing dependencies, ambiguous matches, and
invalid or empty skeletons) and keeps weight editing disabled until the exact PAC LOD0,
palette, source-map, and record-layout requirements are satisfied.

Rig & Weights is temporarily hidden from the product tool rail. Its code and
direct headless tests remain available; the following describes the retained
implementation rather than a currently accessible tool.

Rig & Weights identifies the loaded mesh, named Parts, and automatically attached PAB.
Its searchable bone chooser shows parent context and a labelled gold marker on the
active bone. Bone inspection preserves the edit selection and camera; **Frame bone** and
**Frame influence** provide explicit navigation. **Weight colours** displays the active
bone's resolved influence on visible surfaces using a labelled blue-to-gold 0–100%
scale, independently of orange edit-selection highlights and saved materials. **Select
influenced vertices** replaces the edit selection with positive-weight vertices in
visible Parts, including their rear vertices.

Hidden Parts remain excluded. Selected weight details are collapsible below the
controls. Missing mappings and oversized or invalid display data show an unavailable
reason rather than a partial or guessed influence. Skeleton lines use mesh-space bind
positions, not the PAB's parent-local offsets. These controls inspect the bind rig; they
do not pose it or paint weights with a brush.

### Morph & Refit workflow

**Morph & Refit** uses a collapsible arrow header in the expanded Tools panel,
matching the other tool groups. Click its header to open or close the settings;
closing returns to Orbit navigation. Viewport, the tool groups, Parts,
Geometry Layers and Action History start collapsed. Morph & Refit opens directly to
**Setup**, with **Fit**, **Shape** and **Saved** tabs. The selected tab, nested page
and drafts stay available when returning from another tool or moving between expanded,
pinned and floating settings. Closing panels preserves geometry and selection.

**Setup** follows **1 · Body**, **2 · Garments**, and **3 · Bind to body**.
Load and selection actions sit with their role. **Use loaded parts** retains per-asset
body assignment and **Set body from selection**; **Choose Parts** retains the named
Part checkboxes and **Open Selection tool**, without an inner scrollbar. Long names
remain on one line with the full name on hover. Binding uses the explicit selected
garment set; **Continue to Fit** becomes available once garments are bound. **Clear
Refit** remains separate from preview Reset and Bake.

**Fit** starts with **Fit all enabled garments**, whose scope is independent of the
settings selection. **Review parts** opens the compact **Choose garments** list;
rows show each Part's mode or **Skip**. Click a name to highlight that Part and edit
its settings; Ctrl-click selects several. **Adjust garments** has one **Editing**
scope and one Apply action, targeting either selected garments or all bound garments.
Choosing a garment switches the editor to the selected scope. Clearing a selected
scope disables Apply; it never silently expands to all garments. **Fit as** offers
Flexible, Rigid component, legacy Offset follow and Skip. **Skip**, or clearing
**Refit enabled**, excludes the targets while retaining their mode and settings.

Tightness and Clearance stay visible. **Follow body shape** contains **Body-shape
following %** (the former Intensity control). **Body region**, **Local influence**
and **Check current fit** open directly from their headings. Region and influence
headings show existing restrictions and masks even when closed. Optional sections
retain their open state while using the tool. **Create body slider** is in Shape.
**Shape** offers **Body**, **Sides** and **Sliders** pages for coordinated controls,
paired adjustments and manual values. **+ Create** opens **Procedural** or **Sculpted**
creation; **Edit slider** opens its procedural fields directly. Sculpted creation
captures a neutral body and the edited target shape. Each slider can also own a
separate outfit correction. **Saved** separates **Profiles**, **Presets** and
**Fitting setups**, including existing import, export and matching-setup actions.

**Reset** and **Bake** remain below the scrolling content in every tab and panel
presentation. A pending sculpted slider replaces them with **Save slider** and
**Discard base**; an outfit correction shows **Save correction** and **Cancel**.
Tab navigation remains available while these operations are pending, while conflicting
actions stay disabled. Correction comparison also remains accessible in this strip.

Slider definition labels and fields use separate rows to fit the expanded panel, pinned
settings, and floating windows without horizontal clipping. Short windows scroll
vertically. The preview warning means that topology and definition changes are locked
until Reset or Bake; it does not mean the topology is incompatible.

Framing a small selection retains the complete mesh's camera clipping range.
Scrolling a panel cannot carry camera zoom into a later viewport click.

#### Asset roles and catalogue browsers

**Setup** lists loaded assets under their body or garment role, with Part counts
and full paths on hover. **Set as body**, inside **Use loaded parts**, assigns only
that asset's Parts as the driver. **Load body...** and **Load garments...** open the
loaded game archive catalogue with search,
paging, and source previews. Choosing a body assigns its Parts as the driver; choosing
armor adds and selects its Parts ready for binding. No Free Edit or external mesh file
is required. The panel lists loaded files separately from the assigned body driver and
bound armor/clothing.

Both browsers search the same catalogue: the chosen role determines what the
mesh does. Body is the shape driver; armor is the garment that follows it after
binding. If you load armor before assigning a body, the initial mesh becomes
the body driver, including when an existing Morph profile has no assigned driver.
If you started with clothing instead, Load body assigns the
new body while keeping the original clothing available for selection and binding.

The catalogue comes from the archive workspace, including when Mesh Editor is detached
into its own window. Cancelling the picker or failing to open the catalogue leaves the
editor session available for further commands. The picker puts the searchable archive
list on the left and a taller combined preview on the right. The current target and
selected source share one view in their original archive coordinates, preserving their
relative size and position.

Each has its own **Solid** or **Wire** display choice. **Load garments...** starts with a
shaded, untextured solid target and wire armor; **Load body...** starts with a solid
body source and wire target. Wire edges overlay solid surfaces, including hidden edges,
to make overlap visible.

#### Combined preview and source identity

The combined preview uses the interactive 3D viewport: Alt/Ctrl-drag to orbit,
Shift-drag to pan, and scroll to zoom. **Reset view** restores the shared
framing. Each model keeps its Solid/Wire choice while the camera moves. Display
changes reuse decoded meshes and retain the camera; resizing does not decode or
rebuild the scene. It shows the original archive geometry; live edits and refit
results are inspected in the main editor viewport.

Archive sources keep their own original bytes, Part mappings, palettes, and archive
paths. Each neutral appearance uses its own reversible mapping; Finish restores each
asset's source coordinates before validation and writing. Drafts retain those mappings
in the version 2 refit record and can still load version 1 records. Added meshes retain
their resolved textures and layered material data across loading, Undo/Redo, Bake,
Finish, and reopening.

New archive-refit draft generations own checksummed copies of their DDS and decoded
layer images (up to 512 MiB combined), so clearing the preview cache does not remove
their textures. Missing or damaged draft files reject that generation before it replaces
the loaded geometry. Older drafts still open, with a warning when their cached material
files are missing; reopen the source meshes to reload those textures. Adding an asset
reuses the existing owned textures and compiles only the incoming asset's materials.
Archive loading also reuses geometry during read-only validation and avoids redundant
temporary topology and history snapshots. Per-asset source checks, independent export
copies, and the reversible load remain in place.

Generated support maps use bounded array decoding and fast, lossless PNG compression;
material ownership and texture pixels are preserved. Geometry, rig dependencies, and
materials prepare off the UI thread before one undoable publication. Cancelled, stale,
duplicate, invalid, or oversized sources leave the edit unchanged. Rejected material
preparation also leaves the session material cache unchanged, so another valid archive
import can proceed after a size, write, or cancellation error. Reset or Bake before
loading; Clear Refit first if garments are already bound.

Archive refits preserve the original topology and allow selection across all visible
loaded assets.

#### Body selection and garment binding

**Select body** selects the assigned driver Parts; it does not open another
file. Its highlighted state shows when the body is already selected.
**Select garments** selects non-body Parts even before they are bound. It stays
disabled until the body is assigned, so an unassigned body cannot be included.
When only a body is loaded, **Load armor...** opens the archive browser directly.
Refit setup appears immediately after the meshes, with one compact next action.
The Rust control messages carry slider metadata, status and counts. Full weighted
vertex scopes, target deltas, corrections and masks stay in the host for editing,
saving and export.

Select clothing/armor Parts and bind them. **Create body slider** selects the driver and
opens the slider creator in view when no shape sliders exist. Custom regions can still
be selected with the Selection tool. The panel rejects overlapping roles and setup
changes during an unbaked preview. The initial-binding warning records distance at
bind time; it is not a measurement of the current fit. Binding
replaces the garment set; select every garment that should participate.

Surface, Offset follow and Rigid component modes retain each garment's enabled state,
body-follow intensity, Tightness and clearance. **Changes not applied** marks pending
settings. The single Apply button follows **Editing**: **Apply to Selected Garments**
or **Apply to All Bound Garments**.
Choose **Selected mesh islands** in **Editing** to fit whole selected islands.
**Choose mesh islands** expands an embedded list grouped by garment Part. Each
row shows its effective Fit-as type and **Inherited** or **Custom** status. Click
to select an island, Ctrl-click for several, or use **Select islands** and
**Clear selection**. Each island inherits its Part until edited; mode, Skip, body following, Tightness and clearance
can then be overridden independently. **Apply to Selected Islands** changes only
the fields you edit. **Use Part settings** removes those overrides. Part settings
remain the defaults for the other islands, and island overrides survive Part edits,
Undo/Redo, Bake, saved fitting setups and draft reopening. Output Part identities,
vertices, faces, UVs and skin weights are retained. Independent rigid island
overrides do not automatically regroup with nearby ornaments.
An enabled Custom island still fits when its Part is set to Skip; inherited
islands follow that Skip. Use **Use Part settings** on the Custom island to make
it follow the Part again.

Only fields you change are applied. A **Mixed** marker identifies settings that differ
across the chosen garments. Mixed numeric fields initially display the first Part's
value; **Use displayed following**, **Use displayed tightness** and **Use displayed
clearance** explicitly choose that value for the whole scope. Unchanged fields retain
each Part's settings and masks. Apply is disabled until a field changes, and a refused
update retains the pending edits. Apply pending settings before **Fit all enabled
garments**; fitting stays disabled while edits are pending.
Tightness requires Surface or Rigid component mode on every chosen garment.

**Fit all enabled garments** tightens all enabled bound garments around the loaded
body. It needs no viewport selection, body slider, original body or skeleton. It sets **Tightness %**
to 100 and clearance to at least 0.1%, retaining each Part's mode, intensity, masks and
allowed body region. Inputs must already share the intended alignment and pose.
After excluding islands with **Include** and starting a new edit session from the
finished PAC, unused vertex records do not need body correspondences for tightening.
They retain their followed positions while the remaining garment surface is fitted;
topology and exclusion stay intact. Visible surfaces with unreliable body matches
still reject the fit and retain the previous preview.

| Mode | Fitting behavior | Typical use |
| --- | --- | --- |
| Flexible / Surface | Changes the broad silhouette with a smooth displacement field, retaining folds and moving openings with adjacent cloth. | Cloth and flexible armor. |
| Offset follow | Keeps the existing local-offset body following. It can bend a piece; inward tightening requires another mode. Stored as the legacy `rigid` mode. | Compatibility with existing fits. |
| Rigid component | Keeps connected or touching hard pieces together, including matching material seams; follows the fitted cloth and moves clear of the body without changing dimensions. | Daggers, hard plates, assembled necklaces, pendants, buckles and trim. |
| Skip | Disables body following and fitting for this Part, retaining its stored settings. | Accessories to leave unchanged and position manually. |

**Body-shape following %** controls body-slider following. **Tightness %** independently
controls inward fitting: 0 retains the earlier following/clearance behavior, 100 requests a
natural snug fit, and intermediate values blend from the same neutral geometry.
Clearance sets the gap as a percentage of body size. Parts joined into one rigid
component require consistent intensity, Tightness, clearance and mask influence.
Materials do not choose a mode automatically. A hard piece can span several material
Parts: highlight each, then choose **Rigid component** for all of them. Ctrl-select
and **Apply to Selected Garments** can set their mode together. Matching material
borders with tiny coordinate differences also move as one piece, without snapping
the authored vertices.
Touching ornaments, including tiny gaps at their joins, form one rigid assembly.
A rigid assembly follows its Flexible attachment, moving and rotating with that
area while retaining the shape and spacing of all its links and pendants.
Jewelry spanning the body's centre uses a central join or joins on both sides;
a headwrap touching only one side does not steer the entire necklace. Without
such an attachment, fitting centres the assembly on the body and preserves that
placement during clearance correction. Tightness and influence control how much
centring is applied; Skip and zero influence leave the piece in place.
Use matching body-follow intensity and mask influence at the join for coordinated
body-slider following; deliberately different strengths retain independent following.
Without a nearby Flexible attachment, sparse, body-centred hanging assemblies
can adjust depth and pitch together against the settled cloth and body. The
necklace remains one rigid shape and stays centred; dense plates retain their
existing orientation rules. The search preserves the assembly's dimensions and
uses Tightness and influence to blend the adjustment. This preserves authored
overlaps at joins and prevents pieces from twisting into each other.
An unchanged hard shape can leave extra space where it cannot sit flush to the body.
For separate Flexible layers, Tightness also takes up the loose gap between an
outer belt and its wrap. It retains a clearance gap and their layer order instead
of squeezing both onto the skin. Authored crossing folds retain their construction;
coarse faces cutting through an otherwise outer layer are checked as contacts.
Waist bands retain their height contour and taper as they tighten. The sides of
a rolled profile move together, including on open or double-sided bands, so an
inner edge does not push through the outer face. Proven solid walls keep their
depth. Nonuniform influence masks retain their per-vertex control.
Irregularly spaced rolled edges share a smooth circumferential displacement
field. Contact pressure spreads over the band's physical width, preserving
separation from the inner wrap without introducing narrow ridges that disrupt
the band and its attached rope. This changes fitting movement, not source folds
or material identity.
If the smoother profile cannot resolve a new self-crossing, fitting retries the
previous checked profile/cloth paths from the same starting pose. Each attempt
must still pass all body, layer, shape and rigidity checks.
Rolled belt edges are checked for new self-crossings, including open or repeated
skins. An unresolved crossing retains the previous preview.
Small inset Flexible details, such as raised belt cords, follow their band
without being flattened into it. Compact touching knot pieces keep their shape
and attachment; long hanging panels retain their own fit. Details turn with the
backing as it bends. Surrounding cords share a continuous backing fit across
their thickness, including when refitting an exported or baked mesh.
Rigid means shape-preserving, not fixed in place. Fitting retains the authored
spacing between nearby cloth and hard pieces before resolving body contact.
Clearance then moves each connected hard piece as a whole, so cloth fitting to a
larger body can carry a buckle or dagger outward without stretching it. Skip and
zero influence still prevent this movement.
**Surface** can reshape hard ornaments around the body. **Rigid component** preserves
their dimensions, but may refuse a fit that cannot satisfy body or layer spacing.
Corrections that detach or deform a rigid assembly are refused with the previous
preview retained.
Use **Skip** for accessories that should stay unchanged while the cloth fits, then
position them manually. One Part can contain both flexible and hard geometry;
use its mesh-island controls to give those pieces different fit types.

The fitter uses local body-surface correspondences and a seam-connected displacement
solve, then checks contacts against the complete body, including when an allowed
region limits correspondence. Edge/triangle checks also cover body crossings between
the regular fitting samples. The body search crosses coincident material seams and
measures distance to triangle surfaces, so coarse mesh sections do not cut it short.
Adjoining body Parts can share the correspondence walk across tiny boundary-coordinate
differences when reversed boundary edges match reciprocally with compatible face orientations.
Ambiguous or overlapping candidates remain separate; source vertices are not snapped.
Matching panel borders also share displacement when independent mesh quantization
leaves tiny coordinate differences. Reversed boundary edges with agreeing surface
orientation identify those seams; nearby parallel layer rims remain separate. The
original coordinate offsets stay intact, and protection carries across the seam.
Missing body surfaces, such as a face supplied by a separate mesh, do not pull
covering cloth onto the hole's rim. Clearance checks distinguish that open space
from occupied body volume. Waist and cuff rims follow the nearby fit along a
tapering body while retaining authored flare; narrow bands can tighten even when
their mesh has no interior vertex row. Smoothing follows the width of each connected
piece so loading a full body does not make small arm bands resist tightening.
An isolated target on a different nearby body surface, such as a waist vertex
binding to an arm, is excluded when it jumps far beyond its cloth neighborhood
and pulls against that neighborhood. Surrounding cloth carries the vertex instead;
allowed regions and retained bindings remain unchanged, and body clearance still applies.
It follows the broad cloth direction when choosing targets; a small hem fold should
not redirect a long panel onto nearby feet. Overlapping panels, belts and trim share
nearby cloth movement even when their mesh densities differ. Layer links must run
primarily across the body surface rather than along it, so a nearby sloping cloth
edge does not hold a waist opening at the width of a lower body section. Layer order
comes from the pre-fit garment. Disconnected surface islands receive the same layer protection
whether they occupy one Part or several Parts. Trustworthy coincident seams still
form a continuous surface. Open edges do not push surfaces they do not cover.
Already intersecting or nearly coincident trim follows the shared movement instead
of imposing contradictory inside/outside constraints. The collision stage uses the
conformed silhouette for
shape constraints so original garment width does not resist narrowing. Triangle
guards limit distortion while carrying common movement, so folded hems and trim do
not stick at their old positions. Body contacts are evaluated together: larger
corrections move a wider patch around the limb, while small residuals settle locally.
Contact corrections use two shorter smoothing passes to reduce new pointed areas
around isolated contacts, including on denser meshes. Late adjustments remain local
enough to clear cuffs and thin trim. This smooths the fitting displacement rather
than the garment vertices, so authored folds retain their shape.
Edited outfits retain uniform movement during the clearance solve, including tiny
draws left by excluded Parts. Attached cords limit stretching through their backing
cloth, so the final attachment update retains that protection.
Layer separation is checked again after smoothing. A shortened edge may recover its
authored length during clearance correction; that limit does not pull the garment
back to its old width. Thin folds are checked against their moving neighbors. Masks
constrain movement, including coincident seams.
Unreliable correspondence, unresolved contact or invalid geometry refuses the whole
candidate and identifies the affected Part; the previous preview and settings remain.
A refused fit may need a narrower allowed region, different protection or manual edits.
Inspect the front, back and both sides after fitting, especially thin cords and
folded skirts. Similar colours or a single grey shaded view can conceal overlap
even when the fitting command completes.

Repeated fitting evaluates the same neutral mesh. **Reset** restores the pre-fit
geometry and clears active Tightness. **Bake** makes the preview the new neutral and
clears Tightness; both actions support Undo/Redo. To undo a baked fit, undo Bake or
reload the original. No subdivision, remeshing, UV or skin-weight changes are involved.
Position-only PAC exports preserve the existing face-index slots, including hidden
slots left by exclusions, so fitting does not duplicate retained faces.

Fitting recipes and native morph snapshots write version 3 when island overrides
are present, otherwise version 2. Version 1 reads with Tightness disabled.
Morph draft payloads similarly use version 3 for island overrides; older apps
reject these newer files instead of silently dropping the island settings. Drafts with Morph & Refit state use layer-project version 8 and
retain the neutral geometry and active settings for reopening and Reset. Older readers
reject these new formats. Existing files are read without being rewritten.

Complex outfits retain the existing 90-second command budget, including subsequent
body-slider changes. Inspect the result before baking. Very loose skirts and long
panels may need lower Tightness or protection masks to keep their intended silhouette;
geometry alone does not identify which looseness is part of the garment's design.
Static geometry, renderer and PAC round-trip checks do not establish animation or
in-game appearance.

#### Inspect the current fit

**Analyze current fit**, inside **Check current fit**, measures the garments in
**Editing** (selected or all bound garments). It inspects the current preview without
applying pending settings. The read-only native query runs off the UI thread and does not change
geometry, settings, revisions or Undo/Redo history. It is disabled while another host
request is pending.

**Current fit diagnostics** separates distance to the current body from spacing between
recognized garment layers. Body results include minimum unsigned surface distance and
local normal offset. The normal offset uses the nearest face orientation; it does not
determine whether a point is inside the body. Layer results compare current gaps with
the neutral authored gaps and report the minimum retained fraction. Sample locations
identify the original Part and vertex so you can inspect the smallest measured gaps.

Measurements use model units and deterministic bounded sampling. The panel shows sample
counts, limited location details, partial results and explicit unavailable values.
Missing measurements are never displayed as zero. These samples do not prove that the
whole mesh is collision-free or that the outfit looks correct. Changes to the preview,
Morph & Refit state or selected garment scope hide stale measurements and ask you to
analyze again. The initial-binding warning remains separate from these current results.

#### Control what follows the body

In **Fit**, open **Choose garments** or use **Review parts**, then click a name to
highlight that piece in the viewport and load its fitting settings. Ctrl-click names
to add or remove Parts from the selection. Use **Body-shape following %** under
**Follow body shape** for body-slider following and **Tightness %** for inward fitting,
then use the Apply action for the displayed **Editing** scope. Names stay on one line;
hover to read the full name. Hidden Parts must be shown before selecting them.

**Local influence** uses the ordinary vertex, edge, face or whole-Part selection.
Its **Open Selection tool** action retains that selection.
Set **Selected influence** and choose **Set selected influence** to assign that weight
to the selected garment vertices. **Protect selection** assigns zero; **Restore
selected influence** assigns full influence. **Clear masks on selected garments**
removes their custom masks and returns those garments to full influence.

An absent mask follows fully. In a saved sparse mask, vertices absent from its rows
are protected. Zero influence prevents fitting, clearance and saved outfit corrections
from moving those vertices. Coincident seam vertices use the least influence in their
cohort, so a protected side of a seam stays protected. Protected areas may retain
clipping intentionally. Surface and the original Rigid mode accept mixed weights;
Rigid component requires one weight throughout each connected piece.

When a rigid piece spans several material Parts, select all of those Parts and set
their shared influence together. Setting influence or clearing masks applies the
whole selection as one undoable edit, preserving each Part's mode, intensity and
clearance.

**Body region** keeps binding targets separate from viewport selection:

1. Open **Body region**. Check its target garment names, or use **Use editing targets**
   to capture the current **Editing** scope.
2. Select the body faces or vertices they may follow. **Select body** and **Open
   Selection tool** provide the existing selection routes.
3. Choose **Use selected body region**.

Target checkboxes and **Use editing targets** preserve selected body faces or vertices.
Those targets remain captured when the viewport selection changes. Clicking a garment
name in **Choose garments** still selects it for editing and replaces the body selection.
Region targets choose where garments may follow; they do not change strength.

Only complete triangles inside the selected body vertices are eligible for binding.
A region with no usable triangle is refused. **Use whole body** removes the constraint
for the checked garments. Region changes require a neutral preview, and rebinding
preserves other garments' bindings, modes and masks. Regions constrain correspondence;
clearance still checks the complete selected body.

#### Coordinated body controls and sides

After assigning the body driver, open **Shape → Body** and choose **Create body
controls**. Generation requires source-owned PAC body Parts and their resolved,
matching skeleton. An unavailable reason identifies missing source or palette
information. Reset or Bake the current preview first. Generation creates a new
profile and preserves the previous custom profile and existing garment bindings;
Undo restores them together.

Profiles use compact, lossless JSON and load existing formatted profiles too.
Creation, saving, loading, portable presets and draft storage have no fixed profile
byte limit. Large JSON work runs incrementally on the command worker. Repeated
weighted selections are shared, and history keeps large files in shared temporary
disk storage. These files are released with their last history reference. Memory
budgets can discard older history, but retain the latest Morph edit for Undo/Redo.
Plain geometry edits retain the configured history memory limit even when their
native session has initialized an empty Morph runtime. Finish refuses an edit
whose Undo or Redo snapshot cannot fit.
Topology, file ownership, checksums and atomic rollback remain validated; all
vertex weights and definition fields are retained.

Supported anatomical regions receive detailed Size, Length, Taper, Flatten and
Shift sliders. Coordinated controls appear only when every required generated
slider and its supported rule are present:

| Control | Coordinated shape |
| --- | --- |
| Shoulder contour | Shoulder, upper torso and upper-arm fullness |
| Waist shape | Lower torso, with smaller pelvis and upper-torso contributions |
| Hip-to-thigh transition | Pelvis, hips and thighs |
| Upper-body balance | Upper torso, shoulders, upper arms and forearms |

These controls add to retained manual values. **Shape → Sliders** edits those manual
values and shows the combined preview value when it differs. **Reset body controls**
removes only the coordinated contributions, restoring the manual shape even after
the combined preview reached a slider limit. Ordinary **Reset** clears the complete
morph preview and its layers; **Bake** keeps the current geometry and clears the
layers. All these operations support Undo/Redo.

Layered changes validate saved authored targets and outfit corrections against
their neutral geometry and source/skin identity before use. Every garment referenced
by a correction must remain bound. Resolve pending slider or correction authoring
before changing these controls.

**Shape → Sides** offers **Both**, **Left** and **Right** for supported generated
pairs. Both shifts the two manual values equally and keeps their difference.
Its range narrows near the limits to preserve that difference, including fractional
side offsets. Both displayed endpoints remain usable. Left and Right change only
the selected retained side value. **Link sides** evaluates each pair
at the average of its retained manual values before applying coordinated controls.
It preserves the independent inputs, so unlinking restores them. Editing Left or
Right while linked still updates the retained input; the linked preview continues
to evaluate the pair together. Equal control values do not remove asymmetry already
present in the source body.

#### Sculpted body sliders

Use a sculpted slider when a saved target shape is more useful than a procedural rule:

1. Assign the body driver and Reset the current preview.
2. Open **Shape → Sliders → + Create → Sculpted** and choose **Capture body base**.
3. Shape the body with the existing editing tools, keeping its topology and source
   mapping unchanged. A compatible edited package can also supply the target.
4. Enter the profile and sculpted slider names, then choose **Save slider** below the scrolling controls.
5. Use **Save Profile**, **Save Preset** or a portable export to retain the definition.

The capture becomes the slider's zero base. Saving activates the new slider at 100%
and keeps the visible target; intermediate percentages blend its saved vertex deltas.
Other sliders can be combined with it against that same base. Capturing, saving,
discarding, and normal geometry edits use the existing Undo/Redo history.

**Recapture body base** deliberately replaces the pending reference with the current
neutral geometry. **Discard base** removes the reference and keeps the
current geometry. Save or discard it before changing Morph & Refit setup or finishing.
Compatible Rust sculpt publications retain the capture and fitting runtime across
native-session replacement.

External authored targets must come from a compatible package with retained source
vertex mapping. Matching counts alone are insufficient: Part order, triangles,
source mapping and skin identity are checked. Reindexed or unrelated imports are
rejected before replacing a pending capture.

Authored definitions store exact neutral coordinates at the native float32 boundary.
They are refused on a different neutral body instead of silently applying the saved
deltas to an unrelated shape. Reset retains the original base for further adjustment.
Bake makes the current geometry the new base; undo that bake or reopen the original
matching mesh to reuse the old authored definition, or capture a new definition for
the baked base.

#### Per-slider outfit corrections

Select bound garment Parts, then choose **Edit outfit correction** below the desired
Shape slider. The editor isolates that slider at 100% and sets the other sliders to
zero. Sculpt the selected garments, then choose **Save correction** below the scrolling controls.

The saved displacement is additional to the normal body fit and scales with that
slider. Zero removes its correction; intermediate values apply the corresponding
fraction. With direct sliders, saving keeps the selected slider at 100%. When retained
body-control layers are active, saving returns to the preceding manual, macro and
linked-side settings. **Cancel** in the correction action strip restores every Part's vertex
positions and all slider layers that were active when
editing began. This also discards accidental body edits and shape changes outside
the selected garments. UV and material edits are retained. Undo/Redo restores the
pending correction and discarded shapes. If topology or source/skin identity has
changed, undo that incompatible edit before cancelling; Cancel does not overwrite
changed geometry structure or source mappings.

Edits to unrelated Parts, changed topology, or effectively protected vertices are
refused when saving. Correction capture uses the fitter's actual seam-aware influence
weights, so fractional masks do not attenuate the captured correction twice. Finish
and unrelated Morph & Refit operations require the pending correction to be saved or
cancelled first.

Corrections retain the matching garments' topology, neutral geometry and skin/source
identity. Bind those garments before using a profile that contains their corrections.
Save Profile or Save Preset retains the correction with its slider; the mask and
binding constraints belong in a fitting setup.

Editing a procedural slider retains its saved corrections, including when the
slider is renamed. Undo/Redo restores the definition and corrections together.
Change a sculpted slider by capturing a new target instead of replacing its saved
shape with a procedural rule.

**Clear Refit** removes fitted movement and saved-correction displacement from the
garments. Correction data stays in the profile and applies again only after those
garments are bound and enabled. Saved influence masks remain part of exported
fitting setups; clearing the current bindings clears their session masks.

**Show outfit corrections** compares the automatic fit with the saved corrections
hidden while retaining the body shape and correction data. Turn it back on, or choose
**Resume editing**, before editing, exporting or finishing. View controls, selection,
Undo/Redo and Cancel remain available during the comparison.

**Reset selected outfit correction**, below a Shape slider, removes that slider's
saved correction only from the selected corrected, bound garment Parts. Other
corrections, body-control layers, bindings and influence masks remain intact.
Undo/Redo restores the removed correction and its geometry. When other corrections
remain on that slider, Reset first verifies their original neutral geometry and
source/skin identity. Removing every correction for the slider remains available
if that original base has changed.

#### Geometry layers and output

Archive Refit keeps the original game-file topology, so its Geometry Layers
organise loaded assets but cannot add or remove geometry. Free Edit is disabled
before any folder picker opens. For a separate mesh, Free Edit permits structural
edits and asks for a folder containing a new OBJ package. Finish the archive refit
and open a separate mesh to use that route.

**Finish Edit Mesh** keeps edits to both body and armor. **Build Mod** rebuilds
each asset through its own exact game-format writer and packages every original
archive path together. Hiding an asset changes the view without omitting its
output. Native fitting records its position/normal edits, and splitting the combined
session remaps admitted edit operations to each source file's own Part indices.
Earlier channel edits remain valid through Fit, Bake and Finish; unrelated
unrecorded channel changes still block output. Draft generations retain each
source fingerprint and asset mapping; Undo/Redo restores those mappings with
the geometry. A failure rebuilding any
asset prevents the package from being published. Shipped archives remain
unchanged; installation still uses the existing confirmation and recovery flow.

This is geometry refitting: it does not align mismatched poses automatically or
convert skeletons/weights. Visual fit, clipping during animation, and game
compatibility require separate inspection.

#### Presets and library history

**Save Preset** saves both the active profile and its current percentages into the
settings-owned `mesh_slider_profiles/definitions` and `presets` folders as one undoable
transaction. Finish Edit Mesh commits this library; cancelling the edit discards its
library changes. **Export Preset...** writes a portable JSON file immediately,
defaulting to the `mesh_presets` folder beside application settings. The file includes
the profile, saved vertex regions, procedural rules, topology fingerprint, and
percentages. **Load Preset...** validates the file, loads its profile and values,
previews it, and adds it to the session library with Undo/Redo.

Conflicting IDs get a new imported identity rather than overwriting different saved
definitions. The same driver topology and Part order are required. Authored targets
and corrections also require their recorded neutral geometry and source/skin identity.
Procedural-only profiles retain their version 2 shape. Profiles containing authored
targets or corrections declare version 3, so older CDMW builds refuse unsupported
data instead of silently omitting it. Value presets containing retained manual,
macro or linked-side layers also declare version 3 and verify that their combined
values still agree with the saved slider rules. Direct-value presets retain version 2.
Existing version 1 region migration remains
available; unverified legacy external target files are not reconstructed automatically.

Ordinary preset files retain slider definitions and values. They do not retain
session-specific garment bindings, masks or allowed body regions; use a fitting setup
for that complete configuration.

Body-control, correction and refit operations that do not save files keep their
Undo/Redo independent of other sessions' saved-profile changes. Operations that
write library files still verify the saved library before restoring it, so
unacknowledged external changes are not overwritten.

#### Reusable fitting setups and multiple outfits

Name the fit in the preset-name field and choose **Save reusable fitting setup** to
retain it in the session library. **Matching fitting setups** lists saved setups whose
body and garment Parts have the required neutral geometry, topology and source/skin
identity. Choose a **Saved setup** to apply it to the selected matching garment Parts,
or to all its garment Parts when none are selected. Selection also works before a
profile or garment binding has been configured. A selection containing none of that
setup's garments disables its application; clear the selection to apply to all of
its garment Parts. The body's preset remains shared.
An active shape preview can stay in place during matching and application because
compatibility is checked against its neutral base. Application checks the current
saved file again before changing the fit.

The saved setup includes manual and coordinated values, linked-side settings,
corrections, garment settings, influence masks and allowed body regions. It uses the
same undoable session library as profiles and presets: Finish commits it and Cancel
discards the session's library changes. Matching uses verified loaded Parts; it does
not guess compatibility from an outfit's name or transfer indexed data to other meshes.

**Save fitting setup...** writes a portable JSON file containing the active profile,
slider percentages, body roles, each garment's mode/intensity/clearance, influence
masks and allowed body regions. It records the neutral base even when a preview is
active. Give the setup a name in the preset-name field before saving.

**Load fitting setup...** validates the complete file against the currently loaded
meshes before applying it. The ordered body and garment slots, topology, neutral
coordinates and available source/skin identity must match. It recreates the saved
bindings and applies the body preset and garment settings in one undoable operation.
Conflicting profile or preset IDs receive new identities. Failed imports restore the
previous mesh, runtime, metadata and session library, including failures after the
preview and profile have changed. Retrying starts from the restored fit.
All target Parts' settings and masks are applied together, so a connected rigid
piece split across material Parts keeps a valid shared influence when its setup is
loaded. Other Parts retain their individual mode, intensity and clearance.

A setup can be reopened in a later compatible session. Load multiple outfit assets
around the same body to apply one preset and their individual settings together;
Finish and Build Mod continue through the existing atomic multi-asset output.
The saved-setup selector and service callers can target a subset of the setup's garment
slots. Unselected garments retain their current corrections, bindings and settings.
A partial application that changes body definitions required by those corrections
is refused; include their garment Parts or resolve those corrections first. The body
preset remains shared, so changing it can still change the automatic fit of other
bound garments.

This workflow operates on loaded, verified meshes. It does not search arbitrary
folders for outfits or transfer a garment's indexed mask and corrections to different
topology. Portable setup export writes its chosen file immediately; imported profile
and preset library changes are committed by Finish and discarded when the edit is
cancelled.

Undo and Redo restore library files through the same locked history path and update
the acknowledged profile fingerprint. Subsequent commands and Finish accept those
history changes while continuing to reject unacknowledged external file changes.

### Material presentation

The integrated Rust viewport reuses Archive Browser's complete resolved PAC/PAC_XML
material model together with the native material package for the same mesh identity. The
asynchronous resolver publishes the full model, its exact owning package, and the
acquired lease as one correlated result; native batch reconstruction is only a degraded
fallback because those flattened rows do not retain the complete dye and layer parameter
graph. Stale or cancelled results release their lease rather than leaving a
geometry-only package paired with new material rows.

Verification uses the complete archive identity (normalized path, source PAMT, PAZ
index, and entry offset), so two entries with the same virtual path cannot exchange
materials. CDMW carries that verified context into the isolated shadow package and
copies only bounded, hash-checked DDS resources beneath the session root, retaining
their role, LOD, and material range. Owner-conserved full-graph channels supersede
simplified package composites, while a package composite fills only a channel the
complete graph cannot produce.

A missing, incomplete, or unusable preview package leaves geometry editing available on
the neutral opaque surface and reports the exact texture fallback reason; it is never
presented as successful textured display.

#### Material handoff and relief

If another archive mesh is requested while a Rust Finish is still reaching its
terminal cancellation boundary, CDMW retains only the latest immutable open
request and its package lease. The current session closes first, then the queued
mesh opens once on the next UI turn; a late Finish close cannot tear down the
replacement session. A newer open request supersedes the older one, while an
explicit Close or application shutdown discards the queue and releases its
distinct lease instead of reopening work during teardown.

Height relief follows the same owner boundary. Rust uses the finite displacement
strength attached to the exact authoritative height input first, then the
owner's exact wrapper parameter, the native package amount, and finally the
renderer default. Layer-only and unowned diagnostic height inputs cannot leak
strength to another Part.

#### Renderer sampling

The D3D12 renderer selects 4x MSAA only when the adapter supports both colour resolve
and multisampled depth, otherwise it stays at 1x. Material samplers use linear
minification, magnification, and mip filtering, with 16x anisotropy when the adapter
supports it and a 1x fallback otherwise. **Solid + Wire** renders its wire pass with the
same scene depth test and no depth writes or forward bias, so rear edges remain behind
the surface. Only explicit **X-Ray** uses the no-depth wire pipeline.

Wire and vertex appearance pickers update the GPU overlay colours, and the Normals
overlay uses short, evenly sampled direction guides capped for dense meshes instead of
painting a spike from every vertex. The UV page can switch directly to UV Checker so
coordinate edits have an immediate visible comparison. The mesh buffers stay resident:
same-topology position/normal changes update them in place, while a topology-generation
or ownership change replaces the affected GPU geometry.

The window waits when idle and requests another frame only for pointer/UI input, loader
or CDMW state, resize, or an immediate egui repaint. Edit-change colours compare a
same-topology gesture with its starting positions and distinguish outward, inward, and
tangential movement; these colours are preview vertex data only and do not alter the
authoritative mesh, materials, textures, or output. These behaviors have source/unit and
offscreen renderer coverage, not visible Windows or licensed-game appearance proof.

### Finish, cancellation and terminal outcomes

**Finish Edit Mesh** drains the shadow and prepares one replacement. Exact Game Asset
uses the existing exact validator and in-memory writer without fallback. Free Edit
rechecks the selected destination at Finish and again immediately before commit, then
proves the complete mesh through OBJ export and reparse. The authoritative mesh
revision, Geometry Layers revision, and Morph & Refit revision/state must all still
match the opening snapshot. Geometry, layers, object transform, output state, morph
profiles, and native Morph & Refit runtime then commit as one reversible `Rust Edit
Session`;

Undo and Redo restore that full state. Any rejection keeps Rust open and leaves
authority unchanged. Cancel, close, crash, protocol failure, or forced termination
discards the shadow and only its owned files. An accepted Finish retains validation
for that exact revision; subsequent edits require validation again before **Install
as Overlay**, **Build Mod** or **Add to Archive Browser** can publish it. Build Mod supports DMM/JMM/CDUMM/Crimson
Sharp loose packages and a DMM archive group through owned sibling staging; overlay
installation keeps the existing confirmation, backup, rollback, receipt, and restore
lifecycle.

Neither route rewrites source PAMT/PAZ archives in place.

Finish and Cancel record their terminal outcome before replying to the helper;
neither reads the disposed shadow session. A successful helper exit preserves
the accepted Finish or intentional Cancel status, including during worker teardown.
Late command replies cannot overwrite a terminal outcome, and reopening Hair
Tools during cleanup does not read a disposed session.
Mesh Editor's Current Tool Log retains its latest 2,000 status lines, including
progress, validation failures, and terminal outcomes. Copy and Clear act on this
tool's log without clearing another tool's output.

### State, controller and action ownership

`tab_ui_state.py` is the effect bridge into the domain reducer. Existing mixins still
send protocol messages, run workers, load packages and record diagnostics, but action
visibility, blocker reasons, report/output authority and the resident session payload
are projected from `MeshEditorUiState`. Serious synchronization failures record its
bounded snapshot with session, process generation, request, base/target/service/renderer
revisions and the stable recovery error code. The resident strip keeps **Close** at its
far edge.

It remains available while session work is active, confirms before discarding edits, and
returns Mesh Editor to its no-session state through the same nonblocking worker and
renderer teardown path. The Rust host remains visible before a session and after close
as a loading, availability, or result page. Opening an archive or file session replaces
that page with the process-owned child.

An accepted Finish disposes the shadow and groups the next steps into **Keep
editing**, **Save and reuse**, and **Check or install**. Each action has a clickable
**?** explaining its result. **Resume current edit** retains the current setup;
**Start next edit pass** uses rebuilt game-format bytes as a new baseline.
**Build Mod...**, **Add to Archive Browser**, **Check mesh**, **Install to game...**
and **Close this mesh** act on the accepted revision. Overlay restoration is not
shown on this page. `native_preview_payloads.py` and the old helper-status
path remain compatibility code for retained preview consumers; the direct editor does
not invoke them.

`controller.py` owns the feature-side edit-session bridge over `MeshService` and
converts edit results into native preview update payloads.

### Command palette and tool actions

`actions.py` and `action_bar.py` own the Mesh Editor command palette and Qt tool
surface. They map visible tools to service command keys without applying edits. Topology
tools include local Subdivide and Refine Smooth. Their shared action descriptor owns the
200,000-faces-per-submesh safety cap, which is merged into resident requests before
caller overrides; a request the cap rejects reports the native reason and leaves the
resident session exactly as it was. Faces subdivide exactly; selected wires and vertices
expand to incident faces.

An unselected neighbour across the region border is stitched against the new midpoints
on its edges rather than left spanning them as a T-junction. The remapped selection
keeps the original vertices, the split wires, and the midpoints of fully selected wires
only, so repeating the command refines the same region instead of adopting the bled
boundary ring and quadrupling it per click. Face-selection values are compact face
offsets everywhere in the resident session; per-face source indices are ancestor
bookkeeping, never a selection space.

Geometry and selection are one native history pair, so one Undo or Redo restores both.
The Builder adopts the native remapped selection after remapping topology rather than
clearing its mirror independently. Delete is the exception: it intentionally clears
element selection after commit and never republishes the pre-delete native target
against compacted face offsets. For imported-model authoring, the Selection panel offers
**Create Part from Selection**.

It sends the existing `separate` command after current or provisional Brush selection
authority has landed, requires Faces from exactly one source part, moves those faces
into a uniquely named appended submesh, and retains the source part's vertex channels
and material route. The new Parts row is selected and revealed with its moved-face
count. Create New Item opens an imported source here with Faces as the target while
keeping Orbit as the neutral initial tool, then accepts a stable resident revision back
into its placement/build workflow.

Normal tools include service-routed recalc, tangent generation, flip, sharpen/soften,
weighted normals, and source-normal copy commands; cleanup tools include remove doubles,
delete loose vertices, compact orphans, winding repair, and hole fill. Widgets only emit
descriptors. **Remove Doubles** supports **Exact Game Asset** for PAC LOD0. Native
cleanup retains original-relative vertex and face lineage through Undo/Redo and
reopening. The exact writer retains each survivor's original skin and cloth record;
altered weights, missing lineage, invalid bounds and unsupported layouts remain blocked.
Other cleanup actions still require **Free Edit**.

Distinct lower LODs remain unchanged. Independently stored, byte-identical LOD0
copies may receive the same verified cleanup only when their descriptor counts and
vertex/index splits also match. Their counts and offsets are updated and their
complete payloads checked against the rebuilt LOD0. A distinct lower LOD that would
outrank the new LOD0 still blocks output; no approximate correspondence is inferred.

**Free Edit** also accepts verified compacted source rows, checked against the
original source map, record offset, descriptor and stride. Its OBJ output retains
geometry without a rig.

`triangulate_display` and `quadrangulate_display` are deliberately not
among them: the service refuses both unless the caller passes
`allow_legacy_display_cleanup=True`, so they are legacy/archive-path helpers rather than
tools the rail may offer. `MeshEditorTab.update_editor_session_state()`,
`MeshEditorTab.update_editor_action_state()`, and
`MeshEditorTab.set_active_tool_state()` keep tool enablement and active mode state in
the feature tab, including embedded static-builder refreshes.
`MeshEditorController.apply_editor_action()` is the execution bridge for those
descriptors;

UI shells should emit actions, not implement edit commands.
`MeshEditorController.run_editor_action()` wraps that bridge with native preview update
packaging for action-bar consumers. Correlated resident updates treat every positive
helper request ID as an ordering boundary. A terminal selection may wait behind an
acknowledged geometry frame at the same revision, but it cannot be merged into that
frame or published under its ID. Cancellation or publication failure returns an explicit
rollback result so provisional selection cannot remain stranded.
`MeshEditorController.export_validation_report()` exposes the service-backed pre-export
validator for the active session.

The visible **Run validation** action executes it in a background worker. Its report is
stamped to the checked geometry revision; a later edit retires its output authority
until validation is run again while keeping the previous report visible as
last-known-good context. `MeshEditorController.workspace_summary()` exposes the
service-backed part, material route, UV channel, and skinning summary for panel
rendering. Whole-part selection belongs to the explicit Parts/PARTS lists: clicking a
row toggles it without clearing other selected rows, and the part context menu routes
clone/delete/normal actions through `MeshEditorController` and `MeshService`.

Material and texture names remain read-only diagnostics; no assignment or copy action is
exposed. `MeshEditorController.compare_summary()` exposes source-vs-edited topology,
bounds, scale, orientation, material, texture, and UV mismatch data for the workspace
Compare panel. Parts, UV Map, Rig, Compare, validation, and rebuild presentation all use
`MeshPanelSnapshot`: `ready`, `pending`, `error`, or `unavailable`, with the requested
session/revision kept separate from the revision that produced any retained value. Only
a matching session, geometry revision, request, and generation may publish a worker
result.

Selection-only resident revisions do not invalidate geometry reports, while an
acknowledged geometry revision does; expected native-snapshot gaps remain unavailable
instead of hydrating stale Python geometry, and unexpected exceptions remain visible and
enter the runtime diagnostic trail.

## Preview compatibility and output

Historical `d3d11_*`, `dotnet_*`, and `native_preview_*` Python names remain
where imports, settings, tests, or object names consume them. They construct the
shared Rust preview host; they do not launch the retired renderer. The old
resident C++ interaction packets are described in
[Mesh Core](../../../native/cdmw_mesh_core/README.md), separately from the
production Rust editor's shadow-session contract above.

### Preview profiles

Archive and specialist previews use the viewport-only `--cdmw-preview-session`
route. Their canonical Preview Core material packages, source bindings, role
cameras, and capture requests are owned by the shared preview services. They
are distinct from the editor's `--cdmw-session` route. Read-only source textures
stay with the model while geometry and UVs change.

### Validation and export

For an existing item, use **Modify Original**. When fitting and removing Parts,
complete **Morph & Refit** first, inspect and **Bake** the fit, then **Finish Edit
Mesh > Start next edit pass**. In the next pass, exclude unwanted Parts
with the **Include** controls, then finish and **Build Mod**. **Add to Archive Browser**
offers the same handoff through **Archive Browser > Controls > Edited results**,
where another source asset can be selected. Combined archive Refit retains
each source asset separately; the handoff carries their edited output and captured
dependencies through later passes. A new independent item is not required for an
existing-path replacement. Removing geometry first can also start a later fitting
pass when that edited asset passes the game-format writer. Unsupported topology
cannot be made compatible merely by finishing or reopening it.

**Start next edit pass** rebuilds the accepted changes with the same
validated game-format handoff, then directly opens the current source asset as a
fresh editing session. Materials, textures, rig and captured physics dependencies
remain available; other edited Refit assets and generated companions travel into
later outputs. For the same source identity, continuation carries the verified
material model and its texture-package lease through session teardown, preserving
resolved texture layers, owner slots and colour parameters after geometry removal.
The new baseline still comes from the rebuilt mesh, without copying preview geometry.
It waits for the output worker to retire and drops a queued
continuation if the session closes or changes. Failed preparation leaves the
accepted working session available. It does not switch to Archive Browser.

**Resume current edit** reopens the accepted mesh in the existing working session,
keeping its output policy, Parts and fitting state. The original source remains
the reference; per-action Undo/Redo starts again in the reopened editor.
Starting the next edit pass from the rebuilt mesh starts with the
modified bytes as its new baseline and clears the previous pass's editing state.
Reopened exact sessions validate retained topology against the original source
mesh, rather than treating the edited shadow's opening geometry as the original.
This prevents a false `TOPOLOGY_CONTRACT_UNSUPPORTED` after supported deletion;
the source skin, topology and writer admission checks still apply.

The Refit archive picker excludes the current target from its source search.
That mesh is already loaded; **Load Armor** adds a different mesh. If the current
mesh is the armor, load or assign its body driver, then select the existing armor
Parts and bind them. A disabled Load Armor button without a different prepared
selection does not mean that modified PACs are categorically unsupported.

**Add to Archive Browser** prepares game-format output off the UI thread and
publishes complete results for the current app session without a folder picker,
rescan or change to the archive root. It preserves source identity, prepared
materials, textures, rig and physics resources, and starts the next pass from the
rebuilt bytes with clean editing state. It does not repair physics affected by
geometry changes. Missing source contexts or unsupported game-format rebuilding
remain blocked. See [Archive Browser's edited-result contract](../archive_browser/README.md#edited-mesh-editor-results).

Both result routes retain bounded, geometry-free material metadata for each
source asset. Saved results own independent texture-package and image-cache
leases, so closing the original editor or a reopened pass cannot remove their
resolved layers or colour parameters. Each reopened editor acquires its own
package lease; other fitted assets retain their own material owners. Results
remain session-local and do not survive restarting CDMW.
When rebuilding changes a PAC XML or PAMI material sidecar, the next pass resolves
the rebuilt companions instead of reusing the earlier material snapshot. This
prevents retained source bindings from hiding authored material changes.

**Finish Edit Mesh** retains its successful validation for the accepted revision, so
**Build Mod** opens immediately without requiring a second validation. Any later edit
invalidates that report; **Run validation** checks the new revision. **Export Mesh
File** publishes a separate rebuilt asset and report. **Build Mod** opens one form for
the mod manager, mod name, output folder, version, author and description. It publishes
**DMM**, **JMM**, **CDUMM** or **Crimson Sharp** loose mesh packages using their
respective layouts and metadata, or a **DMM Archive Group** in `0036/`.

DMM owns the mount list, so that package omits `meta/0.papgt`. Packages contain the
replacement payloads and manager descriptors/markers only. The generated README and CDMW
baseline, compatibility and session records stay out of the mod; authoring records are
saved in CDMW's local `mod_export_history` store and remain discoverable for the exact
exported bytes. DMM uses only `manifest.json` for its metadata, without a duplicate
`modinfo.json`. CDUMM uses `modinfo.json` with its default `files/` directory, without a
duplicate manifest or unused encryption marker.

Its detector accepts this layout and its importer reads mod details from `modinfo.json`:
[CDUMM
detector](https://github.com/faisalkindi/CrimsonDesert-UltimateModsManager/blob/master/src/cdumm/engine/crimson_browser_handler.py),
[CDUMM
importer](https://github.com/faisalkindi/CrimsonDesert-UltimateModsManager/blob/master/src/cdumm/engine/import_handler.py).
[DMM's changelog](https://www.nexusmods.com/crimsondesert/mods/633?tab=logs) documents
metadata lookup from `manifest.json` when `modinfo.json` is absent. **Create ZIP beside
the mod folder** adds an archive containing exactly the same files, with no enclosing
staging folder. **Open folder after creation** opens the completed mod folder only after
successful publication. Both options are independent and off by default. Existing
folders and ZIPs are never overwritten; folder names containing dots keep their full
name in the sibling ZIP.

The chosen mod name remains independent of the generated folder name. Cancelling the
form writes nothing, and changing the mesh or target while it is open requires
validation again. Output stages in an owned sibling directory and publishes once; stale
revisions, cancellation, and failure cannot leave a partial final folder or ZIP.

### Overlay installation

**Install to game...** uses the overlay workflow to prepare the exact mount change, carry-forward files,
ownership, and recovery targets for review before confirmation. The service
rechecks the game state, validates staged content, backs up through
`ArchiveMutationService`, and publishes the mount list last. The saved receipt
supports restoring the prior state and removing only paths created by that
installation through the overlay recovery service. Restoration is not offered
on the Finish page. Foreign groups are never adopted.

The worker reports a committed install even if cancellation arrives after publication.
An installation or recovery failure remains an error when cancellation is pending;
failed recovery includes the backup location. Cancellation alone does not claim that
a rollback was performed or succeeded.

### Localization and proof limits

The surrounding PySide controls and Rust's embedded editor receive the app's active
localization catalog, including custom translations. Native messages omit entries
identical to their English source text, which the renderer already uses as a fallback;
translated entries remain intact within the control-message limit. See the root
[documentation and languages](../../../README.md#documentation-and-languages)
reference for the current boundary.
