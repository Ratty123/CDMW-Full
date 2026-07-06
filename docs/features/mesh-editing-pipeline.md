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
  - OBJ export writes `mesh_roundtrip_manifest_v2` sidecar metadata through
    `cdmw.modding.mesh_exporter.write_roundtrip_manifest()`.
  - OBJ import reads that sidecar in `cdmw.modding.mesh_obj_importer.import_obj()`.
  - FBX export exists, but it is visual interchange only for this safety track.
  - DAE/glTF/GLB import preview exists in archive import preview flows, but it
    is not yet a safe game-asset rebuild source of truth.
- Preview package creation:
  - Mesh Editor D3D11 packages live under
    `cdmw.ui.mesh_editor.native_preview_runtime` and
    `cdmw.ui.mesh_editor.native_preview_payloads`.
  - Archive/static replacement preview packages use `cdmw.rendering.native_*`
    helpers and archive-browser static replacement callbacks.
- Archive patching:
  - UI actions route through archive-browser mesh patch/import flows, while
    destructive archive mutation policy remains outside Mesh Editor UI.

## Metadata Loss Risks

- `ParsedMesh` has useful source offsets, vertex stride, descriptor offsets,
  material names, bone rows, and source vertex maps, but it is still a
  compatibility shape rather than a strict rebuild contract.
- OBJ sidecars preserve submesh names, material names, texture names, vertex
  counts, face counts, and source vertex maps. They do not yet preserve raw
  vertex records, source index maps, binary section order, unknown fields,
  original file hash, or full LOD identity.
- FBX, DAE, glTF, and GLB preview/import paths carry visible geometry but not
  enough Crimson metadata for destructive rebuild by themselves.
- PAM/PAMLOD layout recovery can be inferred or fallback-scan based. Rebuild
  paths must treat that confidence as policy input before destructive writes.

## First Safety Slice

- `cdmw.domain.mesh.asset` defines `MeshAsset`, LOD, submesh, vertex/index
  buffers, binary layout, parser confidence, and structured validation issues.
- `cdmw.modding.mesh_asset` converts current `ParsedMesh` output into
  `MeshAsset`, preserving source offsets and raw vertex records when available.
- `cdmw.modding.mesh_roundtrip` runs no-edit parse, rebuild, binary diff, and
  strict/tolerant pass/fail reporting.
- `tools/mesh_pipeline.py inspect <asset> --out inspect.json` writes a MeshAsset
  inspection dump without opening the UI.
- `tools/mesh_pipeline.py roundtrip <asset> --out rebuilt_asset --report report.json`
  runs the no-edit round-trip harness.

## Current Test Coverage

- Existing mesh suites cover Mesh Editor service behavior, native session
  routing, OBJ round-trip sidecars, static replacement, import preview, and
  archive export naming.
- `tests/test_mesh_asset_pipeline.py` now covers the first MeshAsset adapter,
  validator, binary diff, and strict/tolerant no-edit round-trip reporting.
