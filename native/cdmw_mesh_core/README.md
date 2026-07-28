# CDMW Mesh Core

Native mesh editing helper for geometry-heavy Mesh Editor operations.

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
cdmw-mesh-core optimize-json job.json report.json
cdmw-mesh-core import-scene-json job.json report.json
cdmw-mesh-core --version
```

Python keeps the service/session/history boundary and falls back to existing
Python geometry code when this helper is missing or reports an error.
`mesh-editor-session-json` is the resident Edit Mesh protocol. It stores live
submeshes, selection masks, undo/redo history, topology revisions, and sparse
delta report sidecars in C++. `apply` accepts `stroke_phase` (`begin`, `update`,
`end`, `cancel`) plus `stroke_id` for live brush/transform strokes; native
history coalesces matching stroke updates into one undo entry and reports stroke
state in the command response. Transform and brush edits accept D3D11
`screen_drag` payloads with cursor endpoints plus world-view-projection, source
projection overrides, or legacy camera-world/yaw/pitch fallback fields. C++
prefers WVP unprojection at the native pivot/brush center; if a WVP payload is
present but cannot resolve, it fails closed instead of using legacy camera
math. Explicit per-source WVP/transform overrides also fail closed for that
source if malformed instead of falling back to the untransformed base WVP.
Projected drag payloads ignore compatibility `translate`/`delta` vectors.
Legacy non-WVP callers can still use camera-world, yaw/pitch,
distance/FOV, or explicit units-per-pixel. Brush
`screen_radius` payloads resolve D3D11 pixel radius at the native-derived center
using WVP/source projection data and fail closed on unresolved WVP. Projected
radius payloads also ignore compatibility `center`/`radius`/`amount` scalars so
D3D11 Inflate/Pinch amount stays native-derived; older non-WVP callers still
fall back to camera distance/FOV for world radius and default Inflate/Pinch
amount. Vec3
fields still accept both `[x, y, z]` arrays and D3D11-style `{x, y, z}` objects
for compatibility and for legacy brush center/amount payloads.
Resident editor selections can carry brush `weights_binary`/`weights` beside
vertex index groups; when no explicit weights exist, resident vertex selection
acts as weight `1.0`. Brush tools use host-computed weights first, then live
`screen_brush` cursor/radius projection for update/end packets and for
non-selection target begin packets, then resident vertex selection for
selection-target begin packets, then object-space radius falloff. Inflate/Pinch
derive center natively from those weights instead of requiring a D3D11-host
`center` field. This keeps moving D3D11 brush updates from reusing stale
begin-stroke resident weights while letting Smooth/Inflate/Pinch and
brush-target Grab begin packets omit host-expanded groups. Brush-target Grab
uses `screen_drag` for movement and `screen_brush` for weights. `screen_brush`
carries cursor
coordinates, pixel radius, viewport, optional camera-world matrix, legacy
camera yaw/pitch/distance/FOV, optional pan, optional source-submesh filter, and
an optional flattened D3D11 `world_view_projection` matrix plus per-source WVP
or world-transform overrides. Native projection prefers that matrix before
falling back to reconstructed yaw/pitch camera fields; malformed per-source
projection overrides, source-only overrides without a base WVP for other
sources, or projected cursor misses fail closed before object-space brush-radius
fallback.
When brush edits carry
`selection_depth_mode:"visible"`, native builds the same resident projection
depth mask used by selection and filters hidden screen-brush vertex weights;
omitted depth mode keeps prior xray-compatible behavior.
Resident `select` payloads may also include `screen_brush` plus `falloff` or
`screen_region`. `screen_region` carries rectangle/lasso mode, start/end screen
coordinates, optional lasso points, viewport metadata, optional source-submesh
filter, and optional flattened D3D11 `world_view_projection` matrix.
`mesh-editor-session-json select` resolves matching vertices, edges, or faces
from the resident submeshes using the D3D11 projection matrix and optional
`target_mode` before applying the requested selection operation. When a
projected screen selection is present, including source-specific WVP/transform
override arrays, legacy explicit selection groups are ignored and non-overridden
sources do not fall back to legacy camera defaults. Source-target screen
brushes use the D3D11 `world_view_projection` matrix to build an object-space
ray and pick resident source triangles before falling back to
projected-vertex radius picking for older payloads. Edge-target and face-target
screen brushes also ray-pick resident edges/triangles from that matrix for
direct cursor hits before falling back to projected screen distance for
brush-radius selection. When
callers send
`selection_depth_mode:"visible"`, native builds the resident projection depth
mask and filters hidden vertex, edge, and face hits; omitted depth mode keeps
the prior xray-compatible behavior. The standalone D3D11 brush picker and
rectangle/lasso picker use this path instead of expanding candidates inside the
preview host.
The same `screen_brush` selection object can be inlined as an `apply` selection
for unselected Move begin packets, and unselected Grab begin packets use
`target_mode:"vertex"` with `screen_brush`, so native C++ resolves the initial
screen selection before applying `screen_drag`.
Selected Move and selection-target Grab begin packets omit D3D11 groups when
the service selection signature already matches the resident native selection;
C++ reuses that selection and consumes only the incoming `screen_drag` movement
payload plus Grab strength.
`edit-json` owns active Edit Mesh geometry operations: brush sculpt tools
(Grab, Smooth, Inflate, Pinch), Delete, Subdivide, and Refine Smooth. It
returns changed vertices plus topology copy/blend maps so Python can preserve
UVs, normals, bones, and source vertex metadata when applying the native result.
`generate-tangents-json` uses the bundled MikkTSpace reference code, reports
face-corner tangent and handedness evidence, and keeps vertex-aligned tangents
when `vertex_storage_safe` is true. When MikkTSpace reports unsafe shared
vertex storage, Python applies a topology split from the face-corner tangent
data so exported vertex-aligned tangents do not average across seams.
`morph-apply-json` blends morph slider delta sidecars and post-edit deltas in
C++, recomputes smooth normals, and writes morphed vertices/normals as binary
sidecars so Python remains a snapshot/fallback bridge instead of the blend loop.
`auto-uv-json` uses bundled xatlas and reports generated UVs, output faces,
vertex remap, chart counts, and topology deltas. Python can apply the output
through undoable Mesh Edit UV commands, and topology-changing output is gated by
an explicit command flag. Its optional `auto_uv.padding` pixel value is passed
to xatlas chart packing; the compatibility default remains zero.
`import-scene-json` uses bundled ufbx for read-only FBX scene evidence: mesh,
material, texture, rig, and animation counts are reported while Crimson
compatibility remains unmapped until a target asset assignment exists.
`optimize-json` uses bundled meshoptimizer for vertex-cache/overdraw ordering
and opt-in simplification reports. It returns before/after vertex, index,
triangle, cache, overdraw, fetch, and error metrics plus optimized faces; Python
keeps this report preflight-only until an undoable apply path is explicitly
wired.

Related docs: `docs/features/asset-authoring-integrations.md`.
