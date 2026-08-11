# Project Memory

Last updated: 2026-08-11

## Repository rules

- Continue the current restructure; never reset, clean, mass-format, stage, or overwrite the dirty worktree. Modified and untracked source may be user work.
- Use `apply_patch` for edits and the project virtual environment for Python: `.\.venv\Scripts\python.exe`.
- Keep entry points and facades thin. UI owns presentation, services own orchestration and I/O, domain owns dependency-free rules/data, and workers own long-running work. Core must not discover workspace/config dependencies.
- UI code must not mutate archives directly. Route mutation through `ArchiveMutationService`; source PAMT/PAZ files are read-only during tests.
- Preserve public Python imports, CLI scenario names, executable names, profile formats, wire schemas, and native package formats through cached lazy exports or versioned adapters.
- Keep `docs/plans/active/` to one current implementation plan. Delete completed plans and architecture-map-only placeholder modules; durable behavior belongs in owning docs, not completion logs.
- Agent workflows live under `.agents/skills/` — `cdmw-validate-change`, `cdmw-async-ui-work`, `cdmw-safe-archive-mutation`, `cdmw-verify-mesh-editor` — but that directory is **gitignored and local only**, so a fresh clone will not have it. Keep stable invariants in `AGENTS.md`, which is tracked; keep detailed commands and contracts in their owning docs/scripts rather than duplicating them inside skills, precisely because the skills do not travel with the repository.

## Validated restructure baseline

- The whole-codebase repair phases and final validation passed on 2026-07-11; the completed plan was removed from `docs/plans/active/`. Broad test, package, startup, and real-game evidence lives in `docs/release-confidence-plan.md`.
- Static-replacement callback/section facades and the mesh-edit factory pass live globals/state into ordered bounded owners; preserve patch seams, public callback signatures/identity, and signal order. Migrate high-risk `locals()` seams incrementally to validated typed contexts; preview-state wiring is owned by `StaticReplacementPromptStateControls`. Builder close cancels queued post-open callbacks and stops prompt timers before Qt child deletion.

## Test and evidence contracts

- Default pytest and `scripts/codex_check.ps1 -Area full` are headless and must launch no visible native windows. Synthetic geometry is protocol/unit-only.
- `scripts/codex_check.ps1 -Area mesh-unit` is nonvisual mesh coverage. It owns the Builder unresolved-global audit and offscreen Import Mesh/Modify Original construction gate; release packaging repeats the synthetic Builder target without renderer, archive, or licensed-asset I/O. Source-string guards alone do not close escaped runtime wiring regressions.
- `scripts/codex_check.ps1 -Area mesh [-GameRoot PATH]` is the explicit visual real-game gate. Root resolution is argument, `CDMW_GAME_ROOT`, then `C:\games\Steam\steamapps\common\Crimson Desert`.
- That gate requires the sole production .NET/Vortice renderer `d3d11_vortice_shader` and resident edit backend `cdmw_mesh_core_0.1`; the retired native visual renderer has no scenario or fallback path.
- The real proof loads `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` from `0009\0.pamt`, uses production material/texture resolution, forbids checker or synthetic fallback, runs the resident select/transform/material/texture/UV/topology/undo/export sequence, reparses exported GLB/OBJ/DDS/sidecars, and fingerprints source archives before/after.
- The same proof must exercise acknowledged Vortice `textured`, `untextured_faces`, `wire_vertices`, and `vertices` against the real PAC. Display-only changes retain the process, package, buffers, textures, and SRVs. Neutral faces use inverse-transpose, two-sided camera-relative shading with a fixed floor; hidden front/back/oblique captures are synthetic evidence only, while the real PAC remains visual proof.
- Real-proof output is versioned JSON under an owned temporary root. It records PAC/archive/texture provenance and hashes, backend, geometry selection, captures, timings, fallback state, archive fingerprints, and individual gate results.
- Use a system temporary pytest base. Configured gates fail closed; full QA compiles `cdmw`, `tests`, and `tools`.
- Corpus gates require complete classification, zero read errors/crashes, and unchanged source-archive hashes; dated totals belong in `docs/release-confidence-plan.md`.

## Shared identities, I/O, and lifecycle

- Archive scan preflight treats nested PAMT trees outside root-level, `NNNN/`, `game_files/`, and `game_files/NNNN/` layouts as suspicious. It warns and lets the user cancel, open the folder, or scan anyway; it never auto-excludes files.
- Archive entries use one immutable identity: normalized virtual path, source PAMT, PAZ index, and entry offset. Caches, selection, shell bridges, and replacement flows must use all four parts.
- Full Archive Browser catalogue v2 is the default transition-release backend and uses worker protocol v3. The resident self-contained .NET worker owns scan/cache/query/facet/lookup/prepare/text/export and lazy item/material catalogues, and loads only the adjacent native full-archive DLL; Python retains remote pages and bounded prepared contexts. Each generation maps `archive.ali` plus the compact `archive.adi` basename/stem/facet index; PAC association and selection/path/basename restoration use targeted lookups without materializing `lookups.bin`, while general maps remain lazy. Native rebuilds preserve sorted merge order while using at most four PAMT parse tasks, shared per-PAMT source paths, and allocation-free case-insensitive comparison; performance work must retain byte-identical `.ali` and `.adi` output. Prepared PAC contexts pass bounded explicit dependency entries and hash that prepared snapshot for cache identity. The first bounded page may publish before extension facets, so the grouped extension picker stays disabled until `archive_extension_counts` arrives through `facetsReady`. `legacy|v2|shadow` is a developer process override, never a saved user setting. Legacy code/caches remain for this release, and fallback requires an explicit session-only dialog choice followed by request cancellation and nonblocking worker shutdown.
- File/package/report writes use a sibling temporary file or staging directory, flush as appropriate, then atomic replacement/publication. Cancellation must leave no partially published output.
- ZIP/model ingestion is streaming and cancellable, validates member count, expanded size, ratio, traversal, duplicate targets, free space, and time/byte ceilings, then atomically publishes a content-fingerprinted fresh extraction.
- Worker-owning UI follows one contract: immutable snapshot, cancellation token, monotonic request ID, queued delivery, stale-result rejection, bounded progress, `request_shutdown()`, and `iter_shutdown_workers()`.
- Deferred shell close hides the main window while owned work drains, so the final accepted close must explicitly quit `QApplication`; relying on last-visible-window close leaves the packaged process and single-instance guard resident.
- Source-checkout workspace migration must never move the repository's `tools/` tree into `workspace/`; `.git` plus `cdmw/` identifies a source checkout.
- App-owned subprocesses get cooperative grace, then process-tree termination. User-launched game and third-party applications remain user-owned.

## Texture and cache contracts

- All production DDS decode, staging, preview, encode, and rebuild work uses `cd-texture-dx.exe` protocol v2. Missing or failed native execution fails explicitly; no secondary executable is searched or launched. Profile format 4 discards obsolete converter paths/tokens, while the one-release public compatibility shim only warns and ignores obsolete arguments.
- Native DDS publication is sibling-staged, metadata-validated, and atomic. Protocol v2 owns source color policy, mip alpha policy/coverage, DDS alpha metadata, requested-mip decode, and true gray16 PNG staging. The authoritative non-UI gate is `tools/texture_replacer_headless_harness.py --scenario full-suite`; it exercises the real 2048x2048 Texture Replacer rebuild, consumer matrix, policy matrix, and failure lifecycle without archive writes.
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

- `ParsedMesh` is import/export compatibility state. The resident C++ `MeshEditSession` is authoritative for active edits; explicit mesh read/export is the hydration boundary. Active native failures must fail closed, not fall back to stale Python mutation or preview generation.
- Non-topology edits use sparse channel/index deltas. Topology edits use
  copy-on-write affected-submesh snapshots. History is bounded to 64 whole
  operations and 256 MiB while preserving exact undo/redo.
- Procedural Morph & Refit stays resident: C# owns authoring and garment controls; C++ owns fields, exact BVH binding, Surface/Rigid transport, per-garment settings, and history; Python owns correlated transport and atomic v2 persistence.
  Selections expand only at the service boundary; defaults are Surface/100%/zero clearance, preview returns to zero, and driver/garment overlap is refused.
  Compose baked base + ordinary-edit residual + procedural layer; block topology
  while unbaked, keep reference batches immutable, and never restore target import.
- Skinned PAC OBJ round-trips require the matching sidecar even for one submesh.
  A proven target-donor map preserves exact original influence rows, and rebuild
  rejects changes to PAC vertex bytes outside declared position/normal/UV0 edits.
- Fresh/resumed mesh sessions open in Orbit without restoring camera, tool, element selection, or history. Viewport part-pick signals are inert; PARTS is the sole whole-part selector. Click, Brush, Rectangle, and Lasso target active-
  layer vertices, wires, or faces without requiring a part filter. Correlated
  strokes keep one active and one cumulative pending request, preserve newer
  provisional tails across stale replies, and create one history entry at end.
  Topology drains the gesture first; failure restores its pre-stroke selection.
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
- The sole .NET/Vortice renderer retains mesh/GPU buffers, corner mappings, SRV arrays, and immutable draw resources. Sparse edits update affected ranges; topology edits rebuild affected batches and preserve original material lineage. Subdivide owns a 200,000-face/submesh cap, expands wire/vertex regions to incident faces, and atomically histories geometry plus remapped selection. Move applies a local part transform; Grab/sculpt patch a transient vertex buffer from immutable stroke candidates. Present never self-schedules; VSync and maximum frame latency one remain. `Wire + Vertices` emits no solid draw, and opening Morph & Refit must not change source parse/upload, device/surface, helper PID/HWND, camera, or presentation generation.
- Mesh Editor overlay preferences v3 persist wire, vertex, background, grid, committed-selection, and live-selection colors; v1/v2 migrate. Selection colors reach D3D11, GDI, and WPF. Background/grid overrides outrank host replay; X-Ray remains presentation-context-local.
- Native geometry layers preserve complete fragment metadata. Base mesh is permanent; only the active layer is editable, visible copies export, hidden copies remain saved, and Paste/Delete are one geometry-history action. Rename/order/visibility persist outside geometry Undo. `mesh_layer_project_v1` publishes checksum-addressed native snapshots atomically with previous-generation recovery; exact-source Modify Original drafts autosave after 750 ms, become persistent on first layer, and never restore runtime selection/camera/tool/history.
- Preview packages use singleflight, leases, atomic publication, consume/ack cleanup, and safe pruning. Source-stamped PAMT indexes have parse fallback; per-job material maps release while bounded decoded entries remain reusable.
- External material factors are immutable per synthesized texture: normalize and scan material parameters once, then apply the resolved factors per pixel. Preserve byte-identical roughness/metalness/specular outputs and cancellation checks.
- .NET helper-authored OBJ/package/operation paths and generated sidecars stay under the package output root after canonical link-aware resolution. Archive Preview expected stops are keyed by exact process plus generation; unmatched nonzero exits and device loss remain failures.
- `cdmw/ui/preview/` is the shared visible-model host. Stable host/session classes compose focused protocol, value-coercion, and localization owners; MeshService likewise keeps its facade while native-session and native-clone work lives in focused owners. Its `preview` profile is read-only and `authoring` enables Mesh Editor mutations. Visibility is correlated `inactive -> resuming -> active`: matching packages activate in place, differing identities load first, one activation retry precedes automatic recovery, and healthy hide/show cycles preserve PID and resident state. Both profiles retain path/material/scene identity, monotonic generations, stale rejection, package leases, and bounded shutdown. Python/C++ retain decode and mutation authority; authoring recovery replays MeshService state before input resumes. Shared authoring has one scene request/generation owner: preview-host placement delegates to the Mesh Editor tab, and controller scene replay stays disabled while that tab's authoritative rehydrator is installed; preview-only hosts retain independent replay.
- One resident document/resource owner backs separate Original and Imported/Modify contexts with independent normal cameras and explicit linked comparison. Edit Mesh forces Replacement Only and pins the editable camera context across scene/presentation replay; leaving it restores the selected placement preview mode without restarting the renderer. Builder presentation is correlated; placement previews locally at input cadence with an exact provisional editable matrix while Original, role camera frames, and the resident world grid stay fixed. Camera Fit/nudge commands are role-addressed and generation-gated so persistent presentation replay is state-only. Authority requests coalesce at approximately 30 Hz with an exact final transform, and close uses acknowledged deactivation plus one final sync.
- Dynamic resident combo boxes must select `-1` while their item list is empty; clamping an empty list to `0` aborts WinForms construction. Edit Mesh stays on the authoring profile during launch, Ready, and retry; classic compatibility panels stay hidden and off-stack.
- Embedded Edit Mesh consumes Escape instead of rejecting the whole builder; explicit close/replacement still works. Its status and widened FPS readout live in the pane headers, its camera strip remains inside the resident preview, compact 8.5-point tool panels replace the oversized side controls, and embedded status/footer rows consume no preview height. The Qt builder retains callback state in hidden sinks and parents its action row inside the side controls so Edit Mesh can hide it. Preview clearing is idempotent after its Qt owner is deleted, and queued state sync drops stale embedded controls so builder-finished cleanup cannot cascade through deleted `QTimer`/`QPushButton` wrappers. Classic remains the per-form default with its fixed Select/Move/Brush/Topology jump bar, inline label/input rows, and viewport-wide status/FPS footer. Its opt-in Bottom Tool Deck keeps the resident viewport under one permanent Win32 parent and reparents only ordinary tool controls into tabbed bottom tools plus a right inspector; its dimensions/tab are session-only and never overwrite classic splitter preferences. Never assign the hidden compact splitters their real panel minimums during construction; apply them only after nonzero client sizing or every preview profile can fail before renderer startup.
- Resident material protocol v2 updates parameters, resources, and bindings in-process. Mesh Editor tracks `editable_imported` and `original_reference` generations independently; Textured settles only after every required role applies, and failures name the pane while retaining last-valid resources. Initial Archive and authoring packages remain geometry-only. Schema-8 Archive packages use atomic adapter sidecars beside validated native buffers and never enter Python geometry/OBJ/PNG conversion. Renderer-ready native UVs keep the shared Wavefront convention, Source DDS wins over preview PNG, and PAC shader/alpha/two-sided contracts remain independent of DDS resolution. Declared slot/type/subtype/channel evidence outranks path-token guesses; deterministic coverage puts a declared glossiness map below an `ao` parent.
- Preserve the logical absolute Archive cache alias when it is a junction; resolving it to the longer canonical cache target can exceed the native Win32 path budget. Real-PAC harnesses accept geometry `Ready` first and apply resident material state explicitly; they must not wait for legacy initial `textures_ready`. If a before/after archive content hash changes, stop licensed validation without retrying or restoring the archive implicitly.
- Material Authority exactness is artifact-scoped: one revisioned fingerprint covers canonical DDS bindings, affected submeshes, and residual parameters; the .NET preview acknowledges them atomically and Build Mod reuses the same DDS bytes plus read-back-verified emissive/height sidecar values. First user edits activate the existing complete-source route, pending/stale/mismatched state blocks Build, and per-part glow requires exactly one selected source part with shared-material cloning. Proprietary game lighting, layer graphs, and post-processing are not part of this parity claim.
- glTF green-up normals invert in HLSL and base alpha is constant opacity. Exact PAC ownership prevents emissive leakage; proven color-blending masks use R=AO, G=roughness, B=metalness while `_mg` stays layer-only. Zero intensity plus non-authoritative fallback color is not emissive-family evidence; active intensity/color/role/channel is authoritative.
- Production shading uses linear GGX/Smith/Schlick, proven opacity/cutout/occlusion, and authority-gated culling. Blend draws are depth-read/no-write and sorted by transformed submesh center; global fallback culling stays disabled for mixed PAC winding, and depth stays enabled. Source tint and Archive's luminance ACES operator with a 0.5 contrast pivot remain active.
- The RGB warm-front/cool-side environment anchors reflections to source-colored F0; physical Fresnel and GGX/Smith replace the flattened grayscale/ad-hoc metal path. The expanded corpus requires a bounded source-readable metal floor plus Archive Browser chromatic-tint authority so dark and colored assets do not collapse or double-color. Two-sided backfaces flip the tangent frame and final contrast preserves luminance chromaticity. Hidden textured-metal proof v4 retains texture detail and captures four same-material specular-debug views whose brightness/color response is complete, varying, and bounded.
- Wrong-family generic layer albedo may fall back to decoded sidecar tint while keeping same-family technical maps; unproven layer, hair/fur, skin, and blend ordering stays diagnostic. Mutable region edits copy only the affected resource to a full BGRA mip chain, regenerate lower mips after boxed uploads, and retain the resident process/package/viewport. Topology evidence scans the retained protocol tail after event pruning.
- The canonical visual audit prepares one canonical package/material artifact set and captures both Archive and editor roles through the same resident .NET/Vortice implementation. It captures six fixed angles, requires direct verdicts, and fingerprints source archives. Its camera uses Archive's `T(-center) * Rx(pitch) * Ry(yaw)` object basis; normalized right/up/view axes reject mirrored or rolled captures. Hidden automation never calls `Show`; it is renderer-consistency evidence, not visible licensed-game proof.
- Generate Icon must uniformly fit the live camera zoom/pan into its square offscreen target; reusing a wide viewport matrix directly distorts X/Y. The clean 1024x1024 capture feeds a non-blocking rectangle selector, then fit-pads the chosen area into 512x512 without stretching.
- The 2026-07-17 expanded baseline covers 162 unique PACs (156 additions plus six repeat controls) at 136 PASS/24 CONCERN/2 FAIL and exposed shared metal-floor/tint and inferred-cutoff defects. The later non-overlapping 120-PAC material-classification audit moved from 99/4/17 to 119/1/0 after repair; its only remaining concern is sword 004's localized guard tint/material region. Every row classifies the visible material first, and mixed assets use region-level observations; equipment slot or filename is never metal authority.
- A fifth 120-PAC material-first audit excludes all 317 prior-evidence paths and finalized at 120/0/0 after direct review of all 720 paired views. It found no new shared defect across swords, shields, other weapons, helmets, full armor slots, hair/beard, skin, fur, bone, crystal, organic shell, and unusual mixed creatures. Visually ambiguous pale mask 091 was confirmed by its extracted contract as dominant metal; soft apparel and creature controls remained matte. Evidence root: `workspace/mesh-editor-visual-audit/20260717-fifth-material-classification-120`.
- Qualify historical renderer-to-renderer results as prepared-package compatibility evidence, not PAC-source fidelity. The 2026-07-22 source-fidelity v2 run at `cdmw-material-parity-final-120-20260720-111535` completed 3,558/3,558 direct original-detail inspections with clean path/hash integrity and strict finalization at 120 PASS/0 CONCERN/0 FAIL across 1,359 regions. Forty-one of 42 parked rows cleared against source/region/PAC state; the one real defect was textureless generic base tint incorrectly gated by zero blend strength, fixed by honoring explicit `MaterialBaseTint.w` and directly recaptured on spear-0057 with a textured control unchanged. Native DDS source-board previews (21 rows) and hair/fur anisotropy/flow (68 rows) remain explicit unchanged unsupported features; no licensed real-game proof was run.
- Older standard `_sp` maps use G as direct roughness and B as metal/specular response; opaque R/A are controls, not gloss. Armor-family placement promotes a whole submesh only when decoded metal is dominant, while localized metal remains per-pixel on generic mixed cloth/leather. Inferred sparse hair alpha falls back to opaque only when cutoff would discard at least 90% of the decoded color texture; explicit cutout authority is unchanged.
- Offscreen capture resizing must preserve `camera.World` and rebuild only the projection. Recreating an Archive-audit camera through the interactive constructor changes its basis even when yaw/pitch match; rendered-view integrity owns this proof.
- Direct authoritative DDS bytes, formats, dimensions, and mips stay identical to source. Fit, source atlases, capped synthesized outputs, or unsupported response can still soften images. This is CDMW renderer-consistency evidence, never licensed-game parity proof.
- Prepared audit packages own and rewrite every nested selectable `source_path`, including non-direct candidates, so cache eviction cannot invalidate capture. Representative hair PAC `cd_ptm_00_hair_00_0003.pac` must resolve at least one source DDS.
- OpenImageIO is offline metadata/diff evidence only, never runtime shading or DDS authority. Shader comparisons require exact same-camera captures and retained amplified diffs; identical corpus inputs require identical fingerprints.
- `cd-texture-dx` batch JSON parsing stays allocation-light without `std::regex`; legacy archive/icon warmup can leave the parent near 1.7 GiB private memory. Full remote Item Finder warmup starts only after session publication, pins at most the restored 72-row page plus a 96-image general LRU, and leaves the all-icon set in `cache/preview/item-icons`. Other runtime cache paths are grouped under `cache/index/catalogue_v2` and `cache/preview/{models,native,textures/directxtex}`; startup migrates known legacy lanes only into absent destinations. Its executable self-test owns JSON escape and alias coverage.
- Full remote Item Finder category/group ownership is the resident .NET `Cdmw.FullArchive.Core/ArchiveItemCatalog.cs`, not the richer legacy Python catalogue or the PySide dialog. It mirrors Lite's ordered taxonomy across internal, display, localized, model, PAC, and icon naming evidence, with token boundaries and `Item / Unclassified` fallback. Full and the independent Lite repository must port rule changes deliberately; never add a runtime source/binary dependency on the sibling checkout.
- External OBJ/DAE/glTF/GLB missing/incomplete UVs use cancellable xatlas and report review-required. Shared UV transforms bake before the V flip; differing sets use sampler/color-space-correct raster baking, native tangents, normal-basis conversion, gutters, and atomic hashes. Unsupported input blocks safely; PAC/PAM is never auto-unwrapped.
- External ZIP import uses verified extraction; geometry fits the original frame, centers and Y-grounds, and overlay/side-by-side share one grid. Exact `cd_phm_01_sword_0016.pac` plus `wolf_gravestone_sword_free (1).zip` uses archive-resolved original textures and ZIP-owned imported textures. Archive Browser derives a new package's camera from manifest `source_path`: weapon/subweapon/shield families retain fitted overhead (`yaw=0`, `pitch=-89`) and their existing fit, while armor/bodies/hands/feet/generic/missing paths use the asset-facing front (`yaw=180`, `pitch=0`) at `0.75x` fit-relative zoom; refreshing the same model preserves its camera.
- Hardware soak must cover production-scale sparse updates, tail shrink,
  material lineage, handler time, and post-warmup RSS; dated results belong in
  `docs/release-confidence-plan.md`.
- The real nude-PAC gate must leave archives unchanged. Mesh Edit starts with no
  selected part; face/vertex modes can render without textures. Parts visibility
  never changes the alignment basis, and duplicate/delete are resident actions.
- Resident .NET Preview Settings expose only Camera Input in Archive Browser and Camera Input plus placement-Gizmo appearance in Mesh Editor; hidden renderer settings remain preserved. The embedded getter must read the live Builder accessor, not the setup factory's initial object.
  Side by Side alone creates two role panes; Overlay is one comparison surface, and each Only mode is one full-viewport role. Texture/view state syncs across roles while cameras stay independent.
  An equal-size child resize must still refresh GPU pane rectangles/cameras; mode toggling is not a layout initialization mechanism.
  Wheel zoom uses Archive Browser's exact `0.1..64x` fit-relative ladder,
  preserves camera-space pan so a panned focal point stays anchored, and updates
  only the side-by-side pane under the pointer. The .NET renderer child must
  mark forwarded wheel events handled so one physical event cannot bubble into
  a second parent zoom step.

## Startup and packaging contracts

- Archive Lite is the independent Python-free read-only WPF repository checked out beside this one at `D:\CLAUDETEST\CDMW Lite`; it is no longer built or tested from this worktree. That repository owns snapshots of its semantic library, schema, native helpers, and .NET/Vortice renderer and rejects references back here. It starts in Archive Browser, stores settings/cache/logs beside the EXE, publishes full text through bounded preview artifacts, decodes DDS with packaged DirectXTex and WEM with pinned vgmstream, and exposes PAC/PAM/PAMLOD raw or GLB/OBJ/FBX output through unified Export selected. Keep Associated assets in a real column beside the native child HWND because WPF overlays cannot win that airspace; theme switches must rebuild both AvalonEdit surfaces from the cached Dark+/Light+ definitions. Its focused and release owners are root-level `scripts/test_archive_lite.ps1` and `scripts/build_archive_lite.ps1` in the independent repository.
- Public `run_gui()` imports implementation only when called; lazy optional tabs
  must not pull NumPy, OpenCV, or preview stacks into cold facade import.
- Startup smoke uses a unique instance namespace and an atomic marker written
  only after window construction. Lock collision is failure.
- Full startup releases the splash after UI construction and schedules archive load on the next event-loop turn; its explicit one-shot dispatch latch prevents the zero-delay first-run path and legacy 900 ms fallback from starting two remote scans. The first-run archive-path dialog is modeless and resumes startup from `finished`; never reintroduce a pre-main-loop `exec()` because it can leave the packaged shell input-blocked after cache publication. While the shell is hidden, suppress and then restore Qt's quit-on-last-window-close policy around that prompt so Continue/Skip cannot terminate startup. Legacy startup retains its cache behavior. Full's top status belongs only to archive work, uses indeterminate progress without a total, and terminalizes as `Archive ready 100%`; preview readiness stays inside the preview pane.
- Lazy composed `MainWindow` callbacks are QObject-owned and import-deferred.
  Worker signals need those or an owning-thread QObject receiver; lambdas/plain
  callables execute in the worker even with `QueuedConnection`.
- Shell Qt virtuals are explicit controller bridges. The first accepted close
  hides the shell, rejects registered modeless builders, and starts one
  nonblocking coordinator. Close retains all owned `QThread`s and processes
  until teardown is confirmed, force-stops only owned external process trees
  after grace, and publishes the final closed heartbeat last. A finished
  parentless Python worker returns to the UI thread before its QThread quits;
  UI-side cleanup then defer-deletes both objects after that same fence. Pure-Python bulk loops in workers must yield the GIL at their bounded cancellation checkpoints; the static replacement bounds scan does so every 4,096 vertices and is held by the million-vertex heartbeat gate in `mesh-unit`.
- Full diagnostics persist only recovery breadcrumbs and issue-class events by
  default; the existing extra-context preference enables verbose Python/native
  streams. Same-session fingerprint duplicates collapse to one report, the
  newest 20 issue reports are retained, and support actions ignore state logs.
- Release builds regenerate and verify provider metadata before PyInstaller. The
  configured-archive gate loads 1.67M entries, paints, filters, and requires a clean shutdown.
- Release packaging carries the full archive worker plus native DLL under `archive_backend/` in onedir and onefile. The published and exact packaged bundles must pass the headless synthetic protocol/ABI, open/query/page, cancellation, and no-orphan shutdown probe; that does not substitute for separately authorized real-corpus evidence.
- Startup benchmark evidence is owned by
  `docs/reference/app-startup-benchmark-phase5.json` and
  `docs/reference/app-startup-benchmark-phase6.json`; dated timing summaries
  belong in `docs/release-confidence-plan.md`.
- Release Python dependencies are pinned by tested constraints. CI installs .NET 10,
  builds the exact helper, runs nonvisual Python 3.11/3.14 gates, and gates packaging on both QA jobs. Headless entry-report tests close stdin deliberately and mark their real-form construction as `HeadlessSmoke`, so the embedded-form proof does not mistake test EOF for a dead Python host and arm the five-second `Environment.Exit(0)` watchdog. Production embedded launches keep that orphan-prevention path. The report JSON, not process timing, owns the result and is reused across parameterized consumers.
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
- Split cohesive hotspots behind unchanged facades. New owner modules use a
  1,000-line default and functions stay at most 150 lines. Valid cohesive,
  static-data, or generated exceptions must be explicit in the owning guard;
  grandfathered oversize ratchets may only stay level or decrease.
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
