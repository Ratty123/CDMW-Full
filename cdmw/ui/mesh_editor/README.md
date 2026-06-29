# Mesh Editor

Owns the Mesh Editor tab shell, typed session requests, empty state, and embedded
builder hosting. Archive internals and destructive writes stay outside this UI
package.

`workspace.py` owns the standalone Blender-style workspace layout. Its widgets
emit action descriptors; mesh edits still execute through `MeshEditorController`
and `MeshService`. Its Validator tab renders service/domain export validation
findings; it does not inspect mesh geometry itself. Outliner, material, UV, and
skeleton panel rows are populated from the service-backed workspace summary.
Its Compare tab renders the service-backed source-vs-edited summary and emits
preview-mode requests for edited, source, and ghost overlay views.

`MeshEditorTab.open_mesh_session()` opens a standalone in-tab edit session for a
`ParsedMesh` without starting the full Archive Browser builder. It routes toolbar
actions through `MeshEditorController`, updates the native preview host when one
is attached, and falls back to refreshing the lightweight preview panel.
`MeshEditorTab.open_mesh_file_session()` opens a supported PAC/PAM/PAMLOD file
through `MeshService.load_mesh_file()` before entering the same standalone edit
session path for scripted callers. UI callers should use
`MeshEditorTab.open_mesh_file_session_async()`, which runs file IO, parsing, and
service session creation in `MeshFileSessionLoadWorker` before attaching the
controller on the UI thread.
`MeshEditorTab.start_standalone_native_preview()` starts the native D3D11 host
for that standalone session without starting the full app workflow; the
standalone workspace exposes that as its `D3D11` command button and polls the
host status file for loading, loaded, error, and closed events. The visible
button uses `MeshEditorTab.start_standalone_native_preview_async()`, which builds
the Mesh Editor native payload and writes the native preview package in
`MeshNativePreviewPackageWorker` before launching or reloading the host.

`native_preview_payloads.py` owns Mesh Editor payloads for the native D3D11
preview bridge; callers should not duplicate mesh-to-preview JSON/blob packing.

`native_preview_runtime.py` owns standalone Mesh Editor native preview package
and host-command construction for tab/harness callers that run without the full
Archive Browser builder.

`controller.py` owns the feature-side edit-session bridge over `MeshService` and
converts edit results into native preview update payloads.

`actions.py` and `action_bar.py` own the Mesh Editor command palette and Qt tool
surface. They map visible tools to service command keys without applying edits.
Normal tools include service-routed recalc, tangent generation, flip,
sharpen/soften, and source-normal copy commands; cleanup tools include remove
doubles, delete loose vertices, compact orphans, winding repair, hole fill, and
display triangulate/quadrangulate helpers. Widgets only emit descriptors.
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
See `docs/mesh-editor-skeleton-discovery.md` for current read-only PAC/PAB/PABC
relationship evidence and confidence rules.
`MeshEditorController.texture_edit_target()` exposes the selected material
texture target. `MeshEditorTab.open_texture_source_requested` hands local or
archive-cache-materialized DDS files to the existing Texture Editor bridge; the
Mesh Editor does not load or export texture documents itself. Archive-only
texture names resolve through shell-owned archive indexes and
`ensure_archive_preview_source()` before opening. Texture Editor native DDS
export/preview completion emits the same source binding back to Mesh Editor,
which stores a transient per-part preview override and refreshes the D3D11
package with local textures enabled without mutating the edit-session material
route.
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
