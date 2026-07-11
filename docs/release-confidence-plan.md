# Release Confidence Plan

Last reviewed: 2026-07-11

## Goal

Prove the completed phased restructure still imports, starts, packages, and
keeps core user workflows working behind stable facades.

## Read First

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/architecture.md`
4. `docs/project-map.md`
5. `docs/test-matrix.md` when choosing validation
6. `docs/project-map-detailed.md` only when package boundaries are unclear

## Current Focus

- Preserve the completed repair baseline: compatibility facades, public imports,
  dependency direction, bounded owners, and the one-base composed `MainWindow`.
- Keep `docs/plans/active/` empty until new scoped implementation work starts.
- Keep normal/full QA headless; run licensed real-game proof only through the
  explicit local mesh gate.
- Use `$env:TEMP` for pytest `--basetemp`; never place QA output in the repo.

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

2026-07-11:

- Test/tool relevance audit passed: all 389 test modules and 5,114 tests collect;
  canonical nonvisual QA reported 5,107 passed, 5 skipped, and 2 intentional
  visual deselections. The 68-module tool-facing gate reported 960 passed,
  1 environment skip, and 2 visual deselections. Python compile coverage now
  includes `tools`; the production .NET/Vortice helper built with zero warnings
  or errors and passed hidden smoke on `d3d11_vortice_shader`. Redundant Research
  facade behavior tests were replaced by an all-export identity contract, while
  unique owner behavior stayed covered. Configured `codex_check` area paths now
  fail closed instead of silently skipping missing tests.
- Resident editor/import risk completion passed its final sequence. Clean
  headless QA reported 5,110 passed, 5 skipped, and 2 intentional visual
  deselections; `mesh-unit` reported 679 passed. Native helpers and Release
  .NET built with zero warnings/errors.
- The current hidden Vortice soak passed one million vertices and 1,000 sparse
  updates at 59.96 Hz, 0.205 ms handler p95, zero post-warmup RSS growth, and
  passing partial tail-shrink/material-lineage checks. The canonical nude-PAC
  proof passed all 67 gates, including real textured, neutral untextured-face,
  wire-plus-vertices, and vertices-only captures; its handler p95 was 0.637 ms
  and maximum heartbeat gap 36.4 ms. It completed paint/assign/UV/topology/
  undo/export/readback and preserved every source hash. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-f1ecd54552534d918ec61fa885ab24cd\evidence_report.json`.
- External catalogue evidence accounts for 800/800 sources with 739 supported,
  22 review-required, 39 safely blocked, zero unclassified, and zero corpus
  crashes. PAC_XML evidence accounts for 12,886/12,886 archive entries with
  6,046 supported, 6,840 review-required, zero errors/crashes/unclassified,
  and 55 actual source archives unchanged before/after.
- Current-source fast onedir packaging passed with 488 files/447,445,766 bytes.
  `CrimsonDesertModWorkbench.exe` is 16,359,452 bytes, SHA-256
  `31F5871AA94CF2F403CAC6DB8072C7C370FA6D61FA7D7CB536FFAE953B027DA4`;
  packaged startup reached `post_construction`, and the bundled self-contained
  Vortice helper passed hidden GPU smoke.
- The reviewed resident-editor/Material Authority follow-up passed its final
  gates. Integrated focused coverage reported 597 passed, 39 subtests, and two
  intentional visual deselections; `mesh-unit` reported 675 passed; the full
  headless suite reported 4,976 passed, 5 skipped, and 2 deselected in
  1,086.55 seconds. Architecture/import-order/docs coverage, Python compile,
  dependency pins, Rust tests, native builds, and .NET Release build all passed.
- The full-QA wrapper exposed a real false-negative after that passing suite:
  PowerShell `Start-Process -PassThru` returned a process object without a
  readable exit code. `Invoke-QAStep` now starts and owns one
  `System.Diagnostics.Process`, preserves exact nonzero codes, and retains
  timeout/process-tree cleanup. Four QA-runner behavior tests pass. The
  remaining helper, PyInstaller, packaged hidden-GPU, and post-construction
  startup steps were resumed and passed.
- The final hidden Vortice soak passed one million vertices and 1,000 updates
  at 8.102 ms handler p95 with zero post-warmup RSS growth, one initial full
  build, and one affected-batch topology rebuild. Atomic position/normal/UV
  packets, malformed/incomplete rejection, part add/remove/reindex, and
  material-lineage proofs passed.
- Release onefile packaging and post-construction startup passed with both
  `cdmw.ui.shell.window_bootstrap_state` and `cdmw.core.ncnn_model_catalog`
  collected. Artifact:
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`,
  182,649,463 bytes, SHA-256
  `0132F6288F44456DB81A0470A9C08ABC8567F7A10C11CB65659255FB286CC910`.
- The explicit production nude-PAC gate passed again. It bound three real
  archive textures, changed only 12 selected vertices, kept PID/HWND and the
  viewport stationary, recorded 1.624 ms handler p95 and 94.048 ms maximum
  heartbeat gap, applied resident material updates without package/process/SRV
  churn, and left PAMT/PAZ hashes unchanged. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-1f183f23c9f04de8bbcdeecf4e6ea7c9\evidence_report.json`.
- Canonical headless full QA passed: 4,865 passed, 5 skipped, 2 deselected in
  893.46 seconds. Visual and licensed `real_game` scenarios remained opt-in.
- Release onedir packaging passed at
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows`: 447,014,232 bytes
  across 488 files. `CrimsonDesertModWorkbench.exe` SHA-256 is
  `00474ad34dc707aaab942e3c863c9eaf3bdf0fa3406b1fe8703cdae713f586f4`.
  Packaged startup reached the post-construction marker, and the hidden packaged
  Vortice GPU smoke passed with renderer `d3d11_vortice_shader` and 0.4396 ms
  handler p95.
- The explicit read-only real-game gate passed through the production
  .NET/Vortice renderer (`d3d11_vortice_shader`) and resident edit backend
  `cdmw_mesh_core_0.1`. It bound three archive-provenance textures, completed an
  exact 40-pixel viewport drag with zero projection error, changed only 12
  selected vertices, kept the window stationary, recorded 1.6333 ms edit-handler
  p95 and 151.9153 ms maximum heartbeat gap, and left PAMT/PAZ fingerprints
  unchanged. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-0bc29c1d9f474adbb8e3a10eb7771987\evidence_report.json`.
- The whole-codebase repair plan passed its final sequence and was removed from
  `docs/plans/active/`.

2026-07-10:

- Canonical `codex_check -Area mesh` now routes to
  `real-archive-mesh-editor-dotnet-edit-smoke`, not the legacy C++ D3D11 host.
- Read-only proof passed with the exact nude PAC
  `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac`, three
  archive-provenance DDS bindings, renderer `d3d11_vortice_shader`, edit backend
  `cdmw_mesh_core_0.1`, 12 selected-only changed vertices, 1.214 ms main-thread
  handler p95, 101.14 ms maximum heartbeat gap, stationary renderer HWNDs, and
  unchanged PAMT/PAZ SHA-256 fingerprints.
- Legacy C++ D3D11 scenarios remain explicit compatibility/protocol coverage;
  synthetic checker geometry is blocked by default. Normal/full pytest still
  excludes only `visual` and `real_game` markers.
- Release .NET helper publication now runs a hidden Vortice GPU smoke; helper
  preflight requires both the .NET renderer and `cdmw-mesh-core.exe`.

2026-07-08:

- Focused static replacement, D3D11 package, native preview core, and Mesh
  Editor action-bar tests passed: 353 passed.
- Alignment dialog and Mesh Edit responsiveness source guards passed: 149
  passed.
- Release dirty-tree preflight classifies untracked project source/docs under
  known repo roots; generated output and untracked source outside those roots
  still block release packaging.
- `build.bat onedir release` produced
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows/CrimsonDesertModWorkbench.exe`
  14,462,895 bytes, SHA256
  `EB7180A38330E48725D33F78839A73F8FFDE9A85F53218892293F86426BCF1A9`.
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
