# Archive Lite validation matrix

All commands are Python-free and use system temporary directories for synthetic archives and exports. They do not launch the visible application, licensed game content, or real PAMT/PAC data.

## Focused validation

```powershell
.\apps\Cdmw.ArchiveLite\scripts\test_archive_lite.ps1 -Configuration Debug
```

This gate configures and builds `cdmw_archive_core`, `cdmw_preview_core`, `cdmw_archive_accelerator`, `cdmw_mesh_core`, the DirectXTex-backed `cd-texture-dx`, and the Rust `cd-hkx` parser; runs the available native self-tests/version checks; builds the .NET 10 solution and .NET/Vortice renderer; and runs the managed console test runner. Covered behavior includes:

- versioned native index ABI and caller-owned decode buffers;
- raw, LZ4, filename-derived ChaCha20, and PATHC-backed partial DDS decode;
- safe virtual-path normalization and traversal/root rejection;
- archive scan/query/preview/text-search behavior, DDS-to-PNG decode, complete text-document artifact publication, and source-file SHA-256 immutability;
- game-folder recognition and Steam-library parsing, plus missing/current/stale archive-cache health transitions;
- portable settings/cache/log/crash routing beside the distributable with isolated test overrides; round-trip persistence for archive/text-search filters, export options, theme, global font size, layout density, window placement, split panes, and grid columns; deterministic Archive Browser startup; startup auto-load of a current persistent cache without prompting; automatic cache-choice presentation when no index exists; full-fingerprint rejection without an automatic rebuild after same-size/same-timestamp source changes; and a manual Refresh recommendation for stale caches;
- persistent index build/reuse and forced-rebuild routing, real native PAMT parse/sort/write/publish totals, cooperative native cancellation, one-time index isolation and shutdown cleanup, source-byte immutability, and the shared themed cache-choice flow for manual Open and Refresh;
- native mesh-only model-package adaptation, hidden grid/gizmo state, empty texture channels, exact geometry-length checks, path-containment rejection, and a headless synthetic package load through the real .NET renderer;
- synthetic mesh-only GLB 2.0, OBJ, and binary FBX exports, source-geometry immutability, determinate conversion progress, and cancellation that preserves an existing destination;
- exact known-name versus related-hint classification, categorized extension facets whose grouped picker exposes individual extensions with pixel scrolling, freely resizable/configurable file-grid columns, and server-side sorting for every displayed field;
- associated-asset discovery from exact material-sidecar paths, embedded DDS/HKX references, same-family mesh/prefab companions, color-coded filename-only categories with tooltip evidence, multi-selected/family raw export, learned DDS-to-PAC reverse navigation, cancellation/stale-result ownership, worker progress forwarding, and source-byte immutability;
- rich synthetic DDS metadata plus bounded native HKX tagfile parsing, a two-bone parent hierarchy encoded as joint points and a parent-child line, explicit X-Ray wire/vertex presentation for skeleton and collision-only previews, supported collision-shape output without arbitrary object-graph dots, portable helper discovery, and model-package preparation without a grid, gizmo, texture, or source mutation;
- contained atomic export, skip-on-collision, selectable flat or preserved virtual paths, associated-family routing, and manifests;
- content-addressed standalone extraction, package-manifest verification, atomic publication, damaged-cache quarantine/rebuild, cached reuse, and ZIP traversal rejection;
- JSON snake-case protocol serialization, compiled resource parity, portable fatal diagnostics, compact title-row workspace navigation without a secondary tab band or decorative badges, preview-side associated-assets drawer, rich full-document editor/search bindings, a categorized extension selection handler, rounded transparent cache/export-dialog chrome, cache/game controls, and Enter-to-search wiring; and
- a real named-pipe worker process that opens and queries a synthetic PAMT/PAZ archive, publishes the full selected text document outside the bounded protocol message, performs an associated-asset request with progress, reports its cache current, shuts down cleanly, and leaves source bytes unchanged.

## Release/package gate

```powershell
.\apps\Cdmw.ArchiveLite\scripts\build_archive_lite.ps1
```

In addition to rerunning the focused checks in Release, this gate publishes the app, worker, and .NET/Vortice renderer self-contained for `win-x64`, includes the native archive, model-preview, item-name-index, mesh-interchange, DirectXTex DDS, Rust HKX, and pinned vgmstream media helpers, writes a SHA-256 package-content manifest, and calls:

```powershell
.\apps\Cdmw.ArchiveLite\scripts\verify_archive_lite_artifact.ps1 -ArtifactDirectory <published-folder>
.\apps\Cdmw.ArchiveLite\scripts\verify_archive_lite_standalone.ps1 -ExecutablePath <standalone-exe>
```

The portable artifact guard rejects Python source/bytecode/extensions/runtimes, Python-named runtime folders, and PE files that reference a Python DLL. It also checks every Archive Lite/native entry point, including `cd-hkx.exe`, is x64 and the separately hosted pinned vgmstream bundle is consistently x86; runs the native model-preview and DirectXTex self-tests; verifies every packaged vgmstream file against the pinned dependency manifest; verifies the packaged mesh core writes binary FBX 7400; loads and exports a synthetic native package through the packaged renderer without changing its source bytes; runs a hidden synthetic GPU smoke that requires `d3d11_vortice_shader` and measurable textureless contour separation on a faceted form from four angles; constructs and lays out the real WPF `MainWindow` across every theme/font-size/density combination without showing it; exercises the application-to-worker protocol; and rejects an orphaned packaged worker.

The standalone guard requires one x64 Native AOT executable with no runtime companion files. It launches that EXE against an isolated system-temporary data and portable-cache root, verifies first-run extraction and cache routing, launches it again to prove content-addressed runtime reuse without marker mutation, exercises the extracted application's worker-connected self-test both times, rejects an orphaned worker, and removes the isolated runtime afterward.

## Proof boundaries

Passing these gates proves synthetic archive correctness, exact and same-family associated-asset routing for the covered metadata shapes, full text-document handoff, native DDS decode, a synthetic native HKX skeleton preview, native package-to-renderer compatibility, synthetic Blender-interchange structure, hidden production-backend initialization, process lifecycle, portable and standalone packaging composition, first-run/cached launcher behavior, and the absence of a packaged Python runtime/import. Associated-asset name-family matches are intentionally labeled as hints and are not a claim of a dependency-complete game graph. The gates do not prove Blender import or visual fidelity for real PAC/PAM/PAMLOD content, cover every real HKX skeleton/physics variant or every game DDS/WEM/BK2 variant, prove that an installed Windows codec can play proprietary BK2, or provide publisher code signing. Real-asset, Blender, HKX/media-corpus, and visible model-fidelity validation remains a separately authorized gate.
