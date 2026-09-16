# Mesh Editor

Owns the direct, mesh-only Mesh Editor tab shell, typed archive-session requests,
resident authoring workspace, and output orchestration. Archive internals and
destructive writes stay outside this UI package. Static-replacement builder
hosting remains compatibility-only in this tab. Archive Browser exposes
**Import > Replace Mesh from File...** in a separate replacement window; opening
it does not replace the active Mesh Editor session.

The current product boundary is geometry authoring: selection, topology,
transforms, normals/tangents, rigging, Morph & Refit, UV-coordinate editing,
history, original-vs-edited review, validation, and read-only textured display.
Replacement imports and reversible output inclusion extend that foundation in
the existing Parts panel. General material assignment, recolour/glow authoring,
in-game swaps remain separate workflows. Hair Appearance has a scoped DDS handoff.

## Hair creation

Use **Hair Tools (Experimental)** above the viewport. Hairstyles have not been
tested in game and may not work correctly. One setup dialog contains Character
(Kliff, Damiane or Oongka) and Create/Edit. **Create starts with an empty scalp**;
the first verified compatible base supplies skinning and materials only. Create
does not load a thumbnail gallery. Edit shows registered hairstyles with
thumbnails and preselects the active compatible hairstyle. **Start** stays disabled until the
catalogue and donor checks are ready. Browsing choices does not replace the scene.
Finder Create/Edit Hair uses this same dialog.

Mounted appearance and customization documents supply the head, facial details,
scalp, neck and shoulders. Authored head scales use the head joint as their pivot;
the common character scale cancels in the donor's authoring coordinates. Oongka
uses his `5_pom` references even though his registered hair belongs to `1_phm`.
The clean, untextured mannequin uses the head's fitted eye-cover surfaces as
smooth eyes, excluding separate shader-dependent iris/lens meshes, lashes and
brows. Heads without fitted covers retain their separate eye reference.
Reference loading parses fitting geometry and
authored transforms directly, without opening editable sessions or decoding DDS.
Eyes follow the head but remain outside the scalp planting and collision surface.
Compatible single-mesh `_player.pac` registrations at LOD0 are supported. Entries
with multiple PAC references, additional LODs, unsupported layouts or incomplete
dependencies explain their restriction before Start. Ordinary hair PACs retain
the general mesh tools.

Start prepares a complete replacement in isolation before the existing unsaved
work confirmation and scene switch. Cancellation and failed preparation preserve
the current scene; **Retry loading choices** restarts preparation. An active
generated hairstyle can change presets as one undoable edit without reopening its
archive target. Repeated Create requests use the same route.

Select a visible lock and use **Move** to drag it. Ctrl-click toggles selection;
drag empty space for a marquee. **Move reach** sets how much of the lock follows
the grabbed point, with a smooth falloff and fixed roots. **Draw** offers
**Freehand**, **Straight**, **Arc** and **Circle**. Drag the endpoints of a line or
arc, or the diameter of a circle. **Bend** adjusts an arc's direction and depth;
**Stroke smoothing** reduces freehand jitter without trailing behind the pointer.

**Follow scalp** starts enabled for Freehand; the shape tools start in the view
plane. Toggle it to choose surface following, or hold **Ctrl** temporarily to draw
away from the scalp. Contacts remain active in either mode, including card width.
Cards start narrow and follow the scalp before widening into the lock. Long
strokes retain evenly spaced guides; cached scalp data keeps live preview work
local to the active locks. Older strokes with a baked-in straight root retain
their saved shape and need redrawing.

**Erase** and Delete remove the selected geometry; **Cut** removes
the pointed distal section. **Lengthen** acquires a clicked lock like Move,
respects an existing selection and extends tips without moving roots. Empty,
rigid and unresolved selections explain what is required.
Comb, Smooth, Curl and Clump use the highlighted brush region, restricted to the
selection when one exists. Appearance controls width and generated follower
cards. Symmetry uses explicit pairs created while drawing. Escape cancels a
stroke; Ctrl-Z/Ctrl-Y undo or redo one completed action. Alt-drag orbits,
Shift-drag pans, and the wheel zooms.

Existing hair retains its original geometry, UVs, skinning and material sections.
Sections without editor guides are not broken: unchanged sections can be exported
without preparation. To groom them or preview their motion, expand preparation,
select a group or visible locks, choose **Set root / group selected sections**,
then click the scalp. This explicitly combines selected sections sharing a
material. Changed sections without valid guides remain blocked. Mark rigid scalp
pieces as rigid. Draw and follower density are available for generated hair;
unsupported controls explain
that limitation. Existing locks support grooming, cutting and deletion once bound.

Setup contains the readable hairstyle name and **Change references**. Alternatives
show compatible heads or base bodies, filtered in the resident catalogue before
pagination. There is no fallback to an unrestricted archive list. Changed heads
invalidate bindings until explicit rebinding. Setup, Appearance and Advanced are
collapsed; unrelated topology, rigging and UV controls stay hidden in Hair mode.
Switching choices cancels the previous preparation; its late results and errors
cannot replace the current selection. Failed reference choices remain retryable.
Cancelled reference loads release their unpublished assets.

**Play** becomes available when roots, geometry ownership and required textures
are ready. **Head and shoulders** is the default test; Turn, Nod, Body sway and
Wind are also available. Existing sections spanning too far from their guide
cannot simulate safely: assign roots to smaller selections, or mark scalp sections
rigid. Static editing remains available. The Rust XPBD solver drives the rendered cards and uses
matching reference/root/collision transforms. Cached scalp-surface contacts check
guide segments and card width while retaining neck and shoulder collision shapes.
A rest-shape force preserves the groom while allowing softer tip movement; adjust
**Shape softness** to change it. This is an editor preview, not a simulation of
the donor's in-game rig or physics. Optional procedural fills remain in the editor.
A stroke pauses playback and resumes
from the edited rest shape at the current pose. Reset is deterministic. Simulation
frames never modify drafts, output or history. **Use settled shape** explicitly
accepts the neutral-coordinate result as one undoable edit after motion has played.

**Open in Texture Editor** and **Apply edited DDS** retain the template's verified
material slots, dimensions, compression and mip counts. Missing required DDS files
block game-ready validation. Guides are an optional overlay. **Convert to ordinary
mesh** is an explicit undoable action under Advanced.

Hair state v2 records stable locks, geometry ownership and retained source vertices.
Drafts use `mesh_layer_project_v5`/`mesh_layer_generation_v5`, with reads of v1-4.
Legacy generated bindings recover lock ownership without regenerating geometry;
legacy existing hair needs explicit preparation for grooming or motion. Hair,
geometry, materials and output inclusion are saved atomically. The helper
advertises `hair_authoring_v2`.
Small grooming updates publish only changed positions and authored normals;
unchanged UVs, materials and skin records remain resident. Each completed action
keeps its own Undo step. Pending Undo/Redo and Finish wait for ordered publication.
Parts, action history, guides/roots and collision overlays remain available in
collapsed panels; visibility never removes hair from the exported result.
Incremental candidates reuse immutable references; acknowledgements preserve the
camera, selection and newer local edits. Finish drains pending actions first.
Acknowledgements read the validated revision without decoding the complete hair
document again.

Packages retain the additional-choice contract, automatically allocate distinct
internal identities and use the readable name in their manifest. Retained existing
PAC vertices preserve their original skin records, including eight influences,
when reshaped, cut or deleted. Generated geometry always transfers skinning from
an immutable original PAC donor matched by stable part identity, including after
consecutive Draw strokes, Undo/Redo and reopening. The 40-byte PAC layout guard
remains in force. Drafts can be reopened and saved repeatedly without losing part
identities. A multi-LOD donor is blocked until its writer is verified. Installed archives stay
read-only. In-game barber selection, save/load, headgear and motion remain unverified.

For implementation and evidence boundaries see [the hair document](../../../docs/hair-authoring-feasibility.md).

## Replacement workflow

Open an archive mesh, choose **Import Replacement…**, and select **Entire Mesh**
or **Selected Parts**. OBJ, DAE, glTF and GLB use the retained import pipeline.
Review the source-to-target mapping before **Apply Replacement**. Selected-part
replacement preserves every untouched part and its material binding, including
the original PAC vertex and index records at every LOD. Multiple
source parts can map to a target with original materials; imported-material mode
requires one source material part per target.

OBJ face regions with different materials appear as separate source parts even
when they belong to the same object. Material assignments continue across OBJ
object/group boundaries until the file specifies another material.

New imports preserve decoded coordinates: no automatic scaling, alignment or
centering. Scale starts at 1, rotation and translation at 0. Use the existing
transform tools for placement. **Fit to Original** explicitly fits the imported
parts; **Reset Placement** restores their imported positions and normals. Both
restore the imported normal orientation and invalidate outdated tangents, and
both are undoable.
New Item fitting defaults are unchanged.

Source positions, UVs, normals and tangents must contain finite values within
the supported float range. Invalid values stop import before automatic UV
generation or preview conversion, preserving the current edit for a valid retry.
OBJ faces must also reference existing vertices, UVs and normals. Invalid indices
stop import instead of substituting geometry or regenerating authored channels.

**Keep Original Materials** is the default. Missing or stale imported MTL and
texture references do not block this geometry-only mode. Source geometry and
external geometry buffers in both glTF and GLB must still exist and remain
unchanged while reviewing the mapping. **Imported Materials & Textures**
prepares the required DDS and material sidecars before publishing the import.
Missing textures, ambiguous material wrappers, shared selected/untouched material
ownership, unsupported skinning, or invalid coordinate/layout conversion block
Apply with a specific reason. This mode also rejects material dependencies that
changed after import preparation and never silently uses original materials.

Hover over the bottom status message to read the full text, or choose **Details**
for a scrollable, selectable view. **Copy** copies the complete message, including
any part that does not fit in the status bar.

The **Mod** checkbox means **Include in mod** and is independent of viewport
visibility. Excluding a part retains all its editable geometry; re-enabling is
lossless, and every part may be excluded. Only export creates the existing tiny
triangle placeholders, retaining required target sections and their existing
index convention. Output Preview ignores temporary viewport/layer hiding.
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

This workflow handles one eligible PAC/PAM/PAMLOD at LOD0. Active Morph & Refit
profiles/bindings must be cleared before replacement.
Unsupported target layouts remain blocked. Existing sessions without replacement
state retain Exact Game Asset/Free Edit behavior. Replacement uses its own
`replacement_game_asset` policy, not weakened Exact validation.

Neutral-appearance meshes show an **Experimental** warning above the import
controls. Imports and **Mod** inclusion are available immediately for eligible
meshes, with no extra enable button. Positioning, scale or animation may be wrong
in game. Imports still preserve their decoded placement. Skin weights transfer
from the displayed original part; export uses those weights to invert the
neutral display transform. Output Preview reparses the actual written mesh and
displays it in the same neutral frame. Singular transforms, unsupported skin
layouts, invalid geometry and missing dependencies still block the operation.
The left part checkbox controls viewport visibility; the right **Mod** checkbox
controls output inclusion. Opening the editor alone does not change geometry
or output; cancelling the editor discards its edits.

Imports, inclusion and placement changes participate in normal Undo/Redo and
Finish/cancel. Replacement-bearing drafts use version 2 and keep captured
dependencies and output intent together; older apps reject them. Existing
version-1 drafts still load unchanged. Source files are unnecessary after Apply.
New replacement payloads also retain import normals. Older replacement drafts
still reopen and export, but require reimporting before Reset Placement or Fit
to Original because their original normal orientation was not saved. Older
applications reject the new replacement payload version. No bulk migration is
performed.
Experimental replacement drafts use project and payload version 3, retaining
the exact neutral transform and coordinate frame. Older apps reject this format
before attempting generation recovery. Ordinary replacement drafts remain v2.

`mesh_replacement_import.py`, `mesh_replacement_materials.py`, and
`mesh_replacement_output.py` own detached preparation and complete output.
`mesh_rust_replacement.py` and `mesh_rust_replacement_materials.py` publish through
the existing shadow-session/control/material contracts. Task cancellation,
revision checks and import tokens prevent stale candidates from taking over.

Synthetic verification covers format round-trips and the packaged editor. It
does not establish real-game rendering or animation compatibility.

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

Parts use compact, single-line names with the full name and material on hover.
The checkboxes and Visibility menu hide/show parts in the viewport; hidden parts
remain in the output, and a hidden Geometry Layer still controls its own parts.
All and Invert operate on visible parts, and selection changes update the
viewport immediately. Duplicate and Delete target only the explicitly selected
whole parts. They wait for pending selection updates and require Free Edit;
**Enable part edits…** opens the output controls directly. Delete keeps at least
one part, and successful structural edits refresh the list through the same
shadow history used by Undo/Redo.

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

`MeshEditorTab.open_archive_session()` is the normal entry point. A correlated,
cancellable `MeshArchiveSessionLoadWorker` reads and round-trip-validates the
exact archive bytes, creates the authoritative `MeshService` edit session, and
publishes only the current completion. Matching source-hash drafts open against
the current source and produce the non-modal Resume/Start Fresh banner; starting
fresh never deletes a draft. `MeshEditorTab.open_session()` remains a compatibility
wrapper over this direct contract.

Archive PAC sessions resolve the same head-specific PABC neutral appearance as
Archive Browser. The embedded editor labels these meshes **neutral appearance**
and uses the reconstructed face for selection, move/sculpt operations, comparison,
and Undo/Redo. The authoritative mesh keeps the original PAC coordinates. Finish
inverts each vertex's blended skin transform before exact-writer validation and
committing edits, so the game does not apply the face correction twice. Opening
and finishing without a geometry edit preserves the source bytes. Unreadable or
non-invertible resolved appearance data reports a load/preparation error rather
than opening a falsely corrected face; meshes with no linked variation retain
their source shape. Finish or cancel this edit before importing an unrelated
source mesh. Archive Refit has its own per-asset neutral mappings, so it can load
body and armor together without applying the body's appearance transform to the
armor.
Free Edit OBJ output retains the displayed neutral shape; game-asset output
retains the reversible source-coordinate mapping.

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

`MeshEditorTab.open_mesh_session()` opens a scripted in-tab edit session for a
`ParsedMesh` without starting Archive Browser UI. It creates the same
authoritative service session and embedded Rust shadow workflow as an archive
open; it does not build a Vortice authoring package.
`MeshEditorController.native_update_for_result()` is native-payload-only; Python
mesh-based preview packing is explicit archive-only code behind
`legacy_python_update_for_result(..., allow_archive_legacy_preview_rebuild=True)`.
`MeshEditorTab.open_mesh_file_session()` opens a supported PAC/PAM/PAMLOD file
through `MeshService.load_mesh_file()` before entering the same standalone edit
session path for scripted callers. UI callers should use
`MeshEditorTab.open_mesh_file_session_async()`, which runs file IO, parsing, and
service session creation in `MeshFileSessionLoadWorker`, then attaches the
controller and already-loaded mesh on the UI thread.
`tab_rust_editor.py` owns the only production editor route, with process startup,
protocol handling, diagnostics, and shutdown in `tab_rust_process.py`.
`tab_archive_material_context.py` owns correlated archive material requests;
`tab_direct_output.py` owns the direct output actions. The retired
`mesh_editor_backend` preference is ignored and no engine selector is built.
Before loading a mesh, CDMW validates the bundled `cdmw_mesh_lab.exe`; a missing
or incompatible package blocks the open with a visible reason and never falls
back to Vortice.

After the authoritative archive `MeshService` exists, CDMW starts
`cdmw_mesh_lab.exe --cdmw-session <manifest> --embedded-parent-hwnd <decimal>`.
Rust creates one undecorated winit/wgpu child containing the complete editor UI.
`rust_host.py` verifies the reported HWND belongs to the launched process,
attaches it to the native Qt host, and synchronizes resize, show/hide, focus,
DPI/screen changes, and Qt `WinIdChange` re-parenting. Failure terminates the
owned process, leaves no detached window, and offers Retry from a fresh shadow.
The compiled Rust UI emits the merged
`cdmw_rust_mesh_editor_control_contract_v2`; every enabled row has a compiled UI
and dispatch anchor, while every disabled row carries a reason. It has no
Vortice contract input or build-time Vortice probe. Standalone Rust Lab modes
remain independent.
The five direct output buttons use explicit normal, hover, pressed, and disabled
states. Validation-gated outputs and receipt-gated restore stay visibly
unavailable until their prerequisites exist.
The session-state bridge carries one explicit output policy: **Exact Game
Asset**, **Free Edit/Rebuild**, or **Read Only**. Exact PAC/PAM/PAMLOD LOD0
sessions show only writer-safe actions, disable operations whose result cannot
preserve protected records, expose the exact reason in help, and still defer the
final decision to the writer and validator. Higher unproven LODs do not silently
enter the exact policy; Free Edit may author the active higher LOD only to a new
validated OBJ/MTL destination. Imported OBJ/FBX/DAE/glTF sessions likewise
require the user to choose a new output folder before proven non-exact topology
tools appear. MeshInfo and unknown formats remain read-only for selection,
inspection, comparison, and safe export. The Python host and resident forms
reject the same unavailable command before mutation.

Integrated Rust authoring owns a disposable shadow `MeshService` under a single
session directory. The preparation worker creates that isolated mesh once and
the shadow service adopts it directly; it no longer performs two additional
full-mesh clones before the helper can start. Protected channels, Geometry
Layers, object transform, output state, provenance, and the native Morph & Refit
runtime remain isolated from the authoritative session. The initial channel
file references geometry already stored in `document.json` instead of writing a
second positions/normals/UV/index copy. Revisioned local gestures and typed
asynchronous service commands update only that shadow. Candidate payloads are
consumed, superseded state files are pruned after safe replacement, generated
layer and morph-profile trees are independently bounded, and the complete owned
tree has an aggregate limit. Path escape, hash, length, unexpected-entry,
stale-generation, replay, and out-of-order checks fail closed.

The embedded child receives CDMW's active semantic palette, explicit light or
dark variant, UI and data font sizes, scale, and density before reveal and after
every live appearance change. Rust maps those roles to its panels, fields,
buttons, selections, warnings, and disabled states instead of inheriting the OS
theme. The session bar, camera strip, left tools, Parts, Layers, and History are
split into named compact groups so controls remain scannable at constrained
sizes.

Select, Move, Rotate, Scale, Grab, Smooth, Inflate, and Pinch execute locally in
Rust. Selection is acknowledged with a selection-only command; it never sends
geometry channels. Geometry candidates preserve original channel values when
their Rust `f32` representation is unchanged, including fractional PAC values.
Whole-part translation preserves authored normals; rotation and nonuniform
scaling transform them without replacing custom shading with face averages.
Partial-part deformation still updates affected geometry normals.
Selection, bone choice, output policy, and layer presentation changes leave
resident geometry loaded. Geometry updates reuse successfully uploaded textures
when their ownership is unchanged and retain the Bones overlay preference.
Numeric transform steps use the same revisioned transaction lane. Inflate
uses signed strength, where positive values inflate and negative values deflate,
and face Extrude sends an explicit world-X, Y, or Z offset. Cleanup, mirror,
normals/tangents, UV0, bone selection and skin-weight editing are strict typed
`MeshService` commands with explicit selection, allowlisted arguments,
output-policy checks, disposable candidate preflight, and shadow history.
Adjust/Normalize require explicitly selected Vertex elements; Transfer from
Original may restore the immutable source skin channels into an unskinned
working mesh from selected vertices or Parts. Loop Cut count/factor, Refine
Smooth strength/passes, and Weld distance are carried with typed topology
commands. Successful no-op results and host diagnostics are shown instead of
claiming that an edit completed. Morph & Refit hydrates the selected bound
garment's saved enabled/mode/intensity/clearance values before applying a
change; profile creation exposes its rule, axis, amount, feather, falloff, and
mirror inputs instead of creating a hard-coded deformation. Geometry Layer
Copy/Paste names the required selection and Free Edit policy, and layer
visibility removes hidden Parts from both rendering and picking. Cleanup and
other topology-changing tools remain visibly locked by Exact output with a
direct instruction to choose Free Edit. Bevel/chamfer, UV1 and a 2D UV
workspace, true weight paint, posed skeleton deformation, normal-direction or
edge extrusion, sculpt symmetry, and full layered/dye material composition
remain open rather than being presented as functional controls.

Archive PAC sessions resolve a matching PAB automatically from the same archive
index, using the original PAC's bone references as well as descriptor and family
matches, before attaching it to the shadow service. The current Archive Browser
passes its prepared per-asset dependency snapshot into the session instead of
relying on legacy global indexes. Queued opens and draft resumes retain that
snapshot for both skeleton and material lookup until the session closes.
The PAB is a separate skeleton dependency; the PAC's vertex weights alone do not
contain the named bone hierarchy.
The Rust window has no manual PAB picker. Rig & Skin Weights reports the actual
automatic-resolution failure (including missing dependencies, ambiguous matches,
and invalid or empty skeletons) and keeps weight editing disabled until the exact
PAC LOD0, palette, source-map, and record-layout requirements are satisfied.

Rig & Weights is temporarily hidden from the product tool rail. Its code and
direct headless tests remain available; the following describes the retained
implementation rather than a currently accessible tool.

Rig & Weights identifies the loaded mesh, named Parts, and automatically attached
PAB. Its searchable bone chooser shows parent context and a labelled gold marker
on the active bone. Bone inspection preserves the edit selection and camera;
**Frame bone** and **Frame influence** provide explicit navigation. **Weight
colours** displays the active bone's resolved influence on visible surfaces using
a labelled blue-to-gold 0–100% scale, independently of orange edit-selection
highlights and saved materials. **Select influenced vertices** replaces the edit
selection with positive-weight vertices in visible Parts, including their rear
vertices. Hidden Parts remain excluded. Selected weight details are collapsible
below the controls. Missing mappings and oversized or invalid display data show
an unavailable reason rather than a partial or guessed influence. Skeleton lines
use mesh-space bind positions, not the PAB's parent-local offsets. These controls
inspect the bind rig; they do not pose it or paint weights with a brush.

### Morph & Refit workflow

**Morph & Refit** opens as a bordered panel beneath its highlighted tool button,
with its section headings visibly inside that panel. Click an open tool again
to close it and return to Orbit navigation. Viewport, the tool groups, Parts,
Geometry Layers, Action History, and the individual Morph & Refit sections start
collapsed. Each section remembers its open state while navigating between tools
in the current editor session. Closing panels preserves geometry and selection.

**Meshes & selection** offers named Part checkboxes without an inner scrollbar;
long names stay on one line with the full name on hover. **Open Selection tool**
opens the standard selection controls for picking a region and preserves the
current selection. New sliders capture that selection; existing sliders and
presets use their saved regions without requiring another selection. **Shape
sliders** holds preview values, Reset, and Bake. **Create / edit sliders** opens
when editing a slider and keeps its rule/axis/strength and advanced scope options
together. The preview warning means that topology and definition changes are
locked until Reset or Bake; it does not mean the topology is incompatible.

Framing a small selection retains the complete mesh's camera clipping range.
Scrolling a panel cannot carry camera zoom into a later viewport click.

**Meshes & selection** shows a compact card for each loaded asset, with its
current body/armor role, Part count, and full path on hover. **Set as body**
assigns only that asset's Parts as the driver, making an incorrect role easy to
correct. **Add as Body...** and **Add as Armor...** open the loaded game archive catalogue with search, paging,
and source previews. Choosing a body assigns its Parts as the driver; choosing
armor adds and selects its Parts ready for binding. No Free Edit or external
mesh file is required. The panel lists loaded files separately from the assigned
body driver and bound armor/clothing.

Both browsers search the same catalogue: the chosen role determines what the
mesh does. Body is the shape driver; armor is the garment that follows it after
binding. If you load armor before assigning a body, the initial mesh becomes
the body driver, including when an existing Morph profile has no assigned driver.
If you started with clothing instead, Add as Body assigns the
new body while keeping the original clothing available for selection and binding.

The catalogue comes from the archive workspace, including when Mesh Editor is
detached into its own window. Cancelling the picker or failing to open the
catalogue leaves the editor session available for further commands.
The picker puts the searchable archive list on the left and a taller combined
preview on the right. The current target and selected source share one view in
their original archive coordinates, preserving their relative size and position.
Each has its own **Solid** or **Wire** display choice. **Add as Armor...** starts
with a shaded, untextured solid target and wire armor; **Add as Body...**
starts with a solid body source and wire target. Wire edges overlay solid surfaces,
including hidden edges, to make overlap visible.

The combined preview uses the interactive 3D viewport: Alt/Ctrl-drag to orbit,
Shift-drag to pan, and scroll to zoom. **Reset view** restores the shared
framing. Each model keeps its Solid/Wire choice while the camera moves. Display
changes reuse decoded meshes and retain the camera; resizing does not decode or
rebuild the scene. It shows the original archive geometry; live edits and refit
results are inspected in the main editor viewport.

Archive sources keep their own original bytes, Part mappings, palettes, and
archive paths. Each neutral appearance uses its own reversible mapping; Finish
restores each asset's source coordinates before validation and writing. Drafts
retain those mappings in the version 2 refit record and can still load version 1
records. Added meshes retain their resolved textures and layered material data
across loading, Undo/Redo, Bake, Finish, and reopening.
New archive-refit draft generations own checksummed copies of their DDS and decoded
layer images (up to 512 MiB combined), so clearing the preview cache does not remove
their textures. Missing or damaged draft files reject that generation before it
replaces the loaded geometry. Older drafts still open, with a warning when their
cached material files are missing; reopen the source meshes to reload those textures.
Adding an asset reuses the existing owned textures and compiles only the incoming
asset's materials. Generated support maps use bounded array decoding and fast,
lossless PNG compression; material ownership and texture pixels are preserved.
Geometry, rig dependencies, and materials prepare off the UI
thread before one undoable publication. Cancelled, stale, duplicate, invalid,
or oversized sources leave the edit unchanged.
Rejected material preparation also leaves the session material cache unchanged,
so another valid archive import can proceed after a size, write, or cancellation error.
Reset or Bake before loading; Clear Refit first if garments are already bound.
Archive refits preserve the original topology and allow selection across all
visible loaded assets.

**Select body** selects the assigned driver Parts; it does not open another
file. Its highlighted state shows when the body is already selected.
**Select garments** selects non-body Parts even before they are bound. It stays
disabled until the body is assigned, so an unassigned body cannot be included.
When only a body is loaded, **Load armor...** opens the archive browser directly.
Refit setup appears immediately after the meshes, with one compact next action.
The Rust control messages carry slider metadata only; full weighted vertex scopes
stay in the host profiles for editing, saving, and preset export.

Select clothing/armor Parts and bind them. **Create body slider** selects the
driver and opens the slider creator in view when no shape sliders exist. Custom regions
can still be selected with the Selection tool. The panel rejects overlapping
roles and setup changes during an unbaked preview, and shows the binding-distance
warning. Binding replaces the garment set; select every garment that should
participate. Surface and Rigid modes retain per-garment enable, intensity, and
clearance controls, which appear only after binding. **Changes not applied**
marks pending settings; use **Apply to Selected Garments** or **Apply to All Bound
Garments** to update the preview. Surface follows the body surface; Rigid keeps
each garment Part rigid. Intensity controls following strength; clearance adds
space as a percentage of body size. Positive clearance pushes outward even when
the garment was already inside the body when bound. **Fit to body** previews a
fit for every bound garment using Surface, 100% intensity, and the current
clearance (at least 0.1%). It works without creating or changing a body slider;
Reset reverts the preview and Bake keeps it. Surface also checks triangle edges
and interiors against the current body, keeping coincident seams joined. It
checks body contours between those samples and resolves overlapping or tightly
spaced body regions together, including around underarms. Fitting favours the
original shape in clear areas, reducing unnecessary shoulder and sleeve inflation.
Nearby clothing layers over the same body region preserve their separation while
allowing them to slide, including detailed linings beneath coarser outer shells.
Clear belts and trim are not pulled toward layers that move away from them.
The garment's original facing direction helps offset sleeves wrap around the
correct side of an arm during the initial fitting passes. This guidance stops
as the cloth settles and is restricted near open body boundaries and by each
piece's openings, protecting collars and keeping thin attachments from stretching
around a limb. Local stretch and sharp new creases are reduced while folds and
sleeve openings can bend around the body.
Complex layered outfits have a bounded 90-second command budget, including
subsequent body-slider changes.
Inspect folded or tightly fitted areas before baking; unusual outfits may still
need local adjustments, particularly thin wrist trim and folded cuffs. Static
fit and PAC round-trip checks do not establish animation or in-game appearance.
To redo a poor baked fit, undo the bake or reload the
original meshes before fitting again. Shape sliders move the driver and bound
garments together. Use the normal transform tools if the meshes need alignment.

Archive Refit keeps the original game-file topology, so its Geometry Layers
organise loaded assets but cannot add or remove geometry. Free Edit is disabled
before any folder picker opens. For a separate mesh, Free Edit permits structural
edits and asks for a folder containing a new OBJ package. Finish the archive refit
and open a separate mesh to use that route.

**Finish Edit Mesh** keeps edits to both body and armor. **Build Mod** rebuilds
each asset through its own exact game-format writer and packages every original
archive path together. Hiding an asset changes the view without omitting its
output. Draft generations retain each source fingerprint and asset mapping;
Undo/Redo restores those mappings with the geometry. A failure rebuilding any
asset prevents the package from being published. Shipped archives remain
unchanged; installation still uses the existing confirmation and recovery flow.

This is geometry refitting: it does not align mismatched poses automatically or
convert skeletons/weights. Visual fit, clipping during animation, and game
compatibility require separate inspection.

**Save Preset** saves both the active profile and its current percentages into
the settings-owned `mesh_slider_profiles/definitions` and `presets` folders as
one undoable transaction. Finish Edit Mesh commits this library; cancelling the
edit discards its library changes. **Export Preset...** writes a portable JSON
file immediately, defaulting to the `mesh_presets` folder beside application
settings. The file includes the profile, saved vertex regions, procedural rules,
topology fingerprint, and percentages. **Load Preset...** validates the file,
loads its profile and values, previews it, and adds it to the session library
with Undo/Redo. Conflicting IDs get a new imported identity rather than
overwriting different saved definitions. The same driver topology and Part order
are required. Refit bindings remain session-specific; set them for the loaded
body and garments. Legacy profile and preset storage stays compatible.

### Material presentation

The integrated Rust viewport reuses Archive Browser's complete resolved
PAC/PAC_XML material model together with the native material package for the
same mesh identity. The asynchronous resolver publishes the full model, its
exact owning package, and the acquired lease as one correlated result; native
batch reconstruction is only a degraded fallback because those flattened rows
do not retain the complete dye and layer parameter graph. Stale or cancelled
results release their lease rather than leaving a geometry-only package paired
with new material rows. Verification uses the complete archive identity
(normalized path, source PAMT, PAZ index, and entry offset), so two entries with
the same virtual path cannot exchange materials. CDMW carries that verified context into the isolated
shadow package and copies only bounded, hash-checked DDS resources beneath the
session root, retaining their role, LOD, and material range. Owner-conserved
full-graph channels supersede simplified package composites, while a package
composite fills only a channel the complete graph cannot produce. A missing,
incomplete, or unusable preview package leaves geometry editing available on
the neutral opaque surface and reports the exact texture fallback reason; it is
never presented as successful textured display.

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

The D3D12 renderer selects 4x MSAA only when the adapter supports both colour
resolve and multisampled depth, otherwise it stays at 1x. Material samplers use
linear minification, magnification, and mip filtering, with 16x anisotropy when
the adapter supports it and a 1x fallback otherwise. **Solid + Wire** renders
its wire pass with the same scene depth test and no depth writes or forward
bias, so rear edges remain behind the surface. Only explicit **X-Ray** uses the
no-depth wire pipeline. Wire and vertex
appearance pickers update the GPU overlay colours, and the Normals overlay uses
short, evenly sampled direction guides capped for dense meshes instead of
painting a spike from every vertex. The UV page can switch directly to UV
Checker so coordinate edits have an immediate visible comparison. The mesh
buffers stay resident: same-topology position/normal changes update them in
place, while a topology-generation or ownership change replaces the affected
GPU geometry.
The window waits when idle and requests another frame only for pointer/UI input,
loader or CDMW state, resize, or an immediate egui repaint. Edit-change colours
compare a same-topology gesture with its starting positions and distinguish
outward, inward, and tangential movement; these colours are preview vertex data
only and do not alter the authoritative mesh, materials, textures, or output.
These behaviors have source/unit and offscreen renderer coverage, not visible
Windows or licensed-game appearance proof.

**Finish Edit Mesh** drains the shadow and prepares one replacement. Exact Game
Asset uses the existing exact validator and in-memory writer without fallback.
Free Edit rechecks the selected destination at Finish and again immediately
before commit, then proves the complete mesh through OBJ export and reparse.
The authoritative mesh revision, Geometry Layers revision, and Morph & Refit
revision/state must all still match the opening snapshot. Geometry, layers,
object transform, output state, morph profiles, and native Morph & Refit runtime
then commit as one reversible
`Rust Edit Session`; Undo and Redo restore that full state. Any rejection keeps
Rust open and leaves authority unchanged. Cancel, close, crash, protocol
failure, or forced termination discards the shadow and only its owned files.
An accepted Finish is only the handoff into CDMW: the user must run validation
for that exact revision before **Install as Overlay** or **Build Mod** can
publish it. Build Mod supports DMM/JMM/CDUMM/Crimson Sharp loose packages and a
DMM archive group through owned sibling staging; overlay installation keeps the
existing confirmation, backup, rollback, receipt, and restore lifecycle. Neither
route rewrites source PAMT/PAZ archives in place.
`tab_ui_state.py` is the effect bridge into the domain reducer. Existing mixins
still send protocol messages, run workers, load packages and record diagnostics,
but action visibility, blocker reasons, report/output authority and the resident
session payload are projected from `MeshEditorUiState`. Serious synchronization
failures record its bounded snapshot with session, process generation, request,
base/target/service/renderer revisions and the stable recovery error code.
The resident strip keeps **Close** at its far edge. It remains available while
session work is active, confirms before discarding edits, and returns Mesh Editor
to its no-session state through the same nonblocking worker and renderer teardown
path. The Rust host remains visible before a session and after close as a
loading, availability, or result page. Opening an archive or file session
replaces that page with the process-owned child. An accepted Finish disposes the
shadow and shows Run Validation, Build Mod, Install as Overlay, Restore Last
Overlay Install, Reopen Edit, and Close Session against the accepted
authoritative revision. `native_preview_payloads.py` and the old helper-status
path remain compatibility code for retained preview consumers; the direct
editor does not invoke them.

`controller.py` owns the feature-side edit-session bridge over `MeshService` and
converts edit results into native preview update payloads.

`actions.py` and `action_bar.py` own the Mesh Editor command palette and Qt tool
surface. They map visible tools to service command keys without applying edits.
Topology tools include local Subdivide and Refine Smooth. Their shared action
descriptor owns the 200,000-faces-per-submesh safety cap, which is merged into
resident requests before caller overrides; a request the cap rejects reports
the native reason and leaves the resident session exactly as it was. Faces
subdivide exactly; selected wires and vertices expand to incident faces. An
unselected neighbour across the region border is stitched against the new
midpoints on its edges rather than left spanning them as a T-junction. The
remapped selection keeps the original vertices, the split wires, and the
midpoints of fully selected wires only, so repeating the command refines the
same region instead of adopting the bled boundary ring and quadrupling it per
click. Face-selection values are compact face offsets everywhere in the
resident session; per-face source indices are ancestor bookkeeping, never a
selection space. Geometry and selection are one native history pair, so one
Undo or Redo restores both. The Builder adopts the native remapped selection
after remapping topology rather than clearing its mirror independently. Delete
is the exception: it intentionally clears element selection after commit and
never republishes the pre-delete native target against compacted face offsets.
For imported-model authoring, the Selection panel offers **Create Part from
Selection**. It sends the existing `separate` command after current or
provisional Brush selection authority has landed,
requires Faces from exactly one source part, moves those faces into a uniquely named
appended submesh, and retains the source part's vertex channels and material route. The
new Parts row is selected and revealed with its moved-face count. Create New Item opens
an imported source here with Faces as the target while keeping Orbit as the neutral
initial tool, then accepts a stable resident revision back into its placement/build workflow.
Normal tools include service-routed recalc, tangent generation, flip,
sharpen/soften, weighted normals, and source-normal copy commands; cleanup
tools include remove doubles, delete loose vertices, compact orphans, winding
repair, and hole fill. Widgets only emit descriptors. `triangulate_display` and
`quadrangulate_display` are deliberately not among them: the service refuses
both unless the caller passes `allow_legacy_display_cleanup=True`, so they are
legacy/archive-path helpers rather than tools the rail may offer.
`MeshEditorTab.update_editor_session_state()`,
`MeshEditorTab.update_editor_action_state()`, and
`MeshEditorTab.set_active_tool_state()` keep tool enablement and active mode
state in the feature tab, including embedded static-builder refreshes.
`MeshEditorController.apply_editor_action()` is the execution bridge for those
descriptors; UI shells should emit actions, not implement edit commands.
`MeshEditorController.run_editor_action()` wraps that bridge with native preview
update packaging for action-bar consumers.
Correlated resident updates treat every positive helper request ID as an
ordering boundary. A terminal selection may wait behind an acknowledged
geometry frame at the same revision, but it cannot be merged into that frame or
published under its ID. Cancellation or publication failure returns an explicit
rollback result so provisional selection cannot remain stranded.
`MeshEditorController.export_validation_report()` exposes the service-backed
pre-export validator for the active session. The visible **Run validation**
action executes it in a background worker. Its report is stamped to the checked
geometry revision; a later edit retires its output authority until validation is
run again while keeping the previous report visible as last-known-good context.
`MeshEditorController.workspace_summary()` exposes the service-backed part,
material route, UV channel, and skinning summary for panel rendering. Whole-part
selection belongs to the explicit Parts/PARTS lists: clicking a row toggles it
without clearing other selected rows, and the part context menu routes
clone/delete/normal actions through `MeshEditorController` and `MeshService`.
Material and texture names remain read-only diagnostics; no assignment or copy
action is exposed.
`MeshEditorController.compare_summary()` exposes source-vs-edited topology,
bounds, scale, orientation, material, texture, and UV mismatch data for the
workspace Compare panel.
Parts, UV Map, Rig, Compare, validation, and rebuild presentation all use
`MeshPanelSnapshot`: `ready`, `pending`, `error`, or `unavailable`, with the
requested session/revision kept separate from the revision that produced any
retained value. Only a matching session, geometry revision, request, and
generation may publish a worker result. Selection-only resident revisions do
not invalidate geometry reports, while an acknowledged geometry revision does;
expected native-snapshot gaps remain unavailable instead of hydrating stale
Python geometry, and unexpected exceptions remain visible and enter the runtime
diagnostic trail.

## Preview compatibility and output

Historical `d3d11_*`, `dotnet_*`, and `native_preview_*` Python names remain
where imports, settings, tests, or object names consume them. They construct the
shared Rust preview host; they do not launch the retired renderer. The old
resident C++ interaction packets are described in
[Mesh Core](../../../native/cdmw_mesh_core/README.md), separately from the
production Rust editor's shadow-session contract above.

Archive and specialist previews use the viewport-only `--cdmw-preview-session`
route. Their canonical Preview Core material packages, source bindings, role
cameras, and capture requests are owned by the shared preview services. They
are distinct from the editor's `--cdmw-session` route. Read-only source textures
stay with the model while geometry and UVs change.

After **Finish Edit Mesh**, run **Run validation** for the authoritative revision.
**Export Mesh File** publishes a separate rebuilt asset and report. **Build Mod**
publishes either a loose mesh-only manager package or a **DMM Archive Group**
package. Output stages in an owned sibling directory and publishes once; stale
revisions, cancellation, and failure cannot leave a partial final folder.

**Install as Overlay** prepares the exact mount change, carry-forward files,
ownership, and recovery targets for review before confirmation. The service
rechecks the game state, validates staged content, backs up through
`ArchiveMutationService`, and publishes the mount list last. The saved receipt
lets **Restore Last Overlay Install** restore the prior state and remove only
paths created by that installation. Foreign groups are never adopted.

The surrounding PySide controls use the app's localization catalogs. Rust's
embedded editor controls currently remain English-only; a viewport-only
localization acknowledgement does not translate the editor UI. See the root
[documentation and languages](../../../README.md#documentation-and-languages)
reference for the current boundary.
