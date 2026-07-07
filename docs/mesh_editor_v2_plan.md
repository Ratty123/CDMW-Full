# Mesh Editor v2 Plan

Status: Phase 0 implementation map, 2026-07-06.

This note maps the current Python/C++ mesh editing pipeline before more v2
work. It should stay short and factual; detailed feature-state notes remain in
`docs/features/mesh-editing-pipeline.md`.

## Current Parser Entry Points

- `cdmw/modding/mesh_parser.py` owns the compatibility parser shape:
  `ParsedMesh`, `SubMesh`, `MeshVertex`, `MeshBinaryLayout`, `parse_mesh()`,
  `parse_pac()`, `parse_pam()`, `parse_pamlod()`, `build_preview_mesh()`, and
  `inspect_mesh_binary_layout()`.
- Parser confidence is already surfaced as `layout_confidence` with `exact`,
  `inferred`, and `fallback_scan` values. PAC can reach `exact` when descriptor
  offsets and vertex offsets are recovered; PAM/PAMLOD can still be inferred or
  fallback scan based.
- `cdmw/modding/mesh_asset.py` adapts `ParsedMesh` into the stricter
  `MeshAsset` contract, preserving source offsets, vertex stride, raw vertex
  records, material slots, LODs, and binary layout metadata where current parser
  output exposes them.
- `cdmw/domain/mesh/asset.py` owns the domain model and initial rebuild
  validator: `MeshAsset`, `MeshLod`, `MeshAssetSubmesh`, `VertexBuffer`,
  `IndexBuffer`, `BinaryLayout`, `MaterialSlot`, `MeshValidationIssue`, and
  `validate_mesh_asset_rebuild()`.

## Current Mesh Editor UI Entry Points

- `cdmw/ui/mesh_editor/tab.py` owns the tab shell, standalone sessions,
  asynchronous file loading, D3D11 preview launch, and worker wiring.
- `cdmw/ui/mesh_editor/controller.py` is the UI-to-service bridge. It opens
  sessions, routes action descriptors, exposes validation/workspace/compare/UV
  and skeleton summaries, and converts edit results into native preview payloads.
- `cdmw/ui/mesh_editor/workspace.py`, `actions.py`, and `action_bar.py` own the
  visible tool surface, including the native Performance panel and FPS/frame-time
  status, and emit descriptors only.
- `cdmw/services/mesh_service.py` owns edit sessions, command application,
  native resident-session state, export validation, history, and summaries.
- `cdmw/workers/mesh_editor_workers.py` keeps file loading, native preview
  package creation, and edit-command execution off the UI thread.
- Archive Browser entry points currently open export/import actions through
  `cdmw/ui/archive_browser/actions.py` and bridge static replacement edits with
  `cdmw/ui/mesh_editor/static_replacement_adapter.py`.

## Current Import and Export Flow

- OBJ export starts in `cdmw/modding/mesh_exporter.py`. It writes OBJ/MTL and a
  `mesh_roundtrip_manifest_v2` sidecar via `write_roundtrip_manifest()`.
- GLB editable-package export/import starts in
  `cdmw/modding/mesh_glb_interchange.py`. It writes `mesh.glb` and reuses the
  same `mesh_roundtrip_manifest_v2` sidecar contract.
- FBX export also lives in `mesh_exporter.py`, but it is visual interchange for
  this safety track, not a complete game-asset source of truth.
- OBJ import starts in `cdmw/modding/mesh_obj_importer.py`. It reads the OBJ,
  material library texture references, and known OBJ sidecar formats
  (`obj_meta_v1`, `mesh_roundtrip_manifest_v2`) when present.
- Standalone Mesh Editor export/import actions now use
  `MeshEditablePackageExportWorker` and `MeshEditablePackageImportWorker` to keep
  editable-package disk I/O, OBJ sidecar import, session replacement, and export
  validation off the UI thread. The same toolbar also exposes `Open` for the
  last exported editable package folder.
- The Checks panel has `Run` and `Copy` actions. `Run` refreshes export
  validation through `MeshExportValidationWorker` off the UI thread, and `Copy`
  copies the active structured export validation report as JSON.
- The Rebuild panel has `Run`, `Rebuild`, `Preview`, `Package`, and `Save` actions. `Run` generates
  the validation-gated in-memory rebuild report, `Rebuild` writes a validated
  patched asset to a separate chosen file through `MeshService.rebuild_asset()`,
  `Preview` routes the last rebuilt file to the existing archive import-preview
  flow when the session has an archive target, `Package` routes the same file to
  the existing archive package/patch flow, and `Save` writes the last report JSON
  without rerunning rebuild work.
- Archive import preview flows through
  `cdmw/core/archive_mesh_import_preview.py::build_mesh_import_preview()`.
  Round-trip edit mode still calls `build_mesh()` through sidecar-backed
  package import; raw DAE/glTF/GLB scene files route through visual/static
  replacement paths instead.
- Static/full replacement uses
  `cdmw/modding/static_mesh_build.py::build_static_mesh_replacement()` and can
  generate material/texture supplemental payloads when sidecars and replacement
  options provide enough context.

## Current Rebuild Flow

- `cdmw/modding/mesh_importer.py::build_mesh()` is the rebuild facade for
  PAC/PAM/PAMLOD.
- The current order is: no-edit byte-preservation fast path, native rebuild via
  `cdmw/core/mesh_native.py::build_mesh_native()`, then Python builders.
- Python builders are format-specific:
  `mesh_pac_builder.py::build_pac()`, `mesh_pam_builder.py::build_pam()`, and
  `mesh_pamlod_builder.py::build_pamlod()`.
- PAM edits can be transferred to paired PAMLOD with
  `transfer_pam_edit_to_pamlod_mesh()` inside import preview.
- `cdmw/modding/mesh_roundtrip.py` and `tools/mesh_pipeline.py` provide the
  current CLI mesh pipeline harness: `inspect`, `roundtrip`, `export`,
  `import`, `validate`, and `rebuild`.

## Current Native C++ Integration

- `cdmw/modding/mesh_native_core.py` is the Python wrapper for the native mesh
  editor core at `native/cdmw_mesh_core`. It owns resident edit sessions,
  selection, transform/brush/topology/UV/normal/skin-weight commands, native
  preview geometry blobs, and native OBJ/FBX helpers.
- `cdmw/core/mesh_native.py` is the rebuild/audit wrapper using the native
  preview core binary. It only allows native rebuilds when the current format
  and edit shape are marked safe by parity gates.
- Native editor results are allowed to keep the Python mesh dirty until an
  explicit sync, so UI and export paths must ask `MeshService` for the
  authoritative state instead of reading stale `ParsedMesh` directly.

## Current Preview and Renderer Integration

- Mesh Editor D3D11 package creation is in
  `cdmw/ui/mesh_editor/native_preview_runtime.py`.
- Mesh-to-preview payload packing is in
  `cdmw/ui/mesh_editor/native_preview_payloads.py`. Active Mesh Editor preview
  paths fail closed when native preview geometry is unavailable.
- The package writer and host lookup live under `cdmw/rendering/`, especially
  `native_preview_package_writer.py` and `native_d3d11_host.py`.
- Archive Browser/static replacement preview still has separate model-preview
  paths in `cdmw/core/archive_mesh_import_preview.py`.

## Current Build and Packaging Process

- `build_pyside6_app.ps1` is the main Windows app build script. It supports
  `onefile` and `onedir` modes plus `fast`, `debug`, and `release` profiles.
- `build_native_windows.ps1` builds the native helpers with CMake/MSVC.
- `CrimsonDesertModWorkbench.spec` packages Python code and required native
  binaries. Release builds require:
  `cd-texture-dx.exe`, `cdmw-preview-core.exe`,
  `cdmw-d3d11-preview.exe`, and `cdmw-mesh-core.exe`; archive accelerator and
  HKX helpers are optional.
- `docs/test-matrix.md` owns the release packaging command:
  `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -Mode onefile -BuildProfile release`.

## Current Performance Bottlenecks

- Repeated parse/rebuild/parse in import preview is expensive for large meshes,
  especially when validation, texture sidecar discovery, and preview generation
  happen in one flow.
- Native resident editing is the right 60fps path, but IPC/session sync and
  preview package rewrites can dominate if every small UI action forces full
  mesh serialization.
- Python fallback rebuilders still matter for safety and compatibility, but
  they are not the target for interactive editing performance.
- D3D11 preview packages are currently built asynchronously, which protects the
  UI thread; v2 should keep that boundary and avoid synchronous parse/rebuild or
  package writes from widgets.
- Large `mesh_native_core.py` session/report translation is a maintenance and
  profiling hotspot. New v2 contracts should add narrow payloads instead of
  broader generic report shapes.

## Metadata Loss Risks

- `ParsedMesh` is still a compatibility shape. It carries useful source offsets,
  descriptor offsets, materials, textures, UVs, normals, bones, weights, and
  source maps, but it does not fully own unknown sections or original raw binary
  layout as a rebuild contract.
- The GLB/OBJ editable package plus `mesh_roundtrip_manifest_v2` preserves
  visible geometry, material and texture names, counts, source vertex maps,
  source index maps, MeshAsset LOD identity, raw vertex record evidence, and
  unknown-field metadata. Raw source bytes and binary section order remain owned
  by the original asset plus MeshAsset contract.
- FBX, DAE, glTF, and GLB scene imports are visual inputs unless they are part
  of a sidecar-backed Crimson editable package.
- Static replacement can intentionally change topology and draw-section mapping.
  That should remain a separate operation from safe round-trip edits.
- Any fallback-scan layout is unsafe for destructive rebuild unless the user has
  an explicit override and the rebuild report names the risk.

## Recommended v2 Integration Points

- Keep `MeshAsset` in `cdmw/domain/mesh/asset.py` as the strict contract. Extend
  this model before adding more UI behavior.
- Keep parser adapters in `cdmw/modding/mesh_asset.py`; do not move parser
  heuristics into UI or native code.
- Add sidecar/CD mesh interchange beside existing modding import/export helpers,
  then route OBJ/GLB package import through that contract instead of treating
  visual mesh files as complete data.
- Keep standalone UI package actions thin over the worker/service path: export
  package, open the exported package folder, import edited package, replace
  through `MeshService`, then rerun validation before rebuild state changes.
- Keep validation report actions thin over the existing service report object;
  background refresh should call `MeshService.validate_export()`, and copy/save
  actions should not scrape tree-widget text for exportable data.
- Keep final patched-asset rebuild thin over `MeshService.rebuild_asset()` so
  the UI shares the same validation gate and source-overwrite guard as tests.
- Keep developer override narrow: it is enabled only by explicit Mesh Editor
  developer settings, writes to a separate output path, records the reason and
  unsafe condition codes in the rebuild report, and does not bypass topology,
  sidecar, skeleton, material, source-map, or operation blockers.
- Harden `cdmw/modding/mesh_importer.py::build_mesh()` behind a safe rebuild API
  that consumes original bytes, a validated `MeshAsset`, edit operations, and a
  structured rebuild report.
- Keep `tools/mesh_pipeline.py export|import|validate|rebuild` thin over the
  same service/importer/rebuilder gates that the UI uses, so CLI checks remain
  useful proof instead of a separate mesh implementation.
- Put v2 validation ownership in the domain/service boundary:
  `validate_mesh_asset_rebuild()` for pure rules, `MeshService` for session/UI
  presentation, and `MeshEditorController.export_validation_report()` for UI
  access.
- Keep native C++ focused on interactive mesh editing, selection, preview blobs,
  and fast channel operations. Python should remain the owner of PAC/PAM/PAMLOD
  metadata policy and archive mutation safety.
- Update `CrimsonDesertModWorkbench.spec` only when v2 adds real packaged assets
  such as schemas, default sidecar templates, or new native helper binaries.
- The first .NET experiment integration point is now an external process
  launched from standalone Mesh Editor. It receives an exported OBJ package with
  `mesh.cdmeta.json`, original hash, status, output, and edit operation paths;
  Python/C++ remain parser, validator, rebuilder, and package authority. When
  the process exits with an edited OBJ in the declared output package, the
  standalone UI imports it through `MeshDotNetExperimentOutputImportWorker`,
  preserves the sidecar/operation contract, replaces the working mesh through
  `MeshService`, reruns validation, and writes `dotnet_evaluation.md` with the
  current keep/drop recommendation from reported metrics and validation status.
  `tools/dotnet_mesh_editor_experiment` provides the current WinForms wireframe
  prototype and `build_pyside6_app.ps1` publishes it into
  `native/cdmw_mesh_dotnet_editor/build/<Config>` for EXE packaging.

## Current Acceptance Audit

Last audited: 2026-07-06.

This is the current evidence map for the final 20 acceptance criteria. It is
not a goal-complete claim; final release still needs the last gate rerun after
all code changes settle.

| # | Criterion | Current evidence | Status |
|---|---|---|---|
| 1 | Mesh Editor v2 is accessible from main UI | `cdmw/ui/shell/tool_tabs.py` constructs `MeshEditorTab`, adds the `Mesh Editor` asset tab, and registers the detachable tool. `CDMW_GUI_STARTUP_SMOKE_TARGET=mesh_editor` verifies required widgets. | Proved |
| 2 | Included in final EXE | `CrimsonDesertModWorkbench.spec` bundles schemas/native helpers/.NET helper; `build_pyside6_app.ps1` publishes native and .NET helpers. Latest release onefile build and startup smoke are recorded in `docs/release-confidence-plan.md`. | Proved by latest release build; rerun after final code edits |
| 3 | MeshAsset v2 preserves binary identity | `cdmw/domain/mesh/asset.py` owns `MeshAsset`, `BinaryLayout`, raw vertex records, offsets, unknown sections, LOD/submesh identity; `cdmw/modding/mesh_asset.py` adapts parsed meshes. | Proved |
| 4 | Parser confidence is shown in UI | `MeshEditorWorkspace.update_export_validation()` and `update_rebuild_report()` display `parse_confidence`. Startup smoke requires validation state on loaded PAC. | Proved |
| 5 | No-op round-trip exists and is shown in UI | `MeshService.load_mesh_file(..., run_roundtrip=True)` records `_cdmw_no_op_roundtrip_report`; validation UI displays `no_op_roundtrip`; startup smoke requires `PASS`. | Proved |
| 6 | Sidecar-based interchange exists | Editable package export writes `mesh.glb`, `mesh.obj`, `mesh.cdmeta.json`, and `original_asset_hash.txt`; GLB/OBJ import require the sidecar contract. | Proved |
| 7 | OBJ-only reimport is not safe source of truth | OBJ/GLB sidecar import rejects missing/unsupported sidecars for editable packages; imported OBJ sidecar rebuild requires explicit operations. | Proved |
| 8 | Edited mesh import requires validation | `MeshEditablePackageImportWorker` imports then calls `MeshService.replace_working_mesh()` and `validate_export()`; startup smoke fails if imported validation is blocked. | Proved |
| 9 | Unsafe edits are blocked by default | `validate_mesh_export()` blocks topology/source-map/sidecar/parser/no-op failures; `MeshService.rebuild_report()` raises before rebuild unless validation passes or narrow developer override applies. | Proved |
| 10 | Skinned mesh bone data is preserved | Validation compares bone indices/weights and blocks missing skeleton metadata; sidecars include `bone_layout`; file sessions reuse inferred MeshAsset bone counts. | Proved for current safe rebuild path |
| 11 | LOD identity is preserved | MeshAsset/sidecar carry LOD section identity; export validation blocks `lod_identity_changed`; native clone preservation is covered by service tests. | Proved |
| 12 | Submesh identity is preserved | Sidecars carry stable IDs and submesh metadata; validation checks submesh counts/stable IDs/source offsets. | Proved |
| 13 | Unknown binary sections are preserved | MeshAsset stores `unknown_sections`; sidecar/export validation preserve unknown sections and submesh `unknown_fields`; changes block rebuild. | Proved |
| 14 | Rebuilder produces structured reports | `MeshService.rebuild_report()` and `rebuild_asset()` return `MeshRebuildReport` with hashes, validation status, operations, changed byte ranges, warnings, overrides, and output path; UI can save JSON. | Proved |
| 15 | Viewport targets 60 FPS+ | Real archive side-by-side D3D11 proof on actual PAC reports `live_stroke_frame_budget_ok=true`, handler p95 about 14.92 ms, no native fallback, and visual proof PNG. | Proved for live edit proof; keep final performance gate |
| 16 | Heavy mesh operations do not freeze UI | Parse/import/validation/rebuild run through workers; latest Qt responsiveness/cancel harness reported dispatch near 0.06 ms, first progress under 3 ms, cancel latency about 31 ms. | Proved |
| 17 | FPS and frame time are visible | Workspace toolbar label and Performance panel show current/average FPS and frame time plus CPU/GPU/draw/vertex/index/submesh metrics. | Proved |
| 18 | .NET experiment is implemented and connected | UI has `.NET` launch action; Python exports the sidecar package, launches external .NET editor, imports edited output, reruns validation, and blocks rebuild if invalid. | Proved |
| 19 | .NET experiment has keep/drop evaluation | `write_mesh_dotnet_experiment_evaluation()` writes `dotnet_evaluation.md` with FPS, frame, responsiveness, crash, memory, packaging, maintenance, and recommendation; packaged startup smoke requires it. | Proved |
| 20 | Existing unpacking, browsing, preview, packaging flows still work | Recent `smoke` and `archive` gates passed; Mesh Editor rebuilt preview/package actions route through existing archive import-preview and package/patch flows. | Proved by latest gates; rerun at final release gate |

Current final gates to keep before marking the goal complete:

- Real game visual proof: `.\scripts\codex_check.ps1 -Area mesh -GameRoot "C:\games\Steam\steamapps\common\Crimson Desert"`.
- Packaged Mesh Editor PAC smoke with rebuild and .NET:
  `QT_QPA_PLATFORM=offscreen`, `CDMW_GUI_STARTUP_SMOKE=1`,
  `CDMW_GUI_STARTUP_SMOKE_TARGET=mesh_editor`,
  `CDMW_GUI_STARTUP_SMOKE_MESH_ASSET=D:\Byggverkstaden\test_mesh_editor\cd_phm_00_nude_10_0001.pac`,
  `CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD=1`, and
  `CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET=1`.
- Non-mesh regression gates: `.\scripts\codex_check.ps1 -Area smoke` and
  `.\scripts\codex_check.ps1 -Area archive`.
- Synthetic/unit mesh regression is explicit only:
  `.\scripts\codex_check.ps1 -Area mesh-unit`; it is not visual proof and should
  not be cited as game-mesh proof.
