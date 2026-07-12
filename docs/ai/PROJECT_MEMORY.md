# Project Memory

Last updated: 2026-07-12

## Repository rules

- Continue the current restructure; never reset, clean, mass-format, stage, or
  overwrite the dirty worktree. Modified and untracked source may be user work.
- Use `apply_patch` for edits and the project virtual environment for Python:
  `.\.venv\Scripts\python.exe`.
- Keep entry points and facades thin. UI owns presentation, services own
  orchestration and I/O, domain owns dependency-free rules/data, and workers own
  long-running work. Core must not discover workspace/config dependencies.
- UI code must not mutate archives directly. Route mutation through
  `ArchiveMutationService`; source PAMT/PAZ files are read-only during tests.
- Preserve public Python imports, CLI scenario names, executable names, profile
  formats, wire schemas, and native package formats through cached lazy exports
  or versioned adapters.
- Keep `docs/plans/active/` to one current implementation plan. Delete completed
  plans and architecture-map-only placeholder modules; durable behavior belongs
  in owning docs, not completion logs.
- Repo workflows live under `.agents/skills/`: `cdmw-validate-change`,
  `cdmw-async-ui-work`, `cdmw-safe-archive-mutation`, and
  `cdmw-verify-mesh-editor`. Keep stable invariants in `AGENTS.md`; keep detailed
  commands and contracts in their owning docs/scripts instead of duplicating
  them inside skills.

## Validated restructure baseline

- The whole-codebase repair phases and final validation passed on 2026-07-11;
  the completed plan was removed from `docs/plans/active/`. Broad test, package,
  startup, and real-game evidence lives in `docs/release-confidence-plan.md`.
- Static-replacement callback/section facades and the mesh-edit factory pass
  live globals/state into ordered bounded owners; preserve patch seams, public
  callback signatures/identity, and signal order.

## Test and evidence contracts

- Default pytest and `scripts/codex_check.ps1 -Area full` are headless and must
  launch no visible native windows. Synthetic geometry is protocol/unit-only.
- `scripts/codex_check.ps1 -Area mesh-unit` is nonvisual mesh coverage.
- `scripts/codex_check.ps1 -Area mesh [-GameRoot PATH]` is the explicit visual
  real-game gate. Root resolution is argument, `CDMW_GAME_ROOT`, then
  `C:\games\Steam\steamapps\common\Crimson Desert`.
- That gate requires the production .NET/Vortice renderer
  `d3d11_vortice_shader` and resident edit backend `cdmw_mesh_core_0.1`.
  Legacy `real-archive-mesh-editor-d3d11-*` scenarios are compatibility-only.
- The real proof loads
  `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` from
  `0009\0.pamt`, uses production material/texture resolution, forbids checker or
  synthetic fallback, runs the resident select/transform/material/texture/
  UV/topology/undo/export sequence, reparses exported GLB/OBJ/DDS/sidecars, and
  fingerprints source archives before/after.
- The same proof must exercise acknowledged Vortice `textured`,
  `untextured_faces`, `wire_vertices`, and `vertices` modes against that real
  PAC. Display-only changes retain the process, package, resident buffers,
  decoded textures, and SRVs; neutral faces must remain visibly non-black and
  textured mode is restored before mutation/export.
- Real-proof output is versioned JSON under an owned temporary root. It records
  PAC/archive/texture provenance and hashes, backend, geometry selection,
  captures, timings, fallback state, archive fingerprints, and individual gate
  results.
- Use a system temporary pytest base. Configured gates fail closed; full QA compiles `cdmw`, `tests`, and `tools`.
- Corpus gates require complete classification, zero read errors/crashes, and
  unchanged source-archive hashes; dated totals belong in
  `docs/release-confidence-plan.md`.

## Shared identities, I/O, and lifecycle

- Archive scan preflight treats nested PAMT trees outside root-level, `NNNN/`,
  `game_files/`, and `game_files/NNNN/` layouts as suspicious. It warns and lets
  the user cancel, open the folder, or scan anyway; it never auto-excludes files.
- Archive entries use one immutable identity: normalized virtual path, source
  PAMT, PAZ index, and entry offset. Caches, selection, shell bridges, and
  replacement flows must use all four parts.
- File/package/report writes use a sibling temporary file or staging directory,
  flush as appropriate, then atomic replacement/publication. Cancellation must
  leave no partially published output.
- ZIP/model ingestion is streaming and cancellable, validates member count,
  expanded size, ratio, traversal, duplicate targets, free space, and time/byte
  ceilings, then atomically publishes a content-fingerprinted fresh extraction.
- Worker-owning UI follows one contract: immutable snapshot, cancellation token,
  monotonic request ID, queued delivery, stale-result rejection, bounded
  progress, `request_shutdown()`, and `iter_shutdown_workers()`.
- Source-checkout workspace migration must never move the repository's `tools/`
  tree into `workspace/`; `.git` plus `cdmw/` identifies a source checkout.
- App-owned subprocesses get cooperative grace, then process-tree termination.
  User-launched game and third-party applications remain user-owned.

## Texture and cache contracts

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
- Native/.NET renderers retain mesh/GPU buffers, corner mappings, SRV arrays, and immutable draw resources. Sparse edits update affected ranges; topology edits rebuild affected batches and preserve original material lineage.
- Preview packages use singleflight, leases, atomic publication, consume/ack cleanup, and safe pruning. Source-stamped PAMT indexes have parse fallback; per-job material maps release while bounded decoded entries remain reusable.
- The .NET/Vortice editor is the production embedded/standalone presentation child; Python/C++ retain data authority. It starts for replacement builders and original/imported sessions before Edit Mesh. One resident scene contains editable submeshes first and a render-only original reference, plus Y-up grid, four comparison modes, placement TRS, and move/rotate/scale gizmo state. Edit Mesh only gates mutation; turning it off keeps the renderer resident and placement controls visible. Scene-format Flip V normalization is format-driven even when preflight performs the import. Builder close still uses acknowledged deactivation and one final sync.
- Resident material protocol v2 updates shader parameters, texture resources,
  and affected bindings in the same process after `Ready`. Automatic and Manual
  are the normal Material Authority profiles. Unsupported target resource/
  height controls disable with an exact reason; enabled no-ops are forbidden.
- External OBJ/DAE/glTF/GLB missing/incomplete UVs use cancellable xatlas and report review-required. Shared UV transforms bake before the V flip; differing sets use sampler/color-space-correct raster baking, native tangents, normal-basis conversion, gutters, and atomic hashes. Unsupported input blocks safely; PAC/PAM is never auto-unwrapped.
- External ZIP import uses verified extraction; geometry fits the original frame, centers and Y-grounds, and overlay/side-by-side share one grid. Exact `cd_phm_01_sword_0016.pac` plus `wolf_gravestone_sword_free (1).zip` uses archive-resolved original textures and ZIP-owned imported textures.
- Hardware soak must cover production-scale sparse updates, tail shrink,
  material lineage, handler time, and post-warmup RSS; dated results belong in
  `docs/release-confidence-plan.md`.
- The real nude-PAC gate must leave archives unchanged. Mesh Edit starts with no
  selected part; face/vertex modes can render without textures. Parts visibility
  never changes the alignment basis, duplicate/delete are resident actions, and
  wheel zoom spans `1.0` to `500000.0`.

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
  QObject teardown publish `clean_shutdown: true`.
- Release builds reject stale provider metadata. The configured-archive gate
  loads 1.67M entries, paints, filters, and requires a clean shutdown.
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
