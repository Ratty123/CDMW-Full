# CDMW Mesh Core

Native mesh editing helper for geometry-heavy Mesh Editor operations.

## Commands

Current commands:

```powershell
cdmw-mesh-core transform-json job.json report.json
cdmw-mesh-core uv-transform-json job.json report.json
cdmw-mesh-core auto-uv-json job.json report.json
cdmw-mesh-core recalculate-normals-json job.json report.json
cdmw-mesh-core generate-tangents-json job.json report.json
cdmw-mesh-core morph-apply-json job.json report.json
cdmw-mesh-core cleanup-json job.json report.json
cdmw-mesh-core edit-json job.json report.json
cdmw-mesh-core mesh-editor-session-json job.json report.json
cdmw-mesh-core --version
```

## Session authority

Python keeps durable session, history, output, and archive authority. The
native session owns only the live pointer-critical state. Batch commands keep
their documented Python compatibility paths, but resident-interaction failures
fail closed instead of silently switching mutation authority.

## Compatibility interaction APIs

The following native ABI and D3D11-shaped packets remain compatibility contracts. The
production editor is Rust/wgpu/D3D12: local gestures update an isolated shadow session,
and Python owns validated Finish and output. The retired .NET/Vortice client used the
exported `resident_interaction_abi_v1` in `cdmw-mesh-core.dll` for live
Select/Move/Grab/Smooth/Inflate/Pinch input. ABI v1 exposes identity and struct size
probes plus open, close, sync, snapshot preparation, begin, update, end, cancel,
authoritative decision, and vertex-read operations. Snapshot preparation builds the
stamped screen-space buckets, exact large-element lists, triangle depth BVH, and
adjacency off the pointer handler; stale generations are not published.

Begin/Update/End use typed native operations under a per-session lock and never
construct JSON or call the generic edit dispatcher. Every gesture accumulates against an
immutable Begin baseline, End creates one native history entry, and cancellation
restores that baseline exactly.

### Sparse commit replication

The helper applies and validates the terminal sparse delta locally, refreshes its
`ObjDocument`, normal channels, committed selection, and D3D11 buffers, then
self-accepts the native revision before asynchronously replicating the same immutable
`CDMWMIT2` payload to Python. `resident_interaction_commit_v2` binds the transaction to
session/process identity, monotonic sequence, gesture, base/target revisions, topology,
mapping, length, and SHA-256. Python commits a FIFO durable ledger and replies with a
geometry-free `resident_interaction_commit_ack`; it does not echo helper geometry
through `resident_mutation_batch_v3`.

The helper retains at most 16 unacknowledged transactions or 64 MiB and blocks further
authoring/output until durable state catches up. A transport loss can resend one
byte-identical transaction; a semantic rejection rolls the local leases back and
rehydrates the last durable state without killing the helper. Undo/Redo and
host-originated topology, material, and morph changes continue to resynchronize mesh,
selection, and topology revisions through their existing authority path. That historical
client startup verified the DLL hash, ABI version and contract, header hash, and backend
identity before enabling these controls.

### Resident Edit Mesh protocol

`mesh-editor-session-json` is the resident Edit Mesh protocol. It stores live submeshes,
selection masks, undo/redo history, topology revisions, and sparse delta report sidecars
in C++. `apply` accepts `stroke_phase` (`begin`, `update`, `end`, `cancel`) plus
`stroke_id` for live brush/transform strokes; native history coalesces matching stroke
updates into one undo entry and reports stroke state in the command response. Transform
and brush edits accept D3D11 `screen_drag` payloads with cursor endpoints plus
world-view-projection, source projection overrides, or legacy camera-world/yaw/pitch
fallback fields.

C++ prefers WVP unprojection at the native pivot/brush center; if a WVP payload is
present but cannot resolve, it fails closed instead of using legacy camera math.
Explicit per-source WVP/transform overrides also fail closed for that source if
malformed instead of falling back to the untransformed base WVP. Projected drag payloads
ignore compatibility `translate`/`delta` vectors. Legacy non-WVP callers can still use
camera-world, yaw/pitch, distance/FOV, or explicit units-per-pixel. Brush
`screen_radius` payloads resolve D3D11 pixel radius at the native-derived center using
WVP/source projection data and fail closed on unresolved WVP.

Projected radius payloads also ignore compatibility `center`/`radius`/`amount` scalars
so D3D11 Inflate/Pinch amount stays native-derived; older non-WVP callers still fall
back to camera distance/FOV for world radius and default Inflate/Pinch amount. Vec3
fields still accept both `[x, y, z]` arrays and D3D11-style `{x, y, z}` objects for
compatibility and for legacy brush center/amount payloads.

### Brush weights and screen projection

Resident editor selections can carry brush `weights_binary`/`weights` beside vertex
index groups; when no explicit weights exist, resident vertex selection acts as weight
`1.0`. Brush tools use host-computed weights first, then live `screen_brush`
cursor/radius projection for update/end packets and for non-selection target begin
packets, then resident vertex selection for selection-target begin packets, then
object-space radius falloff. Inflate/Pinch derive center natively from those weights
instead of requiring a D3D11-host `center` field.

This keeps moving D3D11 brush updates from reusing stale begin-stroke resident weights
while letting Smooth/Inflate/Pinch and brush-target Grab begin packets omit
host-expanded groups. Brush-target Grab uses `screen_drag` for movement and
`screen_brush` for weights. `screen_brush` carries cursor coordinates, pixel radius,
viewport, optional camera-world matrix, legacy camera yaw/pitch/distance/FOV, optional
pan, optional source-submesh filter, and an optional flattened D3D11
`world_view_projection` matrix plus per-source WVP or world-transform overrides.

Native projection prefers that matrix before falling back to reconstructed yaw/pitch
camera fields; malformed per-source projection overrides, source-only overrides without
a base WVP for other sources, or projected cursor misses fail closed before object-space
brush-radius fallback. When brush edits carry `selection_depth_mode:"visible"`, native
builds the same resident projection depth mask used by selection and filters hidden
screen-brush vertex weights; omitted depth mode keeps prior xray-compatible behavior.

### Screen selection and depth modes

Resident `select` payloads may also include `screen_brush` plus `falloff` or
`screen_region`. `screen_region` carries rectangle/lasso mode, start/end screen
coordinates, optional lasso points, viewport metadata, optional source-submesh filter,
and optional flattened D3D11 `world_view_projection` matrix. `mesh-editor-session-json
select` resolves matching vertices, edges, or faces from the resident submeshes using
the D3D11 projection matrix and optional `target_mode` before applying the requested
selection operation. When a projected screen selection is present, including
source-specific WVP/transform override arrays, legacy explicit selection groups are
ignored and non-overridden sources do not fall back to legacy camera defaults.

Source-target screen brushes use the D3D11 `world_view_projection` matrix to build an
object-space ray and pick resident source triangles before falling back to
projected-vertex radius picking for older payloads. Edge-target and face-target screen
brushes also ray-pick resident edges/triangles from that matrix for direct cursor hits
before falling back to projected screen distance for brush-radius selection. When
callers send `selection_depth_mode:"visible"`, native builds the resident projection
depth mask and filters hidden vertex, edge, and face hits; omitted depth mode keeps the
prior xray-compatible behavior.

The standalone D3D11 brush picker and rectangle/lasso picker use this path instead of
expanding candidates inside the preview host.

### Selection reuse for Move and Grab

The same `screen_brush` selection object can be inlined as an `apply` selection
for unselected Move begin packets, and unselected Grab begin packets use
`target_mode:"vertex"` with `screen_brush`, so native C++ resolves the initial
screen selection before applying `screen_drag`.
Selected Move and selection-target Grab begin packets omit D3D11 groups when
the service selection signature already matches the resident native selection;
C++ reuses that selection and consumes only the incoming `screen_drag` movement
payload plus Grab strength.

## Geometry operations

`edit-json` owns active Edit Mesh geometry operations: brush sculpt tools
(Grab, Smooth, Inflate, Pinch), Delete, Subdivide, and Refine Smooth. It
returns changed vertices plus topology copy/blend maps so Python can preserve
UVs, normals, bones, and source vertex metadata when applying the native result.

### Tangent generation

`generate-tangents-json` uses the bundled MikkTSpace reference code, reports
face-corner tangent and handedness evidence, and keeps vertex-aligned tangents
when `vertex_storage_safe` is true. When MikkTSpace reports unsafe shared
vertex storage, Python applies a topology split from the face-corner tangent
data so exported vertex-aligned tangents do not average across seams.

### Morph blending and garment fitting

`morph_snapshot_create` optionally accepts `history_undo_count` and
`history_redo_count` to retain the corresponding suffixes of the native history
stacks alongside its owned runtime file. The descriptor reports
`history_captured` and `history_retained_bytes`; the service charges the latter
against its history budget. These snapshots restore only into their source
session, validate the runtime file and resident ownership before mutation, and
release their native history on disposal. Ordinary runtime transfers and drafts
omit the counts and continue to restore with empty native history. Service
history markers behind another full snapshot belong to that snapshot's retained
segment, so trimming the live native stack must not discard them.

`morph-apply-json` blends morph slider delta sidecars and post-edit deltas in C++,
recomputes smooth normals, and writes morphed vertices/normals as binary sidecars so
Python remains a snapshot/fallback bridge instead of the blend loop. Resident Morph &
Refit commands are owned by `src/owners/session_morph_01.cpp`. Surface fitting checks
vertices, triangle edges and interiors, joins coincident seams, preserves nearby layer
separation, and limits local stretching and sharp new creases. Initial garment-facing
guidance helps sleeves wrap around limbs; body-boundary and garment-opening guards limit
that guidance around open necks and thin attachments.

Disconnected garment surface islands participate in layer standoff, links, clearance
and final validation even when they share one Part. Trustworthy coincident seams keep
continuous surfaces together. Body correspondence can cross tiny mismatches between
adjoining Parts using conservative reciprocal boundary-edge matches; ambiguous matches
remain disconnected. Neither change snaps source vertices or changes topology.
`tests/test_mesh_refit_layer_boundaries_native.py` owns the same-Part/separate-Part
parity and shifted-body-seam regressions. `tests/test_mesh_refit_tightening_native.py`
retains fitting, masks, rigid-component, history and atomic-failure coverage.

Full Tightness takes up slack between ordered flexible layers toward their clearance
gap. Intermediate Tightness blends from the followed geometry; zero retains the
original gap. Authored vertex-side evidence distinguishes crossing folds from coarse
outer triangles cutting an inner layer. Surface-less records retained by exclusions
cannot establish a layer. Hard trim retains its authored standoff.
Layer order uses the body's outward direction, including solid belts with inward
back faces. Current surface queries, inner-cloth rays and exact edge/triangle
crossings supply contacts on the outer shell; corrections do not push its support
back into the body. Body clearance takes priority over the nominal cloth gap in
narrow joints. Authored crossing hanging ribbons retain their fold relationships.
For shells initially buried in a larger body, the combined-volume exit solver
retains ownership until body clearance is established; exact layer repair then
also covers the emerged shell.
Uniformly influenced waist bands retain their followed height contour during
conforming and contact correction. Wall depth requires a consistently oriented,
closed surface with measurable volume; duplicated or open skins retain their
flexibility. Wall-aware contact gaps preserve solid bands without treating nearby
rope knots or crossing tails as the backing layer. Nonuniform masks retain their
individual constraints.
New transverse self-crossings on waist bands bind local, two-sided contacts,
including rolled edges on open or repeated skins. Source-adjacent faces and
authored crossings are excluded. Contacts retain the source side and move through
the existing mobility, contour and strain constraints; unresolved crossings refuse
publication. This is not a general cloth self-collision guarantee.

Small inset Flexible details share their nearby band's displacement, retaining
their authored relief rather than independently tightening through the backing.
Adjoining band panels contribute a blended field; free knot ends follow their
attachment, while long hanging panels retain independent following. A common
rotation for each connected detail turns its offset with the fitted backing
without introducing conflicting triangle frames. Compact touching knot islands
share one backing patch and rotation, retaining their construction while the long
cord remains flexible. These links require compatible following, Tightness and
uniform mask influence, and use strictly increasing
backing area to keep dependency chains acyclic. Other cloth panels retain independent
surface fitting. Layer order is inherited from the backing, and contact corrections
act through its controls. The final contact passes refresh exact layer crossings
each time before validation.

Transverse body crossings between the regular vertex, midpoint and centroid samples
add persistent contact samples from both meshes' edge/triangle intersections. Old
locations remain constrained as an intersection moves. Exact body contacts bind
after the broad shape solve, avoiding transient contacts steering already-clear
fits. Body and ordered-layer contacts are refreshed before declaring convergence
and checked again before
publication; unresolved contact retains the previous preview. Refreshed layer normals
must also settle before the solver can finish. Initially buried layers become
eligible for exact layer repair after body clearance, rather than remaining
excluded for the entire fit. Intersecting closed driver volumes can still refuse
a fit; a visually plausible partial result does not establish valid separation.

Body-centred rigid assemblies require a central Flexible join or joins spanning the
centre during fitting. An incidental one-sided overlap cannot steer them. Their
lateral placement uses the retained body frame through rigid body rotation, and the
same motion constraint applies during body and layer contact correction. Tightness,
uniform influence and real attachments retain their authority. Local ornaments
can still follow their backing cloth. `tests/test_mesh_refit_rigid_assemblies_native.py`
owns centring, attachment, rigid-distance and Undo/Redo regressions.

The body and source topology remain unchanged during an initial garment fit. Complex
trim still needs inspection; static clearance is not animation or in-game proof. The
owning focused regression file is `tests/test_native_mesh_editor_morph_refit.py` at the
repository root.

#### Selective following and authored targets

Resident sparse morph fields accept `stage: "base"` (the existing default) or
`stage: "post_refit"`. Body targets compose before garment fitting; per-slider
outfit corrections compose afterward and use the same slider percentage. Unknown
stages are refused. Reset, Bake and runtime snapshots retain the stage semantics.
Corrections are active only for enabled, bound garments. Clearing refit removes
their current displacement while retaining the saved correction fields for a later
bind; it cannot reveal previously masked corrections.

`morph_configure_refit` accepts optional `vertex_masks` rows containing a garment
`submesh_index`, `vertex_indices` and `weights`. A missing mask means full
influence; vertices omitted from a present sparse row have zero influence. Omitting
the argument preserves existing masks. An empty array clears masks on the configured
garments; an empty row protects its entire garment. The least mask value in a
coincident seam cohort governs fitting, clearance and post-refit corrections.

For an atomic multi-Part update, `morph_configure_refit` also accepts
`garment_settings` rows that exactly cover `garment_submesh_indices`. Each row has
`submesh_index` and optional `enabled`, `intensity_percent`, `mode`,
`tightness_percent` and `clearance_percent`; omitted values preserve that Part's
current settings. A row's optional `vertex_mask` preserves its mask when omitted,
clears it when `null`, or
replaces it with an object containing `vertex_indices` and `weights`. Batch rows
cannot be mixed with shared top-level settings or `vertex_masks`. All rows are
validated in a private runtime before one recomposition and history entry. This
allows influence changes, mask clearing and fitting recipes to update a rigid
component that spans several material Parts without an invalid intermediate mask.

`morph_bind` accepts `driver_regions` rows containing a driver `submesh_index`
and allowed `vertex_indices`. Only triangles with all three vertices allowed are
eligible. Invalid, out-of-role or triangle-free regions fail before publication.
Omission selects the whole driver. With `preserve_existing: true`, only the named
garments are rebound; their compatible settings and masks, and all other garments'
bindings, remain intact. `garment_regions` in state and snapshots records the scope
for each garment. Clearance continues to check the complete selected body.
The unchanged-driver check accepts exact baseline coordinates or their exact
float32 publication representation, including after Bake and runtime restoration.
Other driver edits remain blocked before a scoped rebind.

The additional `rigid_component` mode solves one rigid rotation and translation
per connected garment piece and interpolates the rotation for intensity. Clearance
uses one shared translation per piece. Nonuniform effective masks within a piece
are rejected. The original `surface` and `rigid` modes retain their behavior.

Authored capture uses an atomic `morph_upload` extension: `preserve_runtime: true`,
verified `neutral_positions` rows and initial `values`. The command removes the
previous morph layer, restores the supplied neutral coordinates and recomposes the
new profile without an intermediate user-visible reset. Invalid payloads restore
the previous geometry and runtime.

A bounded `morph_state` query can request `include_neutral_positions: true` or
`include_effective_vertex_masks: true` for explicit `submesh_indices`. These
read-only arrays stay in host/native operations and are not duplicated in the Rust
control state. Effective masks come from the same seam-cohort computation as the
fitter, so correction capture can normalize partial influence correctly.

#### Current-fit diagnostics

`morph_state` accepts `include_refit_diagnostics: true` with explicit, unique bound
garment `submesh_indices` (1..128), `diagnostic_sample_limit` (1..4096, default 2048,
at least one per requested Part), and `diagnostic_detail_limit` (1..64, default 24).
The diagnostic result uses schema `cdmw.refit_diagnostics.v1` and carries `session_id`,
native `state_revision`, `edit_revision`, normalized requested Part indices, sampling
counts and work limits. The host adds `shadow_revision` and `host_morph_revision`
under the session export lock so the Rust UI can reject stale results.

The query inspects published current coordinates and neutral authored layer spacing.
`body_clearance` reports unsigned distance and local nearest-face normal offset;
normal offset is not an inside-body test. `layer_spacing` reports recognized layer
gaps and retained authored-gap ratios. Original Part and vertex identities remain
available in the bounded sample details. Body and layer availability are independent;
missing/non-finite measurements are not zero. Interrupted nearest-surface searches
are discarded instead of reporting an incomplete search as a measured clearance.

Limits cover the complete bound fit: 128 Parts, 200,000 vertices, 250,000 triangles
and 256 surfaces. Analysis also limits queries to 32,768, triangle tests to 2,000,000
and node visits to 8,000,000, with a cooperative 2,000 ms analysis budget. Preparation
is input-bounded and does not poll the deadline in every inner operation, so this is
not a hard two-second wall-time guarantee. Reports distinguish partial and unavailable
results and explicitly set `global_collision_proof: false`.

This path does not recompose, publish geometry, change settings or revisions, or
write history. Native/service checks live in `tests/test_mesh_refit_diagnostics_native.py`
and `tests/test_mesh_refit_diagnostics_service.py`; the Rust cache, controls and
rendering checks use `headless_ui_tests::refit_diagnostics`.

Runtime snapshots retain exact neutral and composed coordinates. Restoration
distinguishes a native float32 round trip from an actual compatible geometry edit,
preserving the latter as an edit residual. Legacy snapshots keep their existing
fallback behavior. The service owns target/source identity validation, profile
version 3 persistence, fitting recipe files, and reversible publication.

History memory accounting includes retained neutral/composed coordinates and shared
profile/refit data. Shared allocations are counted once across Undo and Redo, so
large authored workflows observe the existing history memory budget.

### Automatic UV generation

`auto-uv-json` uses bundled xatlas and reports generated UVs, output faces,
vertex remap, chart counts, and topology deltas. Python can apply the output
through undoable Mesh Edit UV commands, and topology-changing output is gated by
an explicit command flag. Its optional `auto_uv.padding` pixel value is passed
to xatlas chart packing; the compatibility default remains zero.
