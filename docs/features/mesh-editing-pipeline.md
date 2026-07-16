# Mesh Editing Pipeline

Status: resident .NET/Vortice editor and safe-import contract, 2026-07-16.

## Current Implementation Map

- Parser entry points:
  - `cdmw.modding.mesh_parser.parse_mesh()` dispatches to `parse_pac()`,
    `parse_pam()`, and `parse_pamlod()`.
  - `inspect_mesh_binary_layout()` returns best-effort binary section,
    descriptor, material slot, stride, and parser confidence metadata.
- Rebuild entry points:
  - `cdmw.modding.mesh_importer.build_mesh()` is the format facade.
  - PAC rebuild uses `cdmw.modding.mesh_pac_builder.build_pac()`.
  - PAM rebuild uses `cdmw.modding.mesh_pam_builder.build_pam()`.
  - PAMLOD rebuild uses `cdmw.modding.mesh_pamlod_builder.build_pamlod()`.
  - Static arbitrary replacement uses
    `cdmw.modding.static_mesh_build.build_static_mesh_replacement()`.
- Editor entry points:
  - `cdmw.services.mesh_service.MeshService` owns edit sessions and validation;
    state, payload, report, history, kernel, rigging, and rebuild behavior live
    in focused `mesh_service_*.py` owners behind that facade.
  - `cdmw.ui.mesh_editor.controller.MeshEditorController` adapts UI actions to
    `MeshService`.
  - `cdmw.ui.mesh_editor.tab.MeshEditorTab` owns standalone and embedded UI.
  - Archive-browser static replacement delegates through
    `cdmw.ui.mesh_editor.static_replacement_adapter`.
  - `cdmw.modding.mesh_native_core` preserves the native Python API as a
    753-line direct-export facade. Focused `mesh_native_*.py` owners hold client
    transport, payloads, resident sessions/history, snapshots, selection,
    preview, transforms, editing kernels, and report application; each owner is
    at most 725 lines and each function at most 150 lines.
  - `native/cdmw_mesh_core/src/main.cpp` is a thin executable entry. Focused C++
    owners cover protocol types/payloads, geometry/UV, topology, interchange,
    reports, preview, resident session state, selection, history, apply stages,
    snapshots, command dispatch, and service I/O. CMake composes these normal
    sources through one named unity group; no owner source includes another.
    `tests/test_native_mesh_core_decomposition.py` enforces the 800-line file and
    150-line real-function ceilings.
  - `native/cdmw_d3d11_preview/src/main.cpp` is likewise a thin host entry.
    Ordered CMake unity owners under `src/owners/` retain the existing package,
    renderer, picking, interaction, sparse-update, command, and status protocols
    without source-level owner includes. `tests/native_source_text.py` provides
    the ordered aggregate used by legacy source guards, while
    `tests/test_native_d3d11_preview_decomposition.py` enforces the same 800/150
    ceilings.
- Import/export formats:
  - GLB editable packages are handled by
    `cdmw.modding.mesh_glb_interchange`. They write `mesh.glb` plus the same
    `mesh_roundtrip_manifest_v2` sidecar contract used by OBJ.
  - OBJ export writes `mesh_roundtrip_manifest_v2` sidecar metadata through
    `cdmw.modding.mesh_exporter.write_roundtrip_manifest()` and remains the
    secondary package format.
  - OBJ import reads that sidecar in `cdmw.modding.mesh_obj_importer.import_obj()`.
  - FBX export exists, but it is visual interchange only for this safety track.
  - DAE/glTF/GLB scene preview exists in archive import preview flows, but
    visual scene files without the Crimson sidecar are not safe game-asset
    rebuild sources.
- Preview package creation:
  - Mesh Editor D3D11 packages live under
    `cdmw.ui.mesh_editor.native_preview_runtime` and
    `cdmw.ui.mesh_editor.native_preview_payloads`.
  - Archive/static replacement preview packages use `cdmw.rendering.native_*`
    helpers and archive-browser static replacement callbacks.
  - Sparse live position, normal, and UV updates use one sender thread per
    Python D3D11 host.
    One pending update is retained, newer revisions replace older pending work,
    native update acknowledgements pace delivery, and superseded `delete_after`
    payload files are removed. Revision-capable native and .NET receivers apply
    only monotonic `edit_revision` packets, return explicit applied/rejected
    acknowledgements, and retain the legacy `revision` alias. Revisionless
    acknowledgements remain accepted only until an older host is identified.
  - The native editor session has one authoritative resident submesh map.
    Non-topology undo units retain only changed channel/index values; topology
    units retain one reversible affected-submesh snapshot and swap it on
    undo/redo. Native and Python history are capped at 64 whole units and 256
    MiB, and session/result diagnostics expose retained bytes and stack counts.
    The session view also exposes the ordered applied/undone action timeline.
    Geometry, replacement, rigging, and selection changes use that same order;
    selection history stores only the prior selection descriptor and never
    clones or hydrates the resident mesh.
    Auto-UV captures both a reversible topology snapshot and sparse UV channels,
    so a same-topology unwrap remains exact and undoable.
    Apply roots are filtered to the selection-derived candidate submeshes before
    any kernel runs, so global cleanup kernels cannot mutate an unsnapshotted or
    unselected part. Component material edits capture both the possible topology
    snapshot and sparse metadata channels because a full-face assignment can
    resolve to a metadata-only edit.
  - The persistent mesh-core service accepts mesh-editor jobs and reports
    inline. A failed stateful inline command is never replayed through the file
    protocol; the standalone file protocol remains readable for direct legacy
    callers.
    Live transform/brush replies use inline sparse arrays and create no
    per-command job/report files. Callers that explicitly request a delta output
    directory still receive compact binary descriptors marked `delete_after`
    for consume/ack cleanup.
  - Durable archive preview packages are pinned from renderer launch through
    reload, process failure, cancellation, or close. A loaded reload retires the
    old pin; pruning and manual cache clearing skip every active package lease.
  - Fast untextured geometry is first-load-only. Once a material-complete frame
    is loaded, geometry rebuilds keep it visible until the next coherent
    archive-parity package is ready.
- .NET experiment handoff:
  - `cdmw.services.mesh_dotnet_experiment` exports the active Mesh Editor
    session as an OBJ package plus `mesh_roundtrip_manifest_v2` sidecar,
    `mesh.cdmeta.json`, `original_asset_hash.txt`, status JSON, output folder,
    launch manifest, combined render-only `scene.obj`, and `dotnet_scene.json`.
    Editable submeshes remain first in the scene and the original reference is
    appended with a non-editable role; save/output paths filter back to the
    editable count. The .NET process receives that package only; Python/C++
    remain the parser, validator, rebuilder, and packaging authority. When the
    process exits with an edited OBJ under the declared output package, the
    standalone UI imports it on a worker through the same OBJ sidecar contract,
    replaces the working mesh through `MeshService`, and refreshes validation.
    Helper-reported edited OBJ, package, and operation paths are canonicalized
    beneath that package's owned output directory before any import or sidecar
    write. Traversal, external absolute paths, link/reparse escapes, and aliases
    of either input OBJ fail closed.
    Service native-snapshot clones copy the MeshAsset validation metadata before
    handoff export, so .NET packages keep exact LOD section offsets/sizes instead
    of falling back to preview-only LOD identity.
- Archive patching:
  - UI actions route through archive-browser mesh patch/import flows, while
    destructive archive mutation policy remains outside Mesh Editor UI.

## Metadata Loss Risks

- `ParsedMesh` has useful source offsets, vertex stride, descriptor offsets,
  material names, bone rows, and source vertex maps, but it is still a
  compatibility shape rather than a strict rebuild contract.
- Editable-package sidecars preserve schema/tool identity, source asset
  hash/size, parser confidence, inferred skinning/skeleton facts, LOD/submesh
  stable IDs, material slots, vertex/index counts, vertex stride, binary
  offsets, bounds, import rules, allowed edit operations, source vertex maps,
  and source index maps. They prefer exact MeshAsset material slots when
  available and carry exact MeshAsset LOD section identity, raw vertex record
  count/stride/hash, unknown-section ranges, and JSON-safe unknown submesh
  fields; raw bytes remain owned by the original source asset. The packaged JSON
  Schema for `mesh.cdmeta.json` lives at
  `schemas/mesh/mesh.cdmeta.schema.json`.
- FBX, DAE, glTF, and GLB scene paths carry visible geometry but not enough
  Crimson metadata for destructive rebuild without the editable-package sidecar.
- PAM/PAMLOD layout recovery can be inferred or fallback-scan based. Rebuild
  paths must treat that confidence as policy input before destructive writes.

## First Safety Slice

- `cdmw.domain.mesh.asset` defines `MeshAsset`, LOD, submesh, vertex/index
  buffers, binary layout, parser confidence, and structured validation issues.
- `cdmw.modding.mesh_asset` converts current `ParsedMesh` output into
  `MeshAsset`, preserving source offsets and raw vertex records when available
  and reporting inferred skinning facts in `skeleton_info` without treating them
  as linked skeleton metadata. Service/file-session calls inspect the original
  bytes too, so UI exports get the same PAC section ranges as CLI inspect.
- `cdmw.modding.mesh_roundtrip` runs no-edit parse, rebuild, binary diff, and
  strict/tolerant pass/fail reporting.
- `tools/mesh_pipeline.py inspect <asset> --out inspect.json` writes a MeshAsset
  inspection dump without opening the UI.
- `tools/mesh_pipeline.py roundtrip <asset> --out rebuilt_asset --report report.json`
  runs the no-edit round-trip harness.
- `tools/mesh_pipeline.py export <asset> --out package_dir` writes an editable
  GLB/OBJ package with `mesh.glb`, `mesh.obj`, `mesh.cdmeta.json`, and
  `original_asset_hash.txt`.
- `tools/mesh_pipeline.py import|validate|rebuild <asset> <package_or_obj>`
  reuses the same sidecar identity, service validation, and rebuild gates as
  the editor path. `validate` fails closed on source hash/size mismatch, and
  `rebuild` writes patched bytes only after validation passes.
- Mesh Editor file-session loads can opt into that no-op round-trip off the UI
  thread. `MeshService.validate_export()` then exposes parse confidence, source
  hash, and no-op round-trip status through the existing Checks panel.
- Export validation blocks fallback/failed parser confidence and failed or
  not-run no-op round-trips before rebuild.
- Public validation reports exported by the CLI or copied from the Mesh Editor
  serialize v2 severity names (`warning`, `error`, `fatal`) even though the
  internal UI gate still tracks rebuild-blocking issues as blockers. Issue rows
  also carry stable `expected`, `actual`, `lod_index`, `submesh_index`, and
  `can_continue` fields for UI and CLI consumers.
- Export validation blocks edited unnormalized bone weights, but preserved
  unnormalized rows from the original asset are warnings so skinned no-op
  rebuilds can keep source bone data intact.
- Export validation blocks changed bone indices or bone weights against the
  original mesh by default. Current safe operations preserve skinning data;
  later skinning authoring needs an explicit safe operation and rebuild rule.
- Export validation keeps `missing_skeleton_metadata` as a blocker for skinned
  meshes without linked skeleton data or MeshAsset-derived bone-count evidence.
  File-loaded MeshAsset sessions may use the original inferred bone count to
  validate preserved skinning, and edited bone indices outside that range still
  block rebuild.
- OBJ imports carry sidecar source hash/size into rebuild, and `build_mesh()`
  rejects stale sidecars when the current source bytes do not match. Mesh
  Editor session imports hit the same source identity gate in
  `MeshService.replace_working_mesh()` before the edited mesh enters history.
- OBJ sidecars carry per-submesh raw vertex record count/stride/SHA-256
  evidence when the original source bytes and vertex offsets are available.
  Import identity validation recomputes that digest from the current source
  asset before rebuild, so a stale or corrupted sidecar cannot claim intact raw
  records.
- OBJ sidecars now prefer exact MeshAsset material slots over submesh-derived
  fallback slots, and include MeshAsset unknown-section ranges when parser
  layout recovery exposes them. They also serialize exact MeshAsset LOD section
  identity and JSON-safe unknown submesh fields, then restore those metadata
  blocks on OBJ import. The service still restores unknown metadata from the
  original edit session before validation/rebuild.
- OBJ import rejects unsupported sidecar schema versions, missing stable IDs in
  the strict LOD sidecar block, and non-trivial OBJ rebuilds without sidecar
  metadata.
- GLB package import rejects the same missing/unsupported sidecar metadata
  before scene geometry can replace the working mesh.
- Imported OBJ rebuilds now enforce sidecar topology counts when
  `allow_topology_change` is false. Per-corner OBJ vertex splits are still
  allowed only when their source vertex map covers the same original vertices.
- Strict LOD sidecars must also carry a complete `source_index_map` for indexed
  submeshes; missing, short, or out-of-range index maps fail import.
- Export validation blocks changed LOD counts or per-LOD submesh counts against
  the original session mesh by default, with `expected`, `actual`, and
  `lod_index` fields in the report.
- Export validation blocks changed MeshAsset LOD identity metadata when it is
  present on the original session mesh.
- Export validation blocks changed geometry when the edited submesh lacks a
  complete non-negative `source_vertex_map`, so rebuildable vertex edits remain
  traceable to source asset data.
- Export validation blocks changed MeshAsset unknown sections and submesh
  `unknown_fields` against the original session mesh. Those metadata blobs are
  copied through service session clones so an imported/edit-session mesh cannot
  silently drop them before rebuild.
- Export validation blocks changed original vertex stride/source stride against
  the original session mesh. OBJ sidecar import merges the strict LOD metadata
  into its matched submesh records so native-manifest packages keep stride
  evidence through import and validation.
- MeshAsset rebuild validation blocks dropped or changed raw vertex records
  against the original asset contract, so edited assets cannot lose the source
  bytes needed for metadata-preserving rebuilds.
- Export validation blocks changed source vertex offsets, source index offsets,
  source index counts, and source descriptor offsets against the original
  session mesh. OBJ sidecar import reconstructs vertex offsets from the strict
  LOD sidecar's original vertex offset, vertex stride, and source vertex map.
- Sectionless compact `SkinnedMesh_Box` PAC entries are parsed through a narrow
  inferred box fallback so the real archive corpus does not silently return an
  empty `ParsedMesh` for that debug mesh variant.
- Skinned OBJ sidecars must include per-submesh `bone_layout` metadata.
  Submeshes with empty bone rows are treated as unweighted, including rigid
  weapon meshes in skinned containers; only submeshes with positive
  `max_influences` require a complete `source_vertex_map` for influence
  preservation. This blocks visual-only OBJ packages from pretending they can
  preserve real bone rows.
- OBJ import records sidecar warnings when edited OBJ material names or MTL
  texture paths differ from the sidecar. Export validation surfaces those as
  warnings so preview can continue while rebuild/report UI stays explicit about
  metadata drift; final rebuild is blocked until that sidecar metadata is
  restored or a later explicit safe material operation exists.
- Export validation also blocks material slot count, material slot, and texture
  reference changes against the original session mesh by default. Current safe
  rebuild preserves material/texture identity; material authoring needs a later
  explicit safe operation and rebuild rule.
- `cdmw.domain.mesh.operations` defines the first Mesh Editor v2 operation-list
  contract. OBJ sidecar imports now attach explicit same-count replacement
  operations for positions, normals, and UV0 only when the imported submesh
  still has the sidecar vertex count, and sidecar `allowed_edit_operations`
  can reject disallowed operations before rebuild. Same-count operations also
  require a complete source vertex map, so an edited vertex can always be traced
  back to original asset data before rebuild. Imported OBJ sidecar rebuilds are
  blocked when no explicit operation list is attached. When an original mesh is
  available, export validation and direct rebuild also block channel changes
  that are not covered by the attached operation list.
- Built-in same-count editor actions append undo/redo-aware operation entries:
  transform and brush actions record position edits, normal tools record normal
  edits, tangent generation records tangent edits, and UV transforms record UV0
  edits. Topology and material actions remain outside the safe operation list.
- `cdmw.modding.mesh_importer.rebuild_mesh_with_report()` preserves the
  bytes-only `build_mesh()` API while returning source/rebuilt hashes, parse
  confidence, validation status, edited scope, changed channels, and changed
  byte ranges for rebuild-report UI work. Rebuild reports include the attached
  Mesh Editor v2 operation list and merge validated operation targets into the
  edited scope when the original bytes cannot be parsed for channel diffing.
  Direct rebuild calls reject invalid attached operations before a builder runs;
  when original bytes parse, builders receive a mesh rebuilt from the original
  plus only the channels declared by validated operations.
- `MeshService.rebuild_report()` gates the in-memory rebuild through export
  validation before calling that helper, and the Mesh Editor right-side
  `Rebuild` panel can display the structured report without auto-running
  rebuild work during UI refresh.
- Standalone Mesh Editor has `Run`, `Rebuild`, `Preview`, `Package`, and `Save` actions in the
  `Rebuild` panel. `Run` uses `MeshRebuildReportWorker` so validation/rebuild
  report generation stays off the UI thread. `Rebuild` uses the same worker and
  `MeshService.rebuild_asset()` to write a patched asset only after validation
  passes; it refuses to overwrite the original source file. `Preview` hands the
  last rebuilt file back to the archive import-preview flow when the session has
  an archive target. `Package` sends that file to the existing archive
  package/patch flow through the same preset import setup, so archive writes
  still require the normal builder confirmation. `Save` writes the last
  generated report as JSON without rerunning rebuild work; the tracked
  `MeshReportWriteWorker` stages it beside the destination and atomically
  publishes only after the write completes and cancellation remains clear.
- Developer rebuild override is hidden behind the explicit
  `mesh_editor/developer_mode=true` and
  `mesh_editor/developer_rebuild_override=true` settings. It only allows a
  separate-output patched rebuild for parser-confidence/no-op round-trip
  blockers, keeps all other validation blockers fatal, and records the reason
  plus unsafe condition codes in the rebuild report.
- Standalone Mesh Editor has preview-toolbar `Export`, `Import`, and `Open`
  actions for editable packages. `Export` runs
  `MeshEditablePackageExportWorker` and writes `mesh.glb`, `mesh.obj`,
  `mesh.cdmeta.json`, and `original_asset_hash.txt`; `Import` runs
  `MeshEditablePackageImportWorker`, restores the sidecar alias when needed,
  prefers sidecar GLB import, falls back to OBJ import, replaces the working
  mesh through `MeshService`, and reruns export validation before rebuild can be
  enabled.
  `Open` opens the last exported editable package folder from settings.
- The Checks panel exposes `Run` and `Copy`. `Run` uses
  `MeshExportValidationWorker` to refresh export validation off the UI thread;
  `Copy` copies the current structured export validation report as JSON from the
  same report object rendered in the panel.
- The Mesh Editor preview toolbar and Performance panel show native preview FPS,
  average FPS, frame time, CPU update time, GPU upload time, draw call count,
  vertex count, index count, visible submesh count, and texture memory when
  native status provides them. They consume direct native D3D11 status fields
  (`first_frame_ms`, `geometry_upload_ms`, `vertex_count`, `batch_count`) and
  nested status metrics (`current_fps`, `average_fps`, `frame_time_ms`) from file
  polling or native host events. Embedded replacement D3D11 load summaries also
  surface FPS/frame-time when native status reports them.
- Slow native preview frames over the 16.6 ms target are logged once per metric
  sample in the existing Mesh Editor log strip with frame, CPU, GPU, draw-call,
  and visible-submesh details when available.
- Active native preview package creation fails closed before native handoff when
  malformed non-finite vertex, normal, UV, tangent, or bitangent data is present.
  Explicit fallback-only test helpers still sanitize those values for diagnostic
  payload checks.
- The .NET/Vortice child starts automatically when an embedded replacement
  builder or standalone original/imported mesh session is ready. `Edit Mesh`
  now changes the resident scene from placement-only interaction to geometry
  mutation; turning it off keeps the same process, decoded textures, camera,
  scene buffers, grid, and saved placement-preview choice resident. While edit
  interaction is active, the host and child both force Replacement Only and pin
  input to the editable camera context; Original, Overlay, and Side by Side
  cannot be restored by a queued scene or presentation replay. Turning edit off
  restores the placement preview mode selected in the Builder. Placement keeps
  the Builder setup controls visible, keeps the child's tool panel collapsed, and
  rejects geometry commands. Entering `Edit Mesh` hides the Builder controls
  and exposes the embedded child's dark scrollable WinForms controls on the left.
  Its editable viewport defaults to Wire + Vertices, with round vertex markers;
  the inert Material Debug control is not shown in the Viewport section.
  Its Original role selector is disabled during editing; Imported/Modify remains
  active with move/rotate/scale gizmo selection. In placement, the scene toolbar
  provides two-pane, overlay, focus-Imported/Modify, and focus-Original choices.
  Original and Imported/Modify are distinct role-filtered presentation contexts
  over the same parsed document, geometry buffers, materials, textures, revisions, and
  resource fingerprints. In Side by Side, when both roles exist, one shared
  Vortice viewport, device, and swap chain renders them simultaneously into
  separate left/right rectangles with separate grids and independently stored
  normal cameras and display state. Replacement Only and Original Only each
  render their named role alone in the full viewport. A draggable divider
  resizes the Side by Side rectangles from 18% through
  82%; the host persists that ratio under the existing Builder D3D11 split
  setting. Original accepts camera navigation only. Imported/Modify owns all
  picking and mutation. Explicit Overlay is the single-surface exception and
  links to the editable comparison camera without duplicating resources or
  launching a second helper. Left-dragging the
  viewport in placement mode updates the authoritative Builder TRS controls.
  Placement and Edit Mesh use Archive Browser's fit-relative wheel ladder:
  `0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64`.
  Each wheel event moves one slot based on current zoom divided by fitted zoom,
  regardless of wheel-delta magnitude, and an inverse step restores the exact
  prior slot. Like Archive Browser, zoom preserves camera-space pan: projected
  pan scales with zoom so a detail moved to the framing center stays anchored
  instead of pulling back toward the model's original center. In Side by Side,
  only the pane beneath the pointer changes; the other pane's camera and the
  active camera context remain untouched.
  Every camera, stroke, gizmo, selection-rectangle, divider, or wheel state
  change queues at most one latest-wins invalidation rather than rendering from
  the 16 ms WinForms maintenance timer. A completed Present never schedules
  another frame by itself, and invalidation stays asynchronous so rendering
  cannot monopolize the WinForms input thread. D3D11 presents with VSync and a
  maximum frame latency of one, so continuous input can follow 120 Hz, 144 Hz,
  or another active monitor refresh rate without a software 60 Hz cap when the
  input rate and GPU/display budget permit it.
  Grid, gizmo, selection, wire, and divider vertices stream through one
  capacity-growing dynamic D3D11 vertex buffer and one discard map per pane
  frame. Draw commands preserve the established grid/wire/vertex/selection
  layering after that single upload. Grid, wire, reference, selection, and
  highlight geometry is retained by topology, scene, presentation, material,
  and selection generations, so unchanged overlays do not rebuild or create
  and dispose GPU buffers in the draw loop.
  The production D3D11 child exclusively owns viewport painting: the parent
  WinForms CPU/GDI fallback returns before traversing any faces while that child
  exists. Windowed presentation uses DXGI flip-discard rather than the legacy
  blit model, and camera orbit/pan bypasses gizmo hover hit-testing; ordinary
  hover hit-testing constructs one camera per event. Continuous mouse input
  performs one latest-wins renderer update and does not directly invalidate the
  parent surface as a second paint path.
  The reported FPS is calculated from completion-to-completion frame intervals;
  render work, Present time, interval p95/max, and pacing jitter are reported
  separately so fast submission cannot masquerade as smooth output. Placement
  preview stays local and input-paced while Builder-authority transform
  requests use an approximately 30 Hz latest-wins lane plus an exact final
  mouse-up transform, avoiding synchronous pipe and Qt work on every raw mouse
  event. The local preview reconstructs the exact editable world matrix from
  the acknowledged automatic-alignment matrix plus the provisional manual TRS;
  it never applies that provisional matrix to the Original role. A newer local
  drag survives an older authority frame until a matching frame arrives, and
  the resident world grid remains fixed while placement changes.
  The Y-up grid and placement transform are carried by
  `authoritative_resident_scene_frame_v2`. Python computes one frozen scene
  frame through `cdmw.modding.static_mesh_scene_frame`; the final static build
  and resident preview therefore share the same anchor/axis, length scale,
  automatic roll, fit, floor-correction, and manual-TRS composition. The frame
  carries row-major `System.Numerics` row-vector matrices, right-handed source
  mesh units, exact transformed-vertex world bounds for both roles, placement
  and optional selection pivots, ground/grid origin, framing extent, visibility,
  comparison mode, interaction mode, source identity, and scene generation.
  Legacy comparison offsets remain presentation-only and never enter output
  matrices; the two role rectangles render offset-free role matrices. Each role
  camera retains its own captured framing bounds across resident placement
  frames; only an explicit Fit command recenters or rescales that role. Camera
  payloads carry a per-role command generation so replaying persistent
  presentation state cannot repeat Fit, pan, zoom, or rotation commands against
  either pane. Replacement control changes calculate a latest-wins frame
  off the Qt thread and update resident transforms without OBJ
  export, package rebuild, source reparse, geometry-buffer replacement, or
  renderer restart. A mode-only `Edit Mesh` transition can publish the last
  authoritative frame immediately instead of waiting behind an older transform
  calculation; the older request then becomes stale and cannot replay placement
  mode over the editor. Scene updates and acknowledgements correlate session,
  request, process generation, source identity, and scene generation; stale or
  rejected updates leave the last acknowledged scene frame active. Overlay
  renders the original as a reference wire layer.
  Production presentation exposes separate `Original` and
  `Imported / Modify` resident view contexts inside that same helper process.
  Both contexts retain the same parsed document, geometry buffers, material
  set, and decoded texture resources; role filtering, camera, and display state
  are per-view. Their normal cameras are independent, both role panes must draw
  before readiness is published, and renderer diagnostics expose the shared
  surface plus reference/editable client and screen rectangles. Overlay alone
  links to the editable comparison camera without coupling the two normal role
  cameras.
  Builder camera, Fit, display/quality/lighting, grid/gizmo, UV, highlight,
  hidden-part, routing, and per-part presentation state use one correlated
  `presentation_state_update` lane. The host keeps one active request plus one
  merged pending state and rejects stale session/process acknowledgements.
  While production .NET presentation is active, migrated Builder callbacks
  return through that lane instead of mutating only the legacy preview host.
  brush tools show their active button, gesture hint, and radius circle in the
  viewport. OBJ/glTF/GLB/DAE sources automatically apply the existing Flip V
  normalization, including imports prepared inside the preflight worker.
  a ready acknowledgement stops any covered native D3D11 sibling once so it
  cannot paint over the child. Production readiness is emitted only after
  textures/material bindings are applied and the Vortice viewport has presented
  its first frame. Renderer-blocked or failed embedded startup leaves preview
  unavailable; it never restores a native/classic Mesh Editor renderer. The helper uses
  `mesh_editor/dotnet_experiment_executable`,
  `CDMW_MESH_DOTNET_EXPERIMENT_EXE`, or the bundled
  `cdmw-mesh-dotnet-editor.exe`; stale configured paths fall through to
  bundled/dev discovery. A ready watchdog stops helpers that start but never
  become interactive. Texture resources are deduplicated and hard-linked where
  possible, .NET decode runs in the background, and native D3D11 uses Windows
  file identity to reuse hard-linked SRVs across package paths. The host builds
  the handoff package in
  `MeshDotNetExperimentPackageWorker`, and launches the process with input
  metadata, status, output, and edit-operation paths. Embedded interaction
  mirrors local selection to the resident C++ session, sends incremental
  strokes, and routes screen selection plus topology commands through
  `MeshEditCommandWorker` so native picking never blocks the Qt UI thread.
  Turning Part Pick off clears Builder highlights and the resident selection;
  Clear Selection uses the same authoritative selection bridge.
  The embedded tool panel shows the live authoritative action timeline and
  enables Undo/Redo from its cursor; Ctrl+Z, Ctrl+Y, and Ctrl+Shift+Z use the
  same background command path. Select and brush tools retain camera access
  through Ctrl+left-drag orbit, Shift+left-drag or middle/right-drag pan, and
  wheel zoom, with the active bindings displayed below the viewport.
  Grow, Shrink, and Invert operate only on the active vertex/edge/face domain;
  a retained part highlight cannot expand a vertex selection to the whole mesh.
  Visible-surface selection and brushes rasterize only their screen-space
  brush/region depth bounds, and one brush command shares that depth mask across
  all editable submeshes instead of rebuilding a full-viewport mask per part.
  New mutations are rejected while the worker owns the session. Closing the builder still
  uses ordered deactivation and sync; toggling Edit Mesh does not. Changed material
  inputs synchronize through resident material protocol v2. Material generation
  is ordered independently, so multiple newer material generations may target
  the same resident mesh revision; stale or future mesh revisions fail instead
  of poisoning the geometry revision stream. Helper lifecycle evidence owns the
  actual source-parse, geometry-upload, and device-reset counters, while package,
  process, and full-reload counters remain host-owned. Only a source or session
  replacement, device loss, or explicit process restart creates another
  package/process. Embedded geometry is never replaced from OBJ.
  Builder presentation updates use one active plus one merged pending request,
  correlated by session/request/process. Camera presets/Fit, display,
  quality/lighting, UV, grid/gizmo, highlight, hidden-part, routing, and
  per-part state acknowledge in .NET; stale responses are ignored and
  production-active callbacks bypass legacy-only presentation mutation.
  The .NET material manifest preserves source tint, surface, and emissive factors
  plus packed-channel selectors; glTF metallic-roughness reuses one decoded image
  while sampling roughness from G and metallic from B. A Python-owned resource
  policy declares role, scene submesh, channel, profile, criticality, and
  fallback for every texture. Initial Ready waits for resource resolution and a
  presented frame: a missing declared-required base blocks Ready, while optional
  channels retain their declared fallback and diagnostic. Late original archive
  resources enter the existing reference-role material generation without an
  export commit, package rebuild, camera change, or process restart. Normal-map
  space is also explicit per submesh; glTF/green-up inputs invert green in the
  DirectX shader while DirectX inputs are preserved. PNG-only sessions do not
  report DDS-upload parity warnings. The focused profile corpus records every
  supported profile's channels, criticality, scalar/tint/normal-Y/layer rules,
  real PAC and external-catalogue input fingerprints, and synthetic failure
  cases without claiming visual parity beyond production capture evidence. Its
  representative hair PAC is DDS-backed and corpus generation fails if that
  source resource no longer resolves.
  Package-time material-graph baking keeps source DDS paths authoritative for
  renderer binding and decodes cached PNG previews only for combiner operands.
  Color layers and albedo blend masks use a 512 px cap; direct native normal and
  height DDS maps retain their source resolution and mip chains. Missing or
  unreadable operands fail closed to the raw channel set instead of publishing a
  flat neutral material. Synthesized PNG outputs use a typeless BGRA bitmap
  resource with semantic sRGB or linear views; Vortice uploads the top level,
  generates the complete GPU mip chain, and reports source/GPU mip counts and
  full-chain byte accounting in renderer diagnostics.
  The production bridge prefers an existing source DDS over preview PNG and
  transports channel semantic, evidence authority, sRGB/linear interpretation,
  shader family, alpha mode/cutoff, double-sided state, and unsupported-family
  diagnostics. Vortice uploads supported 2D DDS as immutable native DXGI
  resources with every validated mip; resident dirty-region edits copy only the
  affected resource into a full mutable BGRA mip chain. Each boxed top-level
  upload regenerates that resource's lower mips through its semantic sRGB or
  linear view and reports the editable mip count in renderer evidence. The shader uses
  sRGB-aware views/output, GGX/Smith/Schlick response, separate opacity and
  occlusion inputs, proven cutout, and per-material culling. Blend ordering,
  family layer graphs, hair/fur anisotropy, and captured skin subsurface/wrinkle
  response remain explicit gaps. Classified skin, cloth, and hair nevertheless
  use the native preview's conservative nonmetal contract: zero metalness,
  family roughness floors, achromatic capped dielectric specular, and the same
  family depth-authority values that keep texture hue stable as the camera
  moves. This is an inspection fallback, not exact game-shader parity.
  The flip-discard swap chain remains single-sampled, while the production
  renderer selects a preferred 4x offscreen MSAA color/depth surface (2x, then
  1x fallback when the exact formats are unsupported). Opaque, transparent,
  grid, selection, gizmo, and pane-divider passes share that surface and resolve
  once into the swap-chain backbuffer before Present. Hidden icon and visual
  audit captures use the same sample description, resolve into a 1x readback
  texture, and report sample count, resolve activity, render-surface identity,
  lifecycle counts, and surface-memory estimates. MSAA improves polygon-edge
  coverage; it does not replace source texture resolution, mip generation,
  alpha-cutout filtering, or unsupported material-family shading.
  Native original-reference material batches are applied by authoritative local
  submesh identity. Secondary/prefab batches are decoded as separate
  original-reference-only geometry; they never enter the editable replacement,
  export, or archive-mutation authority. Archive Browser composite previews
  initially hide those prefab batches while leaving the base component visible;
  the Parts menu can explicitly show them. Layer-only detail, damage, grime,
  dye, and overlay textures remain diagnostic bindings and are not promoted
  into a primary base channel when their blend graph is unavailable. None of
  these material changes rebuilds the package, restarts the
  process, replaces the viewport, or moves decode work onto the UI thread.
  For standalone/headless process exits, `MeshDotNetExperimentOutputImportWorker` detects `edited_mesh`,
  `edited_obj`, `output_mesh`, `edited_package`, or `output/mesh.obj`, restores
  the package sidecar if the editor wrote only OBJ geometry, imports through
  `import_obj()`, applies any saved safe edit-operation list, and reruns export
  validation before rebuild can be enabled. Preparation is detached and
  cancellable; it records session identity and expected revision. The service
  then performs one narrow noninterruptible compare-and-swap commit under its
  lock. Cancellation or stale/closed state before commit leaves the live mesh
  unchanged, while a commit that has started always publishes its terminal
  result. Process exits, successful imports,
  and import failures write `dotnet_evaluation.md` in the handoff package,
  comparing reported .NET FPS, frame time, responsiveness, crash behavior,
  memory, packaging complexity, and maintenance complexity against any
  Python/C++ baseline the status JSON provides. Packaged startup smoke can set
  `CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET=1` with a mesh asset to run the bundled
  helper in headless mode, import its output, validate it, and require a
  `replace_positions_same_count` operation, the evaluation file, and positive
  FPS/frame-time metrics. `tools/dotnet_mesh_editor_experiment` is the current WinForms
  viewport: D3D11 materials, vertex/edge/face/part selection, host-owned mesh
  tools, status metrics, same-count diagnostic output, and headless smoke mode.
  Its D3D11 path retains vertex/index buffers across resident edits. Live
  position/normal/UV packets carry exact source-vertex indices; precomputed
  source-channel-to-render-corner maps expand those indices only to incident
  faces and upload contiguous affected buffer byte ranges. Ordinary topology
  updates replace only affected submesh batches. Versioned replace-all packets
  carry a complete snapshot, explicit final submesh count, and original
  material lineage for add/remove/reindex operations. Material SRV
  binding arrays are cached per batch instead of allocated per draw.
  `geometry_resources` renderer status reports full rebuilds, sparse updates,
  upload ranges, live resource ages, estimated resident bytes, and measured
  old-plus-new geometry/texture peak estimates. It also reports stable geometry
  buffer/material-binding identities and sampled DXGI local-memory usage.
  `--headless-gpu-sparse-soak` creates its million-vertex fixture in memory,
  owns a hidden/offscreen HWND without calling `Show` or `Application.Run`, and
  drives 1,000 paced sparse uploads through this production D3D11 resource
  path. It renders verified frames before and after the paced interval; this
  matches production's invalidation/coalescing model instead of serializing
  every edit handler behind `Present`. Its versioned JSON gates handler p95, topology/buffer retention,
  upload counters, cached SRV binding arrays, VRAM estimates, post-warmup
  working-set growth, and hidden-window proof. `--gpu-soak-smoke` permits an
  explicitly non-release reduced diagnostic run.
  `--headless-gpu-frame-pacing-soak --frame-pacing-report <path>
  --frame-pacing-duration-seconds <n> --frame-pacing-target-hz <n>` is the
  sustained hidden presentation gate. It performs the configured warm-up before
  capture, keeps the production device/swap chain resident, and writes
  `cdmw_dotnet_preview_performance_v1` evidence with raw frame, render, Present,
  correlated delayed D3D11 GPU-query, input-latency, heartbeat, allocation, GC,
  queue, resource-identity, RAM, and VRAM samples. Query coverage must resolve
  every issued sample except the bounded in-flight query ring; disjoint or
  dropped queries fail the report. The normal editor keeps only constant-time
  counters active. Percentiles, full diagnostics, DXGI memory, hashing, and JSON
  serialization are outside the render loop. Capture rings are allocated and
  page-committed before the working-set baseline; the report records their byte
  size so ten-minute RAM growth does not mistake lazy instrumentation-page
  commitment for renderer growth.
  The resident helper advertises additive `performance_capture_v1` start/stop
  messages. The canonical real-PAC harness accepts a strict
  `cdmw_dotnet_preview_performance_manifest_v1` only for
  `real-archive-mesh-editor-dotnet-edit-smoke`, prepares the selected PAC once,
  sizes the Qt host to the requested capture resolution, and schedules declared
  camera, Side by Side, overlay/highlight, selection/brush, material, texture,
  topology, and resize workloads with a monotonic rate. Ordered control/final
  protocol events are non-droppable; high-frequency immutable updates retain
  one latest pending value per correlated stream. Texture updates retain one
  latest pending value per resource and upload/generate mips at most once per
  presented frame. Final material, texture, topology, display, and size states
  are restored and acknowledged before the report is closed.
  Release acceptance at 1920x1080/144 Hz requires frame interval p95 at most
  8.68 ms, p99 at most 13.89 ms, fewer than 0.1% of intervals above 13.89 ms,
  no interval above 20.83 ms, input-to-present p95 at most 13.89 ms, host
  heartbeats at most 33.3 ms, no captured-frame managed allocations, no Gen1 or
  Gen2 collection, queue depth at most one, complete input/final-revision
  accounting, stable device/resource identities, and at most 5% post-warm-up
  RAM/VRAM growth. CPU and GPU p99 must remain below 16.7 ms. The windowed path
  remains flip-discard with VSync `Present(1)` and maximum frame latency one;
  its offscreen MSAA resolve must retain one render-surface identity and exactly
  one resolve per presented frame without fixed-size surface churn. It does not
  enable tearing, adaptive quality, or a UI-thread waitable-object wait.
  Explicit performance capture uses a balanced 1 ms Windows timer-resolution
  request and a generation-guarded worker timer that posts at most one pending
  invalidation to the WinForms owner; normal editor use does not raise timer
  resolution. Continuous Qt-parent resize remains an end-to-end hard-gate
  workload and must not be omitted when the other interaction segments pass.
  The helper uses Vortice 3.8.3 on .NET 8.
  Sparse camera bounds retain the six current extremum owners. Interior edits
  update bounds and center in O(changed vertices); moving an extremum inward
  triggers one exact rebase, preventing stale camera and picking coordinates.
  The native-core release soak submits 1,000 paced 64-vertex sparse brush-size
  batches against a million-vertex resident mesh. Latest-wins coalescing may
  discard an overdue pending packet, but every input must be accounted for,
  submission cadence must remain within the 60 Hz gate, and handler p95 must
  remain below 16.7 ms.
  Headless smoke applies a deterministic `+0.001` X translation to submesh 0 so
  the package handoff proves a real same-count edit operation rather than a
  no-op save.
  `build_pyside6_app.ps1` publishes it into
  `native/cdmw_mesh_dotnet_editor/build/<Config>` so PyInstaller can bundle it.
  Release publish writes `cdmw-mesh-dotnet-editor.manifest.json` beside the
  helper and shader. The helper reports semantic/protocol version, manifest or
  development identity, process/assembly/shader SHA-256, renderer/edit backend,
  and capabilities; Python rejects release Ready when the launched files and
  report do not match. Deterministic icon generation uses a correlated
  replacement-only offscreen D3D11 target inside the package output root and
  excludes UI, grid, gizmo, selection, hover, and visible-state mutation.
- Embedded .NET launch diagnostics are persisted through Mesh Editor runtime
  events and the handoff package. Failed launches record executable resolution,
  package paths, parent HWND, process state, QProcess error details, exit
  status, stdout/stderr tails, status JSON summary, toolbar ownership,
  renderer blockers, and `dotnet_launch_diagnostics.json`. The legacy native
  preview button and automatic fallback entry points are disabled; native
  renderer scenarios remain compatibility-only and opt-in.
- External static replacement/import previews clear inherited reference
  skeleton and physics overlay metadata by default. Overlays are preserved only
  through explicit diagnostic/overlay paths. Native original-reference splicing
  recognizes both top-level and `editor_identity.role` ownership, and its v3
  cache key prevents stale packages with duplicate reference geometry.
- External OBJ/DAE/glTF/GLB imports with missing or incomplete UVs run the
  bundled native xatlas unwrap before the mesh is exposed, forward
  cancellation, validate every previously aligned vertex channel, refresh
  totals, and report the result as review-required. If unwrap is unavailable or
  incomplete, import blocks with an exact Blender/DCC TEXCOORD_0 remedy. PAC and
  PAM imports are never auto-unwrapped. A glTF material whose slots share one
  UV set and one complete KHR texture transform is converted losslessly: the
  affine transform runs in raw glTF UV space before the internal V flip, and
  published material slots are normalized to TEXCOORD_0 with an identity
  transform. Materials with different UV sets or per-slot transforms aggregate
  their primitives into one bundled xatlas layout, regenerate MikkTSpace
  tangents, and raster-bake each slot through its wrap/filter sampler. Color
  slots interpolate in linearized sRGB, data slots remain linear, and normal
  samples transform between source and destination tangent bases. Generated
  PNGs publish atomically with eight-pixel chart gutters, provenance/content
  hashes, and source dimensions (or a reported 4096-ceiling downscale). The
  versioned UV-bake report retains source slot, UV, transform, sampler, layout,
  dimensions, warnings, and output evidence. Missing, incomplete, sparse,
  compressed, or unsupported inputs block safely with an exact remedy.
- Active Material Authority uses one evaluator for live/export values and one
  revisioned resident parameter bridge. Automatic and Manual are the normal
  profiles; obsolete aliases migrate to Automatic. Controls without a live
  target resource-rebind or height path disable during the active editor with
  a precise reason instead of becoming enabled no-ops. Parts selection,
  routing, roles, visibility, duplicate/delete, and metadata-aware undo/redo
  share the resident session and atomic all-part material packets.
- Hiding a part never recomputes the alignment basis or camera center; surviving
  parts retain exact placement. Duplicate/Delete are visible beside the compact
  Parts list and route through the same resident mutations as context actions.
- Production viewport modes include textured solid plus untextured faces, wire,
  vertices, and combinations without texture/SRV churn. `Faces (No Textures)`
  uses a dedicated two-sided camera-relative workbench shader: inverse-transpose
  normal transforms, safe zero-normal fallback, wrapped key/fill light, rim
  shaping, and a fixed illumination floor keep projected faces distinct from
  the dark viewport from front, back, and oblique cameras. It does not depend on
  texture/material brightness settings and does not restart or reload the
  resident scene. Wheel and programmatic zoom are clamped from `0.1x` through
  `64x` the pane's fitted zoom. Ordinary vertex dots and wire visual weight are
  also pane-local and fit-relative below `1x`: dots shrink from 7 pixels to a
  2-pixel readability floor, while 1.35-pixel D3D11 wire lines reduce opacity
  to a 20% floor. The normal wire and vertex colors are user-selectable and
  persisted in the local mesh-editor preferences. X-Ray is carried separately
  in each presentation context, switches automatically to high-contrast white
  wire and magenta vertices, and draws wire, vertices, and selection overlays
  without depth rejection; X-Ray picking likewise includes occluded topology.
  Zooming in does not enlarge either overlay beyond its fitted weight; selected
  markers, hover feedback, and picking tolerances stay unchanged.
- Initial external imports and appended parts share the same work-area fit
  helper. External imports are centered against the reference/work area and
  bottom-aligned to the Y-up D3D11 preview grid, while Modify Original clones
  keep their existing coordinates. Full Import Model Replacement also keeps
  the locked placement preset on grid-flat alignment.
- Model Library D3D11 preview derives high-quality texture packaging from the
  active render setting and logs the actual value instead of forcing low-quality
  packages.
- Archive Browser starts each newly selected mesh package in a fitted overhead
  view (`yaw=0`, `pitch=-89`). Refreshing the same model preserves its current
  camera; the initial framing is presentation-only and never changes mesh or
  export transforms.
- Exact import proof uses
  `character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0016.pac`
  with `wolf_gravestone_sword_free (1).zip`: original batches use archive-resolved
  bindings, imported batches use ZIP textures, and both retain one grid/alignment.

## Current Test Coverage

- Existing mesh suites cover Mesh Editor service behavior, native session
  routing, OBJ round-trip sidecars, static replacement, import preview, and
  archive export naming.
- `tests/test_mesh_asset_pipeline.py` now covers the first MeshAsset adapter,
  inferred skinning inspect metadata, validator, binary diff,
  strict/tolerant no-edit round-trip reporting, and structured rebuild reports.
- `tests/test_mesh_pipeline_cli.py` covers CLI export, import, validation,
  source-hash blocking, public validation field shape, and rebuild
  output/report wiring.
- `tests/test_mesh_service_editing.py` covers service-level rebuild-report and
  patched-asset write gating plus OBJ sidecar source-hash rejection before
  session replacement, topology/LOD/source-map expected/actual validation
  fields, native-clone MeshAsset LOD identity preservation, and
  `tests/test_mesh_editor_action_bar.py` covers the
  passive Rebuild panel rows, report JSON saving, patched-asset rebuild button
  gating, the background report/asset worker, editable package export/import
  worker wiring, background validation refresh, and validation-report clipboard
  copy.
- `tests/test_mesh_edit_operations.py` covers the operation-list JSON shape and
  same-count/blocked operation validation.
- `tests/test_mesh_dotnet_experiment.py` covers the .NET experiment handoff
  package/command shape, helper binary resolution, packaging script/spec guard,
  edited-output import helper, and generated evaluation note, and
  `tests/test_mesh_editor_action_bar.py` covers the configured launch button,
  process wiring, output-import trigger, and native performance status label.
- `tests/test_dotnet_gpu_geometry_resources.py` guards retained topology
  generations, sparse incident-face uploads, cached material bindings, and the
  renderer resource-metric contract.
- `tests/test_dotnet_topology_channel_updates.py` covers atomic JSON/binary
  position/normal/UV packets, malformed-packet rejection, missing/separate
  channel alignment, affected-only topology batches, complete part
  add/remove/reindex snapshots, and material-lineage preservation.
- `tests/test_scene_import_uv_contract.py` covers missing/incomplete UV
  generation and failure remedies for OBJ, DAE, glTF, and GLB, including
  cancellation and aligned-channel preservation.
- `tests/test_mesh_edit_revision_protocol.py` covers stale/future ack rejection,
  revision-zero compatibility, rejected-update accounting, and native/.NET
  capability contracts. `tests/test_native_preview_package_cache_concurrency.py`
  covers renderer-lifetime package leases, reload retirement, prune, and cancel.
- `tests/test_mesh_history_bounds.py` covers Python count/byte eviction, native
  sparse exact undo/redo branching, 64-unit eviction, retained-byte evidence,
  topology snapshot swapping, selected-submesh cleanup scope, metadata-only
  material history, inline sparse service transport, and compatibility of the
  existing file protocol and summary fields.
- `tests/test_mesh_dotnet_live_stroke_dispatch.py` covers the production
  embedded .NET queue-depth-one, latest-wins stroke path. The explicit
  `real-archive-mesh-editor-dotnet-edit-smoke` binds real archive DDS files,
  drives the actual Vortice viewport HWND, and gates renderer/edit backends,
  selected-only geometry, linked texture region updates, committed assignment,
  UV/topology undo/redo, coherent export/readback, stable PID/HWND, UI timing,
  captures, and archive hash identity. Scenario-registry validation rejects any
  production visual role that does not name Vortice and marks legacy/checker
  visual roles compatibility-only outside normal/full QA.
- `native-mesh-editor-sparse-update-soak` is the headless Phase 3 exit gate: a
  one-million-vertex session receives 1,000 sparse updates at 60 Hz and records
  submit p95, queue depth, exact undo/redo, retained history bytes, native
  fallback events, and post-warmup process-memory growth.
