# Release Confidence Plan

Last reviewed: 2026-07-08

## Goal

Prove the restructured app still imports, starts, packages, and keeps core user
workflows working. Do not start more large source splits unless validation shows
one is required.

## Read First

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/architecture.md`
4. `docs/project-map.md`
5. `docs/test-matrix.md` when choosing validation
6. `docs/project-map-detailed.md` only when package boundaries are unclear

## Current Focus

- Keep `cdmw_app.py` and `cdmw/ui/main_window.py` thin.
- Preserve compatibility facades and public imports.
- Fix concrete import, startup, source-guard, packaging, or workflow failures.
- Prefer focused behavior fixes over new architecture cleanup.
- Use `%TEMP%` for pytest `--basetemp` if `.pytest-tmp` is locked.

## Validation Order

1. Compile/import smoke over touched restructure surfaces and public facades.
2. Architecture guards:
   `tests/test_architecture_file_sizes.py`,
   `tests/test_architecture_public_facades.py`,
   `tests/test_architecture_import_boundaries.py`,
   `tests/test_architecture_no_wildcard_imports.py`.
3. Runtime/startup smoke from `docs/test-matrix.md`.
4. Focused archive, static replacement, texture, shell, worker, and packaging
   groups from `docs/test-matrix.md`.
5. Full suite only after focused groups are green or remaining failures are
   understood as external-data or environment problems.

## Done

- Relevant focused tests pass.
- Runtime/startup smoke passes.
- Packaging smoke passes or the exact blocker is documented.
- Remaining failures, if any, are classified with owner, command, and reason.

## Latest Validation

2026-07-08:

- Focused static replacement, D3D11 package, native preview core, and Mesh
  Editor action-bar tests passed: 353 passed.
- Alignment dialog and Mesh Edit responsiveness source guards passed: 149
  passed.
- Release dirty-tree preflight passes with untracked test files classified as
  non-runtime source/docs; generated output and untracked runtime source still
  block release packaging.
- `build.bat onedir release` produced
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows/CrimsonDesertModWorkbench.exe`
  14,414,778 bytes, SHA256
  `C7ACB5B8F7224D6491E076FBE199B72AED4A611AECB6313174739EF2217365EF`.
- Packaged onedir startup smoke passed with `QT_QPA_PLATFORM=offscreen` and
  `CDMW_GUI_STARTUP_SMOKE=1`.

2026-07-07:

- Full pytest suite passed from the current worktree: 4236 passed / 5 skipped.
- Release onefile package rebuilt from the current worktree, rebuilt native
  helpers, published the .NET Mesh Editor experiment helper, and validated all
  485 embedded archive members.
- Fresh packaged EXE startup smoke passed with `QT_QPA_PLATFORM=offscreen` and
  `CDMW_GUI_STARTUP_SMOKE=1`.
- Native Mesh Editor benchmark passed with native core available and no fallback
  events on a 100806-vertex / 200344-face session; resident edit/history metrics
  were present and `benchmark_target_ok=true`.
- Qt responsiveness and cancellation harnesses passed with native core available
  and no fallback events. Responsiveness dispatch returned in about `0.05 ms`
  with first progress in about `2.29 ms`; cancellation dispatch returned in
  about `0.07 ms` with first progress in about `2.33 ms` and cancel latency
  about `28.79 ms`.
- Packaged onefile Mesh Editor startup smoke passed against
  `D:\Byggverkstaden\test_mesh_editor\cd_phm_00_nude_10_0001.pac` with both
  `CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD=1` and
  `CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET=1`, covering file-session load,
  validation, no-op roundtrip, editable package export/import, rebuilt PAC
  output, .NET handoff, .NET output import, and post-import validation.
- Real-game Mesh Editor D3D11 proof passed through
  `.\scripts\codex_check.ps1 -Area mesh -GameRoot "C:\games\Steam\steamapps\common\Crimson Desert"`,
  using `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac`
  from `C:\games\Steam\steamapps\common\Crimson Desert\0009\0.pamt`.
  The proof used 7227 vertices / 13296 faces, selected and moved a real face
  cluster, had no native fallback events, kept live stroke handler p95 about
  `5.65 ms`, D3D11 send p95 about `0.228 ms`, and native apply roundtrip p95
  about `4.27 ms`, under the 16.7 ms handler frame budget. Latest proof output:
  `%TEMP%\cdmw-real-archive-mesh-editor-d3d11-side-by-side-codex-check`.
- Release artifact:
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`
  173,982,592 bytes, SHA256
  `73EE67214926667EB6A5B67C4A867D5877A720DDFD195550247FB73A61D04A8F`.

2026-07-06:

- Release onefile package rebuilt from the current MeshAsset GLB-first editable-package
  rebuild/.NET/developer-override smoke tree after the material-slot-count, raw-vertex-record,
  raw-record-sidecar, material-slot-sidecar, unknown-section-sidecar,
  unknown-field-sidecar, LOD-identity-sidecar, LOD-section-range, vertex-stride,
  source-offset, unknown-metadata, native-clone LOD metadata, and packaged
  `mesh.cdmeta.json` schema validation gates plus the real-game smoke guard, native helpers rebuilt,
  .NET Mesh Editor experiment helper published, 485 embedded archive members validated,
  packaged startup smoke passed, visible Mesh Editor native Performance panel and
  FPS/frame-time status wiring were focused-tested, and packaged Mesh Editor asset rebuild plus
  metric-enforced .NET handoff smoke passed with
  `QT_QPA_PLATFORM=offscreen`, `CDMW_GUI_STARTUP_SMOKE=1`,
  `CDMW_GUI_STARTUP_SMOKE_TARGET=mesh_editor`, and
  both `CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD=1` and
  `CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET=1`.
- Current real-game Mesh Editor D3D11 proof used
  `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` from
  `C:\games\Steam\steamapps\common\Crimson Desert\0009\0.pamt`.
  The latest side-by-side smoke selected and moved a real face cluster, wrote
  `real_archive_visual_edit_proof.png`, had no native fallback events, and kept
  live stroke handler p95 about `14.92 ms`, D3D11 send p95 about `0.256 ms`, and
  native apply roundtrip p95 about `13.16 ms`, under the 16.7 ms handler frame
  budget. Latest proof output:
  `%TEMP%\cdmw-real-archive-mesh-editor-d3d11-side-by-side-codex-check`.
- Mesh unit/protocol regression gate passed after the native preview
  malformed-geometry guard: the old synthetic mesh gate is now explicitly
  `.\scripts\codex_check.ps1 -Area mesh-unit`, not visual proof, and reported
  702 passed / 4 deselected.
- Non-mesh regression gates passed:
  `.\scripts\codex_check.ps1 -Area smoke` reported 8 passed, and
  `.\scripts\codex_check.ps1 -Area archive` reported 88 passed.
- Current Qt responsiveness/cancel harnesses passed with native core available
  and no fallback events. Responsiveness dispatch returned in about `0.06 ms`
  with first progress in about `2.49 ms`; cancellation dispatch returned in
  about `0.06 ms` with first progress in about `2.62 ms` and cancel latency
  about `31.1 ms`.
- The packaged Mesh Editor asset smoke loaded
  `D:\Byggverkstaden\test_mesh_editor\cd_phm_00_nude_10_0001.pac` through the
  real file-session path, required validation plus no-op roundtrip `PASS`,
  exported an editable package, reimported it, validated the imported package,
  wrote a rebuilt PAC to a temp output path, launched the bundled
  `cdmw-mesh-dotnet-editor.exe` helper in headless mode, imported the .NET
  output package, reran validation, and required a
  `replace_positions_same_count` edit operation, positive .NET FPS/frame-time
  metrics, and `dotnet_evaluation.md`.
- Onefile archive inspection found the Mesh Editor native/runtime helpers:
  `native\cdmw-mesh-core.exe`, `native\cdmw-d3d11-preview.exe`,
  `native\cdmw-preview-core.exe`, `native\cd-texture-dx.exe`, and
  `native\cdmw-mesh-dotnet-editor.exe`, plus
  `schemas\mesh\mesh.cdmeta.schema.json`.
- Release artifact:
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`
  173,980,247 bytes, SHA256
  `15C1783E16F5BA0D24B364F92DDC63966C1ACFBB92EB31BF65466D6A30807B8F`.

2026-07-05:

- Mesh unit/protocol gate: the old synthetic mesh gate is now explicitly
  `.\scripts\codex_check.ps1 -Area mesh-unit`, not visual proof, and passed
  with 647 passed / 4 deselected.
- Release onefile package built, native helpers rebuilt, 483 embedded archive
  members validated, and packaged startup smoke passed with
  `QT_QPA_PLATFORM=offscreen` and `CDMW_GUI_STARTUP_SMOKE=1`.
- Release artifact:
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`
  SHA256 `E65ED0336F132D1E992EADAAB3495EB1283B215AA08917A5AAC32DA7A8A9F58F`.

2026-06-21:

- Architecture guards: 13 passed.
- Startup/runtime stability: 55 passed, 5 subtests passed.
- Responsiveness/source guards: 49 passed.
- Archive/static replacement matrix: 342 passed.
- Texture workflow matrix: 253 passed.
- Supporting feature tabs: 81 passed.
- Services/domain/workers: 37 passed.
- Full pytest suite: 2846 passed, 6 skipped, 68 subtests passed.
- Fast onedir package built and startup-smoked.
- Release onefile package built, native helpers rebuilt, 482 embedded archive
  members validated, and startup-smoked.
- Release artifact:
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`
  SHA256 `37B9E8455C71A1C5A744E82E120ED17556B354C3A2FB521FDA376CF3BB3EBC0A`.
