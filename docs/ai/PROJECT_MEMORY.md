# Project Memory

Last updated: 2026-07-16

## Repository rules

- Continue the current restructure; never reset, clean, mass-format, stage, or overwrite the dirty worktree. Modified and untracked source may be user work.
- Use `apply_patch` for edits and the project virtual environment for Python: `.\.venv\Scripts\python.exe`.
- Keep entry points and facades thin. UI owns presentation, services own orchestration and I/O, domain owns dependency-free rules/data, and workers own long-running work. Core must not discover workspace/config dependencies.
- UI code must not mutate archives directly. Route mutation through `ArchiveMutationService`; source PAMT/PAZ files are read-only during tests.
- Preserve public Python imports, CLI scenario names, executable names, profile formats, wire schemas, and native package formats through cached lazy exports or versioned adapters.
- Keep `docs/plans/active/` to one current implementation plan. Delete completed plans and architecture-map-only placeholder modules; durable behavior belongs in owning docs, not completion logs.
- Repo workflows live under `.agents/skills/`: `cdmw-validate-change`, `cdmw-async-ui-work`, `cdmw-safe-archive-mutation`, and `cdmw-verify-mesh-editor`. Keep stable invariants in `AGENTS.md`; keep detailed commands and contracts in their owning docs/scripts instead of duplicating them inside skills.

## Validated restructure baseline

- The whole-codebase repair phases and final validation passed on 2026-07-11; the completed plan was removed from `docs/plans/active/`. Broad test, package, startup, and real-game evidence lives in `docs/release-confidence-plan.md`.
- Static-replacement callback/section facades and the mesh-edit factory pass live globals/state into ordered bounded owners; preserve patch seams, public callback signatures/identity, and signal order.

## Test and evidence contracts

- Default pytest and `scripts/codex_check.ps1 -Area full` are headless and must launch no visible native windows. Synthetic geometry is protocol/unit-only.
- `scripts/codex_check.ps1 -Area mesh-unit` is nonvisual mesh coverage.
- `scripts/codex_check.ps1 -Area mesh [-GameRoot PATH]` is the explicit visual real-game gate. Root resolution is argument, `CDMW_GAME_ROOT`, then `C:\games\Steam\steamapps\common\Crimson Desert`.
- That gate requires the production .NET/Vortice renderer `d3d11_vortice_shader` and resident edit backend `cdmw_mesh_core_0.1`. Legacy `real-archive-mesh-editor-d3d11-*` scenarios are compatibility-only.
- The real proof loads `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` from `0009\0.pamt`, uses production material/texture resolution, forbids checker or synthetic fallback, runs the resident select/transform/material/texture/UV/topology/undo/export sequence, reparses exported GLB/OBJ/DDS/sidecars, and fingerprints source archives before/after.
- The same proof must exercise acknowledged Vortice `textured`, `untextured_faces`, `wire_vertices`, and `vertices` against the real PAC. Display-only changes retain the process, package, buffers, textures, and SRVs. Neutral faces use inverse-transpose, two-sided camera-relative shading with a fixed floor; hidden front/back/oblique captures are synthetic evidence only, while the real PAC remains visual proof.
- Real-proof output is versioned JSON under an owned temporary root. It records PAC/archive/texture provenance and hashes, backend, geometry selection, captures, timings, fallback state, archive fingerprints, and individual gate results.
- Use a system temporary pytest base. Configured gates fail closed; full QA compiles `cdmw`, `tests`, and `tools`.
- Corpus gates require complete classification, zero read errors/crashes, and unchanged source-archive hashes; dated totals belong in `docs/release-confidence-plan.md`.

## Shared identities, I/O, and lifecycle

- Archive scan preflight treats nested PAMT trees outside root-level, `NNNN/`, `game_files/`, and `game_files/NNNN/` layouts as suspicious. It warns and lets the user cancel, open the folder, or scan anyway; it never auto-excludes files.
- Archive entries use one immutable identity: normalized virtual path, source PAMT, PAZ index, and entry offset. Caches, selection, shell bridges, and replacement flows must use all four parts.
- File/package/report writes use a sibling temporary file or staging directory, flush as appropriate, then atomic replacement/publication. Cancellation must leave no partially published output.
- ZIP/model ingestion is streaming and cancellable, validates member count, expanded size, ratio, traversal, duplicate targets, free space, and time/byte ceilings, then atomically publishes a content-fingerprinted fresh extraction.
- Worker-owning UI follows one contract: immutable snapshot, cancellation token, monotonic request ID, queued delivery, stale-result rejection, bounded progress, `request_shutdown()`, and `iter_shutdown_workers()`.
- Source-checkout workspace migration must never move the repository's `tools/` tree into `workspace/`; `.git` plus `cdmw/` identifies a source checkout.
- App-owned subprocesses get cooperative grace, then process-tree termination. User-launched game and third-party applications remain user-owned.

## Texture and cache contracts

- All production DDS decode, staging, preview, encode, and rebuild work uses
  `cd-texture-dx.exe` protocol v2. Missing or failed native execution fails
  explicitly; no secondary executable is searched or launched. Profile format
  4 discards obsolete converter paths/tokens, while the one-release public
  compatibility shim only warns and ignores obsolete arguments.
- Native DDS publication is sibling-staged, metadata-validated, and atomic.
  Protocol v2 owns source color policy, mip alpha policy/coverage, DDS alpha
  metadata, requested-mip decode, and true gray16 PNG staging. The authoritative
  non-UI gate is `tools/texture_replacer_headless_harness.py --scenario
  full-suite`; it exercises the real 2048x2048 Texture Replacer rebuild,
  consumer matrix, policy matrix, and failure lifecycle without archive writes.
- Replace Assistant Auto Match rejects resolved-path self matches, leaves their
  destination empty until an authoritative original is chosen, and fans one
  matched package/game path through all selected manager profiles.
- Texture edit history is pixel-exact beyond 100 operations. Before eviction,
  the new oldest state becomes a full LZ4 checkpoint off the UI thread; PNG is
  import/export-only.
- The canvas keeps stable image storage and updates dirty regions. Pointer
  handlers pass immutable/copy-on-write snapshots and never synchronously
  encode/compress full 4K layers.
- Decode, preview, and prepared-package caches use per-key singleflight, atomic
  publication, bounded failures/diagnostics, leases, and expiry-aware pruning.
- Loose overlays bypass result caching unless keys contain exact resolved loose
  dependency stamps. Modified loose files must become visible immediately.
- Archive flat views derive indexes from worker-produced normalized scan data
  and retain only bounded row caches.

## Mesh and preview contracts

- `ParsedMesh` is import/export compatibility state. The resident C++
  `MeshEditSession` is authoritative for active edits; explicit mesh read/export
  is the hydration boundary. Active native failures must fail closed, not fall
  back to stale Python mutation or preview generation.
- Non-topology edits use sparse channel/index deltas. Topology edits use
  copy-on-write affected-submesh snapshots. History is bounded to 64 whole
  operations and 256 MiB while preserving exact undo/redo.
- Mesh session views expose one ordered applied/undone timeline for geometry,
  replacement, rigging, and selection changes. Selection history stores only
  descriptors, remains undoable while the native mesh is dirty, and does not
  hydrate or clone resident geometry. Resident Undo/Redo runs in the command
  worker; Select keeps camera access through Ctrl+left orbit, Shift+left or
  middle/right pan, and wheel zoom, with bindings shown below the viewport.
- Live edit packets have monotonic revisions. One sender per preview source has
  queue depth one, latest-wins coalescing, ack pacing, stale-revision rejection,
  and cleanup of superseded payload files. Revisionless bundled readers remain
  supported during migration.
- Linked base/albedo painting uses negotiated
  `resident_texture_region_updates_v1`: one in-flight patch per resource,
  latest-wins union coalescing, owned immutable composite leases, region-only
  BGRA8 uploads after first copy-on-write resource creation, and acknowledged
  cleanup. Preparation failure must advance pending work and every lease is
  released exactly once.
- Native/.NET renderers retain mesh/GPU buffers, corner mappings, SRV arrays, and immutable draw resources. Sparse edits update affected ranges; topology edits rebuild affected batches and preserve original material lineage. Active .NET interaction uses ordered non-droppable controls plus one latest pending immutable update, and texture patches coalesce to one upload/mip pass per presented frame with exact final acknowledgement. Present never self-schedules another frame. VSync and maximum frame latency one remain, and FPS comes from completion intervals with render/Present/GPU p95/p99 reported separately. Overlay primitives use one reusable dynamic vertex buffer; static and selected geometry is retained by generation. The additive `performance_capture_v1`/`cdmw_dotnet_preview_performance_v1` path uses precommitted fixed rings, delayed D3D11 queries, a capture-only balanced 1 ms timer-resolution request, and Vortice 3.8.3 on .NET 8. Continuous Qt-parent resize remains a distinct DWM/hosting hard gate even when all non-resize segments sustain 144 Hz. While the D3D11 child exists, parent paint must return before the CPU/GDI face loop; DXGI uses flip-discard, and camera drags skip gizmo hover work.
- Mesh Editor normal wire and vertex colors are locally persisted and user-selectable. X-Ray is independent per presentation context, automatically uses white wire plus magenta vertices, and renders both overlay types without depth rejection; the hidden D3D11 smoke owns the corresponding draw-counter proof.
- Preview packages use singleflight, leases, atomic publication, consume/ack cleanup, and safe pruning. Source-stamped PAMT indexes have parse fallback; per-job material maps release while bounded decoded entries remain reusable.
- .NET helper-authored OBJ/package/operation paths and generated sidecars stay under the package output root after canonical link-aware resolution. Archive Preview expected stops are keyed by exact process plus generation; unmatched nonzero exits and device loss remain failures.
- The .NET/Vortice editor is the production embedded/standalone presentation child; Python/C++ retain data authority. One resident document/resource owner backs separate Original and Imported/Modify contexts with independent normal cameras and explicit linked comparison. Edit Mesh forces Replacement Only and pins the editable camera context across scene/presentation replay; leaving it restores the selected placement preview mode without restarting the renderer. Builder presentation is correlated; placement previews locally at input cadence with an exact provisional editable matrix while Original, role camera frames, and the resident world grid stay fixed. Camera Fit/nudge commands are role-addressed and generation-gated so persistent presentation replay is state-only. Authority requests coalesce at approximately 30 Hz with an exact final transform, and close uses acknowledged deactivation plus one final sync.
- Resident material protocol v2 updates shader parameters, texture resources,
  and affected bindings in-process. Python owns resource criticality; required
  failures block Ready, optional failures use declared fallbacks, and late
  reference generations are render-only. Source DDS wins over preview PNG;
  supported 2D DDS preserves native format and mips through semantic sRGB/linear
  SRVs. PAC shader/alpha/two-sided contracts do not depend on successful DDS
  resolution. glTF green-up normals invert in HLSL and base alpha remains a
  constant opacity factor. Exact PAC emissive ownership prevents cross-material
  leakage; proven color-blending masks use R=AO, G=roughness, B=metalness while
  `_mg` remains layer-only. The production shader uses linear GGX/Smith/Schlick
  plus proven opacity/cutout/occlusion and per-material culling; blend draws are
  depth-read/no-write and sorted back-to-front by transformed submesh center.
  Global fallback culling stays disabled because real PACs can mix winding;
  enable culling only from proven material/submesh authority and keep depth
  testing enabled. The production presentation keeps source tint active and
  matches Archive's luminance ACES operator with a 0.5 contrast pivot.
  Its neutral studio environment anchors metallic reflections to source color,
  proven two-sided backfaces flip the tangent frame, and final contrast preserves
  luminance chromaticity. Hidden textured-metal captures must retain texture detail
  with bounded angle-driven chromaticity and brightness drift. Wrong-family
  generic layer albedo may fall back to decoded sidecar tint while retaining
  same-family technical maps. Unproven layer, hair/fur, skin,
  and blend ordering stays diagnostic. Mutable
  region edits copy only the affected resource to a full BGRA mip chain,
  regenerate lower mips after each boxed upload, and preserve the resident
  process/package/viewport contract. Real topology evidence scans the retained
  protocol tail when the bounded event buffer has pruned the original cursor.
  The canonical paired visual audit keeps one native process and one .NET
  process/device/viewport resident, captures six fixed angles, requires direct
  verdicts, and fingerprints source archives. Its audit-only camera uses
  Archive's `T(-center) * Rx(pitch) * Ry(yaw)` object basis; integrity compares
  normalized screen-right/up/view axes so mirrored or rolled captures fail.
  Archive remains perspective and .NET orthographic, so fit/foreshortening is
  not texture-resolution evidence. Hidden automation creates the HWND without
  `Show`; open cards or standalone boundaries also seen in Archive are not
  x-ray regressions. Preserve RGB-versus-scalar emissive authority end to end:
  zero intensity combined with non-authoritative fallback color is not family
  evidence, while active intensity/color/role/channel remains authoritative;
  current nine-family real-PAC evidence matched 130/130 batches. The finalized
  corrected-camera ledgers are 11 PASS/5 CONCERN/0 FAIL across 16 broad models
  and 8 PASS/1 CONCERN/0 FAIL across the affected nine; both retain depth, use
  no X-ray/no-depth passes, and preserve byte-identical archive-fingerprint
  manifests. Direct authoritative DDS bytes, formats, dimensions, and mips stay
  identical to source; fit, source atlases, capped synthesized material
  outputs, or unsupported response can still soften the image. This is CDMW
  renderer-consistency evidence, never licensed-game parity proof.
  Prepared audit packages recursively own and rewrite every nested
  `source_path` the native role scan can select, even when a descriptor is not
  a direct-upload candidate, so cache eviction cannot invalidate later capture.
  The representative real hair corpus entry is `cd_ptm_00_hair_00_0003.pac`;
  it must resolve at least one source DDS instead of recording empty coverage.
  OpenImageIO is optional offline metadata/diff evidence, never runtime shading
  or DDS authority; identical corpus inputs must yield an identical fingerprint.
  `cd-texture-dx` batch JSON parsing must stay allocation-light and must not use
  `std::regex`; archive/icon warmup can leave the parent near 1.7 GiB private
  memory. Its executable self-test owns JSON escape and alias coverage.
- External OBJ/DAE/glTF/GLB missing/incomplete UVs use cancellable xatlas and report review-required. Shared UV transforms bake before the V flip; differing sets use sampler/color-space-correct raster baking, native tangents, normal-basis conversion, gutters, and atomic hashes. Unsupported input blocks safely; PAC/PAM is never auto-unwrapped.
- External ZIP import uses verified extraction; geometry fits the original frame, centers and Y-grounds, and overlay/side-by-side share one grid. Exact `cd_phm_01_sword_0016.pac` plus `wolf_gravestone_sword_free (1).zip` uses archive-resolved original textures and ZIP-owned imported textures. Archive Browser switches to a different mesh package at a fitted overhead camera (`yaw=0`, `pitch=-89`); refreshing the same model preserves its camera.
- Hardware soak must cover production-scale sparse updates, tail shrink,
  material lineage, handler time, and post-warmup RSS; dated results belong in
  `docs/release-confidence-plan.md`.
- The real nude-PAC gate must leave archives unchanged. Mesh Edit starts with no
  selected part; face/vertex modes can render without textures. Parts visibility
  never changes the alignment basis, and duplicate/delete are resident actions.
- Embedded .NET Preview Settings expose only fields with Python transport and a .NET renderer/camera consumer; their getter must read the live Builder accessor, not the setup factory's initial object.
  Side by Side alone creates two role panes; Overlay is one comparison surface, and each Only mode is one full-viewport role. Texture/view state syncs across roles while cameras stay independent.
  Wheel zoom uses Archive Browser's exact `0.1..64x` fit-relative ladder,
  preserves camera-space pan so a panned focal point stays anchored, and updates
  only the side-by-side pane under the pointer. Native renderer children must
  mark forwarded wheel events handled so one physical event cannot bubble into
  a second parent zoom step.

## Startup and packaging contracts

- Public `run_gui()` imports implementation only when called; lazy optional tabs
  must not pull NumPy, OpenCV, or preview stacks into cold facade import.
- Startup smoke uses a unique instance namespace and an atomic marker written
  only after window construction. Lock collision is failure.
- Startup autoload completes path/name lookup caches in the archive scan worker before releasing the splash; manual Archive Browser loads may defer them. The top status must terminalize as `Ready`/`Cache: Healthy`, including failure paths.
- Lazy composed `MainWindow` callbacks are QObject-owned and import-deferred.
  Worker signals need those or an owning-thread QObject receiver; lambdas/plain
  callables execute in the worker even with `QueuedConnection`.
- Shell Qt virtuals are explicit controller bridges. Close retains all owned
  `QThread`s until nonblocking `wait(0)` confirms native teardown; only then may
  QObject teardown publish `clean_shutdown: true`. A finished parentless Python
  worker returns to the UI thread before its QThread quits; UI-side cleanup then
  defer-deletes both objects after that same fence.
- Release builds regenerate and verify provider metadata before PyInstaller. The
  configured-archive gate loads 1.67M entries, paints, filters, and requires a clean shutdown.
- Startup benchmark evidence is owned by
  `docs/reference/app-startup-benchmark-phase5.json` and
  `docs/reference/app-startup-benchmark-phase6.json`; dated timing summaries
  belong in `docs/release-confidence-plan.md`.
- Release Python dependencies are pinned by tested constraints. CI runs
  nonvisual gates on Python 3.11 and 3.14 and packaging is gated by QA.
- Portable self-contained .NET remains the default. Change publish mode only
  when size improves at least 20% and helper-ready p95 regresses under 10%.

## Architecture and maintainability

- Required dependency direction is UI -> services -> domain/core. Domain must
  not import core. Core receives workspace/config dependencies by injection.
- Internal callers import focused owners; compatibility facades expose cached
  lazy symbols with stable identity and import-order behavior.
- Theme palette data lives in `cdmw/ui/theme_schemes.py`; `cdmw/ui/themes.py`
  preserves public lookup and owns Qt palette/stylesheet generation.
- Research UI imports dependency-free `cdmw/domain/research/` contracts/rules
  and the composed `ResearchService`; `cdmw.core.research` is compatibility-only.
- Split cohesive hotspots behind unchanged facades. New owner modules are at
  most 800 lines and functions at most 150 lines unless static/generated data;
  ratchets may only lower grandfathered maxima.
- `MainWindow` has one direct base (`QMainWindow`) and owns shell, archive,
  texture, mesh, and activation controllers. Legacy provider methods are bound
  through stable compatibility descriptors; never add another window base.
- Prefer behavior, protocol, import-order, AST-boundary, and golden-corpus tests
  over fragile source-string guards.

## Useful commands

- Focused tests: `.\.venv\Scripts\python.exe -m pytest <tests>`
- Compile/import: `.\.venv\Scripts\python.exe -m compileall -q cdmw tools tests`
- Headless full gate: `.\scripts\codex_check.ps1 -Area full`
- Nonvisual mesh gate: `.\scripts\codex_check.ps1 -Area mesh-unit`
- Real gate: `.\scripts\codex_check.ps1 -Area mesh -GameRoot <PATH>`
- Native build: `.\build_native_windows.ps1`
