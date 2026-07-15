# Release Confidence Plan

Last reviewed: 2026-07-15

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

2026-07-15:

- The third visual/material parity corpus audited 90 additional read-only PACs
  with run ID `218138b059e14854986a1c8cd1e2329d`. Archive Browser and the
  production `.NET/Vortice` renderer each captured 90/90 assets at six paired
  angles, producing 540 comparisons from 525 native material batches. The
  structured review finalized every row as 27 PASS, 31 CONCERN, and 32 FAIL,
  with zero unreviewed models. Capture integrity, presentation-contract checks,
  and composite completeness passed; one .NET device/viewport served all 90
  resident scene loads with zero device resets. Before/after fingerprints for
  all 26 referenced PAMT/PAZ files were byte-identical. Evidence:
  `workspace/mesh-editor-visual-audit/20260715-third-90/summary.json` and
  `workspace/mesh-editor-visual-audit/20260715-third-90/review.md`.
- This pass restored source tint as the normal production/audit default and
  aligned the .NET luminance tone operator and contrast pivot with the native
  Archive reference. A separate six-angle x-ray regression review confirmed
  depth testing remained enabled and global back-face culling remained disabled
  for mixed-winding PACs. The known 057 body, 064 harpy, and 069 standalone
  upper-body cases now retain the same surface layout as Archive. The notably
  skeletal 036 jacket is one opaque submesh whose open strip construction is
  present in both renderers, not a transparency or lost-face regression.
- End-state validation reported 45 focused visual-audit contract/parity tests
  passed, `mesh-unit` reported 816 passed and 1 skipped, the selected
  architecture hard-limit check passed, and the Release .NET build completed
  with zero warnings and zero errors. The corpus still exposes substantial
  dark/flat bright-material and per-region differences plus unsupported
  authoritative emissive-color graphs. These CDMW comparisons are not
  real-game visual proof, and static captures do not prove animation timing or
  rendered deformation.
- The non-overlapping visual/material follow-up audited 72 unique read-only
  PACs: 10 shields, 5 swords, 14 outfits, 5 bodies, 8 head/face assets,
  10 hair/fur assets, 8 spiders, 6 glass/alpha controls, and 6 unusual props.
  Archive Browser and the production `.NET/Vortice` renderer each captured
  72/72 assets at six paired angles. Direct inspection classified 15 PASS,
  40 CONCERN, and 17 FAIL with no unreviewed rows. One native process and one
  .NET process/device/viewport stayed resident, with zero restarts or device
  resets and 72 resident scene loads. Before/after archive fingerprints were
  identical at
  `0947119118ACBBAFD8555E9BFBEFEA9DC8D453E2FF712CA35F0660EC28D7BAC7`.
  Evidence:
  `workspace/mesh-editor-visual-audit/20260715-final-72/summary.json` and
  `workspace/mesh-editor-visual-audit/20260715-final-72/review.md`.
- Shared repairs moved expensive material composition into the cancellable
  package worker, preserved raw diagnostics and exact native material batches,
  and stopped resident state snapshots from synthesizing images. Audit package
  stabilization now recursively owns and rewrites every `source_path` that the
  native role scan can select, including nested specular/detail descriptors and
  non-direct candidates. A fresh capture-only rerun then completed in 77.3
  seconds with no missing selectable texture sources.
- The corpus did not close shield-layer, outfit palette/dye, generic
  packed-mask, dark-fur, or combined cloth/hair/standard spider graphs. It did
  not contain a true transmissive alpha-blend glass shader; all six glass/alpha
  rows were opaque or cutout controls. Hair/fur anisotropy, full skin response,
  separately composed head/face behavior, visual animation playback, and
  deformation remain outside this static renderer-consistency audit. The
  separate animation/rigging smokes prove parser, binding, and in-memory pose
  changes only, not game timing or rendered deformation.
- Final verification reported 805 passed and 1 skipped from `mesh-unit`; the
  focused visual-audit harness/package group reported 17 passed, and the
  Release .NET build completed with zero warnings and zero errors. Architecture
  hard limits pass. The eight originally oversized repair owners are all below
  800 lines and absent from the size baseline, so the prior "eight stale files"
  description is resolved. The repository-wide ratchet remains red on 12 other
  pre-existing/concurrent file-growth entries, 10 new oversized functions, and
  5 grown oversized functions; none is an owner introduced or left oversized
  by this visual-audit goal.

2026-07-14:

- The angle-stability follow-up removed view-dependent material recoloring from
  both production preview shaders. Identical-material camera sweeps reduced
  maximum chromaticity drift from 0.1670 to 0.0097, kept all-view mean luma
  within a 0.8245 ratio, and produced no near-white clipping. The release-scale
  hidden Vortice gate passed at 1,000,000 vertices and 1,000 paced updates with
  0.1908 ms handler p95. Evidence:
  `%TEMP%\cdmw-dotnet-gpu-sparse-soak-angle-color-final.json`.
- The reported `cd_phm_02_sword_0014.pac` handle now rejects its proven
  wrong-family generic layer as visible albedo, falls back to the decoded gold
  material tint, and retains the same-family normal/material maps. Direct-slot
  manifest parsing also prevents a nested normal-map `base` field from being
  rebound as albedo. The exact package loaded six batches with five intended
  base textures and no handle-normal-as-base binding; 109 focused tests and
  `mesh-unit` (729 passed, 1 skipped) passed. The visible production
  `.NET/Vortice` real-PAC gate preserved one resident package/process, reported
  zero reloads/restarts, and left every PAMT/PAZ fingerprint unchanged.
  Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-7415cb44a2b047e1b3539b1f010d13b9\evidence_report.json`.
- The user-reported black fully-metallic/two-sided preview regression is closed
  by production-shader environment response, backface tangent-frame correction,
  and a linear-middle-gray contrast pivot. The pre-fix identical-camera proof
  recorded zero front and oblique luma; the release-scale hidden Vortice gate
  now keeps front/back mean luma within 0.1%, retains textured oblique detail,
  and passes at 1,000,000 vertices plus 1,000 paced updates (59.9692 updates/s,
  0.1918 ms handler p95). Evidence: `%TEMP%\cdmw-dotnet-metal-baseline.json`
  and `%TEMP%\cdmw-dotnet-gpu-sparse-soak.json`.
- The exact authorized Wolf Gravestone ZIP import passed, its corpus row retained
  base/packed-material/normal semantics plus the explicit unsupported sorted
  alpha-blend flag, and the runtime resource-policy probe passed. `mesh-unit`
  reported 725 passed and 1 skipped. The canonical visible real-PAC
  `.NET/Vortice` gate then passed with three native DDS bindings, a stable
  resident process/package, 0.5730 ms stroke-handler p95, and unchanged source
  payload plus PAMT/PAZ hashes. Evidence:
  `%TEMP%\cdmw-mesh-material-profile-corpus.json`,
  `%TEMP%\cdmw-material-resource-policy-runtime.json`, and
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-8d3848e45e974221a6f14aaf72560ca4\evidence_report.json`.
- Read-only inspection of the reported original
  `cd_phm_02_sword_0014.pac` found six opaque batches and no source transparency
  contract; five batches are fully metallic, which directly exercises the fixed
  black-metal path. Its gold/emissive tints are source-derived. Exact game-layer
  parity remains unclaimed because one handle-layer texture choice is marked
  wrong-family and the package reports `material_quality_safe=false`. Evidence:
  `%TEMP%\cdmw_user_sword_native_evidence_iadim4ll\package\manifest.json`.
- The remaining material-risk follow-up passed all 73 production real-PAC gates.
  Two linked Texture Editor strokes regenerated a 12-level editable BGRA chain
  from a 12-mip native source; the canonical topology/UV/undo/redo/export flow
  settled with one PID, zero reloads/restarts, and unchanged PAMT/PAZ hashes.
  Evidence: `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-377f9781878941c4a27091a8dfe506dd\evidence_report.json`.
- The full hidden Vortice gate passed at 1,000,000 vertices and 1,000 updates
  with 59.9752 effective updates/second, 0.2247 ms handler p95, and no failed
  gates. `mesh-unit` reported 722 passed and 1 skipped; the focused material,
  mip, evidence, and corpus tests passed, as did the Release build and runtime
  material-policy report. Evidence:
  `%TEMP%\cdmw-dotnet-gpu-sparse-soak-risk-followup-20260714.json` and
  `%TEMP%\cdmw-material-resource-policy-risk-followup-20260714.json`.
- The bounded real-game corpus now uses
  `cd_ptm_00_hair_00_0003.pac` for hair and requires it to resolve a source DDS.
  The current game data resolves one DXT5 resource with 11 mips; the seven-asset
  game-only corpus fingerprint is
  `639459e0349d3d347666248f97df588ff1b05181d07457cef6786c2f32e41b7d`.
  Evidence: `%TEMP%\cdmw-material-fidelity-corpus-risk-followup-20260714.json`.

2026-07-13:

- Material-fidelity hardening passed the production .NET/Vortice real-PAC gate
  with native BC1 sRGB uploads preserving 11-12 source mips for all three
  canonical DDS resources and zero native-upload fallbacks. The same resident
  PID/HWND, one package/process, zero reload/restart, and unchanged PAMT/PAZ
  hashes were proven. Deterministic 512x512 capture comparison changed 7,101
  pixels; foreground mean luma rose from 30.42 to 62.77 and the below-25 dark
  fraction fell from 47.23% to 0.26% while the dark workbench background stayed
  stable. The bounded corpus now contains body, clothing, hair, weapon, prop,
  layered armor, fur, and external-model rows (fingerprint
  `5cca4652c9bb50620b1d5022ada731732ea3cc58e102a1ecb69c7d0d7670c619`).
  Evidence: `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-1d5a55496ece49ff839d90b62f796823\evidence_report.json`,
  `%TEMP%\cdmw-material-fidelity-before-after-20260713.json`, and
  `%TEMP%\cdmw-material-fidelity-corpus-after-20260713.json`.
- The resident .NET/Vortice repair implementation closed all 18 source defects
  with owning behavior/protocol tests. `mesh-unit` reported 704 passed and 1
  skipped. A direct full run reported 5,302 passed, 6 skipped, and 3 intentional
  deselections. `run_full_qa.ps1` then completed in 1,026.3 seconds, including
  canonical full pytest, compileall, dependency checks, `cd_hkx` format/tests,
  production helper publication, hidden GPU proof, a clean temporary onedir
  build, packaged helper GPU proof, and packaged startup smoke.
- The canonical real nude-PAC proof passed all 72 gates through
  `d3d11_vortice_shader` and `cdmw_mesh_core_0.1`. It bound three archive DDS
  textures, changed only 12 selected vertices over 40 physical updates, recorded
  0.5038 ms handler p95 and 38.8021 ms maximum heartbeat gap, produced a 16,744
  pixel material difference, completed topology/UV/material/texture/undo/export/
  readback, and preserved every PAMT/PAZ hash. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-7b829aea6dc94e998630a809543125ef\evidence_report.json`.
- The final full-scale hidden Vortice soak passed with one million vertices,
  1,000 sparse updates plus 64 warmups, 59.9742 effective updates/second,
  0.2084 ms handler p95, 0.4659 ms maximum, and zero post-warmup growth. Evidence:
  `%TEMP%\cdmw-mesh-editor-resident-repair-20260713-004343\dotnet-gpu-sparse-soak-final.json`.
- External import proof passed against the authorized sword ZIP; the focused
  real-game test reported 1 passed. The material corpus covers 20 declared
  policy profiles, two hashed actual assets, and three failure cases with corpus
  fingerprint `46a6af2113ca7c7d6543d628c7b0590c87f4fbce20c45ce104372221ff4eecf5`.
- Current-worktree release builds and their startup/helper verification passed
  again after the final packaged-UI repairs. The onefile artifact is
  183,141,243 bytes, SHA-256
  `87841F35E7F62EDA635777E778B4FE1F8DA99462B8D5EAF1098C4C6E85C798CC`.
  The onedir EXE is 16,460,434 bytes, SHA-256
  `A04A317C09EFDAE30D56462793055D5CFFCB397AF6388165D5378DE75A2B458D`.
  Its bundled helper SHA-256 is
  `A9BCADB48CC5BC330162CEF9C789BCAB8341DC1C4F59E6235133D88B891F45B4`,
  and the helper-manifest file SHA-256 is
  `96BE3BBFB041A8A902E7106A030C0C821D83D9C37D0138B04C556FC4FDE099F6`.
- Computer Use completed the real packaged Mesh Editor workflow in both release
  modes against
  `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` after loading
  the 1,674,731-entry archive cache. Onedir rendered separate Original and
  Imported/Modify views. The final clean artifact was exercised from an
  authorized temporary copy and kept helper PID 21620 across Edit Mesh, Finish
  Edit Mesh, and placement; the preceding full control pass also proved
  immediate edit-mode re-entry without reload. Runtime evidence recorded
  `mesh_dotnet_edit_mode_finished_resident` with process generation 1 and no
  deactivation/provenance-block event. Select All and Clear Selection produced
  visible acknowledged selection changes. The embedded Advanced section opened
  inside the Builder with no orphan window. Onefile repeated the real-PAC
  Builder/helper smoke with helper PID 28236 and recorded
  `mesh_dotnet_helper_provenance_verified` from its `_MEI` extraction.
- The visible pass exposed and closed three packaged-only defects: Builder
  factory read-before-assignment plus an orphan parentless Advanced section,
  false helper-provenance rejection after an already verified
  `protocol_ready`, and Finish Edit Mesh hiding the resident helper and leaving
  a blank viewport. The final `mesh-unit` gate reported 706 passed and 1
  skipped; focused resident-finish/true-close/busy-stroke review reported 20
  passed. Both Builders were cancelled, `Build Mod` was never invoked, no game
  archive was written, and both applications shut down without helper orphans.
- The full-suite runtime smoke exposed and closed an Item Icons worker teardown
  race: finished Python workers now return to the UI thread before their QThread
  quits, and both objects are defer-deleted only after nonblocking native teardown
  confirmation. Focused Item Icons/output/runtime/documentation coverage reported
  26 passed. The completed active plan was removed from `docs/plans/active/`.

2026-07-12:

- Mesh selection and harness-truth fixes passed the final canonical sequence.
  `mesh-unit` reported 680 passed; full headless QA reported 5,169 passed,
  5 skipped, and 2 intentional visual/real-game deselections. The .NET Release
  build completed with zero warnings/errors, and size ratchets pass with
  `real_dotnet.py` reduced to 716 lines behind the 143-line physical-input owner.
- The explicit nude-PAC proof passed all 70 gates through renderer
  `d3d11_vortice_shader` and edit backend `cdmw_mesh_core_0.1`. It bound three
  real archive textures, proved foreground-visible renderer PID ownership for
  every capture/input, exercised textured/untextured-face/vertex views, delivered
  40 physical drag updates, completed paint/assignment/UV/topology/undo/export/
  readback, proved initial/no-part and face-without-part selection, recorded
  0.6332 ms handler p95 and 50.06 ms maximum heartbeat gap, and preserved every
  PAMT/PAZ hash. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-fe7c05b56b0c41949d6d011561ec0140\evidence_report.json`.
- Release onedir packaging passed with 471 files/447,385,055 bytes. The EXE
  SHA-256 is `D1F426BF80AE74EFA28A521E13FE19E09BC13E5DE226CD0DED5CBB585641F643`;
  the bundled .NET helper SHA-256 is
  `203D9822D54861910D1134C4D5F629D0738ADC5F2446C82AC3C3C4B2E6D3C542`.
  Packaged and installed startup reached `post_construction`; installed hidden
  Mesh Editor lazy-target smoke passed. Against the installed build and actual
  1,674,731-entry archive cache, Archive Browser reached ready in 2.529 s, then
  canonicalized `All files.pac`, searched `Nude`, returned 75 results in 1.157 s,
  and closed cleanly. Installed real-PAC UI verification proved no initial part
  selection, vertex/face selection without a Parts-row selection, Clear
  Selection, and blank-list clearing of part highlight; shutdown was clean and
  all source archive hashes remained unchanged.
- Full resumable corpora completed. The external catalogue classified all 800
  models and all 418 ZIP members (`corpus_ok=true`, zero unclassified). The
  archive-backed PAC_XML audit classified all 12,886 entries, reported zero
  read/parse errors or crashes, preserved every source archive fingerprint, and
  finished with `ok=true`. Evidence remains under `%TEMP%` as
  `cdmw-external-model-audit-resident-goal.json` and
  `cdmw-pac-xml-audit-resident-goal.{json,csv}`.
- The latest recorded hidden .NET soak covered one million vertices and 1,000
  sparse updates at 59.96 Hz, 0.2024 ms handler p95, and 0.16% post-warmup RSS
  growth, with one initial full build and passing tail-shrink/material-lineage
  proof.
- The Phase 6 startup benchmark passed against
  `docs/reference/app-startup-benchmark-phase5.json`: public import p95 was
  197.077 ms with no forbidden heavy modules, first-window p95 was 1746.569 ms
  (31.258% better than baseline), first-tab p95 was 233.923 ms, and helper-ready
  p95 was 517.075 ms. Result:
  `docs/reference/app-startup-benchmark-phase6.json`.

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
