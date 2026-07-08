# Mesh Editing Pipeline

Status: first safety slice, 2026-07-06.

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
  - `cdmw.services.mesh_service.MeshService` owns edit sessions and validation.
  - `cdmw.ui.mesh_editor.controller.MeshEditorController` adapts UI actions to
    `MeshService`.
  - `cdmw.ui.mesh_editor.tab.MeshEditorTab` owns standalone and embedded UI.
  - Archive-browser static replacement delegates through
    `cdmw.ui.mesh_editor.static_replacement_adapter`.
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
- .NET experiment handoff:
  - `cdmw.services.mesh_dotnet_experiment` exports the active Mesh Editor
    session as an OBJ package plus `mesh_roundtrip_manifest_v2` sidecar,
    `mesh.cdmeta.json`, `original_asset_hash.txt`, status JSON, output folder,
    and launch manifest. The .NET process receives that package only; Python/C++
    remain the parser, validator, rebuilder, and packaging authority. When the
    process exits with an edited OBJ under the declared output package, the
    standalone UI imports it on a worker through the same OBJ sidecar contract,
    replaces the working mesh through `MeshService`, and refreshes validation.
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
- Skinned OBJ sidecars must include per-submesh `bone_layout` metadata and a
  complete `source_vertex_map` before import. Submeshes with empty bone rows are
  treated as unweighted within the skinned asset; only submeshes with positive
  `max_influences` require influence-count preservation. This blocks visual-only
  OBJ packages from pretending they can preserve bone rows.
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
  generated report as JSON without rerunning rebuild work.
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
- `Edit Mesh` is the embedded .NET entry point when the helper is available;
  the normal preview controls no longer expose a dedicated `.NET` button. The
  helper uses `mesh_editor/dotnet_experiment_executable`,
  `CDMW_MESH_DOTNET_EXPERIMENT_EXE`, or the bundled
  `cdmw-mesh-dotnet-editor.exe`, builds the handoff package in
  `MeshDotNetExperimentPackageWorker`, and launches the process with input
  metadata, status, output, and edit-operation paths. On process exit,
  `MeshDotNetExperimentOutputImportWorker` detects `edited_mesh`,
  `edited_obj`, `output_mesh`, `edited_package`, or `output/mesh.obj`, restores
  the package sidecar if the editor wrote only OBJ geometry, imports through
  `import_obj()`, applies any saved safe edit-operation list, syncs embedded
  output back into the replacement preview when launched from that surface,
  finalizes a textured/material preview rebuild from the edited working mesh,
  and reruns export validation before rebuild can be enabled. Process exits, successful imports,
  and import failures write `dotnet_evaluation.md` in the handoff package,
  comparing reported .NET FPS, frame time, responsiveness, crash behavior,
  memory, packaging complexity, and maintenance complexity against any
  Python/C++ baseline the status JSON provides. Packaged startup smoke can set
  `CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET=1` with a mesh asset to run the bundled
  helper in headless mode, import its output, validate it, and require a
  `replace_positions_same_count` operation, the evaluation file, and positive
  FPS/frame-time metrics. `tools/dotnet_mesh_editor_experiment` is the current WinForms
  prototype: OBJ wireframe viewport, submesh selection, basic X translation,
  same-count position operation output, status metrics, and headless smoke mode.
  Headless smoke applies a deterministic `+0.001` X translation to submesh 0 so
  the package handoff proves a real same-count edit operation rather than a
  no-op save.
  `build_pyside6_app.ps1` publishes it into
  `native/cdmw_mesh_dotnet_editor/build/<Config>` so PyInstaller can bundle it.
- Embedded .NET launch diagnostics are persisted through Mesh Editor runtime
  events and the handoff package. Failed launches record executable resolution,
  package paths, parent HWND, process state, QProcess error details, exit
  status, stdout/stderr tails, status JSON summary, and
  `dotnet_launch_diagnostics.json` before native/classic fallback starts.
- External static replacement/import previews clear inherited reference
  skeleton and physics overlay metadata by default. Overlays are preserved only
  through explicit diagnostic/overlay paths.
- Initial external imports and appended parts share the same work-area fit
  helper. External imports are centered against the reference/work area and
  bottom-aligned to the Y-up D3D11 preview grid, while Modify Original clones
  keep their existing coordinates.
- Model Library D3D11 preview derives high-quality texture packaging from the
  active render setting and logs the actual value instead of forcing low-quality
  packages.

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
