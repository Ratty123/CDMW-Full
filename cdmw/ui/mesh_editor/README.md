# Mesh Editor

Owns the Mesh Editor tab shell, typed session requests, empty state, and embedded
builder hosting. Archive internals and destructive writes stay outside this UI
package.

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

`MeshEditorTab.open_mesh_session()` opens a standalone in-tab edit session for a
`ParsedMesh` without starting the full Archive Browser builder. It routes toolbar
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
The standalone and embedded Mesh Editor viewport is .NET/Vortice-only.
`start_standalone_native_preview()` and its async counterpart are the live entry
point into that renderer: they push session and scene state to a running .NET
editor process, or start one when none is running. The Python D3D11 preview host
was removed with the resident Vortice migration, so there is no D3D11 fallback
and no host-command construction left to own.

`native_preview_payloads.py` owns Mesh Editor payloads for the .NET preview
bridge; callers should not duplicate mesh-to-preview JSON/blob packing.

`controller.py` owns the feature-side edit-session bridge over `MeshService` and
converts edit results into native preview update payloads.

`actions.py` and `action_bar.py` own the Mesh Editor command palette and Qt tool
surface. They map visible tools to service command keys without applying edits.
Topology tools include local Subdivide and Refine Smooth, which adds connected
detail before smoothing the affected area for less pointy surfaces.
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
`MeshEditorController.export_validation_report()` exposes the service-backed
pre-export validator for the active session.
`MeshEditorController.workspace_summary()` exposes the service-backed part,
material route, UV channel, and skinning summary for panel rendering. The
Outliner and Parts & Routing panel both support persistent whole-part selection:
clicking a part toggles it on/off without clearing other selected parts, and the
part context menu routes clone/delete/normal/texture actions through
`MeshEditorController` and `MeshService`. The Parts & Routing panel also shows
selected-part count, names, material routes, and textures, exposes visible
select-all/clear/invert and clone/delete/normal/texture buttons, and disables
unavailable texture actions when the current selected part has no texture.
`MeshEditorController.compare_summary()` exposes source-vs-edited topology,
bounds, scale, orientation, material, texture, and UV mismatch data for the
workspace Compare panel.
Native D3D11 viewport part-pick events route into the same persistent
whole-part selection and context-menu path used by the Outliner and Parts &
Routing panel. The tab replays native part-picking enablement after preview
load/reload and reports unavailable picker state in the workspace. UI code still
delegates clone/delete/normals/texture work through `MeshEditorController` and
`MeshService`.
Production .NET stores separate `reference` (Original) and `editable`
(Imported/Modify) presentation contexts over one document/resource owner.
Placement can use any supported preview mode. Edit Mesh always presents only
Imported/Modify, pins navigation to its editable camera context, and disables
the Original selector. Entering Edit Mesh defaults its editable viewport to
Wire + Vertices; leaving Edit Mesh restores the Builder's selected
placement preview mode without restarting the resident renderer.
After that initial default, the selected display mode is authoritative: tool,
selection, scene, material, and tab-visibility publications add their overlays
without replacing it, so Solid stays Solid while selecting or editing. The
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
this modal. The viewport's own background and grid colors are picked in the
editor's Viewport section beside the wire and vertex swatches, persist in
`mesh-editor-viewport-background.json` next to the topology appearance, and
override the host presentation snapshot so an accepted scene frame cannot
replace them. Archive Browser Preview Settings use a separate resident .NET target
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
placement visibility preference. Edit Mesh opens with no rail page selected and
the viewport on Orbit — orbit owns no page, and neither does any tool the rail
has not been taught — so the first drag turns the model rather than editing it,
and the tool-properties column stays collapsed to the icon rail until a tool is
picked. The Orbit button in the Viewport section returns the viewport to Orbit
navigation; the camera is otherwise reached by the rebindable modifiers named on
the navigation strip. Host
`tool_state` synchronization still applies its requested tool directly and does
not toggle it off during resident-state replay. Every .NET button uses the same
dark-theme depth treatment: raised at rest and visibly sunken while held by
mouse or keyboard. Stateful tool, placement-gizmo, and active-pane buttons keep
the sunken bevel after release, with color serving as a secondary state cue.
Rendered Gizmo size and pointer hit testing share the Preview Settings values,
so customized handles remain aligned with interaction.
Native D3D11 viewport Move/Grab/Smooth/Inflate/Pinch stroke events also route
through `MeshEditorController`/`MeshService` as resident native-session
`transform`/`brush` commands with `stroke_phase` and `stroke_id` payloads.
Each gesture builds its immutable projected candidates once. Move then applies
a renderer-local part transform on every pointer update; Grab and sculpt tools
patch a transient vertex buffer from the stroke baseline through a screen-space
spatial index. Protocol updates are bounded to 16 ms, retain the full cursor
segment since the last publication, and enter the existing one-in-flight plus
one-latest-pending dispatcher. Only a matching stroke ID, request, and revision
can reconcile the local result; Cancel restores the baseline and a completed
stroke creates one history entry.
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
selection is empty. Grab with an existing selection sends only `screen_drag`
plus the tool scalar fields and relies on the matching resident C++ selection;
Grab without one, and Smooth/Inflate/Pinch without one, establish an internal
screen-brush scope under the first hit without selecting a PARTS row. Their
begin and update packets carry native `screen_brush` context and omit D3D11
candidate groups; native core chooses the resident selection when present and
screen-brush weights otherwise.
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
Smooth, Inflate, Pinch, and Remove do not build
unused drag payloads. Current D3D11 packets do not serialize `camera_world`,
yaw/pitch, pan, distance, or FOV fallback fields; native mesh core still accepts
legacy `step_delta`/`delta` vectors and camera fields for non-updated non-WVP
callers.
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
Edit Mesh separates mesh-region selection from whole-part selection. The
visible Select tool targets mesh vertices with Click, Brush, Rectangle, and
Lasso; only an explicit row action in PARTS selects a whole part. Legacy edge
and face target maps remain accepted internally, but `source` and `part` are
never valid viewport targets. X-Ray changes only the visibility filter. A new
editor opens in Orbit with no selection armed, operation Add, and shape Brush.
Operation and shape remain sticky while tools change, while a newly opened
editor restores those defaults. The sculpt brushes act on selected mesh
elements, or use the initial hit region as an internal stroke scope without
changing PARTS when none is selected.
The builder's Selection combo (Brush/Lasso/Rectangle) is honored by the
resident editor: a brush-mode Select drag paints renderer-local vertex highlights
on every pointer update while sending throttled add/subtract
`screen_brush` dabs that native unions over the swept path (Replace starts the
new selection on the first dab; Subtract erases; a plain click keeps the
precise 14px click pick), and a cursor step longer than the brush radius is
sent as a swept-segment `screen_region` quad instead of a disc, so the painted
band has no holes at any cursor speed — the 30ms cadence bounds message rate,
never coverage. A lasso-mode drag draws the polygon actually swept in the
overlay and sends it as `screen_region` mode "lasso" with rectangle endpoints
kept as the older-core fallback. Helper-raised screen selections have exactly
one native authority: the tab's protocol handler applies them, answers the
helper's pending request, and commits the result back through the builder;
the builder's own screen-selection route is legacy-panel-only. Intermediate
paint dabs apply inline off the action-worker path; the final dab records the
one selection-history unit for the drag. Toggle records each crossed vertex once
per gesture, so crossing the same vertex again cannot undo the first pass. The old
D3D11 vertex/edge/face hover
candidate projectors are removed; Mesh Edit overlay drawing keeps the cursor
ring and selected geometry while hit resolution stays in native screen
selection.
`MeshEditorTab` routes those events to a resident native `select` command
through `MeshService`, C++ expands the requested selection mask from the D3D11
projection matrix, composes D3D11 per-source world transforms when alignment
preview transforms are active, ignores leaked legacy groups for projected
screen selection including source-specific projection override arrays, prevents
non-overridden sources from using legacy camera defaults, treats region edge
selection as projected segment hits with hit-point depth checks,
treats region face/source selection as projected triangle hits, applies native
visible-depth filtering when requested for brush or region selection, and pushes
the resulting selection groups back to the D3D11 preview host.
D3D11 brush candidate weight sidecars are forwarded as native selection weights,
so C++ applies host-computed screen/depth falloff instead of recomputing it in
Python or from object-space distance.
`MeshEditorController.uv_summary()` exposes service-backed UV island bounds,
selection, and texture routing for the workspace UV panel.
The workspace UV tab includes a non-mutating `MeshUvCanvas` that paints the
current UV island bounds over a texture/grid backdrop from that summary.
Drag-box and right-drag lasso selection on that canvas emit UV bounds/polygons;
`MeshEditorTab` routes them through `MeshEditorController`/`MeshService` before
sending normal native selection refresh payloads.
UV toolbar descriptors route move/rotate/flip, island transforms, normalize,
axis align, island pack, grid/pixel snap, and planar/box/cylindrical projection
through `MeshService`; widgets do not mutate UV arrays directly.
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
source/confidence and the default `30.0` FPS path is unproven. PABC skeleton
variation payloads are parsed as read-only bone-hash records with three 4x4
float blocks per record. PASEQC lane references can be threaded into parsed PAA
clips as preview-only sequence segment metadata with per-field confidence; blend
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
See `docs/features/mesh-editor-skeleton-discovery.md` for current read-only PAC/PAB/PABC
relationship evidence and confidence rules.
`MeshEditorController.texture_edit_target()` exposes the selected material
texture target. `MeshEditorTab.open_texture_source_requested` hands local or
archive-cache-materialized DDS files to the existing Texture Editor bridge; the
Mesh Editor does not load or export texture documents itself. Archive-only
texture names resolve through shell-owned archive indexes and
`ensure_archive_preview_source()` before opening. Texture Editor DDS results
carry explicit preview/assign semantics back to Mesh Editor. Compressed preview
stores a transient per-part override without mutating the edit session.
Export/Assign routes through the resident `material_assign` command, so the
binding participates in revisioned undo/redo and editable-package export; a
running .NET/Vortice session receives an authoritative `material_state_update`
without a renderer restart.
Linked base/albedo edits also emit deferred tight BGRA8 dirty regions after a
history commit, undo, or redo. The .NET bridge derives the active material
resource ID, keeps one in-flight update plus one latest-wins pending union per
resource, leases an initial composite read-only until its worker copy completes,
and deletes owned binary payloads on acknowledgement or shutdown. A concurrent
Texture Editor mutation takes a copy-on-write cache instead of changing the
emitted composite.
Full DDS assignment remains the export-authoritative fallback.
Resident material resources use the Python-owned criticality contract. Required
concrete base resources block initial Ready on decode failure; optional normal,
surface, emissive, height, and legacy/symbolic resources keep an explicit
fallback plus diagnostic. Late original/reference textures use a render-only
reference-role generation and never commit into the editable export session.
glTF/green-up normal inputs carry `invert_green_for_directx` to the HLSL path;
already-DirectX inputs preserve green.
Source DDS paths take precedence over preview PNG paths. Supported 2D DDS
resources keep their native DXGI format and full mip chain, with semantic
sRGB/linear SRVs and per-resource upload diagnostics. Region painting remains
copy-on-write and affects only its resource; its mutable BGRA resource keeps a
full mip chain regenerated after each boxed upload. Shader-family, alpha, culling,
opacity, and occlusion evidence are resident state; unproven layer, hair/fur,
skin, and blended-alpha behavior is reported rather than approximated.

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
