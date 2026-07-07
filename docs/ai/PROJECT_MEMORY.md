# Project Memory

Last updated: 2026-07-07

## Repo Rules

- Continue the current restructure; do not restart or reset the worktree.
- Preserve unrelated local changes. This repo often has a large dirty tree with
  untracked source/docs/tests, so scope diffs and validation to touched files.
- Keep `cdmw_app.py` and `cdmw/ui/main_window.py` thin. Feature UI belongs under
  `cdmw/ui/<feature>/`, business operations under `cdmw/services/`, pure rules
  under `cdmw/domain/`, and long-running work under `cdmw/workers/`.
- Do not mutate archives directly from UI code. Archive mutation/export safety
  stays outside normal Mesh Editor UI actions.
- Use targeted validation first. `.\scripts\codex_check.ps1 -Area mesh` is
  real-game Mesh Editor proof; broad synthetic/unit coverage is
  `.\scripts\codex_check.ps1 -Area mesh-unit` and should run only at milestone
  gates, not after every native mesh slice.
- Keep `docs/plans/active/` limited to current plans. Superseded, completed,
  handoff, and new-chat bootstrap plans should be deleted rather than left under
  active.
## Native Mesh Editor Rebuild

- Active contract: `docs/plans/active/native-mesh-editor-rebuild.md`.
- Target split: Python/Qt UI and service shell, C++ mesh/texture/preview core,
  optional Blender authoring bridge for workflows beyond Blender-lite editing.
- `ParsedMesh` remains import/export compatibility data, not desired live edit
  storage.
- Normal Edit Mesh runtime should use resident C++ `MeshEditSession` through
  `mesh-editor-session-json`; no silent Python fallback when native core is
  available or required.
- Required runtime ownership in C++ includes live mesh state, selection masks,
  edit tools, topology, undo/redo, live strokes, coordinate transforms, sparse
  preview deltas, UVs, normals/tangents, skin weights, texture hot paths, and
  timing metrics.
- Do not add Rust or C# for this rebuild. They add bridge cost without solving
  the current Python/GIL hot-path problem.
- Texture hot paths use existing `native/cd_texture_dx` DirectXTex integration
  through `cdmw.core.texture_native`. OpenImageIO-style tooling stays optional
  and format/workflow-driven.

## Mesh Runtime Notes

- `ParsedMesh` is still the compatibility parser/export shape. The strict
  rebuild contract starts in `cdmw.domain.mesh.asset`; use
  `cdmw.modding.mesh_asset` to convert parser output and
  `tools/mesh_pipeline.py inspect|roundtrip|export|import|validate|rebuild` for
  UI-free MeshAsset inspection, no-edit rebuild diff reports, sidecar package
  export/import, validation, and gated rebuild reports. MeshAsset
  conversion from a parsed mesh inspects original bytes when no layout is
  supplied, so UI/service file sessions keep PAC LOD section ranges instead of
  only CLI inspect paths. MeshAsset `skeleton_info` and OBJ sidecars
  report inferred skinning facts; file-loaded MeshAsset sessions may use the
  original inferred bone count to validate preserved skinning, but linked
  skeleton metadata is still required for real skeleton authoring. Use
  `cdmw.modding.mesh_importer.rebuild_mesh_with_report()` when callers need
  source/rebuilt hashes, changed byte ranges, and edited-scope metadata; UI
  paths should go through `MeshService.rebuild_report()` so validation gates the
  in-memory rebuild first. Final file writes should go through
  `MeshService.rebuild_asset()`, which uses the same validation gate and refuses
  to overwrite the original source path. Standalone UI runs both paths through
  `MeshRebuildReportWorker` from the Rebuild panel, can preview the last rebuilt
  file through the archive import-preview flow or send it to the archive
  package/patch flow when an archive target is present, and can save the last
  report as JSON without rerunning rebuild work.
  Standalone UI editable-package Export
  and Import buttons run through `MeshEditablePackageExportWorker` and
  `MeshEditablePackageImportWorker`; import replaces the working mesh through
  `MeshService` and reruns validation before rebuild state changes. The adjacent
  Open button opens `mesh_editor/last_editable_package_dir`. The Checks panel
  Run button uses `MeshExportValidationWorker` to refresh validation off the UI
  thread, and Copy copies `standalone_last_export_validation_report` as JSON
  instead of scraping displayed tree rows.
- Export validation preserves skinning by default: changed bone indices or bone
  weights against the original mesh block rebuild unless a later explicit safe
  skinning operation/rebuild rule is added.
- Export validation preserves material identity by default: changed material
  slot counts, material slots, or texture references against the original
  session mesh block rebuild unless a later explicit safe material
  operation/rebuild rule is added. OBJ sidecars prefer exact attached MeshAsset
  material slots when available instead of rebuilding slot metadata from visible
  submeshes.
- Export validation preserves unknown metadata by default: changed MeshAsset
  unknown sections or submesh `unknown_fields` against the original session mesh
  block rebuild.
- Export validation preserves original vertex stride by default: changed or
  dropped submesh source/original vertex stride against the original session
  mesh blocks rebuild. OBJ sidecar import merges strict LOD metadata into
  matched submesh entries so native-manifest packages carry stride evidence
  back into validation.
- MeshAsset rebuild validation preserves raw vertex records by default: dropped
  or changed raw records block rebuild so source bytes remain available for
  metadata-preserving patching.
- Export validation preserves source offsets by default: changed or dropped
  source vertex offsets, source index offsets/counts, or source descriptor
  offsets against the original session mesh block rebuild. OBJ sidecar import
  reconstructs vertex offsets from original vertex offset, stride, and source
  vertex map.
- Imported OBJ rebuilds validate sidecar source hash/size and topology counts;
  `allow_topology_change=false` still permits OBJ vertex splits only when the
  source vertex map covers the same original vertices. Skinned OBJ sidecars must
  include per-submesh `bone_layout` metadata and complete `source_vertex_map`
  rows at import. Strict LOD sidecars must include a complete inline
  `source_index_map` for indexed submeshes. OBJ sidecars also carry raw vertex
  record count/stride/SHA-256 evidence when source bytes and offsets are
  available; source identity validation recomputes those hashes from the
  current source asset before rebuild. They also include MeshAsset
  LOD section identity and unknown-section range evidence when parser layout
  recovery exposes it, plus JSON-safe unknown submesh fields restored on OBJ import. OBJ material-name and MTL
  texture-path drift from the sidecar are stored as sidecar warnings and
  surfaced by export validation. Same-count
  OBJ sidecar imports also attach explicit Mesh Editor v2 operations for
  position, normal, and UV0 replacement when the sidecar vertex count still
  matches; `allowed_edit_operations` can reject those before rebuild. Rebuild
  reports include the attached operation list and use validated operation
  targets as edited-scope fallback when original bytes cannot be parsed for
  channel diffing. Direct rebuilds reject invalid attached operations before
  running a builder, and operation-required paths block original-to-edited
  channel changes that are not covered by the attached operation list. When
  original bytes parse, direct builders receive original mesh data with only
  validated operation channels copied from the edited mesh. Built-in same-count
  transform/brush/normal/tangent/UV actions append undoable operation entries.
  Same-count and transform-style operation validation requires a complete
  `source_vertex_map` for the target submesh. `MeshService.replace_working_mesh()`
  rejects OBJ sidecar source hash/size mismatch before mutating the session.
  Material-name and texture-path sidecar drift remains previewable as warnings
  but blocks final rebuild by default. Imported OBJ sidecar rebuilds also
  require an explicit attached operation list.
- Editable package export now writes `mesh.glb` as the primary interchange and
  `mesh.obj` as the secondary format. Package import prefers sidecar GLB, falls
  back to OBJ, and aliases `mesh.cdmeta.json` back to the selected mesh sidecar
  when external editors keep only the package-level metadata. Visual-only GLB
  without that sidecar remains blocked from rebuild.
- Mesh Editor developer rebuild override is settings-only:
  `mesh_editor/developer_mode=true` plus
  `mesh_editor/developer_rebuild_override=true`. It can only force a separate
  output rebuild past parser-confidence/no-op round-trip blockers and writes
  `developer_overrides` plus `developer_override_blocker:*` warnings into the
  rebuild report; normal topology/sidecar/skeleton/material/operation blockers
  still fail closed.
- The first .NET Mesh Editor experiment path is an external process launched
  from standalone Mesh Editor or the embedded replacement-builder Mesh Editor
  toolbar; active follow-up plan is
  `docs/plans/active/embedded-dotnet-mesh-editor.md`, which embeds that process
  inside `Edit Mesh`, adds solid/textured display with optional wire overlay,
  and requires toggling Edit Mesh off to import the .NET-edited mesh before
  restoring the textured preview. The `.NET` button reads
  `mesh_editor/dotnet_experiment_executable`,
  `CDMW_MESH_DOTNET_EXPERIMENT_EXE`, or bundled
  `cdmw-mesh-dotnet-editor.exe`, then uses
  `MeshDotNetExperimentPackageWorker` to export an OBJ sidecar handoff package
  and launches the process with package/status/output/edit-operation paths.
  `tools/dotnet_mesh_editor_experiment` is the current WinForms wireframe
  prototype; `build_pyside6_app.ps1` publishes it into
  `native/cdmw_mesh_dotnet_editor/build/<Config>` for PyInstaller bundling.
  `MeshService.working_mesh(clone=True)` preserves MeshAsset validation metadata
  through native-snapshot clones, so .NET handoff sidecars keep PAC LOD section
  offsets/sizes and do not trip `lod_identity_changed` on reimport.
  When it exits with edited OBJ output, `MeshDotNetExperimentOutputImportWorker`
  imports through the sidecar path, replaces the working mesh via
  `MeshService.replace_working_mesh()`, syncs embedded launches back into the
  replacement preview, and reruns export validation before rebuild can be
  enabled. Embedded replacement D3D11 load status surfaces FPS/frame-time when
  native status reports it. Each run writes `dotnet_evaluation.md`. Python/C++
  still own parsing, validation, rebuild, and archive/package writes. .NET
  output import now fails closed when `edit_operations.json` is missing or empty,
  edge selections include stable descriptors plus `topology_generation`, D3D11
  reports present/dirty-to-present/device-loss metrics, and release packaging
  runs `scripts/release_preflight.py` to block generated output or unclassified
  untracked source.
  The first embedded .NET slice passes `--embedded --parent-hwnd`, refuses an
  embedded launch if no Qt preview host HWND is available, runs WinForms
  borderless as a child window, resizes it to the host, and lets
  `mesh_editor/use_embedded_dotnet_viewport` start .NET from `Edit Mesh` while
  preserving the existing D3D11 route as rollback. The WinForms viewport now
  defaults to solid shaded mesh with optional wire overlay and auto-saves edited
  embedded sessions on close so the existing output import path can sync the
  edited mesh back into the builder. The second embedded slice adds an NDJSON
  protocol over `QProcess` stdin/stdout: .NET sends ready/metrics/selection,
  stroke, command, save, and error events; Python sends session state,
  selection updates, preview vertex/triangle updates, command results, and close
  requests. .NET emits `selection_depth_mode=visible` by default and `xray` only
  when its X-Ray toggle is on. Live selection/stroke/topology/history commands
  route back through `MeshEditorController`/`MeshService`; copy/paste is still
  disabled except for the existing Duplicate command until metadata-preserving
  paste is proved. If embedded .NET closes without an edited OBJ because live
  edits were already applied by Python/C++, the builder syncs from the current
  Python/C++ working mesh instead of restoring the pre-edit preview. .NET
  applies incoming vertex preview updates, including binary descriptors, and
  refreshes topology preview groups for display; topology sidecar save remains
  Python/C++ authoritative.
- `MeshService` owns edit-session mutation and routes supported native-session
  actions through `cdmw/modding/mesh_native_core.py`.
- `MeshEditCommandWorker` is the unified async worker for Mesh Editor commands;
  it receives immutable `MeshEditCommand` payloads and injects `stop_event`.
- `MeshEditorController` should stay a thin adapter over `MeshService`.
- Standalone and embedded Mesh Editor surfaces should share the same service and
  native-session command path.
- Standalone D3D11 Move/Grab/Smooth/Inflate/Pinch strokes are wired from host
  signals to native-session `transform`/`brush` commands with `stroke_phase` and
  `stroke_id`.
- `MeshService` tracks resident native selection signature and active stroke id.
  Live-stroke update/end/cancel packets reuse C++ session selection when the
  signature and stroke id match.
- D3D11 Move/Grab updates omit redundant candidate groups once a matching stroke
  id is active. Move begin with existing resident vertex/edge/face/source
  selection and selection-target Grab begin now omit D3D11 groups too;
  `MeshService` reuses resident C++ selection on `begin` when the Python-side
  selection signature matches the native session. Move or Grab begin with no
  resident selection carries `screen_brush` as native screen selection, so C++
  resolves the initial transform/brush selection. Brush-target Grab and
  Smooth/Inflate/Pinch begin and update packets carry `screen_brush`,
  `target_mode`, and
  `selection_depth_mode` instead of host-recomputed groups; resident C++ chooses
  selection weights for selection-target strokes, screen-brush weights for
  brush-target strokes, and native visible-depth filtering when requested. The
  D3D11 host no longer keeps a per-drag candidate cache or stroke-group JSON
  serializer for active screen strokes; non-Mesh-Edit source hover/click paths
  still use the legacy `source_part_at` projection.
- D3D11 non-selection Remove (`delete_mode=live` or `release`) begin/update
  packets carry `screen_brush`, `target_mode=face`, and `selection_depth_mode`
  without host-expanded groups. Live Remove forwards that as
  `_native_screen_selection_payload` to resident native Delete on each update;
  release Remove accumulates native `select` hits and deletes the resident C++
  face selection on mouse-up.
- D3D11 brush candidate weight sidecars are preserved as native selection
  weights. Resident C++ brush tools consume explicit host weights first, then
  live update/end `screen_brush` projection weights, then object-space radius
  falloff.
- D3D11 Move/Grab `screen_drag`, Inflate/Pinch `screen_radius`, and brush
  `screen_brush` packets carry D3D11 WVP plus active per-source world
  transforms through Qt/service. The D3D11 host owns preview-package
  normalization from `manifest.json`: for native Mesh Core source-space edit
  groups it applies source-to-preview normalization before updating live
  vertices/triangles, and it composes source-to-preview normalization before
  alignment transforms when emitting `source_submesh_world_transforms`;
  resident C++ composes source transforms,
  derives brush center from native weights when needed, resolves pixel radius/amount, and
  ray-picks/projection-weights from WVP. Current D3D11 packets no longer
  serialize `camera_world`, yaw/pitch, pan, distance, FOV fallback fields, or
  Inflate/Pinch `center`; unresolved base/source WVP, projected screen-brush
  misses, and stale projected drag/radius scalars fail closed instead of legacy
  camera/object-radius fallback. Legacy vectors/camera fallbacks remain only for
  non-WVP callers; explicit D3D11 weights still win.
  Standalone and embedded Python forwarding strips legacy screen camera/FOV
  fields from incoming D3D11 screen payloads before dispatching native commands;
  `MeshService` strips the same fields again when building native edit payloads
  and when merging native screen selection payloads.
- Standalone D3D11 brush-selection events carry `screen_brush`, `target_mode`,
  `selection_depth_mode`, operation, and falloff through `MeshEditorTab`/
  `MeshService` into resident C++ `select`; C++ expands vertex/edge/face/source
  masks, ray-picks edge/face/source hits from D3D11 WVP where applicable,
  applies native visible-depth filtering, ignores leaked projected-selection
  groups, and Qt pushes native selection back to the host overlay. Mesh Edit
  source-part clicks use the same native source `screen_brush` path;
  source-part context uses that path too, native misses preserve selection, and
  Mesh Edit hover clears stale source hover without host
  projection.
- D3D11 native-screen tools draw the cursor ring without doing host-side hover
  candidate/ray expansion. Existing selected geometry still renders from
  returned selection groups; the old D3D11 vertex/edge/face hover candidate
  projectors are removed, and brush/selection/remove hit resolution stays in the
  resident native path.
- Standalone D3D11 rectangle/lasso selection events carry `screen_region`
  through the same Qt/service/native `select` path. Region payloads include
  start/end coordinates, optional lasso points, source filters, viewport,
  and WVP; C++ expands masks/depth filtering from resident mesh.
- Archive-browser/static replacement D3D11 selection-change callbacks route
  `screen_brush`/`screen_region` through `StaticReplacementMeshEditSession.select`,
  copy the resolved `MeshEditSelection` back into UI state, and sync that state
  to the D3D11 overlay. Native screen-selection failures or unavailable native
  core report an error instead of legacy `groups` or Python selection fallback.
- `mesh-editor-session-json` uses an inline report path over the persistent
  `cdmw-mesh-core --service` pipe. The temp `job.json`/`report.json` protocol
  remains for other native jobs and compatibility fallback.

## Current Handoff Points

- Resident native topology commands set `suppress_vertex_remap_report`; C++ still
  returns topology buffers, attributes, preview triangle groups, and changed
  vertex ranges/binary descriptors.
- Same-submesh native topology commands keep the resident C++ session
  authoritative and defer Python `ParsedMesh` topology sync until
  `working_mesh()` is requested. `session_view()` uses cached native counts while
  dirty and now fails if those native counts are missing. `MeshService.apply_command()`
  also uses cached dirty counts for topology comparisons and does not clear
  Python tangent arrays while resident C++ topology is dirty.
- Native `MeshService.apply_command()` actions without explicit command
  selection reuse the resident session selection instead of pruning it through
  Python `working_mesh()`. Non-native/legacy paths still prune Python selection
  before dispatch.
- Defer eligibility is derived from the native-session topology action set, so
  mirror/extrude/inset/loop cut/edge split/merge/weld/bridge/fill stay resident
  too.
- Dirty same-submesh topology undo/redo stays resident: service undo/redo skips
  pre-history export, calls native history first, keeps cached dirty counts for
  defer-eligible reports, and hydrates Python only when `working_mesh()` is
  requested.
- C++ session reports surface `preview_triangle_group` descriptors through
  `MeshEditResult.native_preview_triangle_groups`. The controller uses those
  groups directly for same-submesh and append topology refresh without calling
  `working_mesh()`.
- Native topology results also carry `MeshEditResult.submesh_counts`, so
  embedded/static replacement status math uses C++ counts instead of hydrating
  dirty Python `ParsedMesh` topology. If deferred native topology lacks preview
  triangle groups, `MeshEditorController.native_update_for_result()` raises
  instead of rebuilding preview triangles from Python mesh state.
- Native material assign/copy reports now emit C++ `preview_triangle_group`
  descriptors for material-only submesh updates and material undo/redo. The
  controller consumes those groups before `working_mesh()` and sends default
  material override reset values from native report metadata, so stale D3D11
  overrides are cleared without Python preview rebuild.
- Native transform/brush/normal/UV reports now carry
  `MeshEditResult.native_preview_vertex_update_groups`; the controller consumes
  those descriptors before `working_mesh()` and raises if native changed-vertex
  results lack a preview payload. Flip normals emits a native triangle preview
  group for face-order changes.
- Native affected-submesh results now fail closed before `working_mesh()` if
  they carry native editor metrics but no preview payload. `generate_tangents`
  is the explicit no-preview exception because the current D3D11 update path
  does not consume tangent buffers.
- Active native command results now also fail closed before `working_mesh()` if
  affected vertices/submeshes/topology are present but native preview payloads
  are missing, even when a malformed synthetic result lacks native timing
  metrics. Active native no-op results also return an empty native update before
  `working_mesh()`.
- Standalone native preview delta application marks the preview stale instead of
  calling `_refresh_standalone_preview()` when the D3D11/native update target is
  unavailable or rejects the delta; active edit updates should not rebuild the
  Qt/Python preview as a hidden fallback.
- Static-replacement adapter results now fail before `working_mesh()` if
  `submesh_counts` are missing, including deferred native results with
  `python_apply_deferred=1.0`; active native edits must carry the shared
  count/result shape.
- Static replacement uses `StaticReplacementMeshEditSession.sync_working_mesh()`
  only at explicit boundaries such as leaving Edit Mesh or Reset Scope. This
  hydrates resident native edits back into the compatibility `ParsedMesh` before
  Python preview/texture rebuilds or base-source resets.
- Embedded/static replacement callbacks route result mesh storage through the
  deferred-native guard. When `python_apply_deferred=1.0`, callbacks keep the
  resident/native state authoritative and native undo/redo applies D3D11 preview
  payloads or raises instead of replacing the working mesh with stale Python
  `ParsedMesh` data.
- Static-replacement background edit workers use
  `StaticReplacementMeshEditSession.submesh_counts` for status math instead of
  hydrating `session.controller.working_mesh()` before dispatch.
- `MeshService.apply_command()` refuses non-native geometry dispatcher actions
  except explicit legacy display cleanup, so new domain actions cannot silently
  fall through to Python mesh mutation.
- `MeshService` derives native-required edit actions from shared
  `MESH_GEOMETRY_ACTIONS` and subtracts only explicit legacy display cleanup.
  The UI `NATIVE_EDITOR_SESSION_COMMANDS` gate is now derived from
  `MESH_EDIT_ACTIONS` with only mode/select/display-cleanup excluded, so new
  topology/geometry tools route native by default instead of drifting into
  Python or missing controller payload guards.
- Native apply and native undo/redo reports in `MeshService` use complete
  submesh counts as the shared active result shape, mark Python mesh state dirty,
  and defer hydration to explicit mesh read/export; the old Python report
  applier bridge export has been removed.
- Dirty native geometry edits chain in the resident C++ session. A second native
  geometry edit must not call `export_native_mesh_editor_session_to_mesh()` just
  to refresh Python state first.
- Static-replacement native brush/transform results are delta-only: `result.mesh`
  can remain a stale compatibility mesh, and callers must use native preview
  update payloads for active geometry changes.
- Embedded static-replacement status totals use cached native `submesh_counts`
  from deferred native results instead of recomputing totals from stale
  `ParsedMesh` geometry.
- Deferred native live edits in embedded/static replacement require an accepted
  native preview payload. Missing/rejected payloads raise before Python queued
  live vertex preview fallback can run.
- Embedded action-bar native non-topology results also route through that
  preview-payload gate before live-triangle refresh fallback.
- Embedded/static preview model refresh treats cached native `submesh_counts` as
  dirty native state. D3D11 paths may defer the Qt preview model, but Python
  `parsed_mesh_to_preview_model()` rebuild fallback raises instead of hydrating
  stale compatibility mesh data.
- Static preview refresh/rebuild, texture/texture-UV refresh, transform refresh,
  and stale-reload queues now block while Mesh Edit is enabled on the active
  Mesh Edit tab, record `mesh_edit_static_preview_*_blocked` events, and report
  that native D3D11 preview payloads are required instead of silently scheduling
  Python static preview work.
- The shared `_safe_refresh_static_dialog_preview(live_mesh_edit=True)` helper
  also blocks active Mesh Edit before Python static preview rebuilds, so restore
  and snapshot paths cannot resurrect the synthetic preview fallback.
- Embedded/static topology commits apply `MeshEditorNativeUpdate` before legacy
  triangle replacement. Deferred native topology without an accepted preview
  payload must raise instead of generating triangles from Python mesh state.
- Embedded/static live-triangle refresh also fails closed while Mesh Edit is
  active and D3D11 native refresh is unavailable; non-active static replacement
  preview remains the only path that may queue a Python static rebuild.
- Embedded/static Delete, Subdivide/Refine, Split, and action-bar native commit
  callbacks apply native preview payloads before Python preview-model rebuild,
  then use live-triangle fallback only when the native update was not applied.
- Embedded/static stroke commits with a native result apply the returned native
  preview payload before Python totals/model refresh, and skip Python preview
  rebuild when the native update is accepted.
- Embedded/static active stroke finish also skips compatibility-mesh normal
  recompute, morph-delta capture, Python preview rebuild, and final live-preview
  fallback after any native live preview payload was accepted during the stroke.
- Embedded/static active stroke finish now also fails closed when D3D11 native
  refresh is inactive instead of queuing a static Python preview rebuild.
- Embedded/static morph-slider apply fails closed while Mesh Edit is active
  before Python morph-slider mesh mutation or static preview rebuild can run;
  non-active static replacement keeps the legacy morph-slider path.
- Embedded/static D3D11 live vertex and triangle refresh paths stop before
  Python-generated preview groups when native group generation misses; the
  existing stale-preview path handles the failure instead of rebuilding group
  geometry from transformed compatibility meshes.
  Static-replacement Python live vertex and triangle preview packers are
  native-required by default; old Python geometry packing runs only with
  explicit legacy opt-in.
- Embedded/static source-part, copied-original, selected-part enable, and
  geometry-history restore preview helpers fail loudly while Mesh Edit is active
  if native D3D11 refresh is unavailable. Static-replacement Python preview
  rebuilds remain available only outside active Mesh Edit.
- Embedded/static source-part topology mutations (delete, duplicate, imported
  append) fail before Python `ParsedMesh` submesh mutation while Mesh Edit is
  active; non-active static replacement keeps the legacy source-part path.
- Embedded/static copied-original append also fails before Python `ParsedMesh`
  submesh mutation while Mesh Edit is active; non-active static replacement
  keeps the legacy copied-original path.
- Embedded/static selected-source transform/enable adjustments, including
  alignment nudge/D3D11 part transforms, source include/exclude tree toggles,
  source routing target/role changes, and advanced mapping edits, fail before
  Python source-part, routing, or role mutation while Mesh Edit is active;
  non-active static replacement keeps the legacy adjustment/routing path.
- Embedded/static complete-swap material routing fails before Python mapping
  generation, undo snapshots, texture override clears, or preview/material
  refresh queues while Mesh Edit is active; non-active static replacement keeps
  the legacy complete-swap routing helper.
- Embedded/static source-part grouped material routing fails before Python
  texture-set regrouping, undo snapshots, manual texture override clears,
  mapping rewrites, or material-plan refresh while Mesh Edit is active;
  non-active static replacement keeps the legacy grouped-routing helper.
- Embedded/static native Split/Duplicate results keep C++ topology authoritative
  for new source parts. Python updates appended/selected source UI bookkeeping
  only and no longer copies `StaticSourcePartAdjustment` records onto the new
  source after native topology completes.
- Embedded/static native undo/reset/delete-empty flows no longer mutate
  `StaticSourcePartAdjustment.enabled` after active Mesh Edit results. Source
  enable-state restore attempts now report that native part-state execution is
  required instead of silently changing Python adjustment records.
- Embedded/static source-part geometry actions for work-area normalization,
  fit-size, nudge, and center-on-target also fail before Python `ParsedMesh`
  vertex or adjustment mutation while Mesh Edit is active; non-active static
  replacement keeps those legacy routing helpers.
- Embedded/static source material role/glow overrides fail before Python
  `source_part_adjustments` or `source_role_overrides` mutation while Mesh Edit
  is active; the shared glow/export flush helper is guarded too, so direct glow
  checkbox, selected-part role/reset/remove, or export-flush callers cannot
  mutate Python adjustments while active. Non-active static replacement keeps
  the legacy material override helper.
- Embedded/static selected-source material tuning (brightness, contrast,
  saturation, gamma, tint) also fails before Python adjustment mutation or
  material preview refresh while Mesh Edit is active; non-active static
  replacement keeps the legacy material tuning helper.
- Embedded/static copied-source texture routing actions now fail before Python
  copied-texture intent/disabled-set mutation or texture preview refresh while
  Mesh Edit is active; non-active static replacement keeps those legacy texture
  routing helpers.
- Embedded/static donor material routing actions now fail before Python donor
  material plan mutation, texture dirty flags, or texture preview refresh while
  Mesh Edit is active; non-active static replacement keeps the legacy donor
  material helper.
- Embedded/static added-part texture override actions now fail before Python
  source-material texture override mutation while Mesh Edit is active; the
  shared added-part texture override helper is guarded too, so direct helper
  callers cannot bypass the UI callback guard. Non-active static replacement
  keeps the legacy added-part texture helper.
- Embedded/static texture table override actions now fail before Python texture
  override assignment mutation while Mesh Edit is active; non-active static
  replacement keeps the legacy texture table helper.
- Embedded/static live-preview refresh now also blocks while Mesh Edit is active
  and native D3D11 commands/preview are unavailable, instead of falling through
  to Python Qt preview rebuild.
- Embedded/static D3D11 restore/cancel snapshot paths mark the Python preview
  model dirty and refresh native live triangles directly instead of rebuilding
  `parsed_mesh_to_preview_model()` before the D3D11 update.
- Embedded/static undo/redo history restores with native preview payloads apply
  the native D3D11 update before Python preview-model rebuild and skip the
  rebuild when the update is accepted.
- Embedded/static direct edit dispatch now requires the static resident native
  session; the old injected/direct `apply_static_replacement_edit` callback
  fallback is removed from active callbacks.
- Embedded/static sparse vertex history restores that succeed through native
  restore skip morph delta capture and Python preview-model rebuild while D3D11
  preview is active; they mark the preview model dirty and push live deltas.
- Embedded/static Reset Scope and Full Reset require native base-submesh
  restore; Python `copy.deepcopy(base_source)` geometry fallback is disabled in
  active callbacks.
- Embedded/static Reset Scope first syncs any dirty resident native edit session
  into Python state, then native-restores the scoped base submeshes and clears
  the old resident session so a later toggle-off cannot re-export stale pre-reset
  geometry. Live D3D11 triangle replacement refuses to send empty groups for
  non-empty sources; missing groups mark the preview stale instead of clearing
  the mesh in-place.
- Embedded/static undo and live-stroke base snapshots require native submesh
  snapshots; active callbacks no longer clone full `ParsedMesh` snapshots when
  native snapshotting is unavailable.
- Embedded/static normal recompute failures no longer import
  `recompute_submesh_normals` in active callbacks; Python normal recompute is
  reported as disabled instead of mutating stale compatibility meshes.
- Embedded/static morph-slider bake uses native submesh snapshot/restore for
  the baked base mesh and no longer falls back to full Python mesh clone.
- Embedded/static sparse history current/restore failures now fail closed in
  active callbacks; Python sparse vertex scan/restore mutation is disabled.
- Static geometry history sparse restore and normal recompute also fail closed
  after native failure; they no longer mutate Python vertices or normals.
- Static geometry history full-state restore also fails closed while Mesh Edit
  is active after sparse native restore misses; Python source/material/texture
  state replay is disabled until native history owns that state.
- Standalone D3D11 native stroke dispatch rejects move/vertex begin/update
  packets without `screen_drag` and no longer converts missing drag payloads
  into Python `translate`/`delta` vectors. End/cancel packets may omit
  `screen_drag` only to close an existing native stroke.
- Embedded/static native screen/descriptor strokes raise before the Python
  preview-to-source inverse-transform branch when native update payload data is
  missing. The inverse path is legacy-only, not active native stroke fallback.
- Embedded/static active stroke updates delete the old scalar preview-to-source
  edit branch entirely; exported inverse helpers are fail-closed compatibility
  stubs and are no longer injected into active static dialog callback context.
- Embedded/static Move, Vertex, and Grab screen-drag preview packets now enter
  the resident native stroke lifecycle: first drag packet sends native
  `begin`, later packets send `update`, and mouse-up sends native `end`. The
  embedded path reuses resident C++ selection after the first packet instead of
  replaying each drag as an independent native edit.
- `StaticReplacementMeshEditSession.open()` keeps the incoming compatibility
  `ParsedMesh` for display/import state instead of hydrating through
  `controller.working_mesh()` immediately after native session open.
- Static-replacement adapter results raise on missing counts, including
  deferred-native results, instead of hydrating through
  `controller.working_mesh()`; active native/static results must carry
  `submesh_counts`.
- Standalone mesh file open paths pass the already-loaded `ParsedMesh` to UI
  display, including async `MeshFileSessionLoadWorker`, instead of hydrating via
  `controller.working_mesh()` after native session open.
- `MeshEditorController.native_update_for_result()` no longer calls
  `working_mesh()`. Python mesh-based preview packing is isolated behind the
  explicit archive-only `legacy_python_update_for_result(...,
  allow_archive_legacy_preview_rebuild=True)` helper.
  Triangle, vertex-update, and selection-overlay preview group helpers are
  native-required by default; Python group generation requires explicit legacy
  opt-in.
- Mirror/Duplicate/Separate append topology defers Python sync when native
  reports have complete counts and preview groups. Export snapshot summary
  discovery hydrates appended native submeshes only when Python mesh state is
  explicitly requested.
- Native `select` reports carry `selection_groups` with C++-expanded overlay
  source vertices/edges/faces. `MeshEditResult.native_selection_groups` feeds
  the controller before any `working_mesh()` access, and resident native select
  results fail closed if a non-empty selection lacks native groups. Plain active
  `select` now returns an error when the native core is unavailable instead of
  applying Python selection fallback.
- Embedded D3D11 selection sync is selection-group-only: missing group sender,
  build errors, or host rejection record an event and return false instead of
  expanding source selection through legacy `set_mesh_edit_vertex_selection`.
  Non-empty selections with empty native group output also fail closed instead
  of clearing the D3D11 overlay.
  `mesh_edit_selection_groups()` is native-required by default; Python
  selection-overlay generation requires explicit legacy opt-in.
  Non-D3D Qt preview widgets still use their legacy vertex selection display.
- UV region/lasso selection is native-required. `select_native_mesh_uv_vertices`
  performs native UV hit testing, then `MeshService` applies the resulting
  vertex mask through the resident native `select` path; it no longer calls
  Python UV selection or Python selection-operation helpers for active UV
  selection.
- Selected skin-weight adjust/normalize/transfer controls now require a native
  target submesh session. If native returns no result, cannot hydrate the target
  session, or is unavailable, the active Mesh Editor raises instead of sending
  Python target vertices/bones or mutating Python bone indices/weights.
- Embedded/static replacement selection actions fail closed when native
  selection is unavailable. Active Select Whole Part, Invert, Grow, Shrink, and
  Smooth no longer call cached Python vertex-expansion helpers.
- Dirty resident native sessions use C++ `mesh-editor-session-json summary` for
  workspace summaries. Dirty UV summary intentionally raises until a resident
  native UV-summary path exists, avoiding stale Python `ParsedMesh` reads.
- Topology reports copy current native submesh material metadata before report
  serialization, so same-submesh triangle groups drive D3D11 material override
  groups without Python material preview rebuilds.
- Resident normal edits include `preview_vertex_output_path` in C++ session delta
  payloads, so recalc/copy normal preview updates return binary
  position/normal/UV descriptors instead of inline Python arrays.
- Resident auto-UV runs xatlas inside native `uv_transform` apply when
  `auto_uv` is true. C++ updates resident session/history and emits generic
  mesh-edit reports for topology/index-buffer changes or UV buffers for
  vertex-aligned changes; standalone Auto UV sends `allow_topology_change=True`
  directly and no one-shot Python `working_mesh()`/report preflight is used.
- Native topology history clears selection for destructive Delete, but
  duplicate/non-destructive topology edits keep/prune valid selection context so
  undo/redo restores the correct mode and selection payloads.
- Native submesh snapshot metadata strips transient preview/history attrs to
  prevent stale topology descriptors after dirty native history hydration.
- Resident native export owns material `extra_attrs`: exported summaries and
  snapshots copy native attrs when present and clear stale Python attrs when
  absent. Resident normal edits update native normals/faces and invalidate
  tangents; resident tangent edits update or clear native tangent buffers.
- Active resident apply forwards `native_selected_vertices_binary_by_submesh`
  into native selection payloads as per-submesh `selected_vertices_binary`
  descriptors; the old Python one-shot delete/brush/transform helpers must not
  be required for binary selection edits.
- Resident native face selection maps explicit/editor face ids through
  `source_face_indices` when malformed faces were compacted, so selecting an
  invalid original face id no-ops instead of targeting compact face offset 0.
- Resident native `delete_parts` removes selected source submeshes from C++
  session state and history directly; Python accepts sparse native submesh ids
  in returned count summaries and hydrates/export snapshots from native state.
- Resident native UV edits update C++ UV storage and clear tangents/signs there,
  so export/hydration cannot reuse stale generated tangents after UV mutation.
- Resident native transform honors `recompute_normals`: C++ preserves resident
  normals when false, recomputes resident normals when true, and clears resident
  tangents/signs after vertex edits. Python only reports tangent invalidation
  from the stale compatibility mesh while native state is dirty; it must not
  clear those arrays before explicit hydration.
- Dirty resident texture-target queries use native session summary metadata
  instead of pruning or reading the stale Python `ParsedMesh`.
- Dirty resident compare, skeleton/skin-weight, and pose-preview queries fail
  closed instead of syncing, pruning, cloning, or mutating stale Python
  `ParsedMesh` state. Export/explicit mesh reads remain the hydration boundary.
- Clean pose preview deformation and deformed-normal recompute are native-required
  too. If native pose preview or native normal recompute returns no result, the
  active Mesh Editor raises instead of showing an unchanged clone or recomputing
  normals in Python.
- Standalone Mesh Editor preview package creation fails closed when native
  geometry or pose-preview payload generation is unavailable or blocked; Python
  reference and empty-preview builders are removed from active payload helpers.
- Standalone Qt preview refresh now also fails closed while resident C++ mesh
  state is dirty. Edited/ghost preview refresh clears with a native-D3D11-required
  message instead of rebuilding from Python; source-only compare remains allowed.
- Dirty resident skeleton controls also fail before mutating Python-side
  skeleton, pose, or animation state, so a failed dirty-native summary cannot
  leave UI metadata half-applied.
- Dirty resident undo/redo requires native history entries. If a legacy Python
  snapshot is encountered while the C++ session is authoritative, undo/redo
  raises instead of exporting the native mesh to restore stale Python history.
- Dirty resident native sessions also block explicit legacy display cleanup
  commands instead of exporting the native mesh and running Python display
  topology mutation. Export/explicit mesh reads remain the only hydration
  boundary.

## Validation Commands

- Use project venv:
  `.\.venv\Scripts\python.exe -m pytest <tests> --basetemp="$env:TEMP\cdmw-pytest-<name>"`.
- Mesh high-signal checks: native session/action/dev-harness/source-guard tests
  plus harness scenarios `native-mesh-editor-benchmark`,
  `native-mesh-editor-static-screen-stroke`,
  real archive Mesh Editor D3D11 edit smokes,
  `native-mesh-editor-qt-responsiveness`, and
  `native-mesh-editor-qt-cancellation`.

## Recent Proofs

- Current 100k/200k benchmark after resident select/dirty-history cutover uses
  native `session_view()` counts between commands, not `working_mesh()`, so the
  harness does not hydrate stale Python meshes mid-chain. Latest run passed with
  source Grow selecting 100,806 vertices, Delete/Subdivide/Refine topology
  changes, brush/undo/redo, native timing metrics, and no fallback events.
- Synthetic D3D11 delta harnesses are protocol checks only: they use
  matrix-only `screen_drag` to prove vertex-delta/native screen-selection
  packet handling, D3D11 topology deltas without `replace_all`, native
  apply/history metrics, and no fallback. They are not visual edit proof. The
  standalone/static screen-stroke harness sends two incremental native
  transform packets (`0->2`, then `2->5`) and verifies the selected vertex
  moves exactly the combined delta, so a cumulative/absolute over-application
  regression fails without opening the checkerboard preview as visual proof.
- `real-archive-mesh-editor-d3d11-edit-smoke` loads the real archived PAC entry
  `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` from
  `0009/0.pamt`, derives a small visible face cluster from the actual D3D11 WVP,
  selects it in a resident native session, sends real D3D11 mouse down/two
  incremental moves/mouse-up messages through the cursor-ring Move path, handles the resulting
  `mesh_edit_stroke_*` payloads through `MeshEditorTab`, pushes the D3D11
  `update_mesh_edit_vertices` delta, and captures before/after PNGs. Latest
  standalone rerun selected 12 faces on the real mesh, dragged from `(452,175)` to
  `(484,175)`, moved the projected selected center from `(451.91,174.59)` to
  `(483.91,174.59)`, measured selected projected delta
  `(32.00000096,0.00000008)` against expected `(32,0)` with under `0.000001`
  px screen error across move packets `(452,175)->(468,175)->(484,175)`, updated
  61 D3D11 vertices per move / 12 native vertices, capped selected displacement
  at about `0.137`, and had no native fallback events. The side-by-side real-PAC
  rerun (`real-archive-mesh-editor-d3d11-side-by-side-edit-smoke`) used the
  replacement viewport offset `x=483`, kept drag points inside that viewport,
  dragged `(693,175)->(725,175)`, measured projected selected delta
  `(32.00000076,0.00000008)` against expected `(32,0)`, and had no fallback
  events. The harness now writes raw loaded, selected-before-drag, after-drag,
  and `real_archive_visual_edit_proof.png` contact-sheet diff captures so this
  proof is inspectable on actual game geometry instead of a synthetic rectangle.
  Latest side-by-side visual proof passed under
  `%TEMP%\cdmw-real-archive-mesh-editor-d3d11-side-by-side-codex-check`: live
  vertex-update send p95/max was about `0.235 ms`, handler p95/max was about
  `5.95 ms`, native apply roundtrip p95/max was about `4.39 ms`,
  `live_stroke_frame_budget_ok=true`, the projected selected delta remained
  `(32.00000076,0.00000008)` against expected `(32,0)`, and there were no native
  fallback events. The applied-update event wait is still about `50 ms`, so
  future performance work should reduce visual apply latency without putting
  `WM_COPYDATA` waits back on the Qt handler path.
- `scripts/codex_check.ps1 -Area mesh` now runs the real archive side-by-side
  Mesh Editor D3D11 smoke. Use `scripts/codex_check.ps1 -Area mesh-unit` only
  for synthetic/unit regression coverage, and run Qt harness scenarios directly
  only when validating worker responsiveness/cancellation.
- Project `AGENTS.md` now repeats this: `codex_check -Area mesh-unit`,
  `build_synthetic_mesh`, `harness_quad`, `full-suite-smoke`, and synthetic
  D3D11 harnesses are unit/protocol coverage only, not game-mesh visual proof.
- Do not use `native-mesh-editor-d3d11-delta` or
  `native-mesh-editor-d3d11-payloads` as visual edit proof. They are synthetic
  checkerboard regression harnesses and intentionally do not show game geometry.
  `tools/mesh_editor_dev_harness.py` blocks them unless
  `--allow-synthetic-d3d11` is passed for protocol-only regression testing.
- `tools/mesh_editor_dev_harness.py` defaults to the real archive side-by-side
  Mesh Editor D3D11 smoke. `full-suite-smoke` is also blocked unless
  `--allow-synthetic-d3d11` is passed, so accidental visual-test runs should no
  longer open the synthetic `harness_quad` square.
- `scripts/codex_check.ps1 -Area mesh` was changed from synthetic pytest
  coverage to the same real archive side-by-side proof. The old synthetic broad
  gate is now explicitly `-Area mesh-unit`.
- `tools/mesh_editor_dev_harness.py` moves D3D11 harness windows to screen 1
  (`\\.\DISPLAY1`, falling back to primary) before captures and mouse input.
- Active embedded Mesh Edit no longer wires Python `preview_to_source` helpers
  through the static dialog callback namespace. If Mesh Edit is active and
  native D3D11 refresh is unavailable, shared preview refresh/commit helpers
  now status-error instead of rebuilding a Python preview model.
- Current D3D11 coordinate-ownership slices have runtime coverage for WVP/source-transform
  `screen_drag`, `screen_radius`, `screen_brush`, and `screen_region`, native
  source click/context, edge/face ray picking, visible/xray filtering,
  brush-target weights, screen-brush-derived projected radius centers, Remove face deletion, hover-without-host-hits, static
  matrix-only drag with source-transform overrides before Python inverse fallback, fail-closed unresolved/malformed
  base/source projection payloads, projected brush misses, and projected
  drag/radius/groups legacy scalars, including source-specific projection
  override selection payloads and non-overridden sources. Active D3D11
  begin/update payloads no longer serialize host candidate groups,
  `drag_candidates`, `camera_world`, or
  legacy camera fallback fields; `native-mesh-editor-d3d11-payloads` gates emitted
  `source_submesh_world_transforms` on real D3D11 screen payloads, and the D3D11
  delta harness gates native consumption on transform/brush screen drags.
- Real resident-session topology tests now prove native preview triangle groups
  with `python_apply_deferred=1.0` and no Python report/export path for
  cleanup (`remove_doubles`, `delete_loose_vertices`), `extrude`, append
  `mirror`, and the previously weaker real-kernel coverage for `split`,
  `edge_split`, `bridge`, and `fix_winding`.
- Active standalone and embedded Mesh Editor action bars no longer expose
  `triangulate_display`/`quadrangulate_display`; embedded direct dispatch
  `MeshEditorController`, and `MeshEditCommandWorker` direct dispatch reject
  them as legacy display-shape cleanup. Domain/service helpers remain for legacy
  one-shot display-polygon plumbing until resident C++ can preserve non-triangle
  display polygons, but direct `MeshService.apply_command()` now requires
  `allow_legacy_display_cleanup=True` before running them.
- Focused pytest, native release builds, standalone/static screen-stroke
  harnesses, native D3D11 payload/delta harnesses, and source guards passed for
  the active native Mesh Editor cutover.
- Current post-cutover rerun after the shared action-set cleanup passed Python
  compile checks, focused source/service/native-session/dev-harness pytest,
  Release builds for `native/cdmw_mesh_core` and `native/cdmw_d3d11_preview`,
  and fallback-free harnesses for static screen stroke, D3D11 delta, D3D11
  payloads, standalone stroke, the 100k/200k benchmark, Qt responsiveness, and
  Qt cancellation.
- Current mesh-gate rerun on 2026-07-05 passed focused py_compile, 156 focused
  native/source/controller tests, Release builds for `native/cdmw_mesh_core` and
  `native/cdmw_d3d11_preview`, fallback-free workflow and 100k/200k benchmark
  harnesses, static screen stroke, Qt responsiveness/cancellation, and the real
  side-by-side PAC D3D11 visual proof under
  `%TEMP%\cdmw-real-side-by-side-visual-edit-proof-current`.
- Final mesh unit/protocol gate on 2026-07-05 passed the legacy
  `.\scripts\codex_check.ps1 -Area mesh` path, now
  `.\scripts\codex_check.ps1 -Area mesh-unit`, with 647 passed / 4 deselected,
  then release onefile packaging rebuilt native helpers, validated all 483
  embedded archive members, and the packaged EXE startup-smoked with
  `QT_QPA_PLATFORM=offscreen` and `CDMW_GUI_STARTUP_SMOKE=1`. Artifact:
  `dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`,
  112,120,874 bytes, SHA256
  `1913D716177EA4667C220D4BA960C4712BDC588D194B226CD98A23A08F1C80DF`.
- Release PyInstaller packaging now treats `native/cdmw_mesh_core/build/Release/cdmw-mesh-core.exe`
  as required, alongside the D3D11 and texture native helpers. A 2026-07-05
  `build.bat onefile release` run rebuilt native helpers, validated all 483
  archive members, startup-smoked the packaged EXE, and archive inspection found
  `native\cdmw-mesh-core.exe` (1,909,760 bytes),
  `native\cdmw-d3d11-preview.exe` (921,600 bytes), and the other native helpers
  embedded in the onefile artifact.
- Current 2026-07-06 release onefile package after the MeshAsset GLB-first editable-package
  rebuild, material-slot-count, raw-vertex-record, raw-record-sidecar,
  material-slot-sidecar, unknown-section-sidecar, unknown-field-sidecar,
  LOD-identity-sidecar, LOD-section-range, vertex-stride, source-offset,
  unknown-metadata, native-clone LOD metadata, developer override, and packaged
  `mesh.cdmeta.json` schema validation gates, real-game smoke guard, and .NET handoff smoke rebuilt native helpers,
  published the .NET Mesh Editor experiment helper, validated all 485 embedded archive members,
  startup-smoked cleanly, focused-tested the visible native Performance panel,
  FPS/frame-time label, and slow-frame log entry,
  kept active native preview fail-closed for non-finite geometry, passed the
  legacy mesh unit/protocol gate, now `.\scripts\codex_check.ps1 -Area mesh-unit`,
  with 700 passed / 4 deselected, passed
  `.\scripts\codex_check.ps1 -Area smoke` with 8 passed, passed
  `.\scripts\codex_check.ps1 -Area archive` with 88 passed, passed current Qt
  responsiveness/cancel harnesses with no native fallback, passed
  a current real-game side-by-side D3D11 edit smoke on
  `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` from
  `C:\games\Steam\steamapps\common\Crimson Desert\0009\0.pamt` with no native
  fallback and live handler p95 about `14.92 ms` under the 16.7 ms frame budget,
  passed current Qt responsiveness/cancel harnesses with no native fallback
  (`~0.06 ms` dispatch, first progress under `3 ms`, cancel latency about
  `31 ms`), and passed the packaged Mesh Editor asset rebuild plus
  metric-enforced .NET handoff smoke with
  `QT_QPA_PLATFORM=offscreen`, `CDMW_GUI_STARTUP_SMOKE=1`,
  `CDMW_GUI_STARTUP_SMOKE_TARGET=mesh_editor`, and
  `CDMW_GUI_STARTUP_SMOKE_MESH_ASSET=D:\Byggverkstaden\test_mesh_editor\cd_phm_00_nude_10_0001.pac`,
  plus `CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD=1` and
  `CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET=1`.
  That smoke opens the Mesh Editor tab, loads the PAC through
  `open_mesh_file_session()`, and requires validation plus no-op roundtrip
  `PASS`; the rebuild variant then exports an editable package, imports it back,
  validates the imported package, and writes a temp rebuilt PAC through the
  Mesh Editor workers. The .NET variant launches bundled
  `cdmw-mesh-dotnet-editor.exe` in headless mode through the same package
  handoff, imports its output, reruns validation, and requires a
  `replace_positions_same_count` edit operation, positive .NET FPS/frame-time
  metrics, and a keep/drop `dotnet_evaluation.md`. Artifact:
  `dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`,
  173,980,247 bytes, SHA256
  `15C1783E16F5BA0D24B364F92DDC63966C1ACFBB92EB31BF65466D6A30807B8F`.
  Onefile archive inspection found `native\cdmw-mesh-core.exe`,
  `native\cdmw-d3d11-preview.exe`, `native\cdmw-preview-core.exe`,
  `native\cd-texture-dx.exe`, `native\cdmw-mesh-dotnet-editor.exe`, and
  `schemas\mesh\mesh.cdmeta.schema.json`.
- Full `tests/test_mesh_service_editing.py` now passes: 386 passed on
  2026-07-06 after LOD identity sidecar preservation.
- Native texture roundtrip and fast/release onefile package smokes passed on 2026-07-04.

## Next Useful Slices

- Native Mesh Editor native cutover passed final audit on 2026-07-05: active
  edit actions route through the resident C++ editor session, active UI paths
  consume native preview payloads, and Python mesh mutation/preview rebuild
  paths are explicit legacy/archive-only. Use the real PAC side-by-side D3D11
  edit smoke on screen 1 for future visual proof; checkerboard D3D11 harnesses
  are protocol-only.
