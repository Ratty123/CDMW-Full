# Mesh Editor

Owns the direct, mesh-only Mesh Editor tab shell, typed archive-session requests,
resident authoring workspace, and output orchestration. Archive internals and
destructive writes stay outside this UI package. Static-replacement builder
hosting remains compatibility-only and is not reachable from normal Mesh Editor
or Archive Browser UI.

The current product boundary is geometry authoring: selection, topology,
transforms, normals/tangents, rigging, Morph & Refit, UV-coordinate editing,
history, original-vs-edited review, validation, and read-only textured display.
Texture/material assignment, recolour/glow authoring, replacement/import-preview
workflows, in-game swaps, and Texture Editor handoffs are not Mesh Editor
features. Dedicated texture tools and Create New Item own those jobs.

`tab.py` is the stable public Qt class. Bounded `tab_*.py` owners hold shell,
native-preview, package, .NET protocol/process, report, session, state,
interaction, and action behavior. `tab_compat.py` keeps historical public
monkeypatch seams live without moving behavior back into the facade.

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

`MeshEditorTab.open_mesh_session()` opens a scripted in-tab edit session for a
`ParsedMesh` without starting Archive Browser UI. It routes toolbar
actions through `MeshEditorController`, updates the native preview host when one
is attached, and falls back to refreshing the lightweight preview panel.
`MeshEditorController.native_update_for_result()` is native-payload-only; Python
mesh-based preview packing is explicit archive-only code behind
`legacy_python_update_for_result(..., allow_archive_legacy_preview_rebuild=True)`.
`MeshEditorTab.open_mesh_file_session()` opens a supported PAC/PAM/PAMLOD file
through `MeshService.load_mesh_file()` before entering the same standalone edit
session path for scripted callers. UI callers should use
`MeshEditorTab.open_mesh_file_session_async()`, which runs file IO, parsing, and
service session creation in `MeshFileSessionLoadWorker`, then attaches the
controller and already-loaded mesh on the UI thread.
The direct Mesh Editor viewport is .NET/Vortice-only. The helper launches with
`--direct-authoring`: edit controls are visible immediately, placement and the
Edit Mesh toggle are absent, and Qt owns close and output actions.
Normal sessions expose only that resident **Mesh Edit Session** form plus the
compact Qt-owned validation/output/package strip beneath it. The earlier Qt
mode row, Tools/Edit/UV/Rig deck, duplicate part/material and report tabs, and
status/performance log remain constructed only for compatibility callers and
are hidden from the normal product surface.
The five direct output buttons use explicit normal, hover, pressed, and disabled
states. Validation-gated outputs and receipt-gated restore stay visibly
unavailable until their prerequisites exist.
The session-state bridge also declares whether the current source requires an
exact PAC/PAM/PAMLOD output. Those sessions show the complete Topology, Parts,
clipboard, and Layers control surface, but disable operations whose result cannot
preserve protected records and expose the exact reason in help. The host rejects
the same commands before mutation. **Delete Selection** remains available through
the exact face-delete route. Imported GLB/OBJ sessions opened by **Create New
Item** declare a working-mesh output instead, so Create Part, duplicate and the
other imported-model topology tools are enabled.
The resident strip keeps **Close** at its far edge. It remains available while
session work is active, confirms before discarding edits, and returns Mesh Editor
to its empty state through the same nonblocking worker and renderer teardown path.
`start_standalone_native_preview()` and its async counterpart are the live entry
point into that renderer: they push session and scene state to a running .NET
editor process, or start one when none is running. The Python D3D11 preview host
was removed with the resident Vortice migration, so there is no D3D11 fallback
and no host-command construction left to own.
Helper status JSON commits are serialized per destination across processes,
then published through a unique sibling file and an atomic replacement, so an
overlapping helper or a monitor reading the prior status cannot collide with a
new write. Fatal reporting is best effort: embedded and headless failures
preserve the original exception on stderr and exit nonzero without opening a
Windows application-error dialog even when the status destination is locked.

`native_preview_payloads.py` owns Mesh Editor payloads for the .NET preview
bridge; callers should not duplicate mesh-to-preview JSON/blob packing.

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
Native D3D11 viewport part-pick and part-context events are compatibility no-ops.
They cannot change a PARTS selection or open its menu. The historical
`select_parts` action key is retained for settings/dynamic callers but presents
as Select and arms vertex selection, never source-part picking.
Production .NET stores separate `reference` (Original) and `editable`
presentation contexts over one document/resource owner. Direct authoring starts
in `mesh_edit`/`replacement_only`, pins navigation to the editable camera, and
does not expose placement mode or an Edit Mesh toggle. The helper's Mesh View
selector is the one visible authority, including **Solid (Textured)**; changing
geometry or UVs keeps the same resident source-material bindings.
After that initial default, the selected display mode is authoritative: tool,
selection, scene, material, and tab-visibility publications add their overlays
without replacing it, so Solid stays Solid while selecting or editing. The
selector also stays on the requested **Solid (Textured)** mode while the renderer
temporarily shows readable untextured faces during material resolution. A
definitive resolution or binding failure reports its reason and then moves the
selector to the actual fallback. The
resident tab lifecycle is explicit `inactive -> resuming -> active`. Returning
to Mesh Editor activates the already-resident matching package immediately; a
different desired identity loads before activation. One timed activation retry
precedes the existing helper recovery/rehydration path, preserving the healthy
PID and the scene revision, camera, selection, tool, and display state whenever
the process itself is healthy.
When both roles exist it renders both contexts at once in separate rectangles,
each with its own grid and independent camera/display state, inside one shared
D3D11 viewport and swap chain. The divider is draggable and its ratio is shared
with the Builder's persisted preview setting. Original is camera-only;
Imported/Modify alone can select or mutate. Explicit Overlay remains a
single-surface comparison mode. Outer Builder camera/Fit, display,
quality/lighting, UV, grid/gizmo, highlight, visibility, routing, and part state
use the correlated resident presentation lane and bypass legacy-only mutation
while .NET owns the session. Placement gizmos render an exact provisional
editable matrix at input cadence; Original never receives that transform. Role
camera framing bounds and the world grid stay fixed through resident placement
updates. Only an explicit, role-addressed Fit command reframes a pane, and
camera command generations prevent persistent presentation replay from
reapplying an earlier Fit or camera nudge.
Textured readiness is tracked independently for the `editable/imported` and
`original_reference` material roles. A generation is settled only after every
role required by the active scene acknowledges it; an Imported acknowledgement
cannot complete Original, and failures identify the affected pane while the
last valid presentation remains resident.
Preview Settings opened anywhere while .NET/Vortice owns the embedded Mesh
Editor session use an explicit .NET preview target. In that context the dialog
shows Camera Input and Gizmo tabs. Camera Input contains orbit sensitivity, pan
sensitivity, the four orbit/pan inversion switches, and the rebindable orbit and
pan modifiers -- the held keys that move the camera while an edit tool owns the
left button. A pair that shares a key is resolved by
`cdmw.domain.camera_bindings` before it reaches the helper, because the viewport
tests pan first and a collision would otherwise leave orbit silently dead. Gizmo contains the
X/Y/Z, active/hover, and label colors plus line thickness, overall size,
font/label size, and handle size. Those values apply live through the resident
presentation payload and persist with the main Preview Settings config.
Display, topology, X-Ray, grid, material, texture, and lighting controls stay
on their owning .NET/Builder viewport surfaces instead of being duplicated in
this modal. The viewport's own background, grid, wire, vertex, committed
selection, and live-selection colors are picked in the editor's Viewport
section. Overlay preferences use schema v3 and migrate the v1/v2 wire and vertex
values while defaulting the new swatches to gold and cyan. The same chosen
selection colors feed face, wire, and vertex overlays in the D3D11, WPF, and GDI
paths. Background/grid values persist in
`mesh-editor-viewport-background.json`; overlay colors and sizing persist beside
it, and both override host presentation replay. Archive Browser Preview Settings use a separate resident .NET target
and likewise show only Camera Input; texture loading remains on the Archive
Preview toolbar. Reset Camera Input restores the two sensitivity values while
preserving the inversion choices, Gizmo appearance, and every hidden renderer
setting. Each role pane keeps its own camera, and wheel zoom uses reciprocal
steps with fit-relative bounds so a large mesh whose fitted zoom is below `1.0`
can always zoom back out. The same wheel path is used in placement and Edit
Mesh.
Embedded .NET Mesh Edit screen payloads pair the active camera with a
per-editable-submesh WVP built from the exact model matrix used to render that
submesh. Brush, click, drag, and region selection therefore stay aligned with
placed or transformed replacement geometry, and the source filter excludes
hidden submeshes. The host preserves `vertex`, `edge`, and `face` target modes
on this screen-selection route; a stale `source` or `part` target falls back to
`vertex` instead of turning a viewport hit into a PARTS selection. Vertex click
targets use a 14-pixel tolerance and the D3D11
overlay expands vertex points to round 7-pixel screen-space markers. Smooth defaults
to three iterations per dab, while Inflate and Pinch include native
`screen_radius` amount context; brush tools paint under the cursor without a
selection prerequisite.
The Archive Browser .NET Preview Settings registry contains only the six
resident camera-input fields. The Mesh Editor registry adds nine
placement-Gizmo appearance fields. Each visible field has a Python presentation
payload key, a .NET parser, and a resident runtime consumer. Renderer settings
may still travel through the correlated presentation state from their owning
viewport surface, but that transport alone does not make them appropriate modal
controls. Texture and view-mode choices synchronize across both role panes
without merging their independent cameras.
The Gizmo is a placement aid: entering Edit Mesh suppresses both its renderer
overlay and its pointer interaction, while leaving Edit Mesh restores the saved
placement visibility preference. Edit Mesh opens with the viewport permanently
visible as the leftmost working surface and Orbit as its neutral state. The tool
dock and the always-visible Parts/Layers/Action History inspector occupy one
fixed-width right column, split vertically; the width is sized for the widest
tool page once, so opening Select, Move, Grab, Smooth, Inflate, Pinch, Topology,
Morph & Refit, or Viewport does not resize the D3D surface or recreate its swap
chain. Viewport is therefore never a page that must be opened to reveal the
preview. The Orbit button in the Viewport section returns interaction to Orbit
navigation; the camera is otherwise reached by the rebindable modifiers named on
the navigation strip. Host
`tool_state` synchronization still applies its requested tool directly and does
not toggle it off during resident-state replay. The visible resident host
receives the active application palette before reveal and again on a live theme
change, including light/dark common-control treatment, fields, panels, text,
buttons and accent states. Every .NET button keeps the same depth treatment:
raised at rest and visibly sunken while held by mouse or keyboard. Stateful tool,
placement-gizmo, and active-pane buttons keep the sunken bevel after release,
with color serving as a secondary state cue.
Rendered Gizmo size and pointer hit testing share the Preview Settings values,
so customized handles remain aligned with interaction.
Native D3D11 viewport Move/Grab/Smooth/Inflate/Pinch stroke events also route
through `MeshEditorController`/`MeshService` as resident native-session
`transform`/`brush` commands with `stroke_phase` and `stroke_id` payloads.
Move and Grab build their immutable projected candidates once and display an
exact renderer-local preview on every pointer update. Native Grab captures the
same initial weights and center on `stroke_begin`, then reuses that fixed scope
even after the cursor leaves the mesh. Smooth, Inflate, and Pinch display the
correlated resident-native result stream instead of a second local sculpt
approximation. Protocol updates are bounded to 16 ms; coalescing retains the
complete compact `screen_path` polyline, not only its newest endpoint, while
the visible-depth mask spans that complete path and the dispatcher keeps one
in-flight plus one pending update. The renderer publication lane is also
acknowledgement-paced: while one geometry frame is applying it retains only the
newest cumulative nonterminal stroke outcome, acknowledges every superseded
request as coalesced, and treats end/cancel as an ordering boundary. Only a matching
stroke ID, request, and revision can reconcile the result. Cancel restores the
baseline, and the terminal phase publishes one cumulative geometry frame and
creates one history entry.
When the shared helper adopts a new process generation or session identity, the
revision queue adopts it at the same boundary, discards work addressed to the
old identity, and restores the process's negotiated revision capabilities. A
rejected mutation performs one authoritative resident-state resync; its applied
acknowledgement clears recovery before the next edit is released, so a
recovered Grab, sculpt, UV, or Morph update cannot remain stuck behind an
already-completed resync. Activation acknowledgements are exposed to Mesh
Editor only after the shared controller validates their request, process, and
package generations.
Move requires an existing resident vertex, edge, face, or explicit PARTS
selection and reports that prerequisite without starting a stroke when the
selection is empty. Grab, Smooth, Inflate, and Pinch carry native
`screen_brush` context and omit D3D11 candidate groups; native core restricts
that brush to the resident selection when present. Without one, the initial
hit establishes an internal brush scope without selecting a PARTS row. Grab's
scope is fixed for the complete stroke, while sculpt weights follow every
retained path segment.
D3D11 Move and Grab paths build `screen_drag` cursor endpoints plus viewport and
world-view-projection context through Qt and `MeshService`; `screen_drag`
includes per-source world transforms when alignment preview transforms are
active, so native mesh core composes them with the base WVP, unprojects at the
native pivot or brush center, and resolves pixel deltas, object-space
displacement, and transform axis constraints during apply. If a D3D11-style WVP
payload cannot be resolved, native mesh core fails closed instead of falling
back to legacy camera math; malformed per-source WVP/transform overrides also
fail closed for that source instead of using the base untransformed WVP.
Projected drag ignores compatibility `translate`/`delta` vectors if present.
Standalone D3D11 stroke dispatch requires `screen_drag` for Move/Vertex
begin/update packets and does not synthesize `translate` or brush `delta` when
the native drag payload is missing. End/cancel packets may omit `screen_drag`
only to close an existing native stroke.
Smooth, Inflate, and Pinch carry `screen_drag` and, when updates coalesce,
`screen_path`; native mesh core integrates their falloff exposure over each
retained segment. An inert terminal packet has zero sculpt strength, while a
terminal packet that absorbed real cursor travel keeps its strength. Current
D3D11 packets do not serialize `camera_world`, yaw/pitch, pan, distance, or FOV
fallback fields; native mesh core still accepts legacy `step_delta`/`delta`
vectors and camera fields for non-updated non-WVP callers.
Brush-target Grab packets pair that `screen_drag` movement with `screen_brush`
weight resolution. Smooth update packets send strength/iterations plus
`screen_brush`, while Inflate and Pinch updates send
`screen_brush`/`screen_radius`/strength payloads so native mesh core owns
pixel-radius to world-amount conversion and can derive screen-space brush
weights when explicit update weights are absent. `screen_radius` includes the
D3D11 world-view-projection matrix plus per-source world transforms when
alignment preview transforms are active, so native mesh core composes them and
converts the pixel radius/default amount at the native-derived center; unresolved
WVP payloads do not fall back to legacy distance/FOV amount math, and projected
radius ignores compatibility `center`/`radius`/`amount` scalars if present.
Current D3D11 packets do not serialize `camera_world`, distance/FOV fallback
fields, or center.
`screen_brush` includes the D3D11 world-view-projection matrix; native mesh core
uses WVP for projection and ray picking. Malformed per-source projection
overrides, source-only overrides without a base WVP for other sources, and
projected cursor misses fail closed before brush weights can fall back to
object-space radius.
Current D3D11 packets do not serialize `camera_world`, yaw/pitch, pan,
distance, or FOV fallback fields.
Smooth/Inflate/Pinch packets also carry `target_mode` and
`selection_depth_mode`, so native brush weights apply the same selection-vs-brush
and visible-vs-xray rules the D3D11 host previously resolved. Inflate/Pinch
center is derived in native mesh core from explicit weights, resident vertex
selection, or screen-brush weights, not serialized by the D3D11 host.
Standalone D3D11 brush-selection events now send `screen_brush`, target mode,
operation, selection depth mode, and falloff instead of expanding vertex,
edge, face, or source-part candidates in the host. Source-part click selection
while Mesh Edit is active also sends a source-target `screen_brush` payload
instead of resolving the part inside the D3D11 host. Source-part context
requests while Mesh Edit is active use the same native source screen pick; a
native miss preserves the current selection and skips the menu. Mesh Edit hover
clears stale source hover state without projecting source parts in the D3D11
host.
Standalone D3D11 rectangle/lasso selection events now send `screen_region`
with D3D11 start/end coordinates, optional lasso points, source-submesh filter,
viewport, and world-view-projection matrices instead of expanding selection
candidates in the host.
`selection_mode` in `tool_state` names the Select drag shape and accepts only
`brush`, `lasso` and `rectangle`. The element mode travels as `target_mode`; a
host that publishes anything else in the drag-shape field is ignored outright,
including for the record of what the host last said, so a shape picked in the
editor survives every control refresh.
Morph & Refit profile creation is a four-page guided wizard: Profile, Parts,
Deformation, and Preview & Save. It generates the technical profile ID
automatically, offers named PARTS rows or the acknowledged viewport mesh
selection, exposes
only the axis fields meaningful to Volume/Scale/Move/Flatten/Taper/Twist, and
keeps category, ID, range, feather, falloff, mirror, and local basis under
the working Advanced expander. Editing an existing slider preserves its
authored region unless Replace is explicitly selected. Minimum/default/maximum
previews use the correlated resident morph
lane; Finish saves `mesh_morph_profile_v2` and returns preview to zero, while
Cancel restores zero and removes the temporary definition. The main section
then stays linear: profile sliders, optional Refit, Review and Apply. Refit
names its driver and garment part selections and rejects overlap; Reset and
Bake remain explicit, and saving never bakes geometry.
Opening Morph & Refit batches redraw only for the tool column. It does not
reparse the source, upload geometry, recreate the D3D device/surface, change the
helper PID/HWND, touch camera contexts, or advance presentation generation.
Morph commits reuse the submesh counts already returned by native core instead
of attempting a disabled geometry hydration.
Edit Mesh separates mesh-region selection from whole-part selection. The
Selection target control offers Vertices, Wires (`edge` on the protocol), and
Faces. Click, Brush, Rectangle, and Lasso all honor that target and restrict
hits to the active geometry layer; they do not require a PARTS filter. Only an
explicit row action in Parts & Routing/PARTS selects a whole part. `source` and
`part` are never valid viewport targets. X-Ray changes only the visibility
filter. Every fresh or resumed editor opens in Orbit with no selection armed;
runtime tool, selection, camera, and Undo/Redo state are not restored from a
draft. Moving between tool pages inside the same live session preserves the
current tool.
Selection gestures use the background latest-wins stroke dispatcher. Immutable
begin/update/end/cancel requests carry stroke ID, sequence, target, operation,
and every unsent swept brush/region sample. One update may run while one merged
update waits; native selection never runs inline on the Qt UI thread. Provisional
geometry stays ahead of the last acknowledged base, and an old acknowledgement
cannot clear a newer tail. The matching final acknowledgement creates exactly
one selection-history entry; cancellation, failure, or session retirement
restores the pre-stroke selection and clears the correlated provisional state.
Lasso spatially samples its visible points while drawing, appends the exact
mouse-up endpoint, and uses that same unsimplified polygon for local and native
tests. Its immediate target-specific mouse-up result remains visible until
native authority answers.
`MeshEditorTab` routes those events to a resident native `select` command
through `MeshService`, C++ expands the requested selection mask from the D3D11
projection matrix, composes D3D11 per-source world transforms when alignment
preview transforms are active, ignores leaked legacy groups for projected
screen selection including source-specific projection override arrays, prevents
non-overridden sources from using legacy camera defaults, treats region edge
selection as projected segment hits with hit-point depth checks,
treats region face selection as projected triangle hits, applies native
visible-depth filtering when requested for brush or region selection, and pushes
the resulting selection groups back to the D3D11 preview host.
Topology commands first drain the final correlated selection request. A
Subdivide, Refine Smooth or Create Part click made while Brush/Lasso selection is still
provisional is queued without the helper's older `local_selection` snapshot and
runs against resident selection authority after mouse-up; a failed or cancelled
selection terminal cancels the queued command.

Brush projection is resident across short gestures. Arming Select or settling the
camera starts an immutable background projection build; a first dab that arrives early
is queued against that correlated build rather than constructing the whole mesh on the
WinForms input thread. Depth tiles are prepared only where the brush touches. Geometry,
topology, vertex positions, camera/model matrices, viewport size, X-Ray, or visible and
editable part changes invalidate the cache; ending a gesture and switching tool pages do
not. The stable left viewport prevents ordinary menu/tool activation from changing its
size and invalidating the projection. Selection status
adds build, hit, invalidation, stale-build, and cold/warm first-dab timings, and the GPU
interaction soak exercises repeated short Face Brush gestures as well as the existing
held stroke and authoritative mouse-up paths.

Copy/Paste is an internal Mesh Editor clipboard (`Ctrl+C`/`Ctrl+V`), not the OS
clipboard. Faces copy exactly; vertex or wire selections copy only fully
enclosed faces and otherwise report `No complete faces selected to copy`.
Paste preserves material/source fragments and all native vertex attributes under
one logical `Selection copy N` layer. The LAYERS list keeps an immutable,
always-visible Base mesh plus named copied layers with active-layer isolation,
Rename, visibility, Move Up/Down, and Delete. Visible layers participate in
build/export; hidden layers remain saved. Paste and Delete are one geometry
history action each. Name, order, visibility, and active-layer metadata persist
immediately without becoming geometry Undo entries or being rolled back by a
later topology Undo.

Layer projects use an atomic `mesh_layer_project_v1` descriptor and checksummed
native binary snapshot generations. A 750 ms cancellable latest-wins autosave
writes a complete new generation before switching the descriptor and retains
the previous good generation for recovery. The first copied layer promotes a
temporary Modify Original clone to `persistent_app_draft`. Draft discovery is
exact-source-SHA-256 only, newest first, and offers Resume or Start New without
deleting older or incompatible drafts. Camera, selection, active tool, and
Undo/Redo history are runtime-only. Closing with dirty state waits off the UI
thread; a failed save leaves the editor open for Retry or an explicitly
confirmed Close Without Saving.

`MeshEditorController.uv_summary()` and the service-owned UV actions remain
available to retained compatibility and automation callers. The old Qt UV
canvas and icon grid are no longer a visible second editor beside the resident
form; any future normal-product UV surface belongs in the resident workspace.
`MeshEditorController.skeleton_summary()` exposes service-backed skinned part,
bone-index, weight-normalization, and linked-skeleton metadata status for the
workspace Skeleton panel.
The Skeleton panel also renders proof-gated authoring status rows from the
domain summary: blocked, preview-only, exportable, and archive-mutation states.
`MeshEditorController.attach_skeleton()` records a parsed PAB-like skeleton on
the active edit session; the Skeleton panel renders root/depth/parent rows from
that service summary. Attached skeletons also feed Mesh Editor native D3D11
package overlay metadata through the existing preview package writer path.
Skeleton pose-preview controls select bones, toggle preview mode, apply
service-owned rotation metadata, and reset pose state. Preview meshes deform
from attached PAB bones plus PAC bone indices/weights without mutating the edit
session mesh. Parsed animation clips can be attached through the service and
played, paused, scrubbed, stepped, looped, speed-adjusted, or rewound from the
Skeleton panel when their tracks bind to the attached skeleton. Structured
animation documents can be converted to clips only when they already contain
explicit bone-track rotation rows. Real PAA payloads can be converted to
preview clips only when a keyframe table is exactly owned by an attached PAB
bone hash at `table_offset - 8`; their playback timing is labeled by
source/confidence and the default `30.0` FPS path is unproven. Model-linked PABC
skeleton variations are parsed as bone-hash records and applied only to cloned
Archive Browser, Model Library, loose-package presentation geometry and visual
FBX export. Resolution keeps the model's exact prefabdata authoritative while
following a separately owned PAB or head PAMT only when character identity,
component, current/legacy namespace and skin binding agree. A linked PAMT
supplies named global/local skeleton poses; FBX converts every non-base target
into a Blender shape key and keeps UTF-8 target names while the source/edit mesh
stays exact. Unsupported descriptor-only or incomplete test bindings fall back
without guessing a weighted bone.
PASEQC lane references can be threaded into parsed PAA clips as preview-only
sequence segment metadata with per-field confidence; blend
and runtime sequence semantics remain unknown. The Skeleton inspector shows the
currently active sequence lane/status when a segment covers the sampled playback
time, and the read-only harness gates same-time repeat scrub output as
deterministic while preserving export geometry. Same-stem source and compiled
PASEQ references can be compared as read-only clip-reference overlap evidence,
including paired source/compiled lane indices and string offsets when both
payloads reference the same clip; readable event/phase marker strings can also
be overlapped, and unique timeline field names can be compared to show which
timing/blend declarations remain source-only; semantic aliases such as
`_startBlendingTime` to `_startBlendTime` stay read-only until value binding is
proven. Executable event semantics remain unknown. Source PASEQ documents expose
`_framesPerSecond` declarations, candidate
FPS counts, and post-declaration candidate value rows with context labels, so
length-prefixed strings do not get treated as FPS bindings. They also expose
blend-window declarations such as `_startBlendingTime`/`_endBlendingTime` plus
unbound nonzero `float32` blend candidates after the declaration region;
value-offset binding remains unknown for both. The harness can also emit
source/compiled active-lane byte-window context around the selected PAA path;
those windows show string lengths and opaque aligned scalars only, with
`active_lane_record_layout_unbound` status until lane start/blend layout is
proven.
PAPR/PASEQ relationship evidence stays blocked until its timing/constraint
semantics are proven. PAPR previews expose read-only constraint string evidence,
including bone/helper references and driver/limit expressions, inferred
nearby-string record candidates, plus related HKX physics references when archive
context resolves them; record layout, value offsets, and solver behavior remain
unknown. The Skeleton panel can render that parsed PAPR evidence as disabled
constraint rows, including capped raw candidate rows with exact-name matches to
attached skeleton bone indices and numeric suffix-base matches when available;
parent-role `P_` prefix-base matches are also labeled when the stripped base
exists in the attached skeleton. It also summarizes all available candidate-row
match coverage. Readable PAPR expression tokens are summarized as proven tokens
with unknown solver semantics. Decoded string offsets for candidate target,
helper, and parent fields are summarized as proven offsets while record layout
stays inferred. Candidate rows also show inferred readable-string span bounds
and decoded-string field order with `nearby_string_span_only_value_layout_unproven`
layout status, plus read-only inter-field gap byte classes and unbound aligned
scalar hints. Expression syntax signatures group readable formulas by shape,
channel, limit operator, and numeric-role sequence without evaluating them.
Expression-numeric to gap-scalar matches are summarized as
unbound search hints when present, including which decoded field pair contained
the match and relative distances from the previous decoded field end and to the
next decoded field start; those spans, orders, gaps, scalars, matches, and
relative distances are not value offsets. Parser summaries also keep capped raw
match samples with exact-u32, exact-float32, or approximate-float32 value
confidence, candidate-relative offsets from the inferred expression row, and
aggregate rows split role, field-pair, and value-confidence counts by inferred
constraint family. Compact match signatures combine those fields with
gap-relative deltas, with separate candidate-relative signatures adding the
inferred expression-row offset, as search fingerprints; read-only evidence does
not overclaim binding.
Solver-readiness rows count bound candidate fields but keep solver ready at zero
until record layout and expression semantics are proven.
UI candidate-family rows identify disabled inferred families such as driver
expressions and local transform limits, and per-family readiness rows show their
own binding counts/blockers. Disabled candidate rows can also show parser-provided
channel, limit-operator, numeric-constant/role, syntax-shape,
expression-semantics confidence, decoded string-offset evidence, and inter-field
gap/scalar/numeric-match evidence. UI code does not parse PAPR, evaluate
expressions, or run constraint solving.
Selected vertex weights are summarized in the Skeleton panel; `Transfer W`,
`W+`, `W-`, and `Norm W` route through `MeshService` to copy source weights for
selected vertices or whole selected parts, nudge selected-bone weights, or
normalize rows without UI-side mesh mutation. Import/adapter callers can pass a
source skeleton so transfer remaps source bone indices onto the attached target
skeleton by matching bone names; `MeshEditorTab` carries that source skeleton
through standalone sessions and the Skeleton panel `Transfer W` action. Direct
local PAC/PAM/PAMLOD file sessions also load and attach a sibling or
supplemental `.pab` skeleton when one is available.
`cdmw/core/archive_mesh_appearance.py` owns the read-only PAC/PAB/PABC/PAMT
relationship resolution used by presentation preview and visual FBX export;
`cdmw/core/character_appearance_bundle.py` owns the atomic hashed bundle
manifest. **Character Dependency Package** preserves the selected app and exact
virtual dependency tree, writes a ready-to-import FBX under `cdmw_blender`, and
lets a reopened loose PAC reproduce the same presentation after hash validation.
Texture resolution is read-only. Mesh Editor reuses an already-resolved Archive
Browser material context when one exists. A native Archive Browser handoff pins
its resident package before retiring the Browser renderer and carries that path
into the request-correlated material-context worker, which
hydrates the already-resolved native material batches before attempting the slower
Python archive resolver. The lease remains held for the direct edit session so cache
pruning cannot remove its DDS sources. PAM/PAMLOD handoffs also retain their companion;
selecting **Solid (Textured)** waits on that worker and the resident material
acknowledgement rather than failing because Archive Browser had not loaded textures
first. If a required texture cannot decode or bind, the choice reports the failure
and visibly falls back to an untextured mode without blocking geometry editing.
Mesh Editor never writes DDS data, material sidecars, PAMT, or PAZ archives. The
retired Texture Editor bridge, DDS-region update queue/capability, and Colour page
remain archived implementation only and are not constructed, advertised, or
dispatched by the normal product.

`MeshObjectTransformState` is part of `MeshEditSessionView` and every history and
draft snapshot. `MeshService.set_object_transform()` applies one affine delta to
every submesh through the native all-submesh path around the fixed original
source-bounds centre. Location, rotation, linked or independent XYZ scale,
15-degree tilt buttons, and position/rotation/scale/all resets each publish one
undoable gesture without changing selection. Editable-package import resets the
controls to identity because the imported geometry already contains its
transform. The legacy separate Qt panel remains a compatibility surface and is
not mounted beside the direct resident form.

Mesh-only outputs first drain pending resident strokes, then capture one
immutable validated session/revision snapshot. **Export Mesh File** atomically
publishes the rebuilt asset and report. **Build Mod** publishes either a loose
mesh-only folder or a DMM archive-group overlay package. **Install as Overlay**
prepares the exact mount-list change, carry-forward set and backup targets before
confirmation; apply rechecks the game state, stages and validates the complete
overlay, backs up through `ArchiveMutationService`, and publishes the mount list
last. The resident helper is the editor rather than a blocking output task, so
it does not itself disable **Run validation** or an output whose own validation
and target prerequisites are current. Cancellation or failure after backup
rolls back. The receipt consumed by
**Restore Last Overlay Install** restores the prior overlay/mount state and
removes only paths created by that receipt. Source textures and material
sidecars remain inherited and unchanged. Restore validates the exact CDMW owner
marker and proves the receipt's backup/created target sets against the backup
manifest before invoking restore or deleting any overlay-owned path.

Resident output import is prepare-then-commit. The worker prepares and validates
an immutable replacement against a session/revision snapshot without touching
the live service. Only the current UI result may enter the locked,
noninterruptible commit; cancellation remains effective until that boundary and
cannot suppress completion after mutation begins.

Generate Icon requests a correlated 1024x1024 offscreen D3D11 replacement
render inside the package output root. The offscreen camera uniformly fits the
visible camera into the square target, so wide previews keep their proportions
instead of being rescaled independently on X and Y. A non-blocking selection
dialog then lets the user drag any source rectangle; the chosen area is fit and
padded into the final 512x512 PNG without stretching. Capture excludes controls,
grid, gizmo, selection, hover, and brush overlays and does not alter the visible
camera or scene state.
`shell_bridge.py` may forward action-bar signals to the active embedded builder
handler and update shell status/active-tool state; it must not implement mesh
edit commands. The embedded static builder handler may delegate selected-geometry
actions through the Mesh Editor service adapter before refreshing its legacy
preview/build state, including edge actions derived from selected faces or
adjacent selected vertices. Rotate/Scale actions prompt for one numeric value
before using the service transform path. Material Assign/Copy prompts from
existing mesh parts and routes through the same service adapter so Material
Authority metadata stays with the edited mesh state.

`static_replacement_adapter.py` is the compatibility bridge used by Archive
Browser static replacement code when it delegates mesh edits and session history
to Mesh Editor service commands.
Active static-replacement Mesh Editor callbacks require accepted native preview
payloads for changed native results. Missing or rejected D3D11/static payloads
raise instead of rebuilding live preview triangles or inverse transforms from
Python mesh state.
