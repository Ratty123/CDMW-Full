# Archive Lite validation matrix

All commands are Python-free and use system temporary directories for synthetic archives and exports. They do not launch the visible application, licensed game content, or real PAMT/PAC data.

## Focused validation

```powershell
.\apps\Cdmw.ArchiveLite\scripts\test_archive_lite.ps1 -Configuration Debug
```

This gate configures and builds `cdmw_archive_core`, `cdmw_preview_core`, and `cdmw_archive_accelerator`; runs the available native self-tests/version checks; builds the .NET 10 solution and .NET/Vortice renderer; and runs the managed console test runner. Covered behavior includes:

- versioned native index ABI and caller-owned decode buffers;
- raw, LZ4, filename-derived ChaCha20, and PATHC-backed partial DDS decode;
- safe virtual-path normalization and traversal/root rejection;
- archive scan/query/preview/text-search behavior and source-file SHA-256 immutability;
- native mesh-only model-package adaptation, hidden grid/gizmo state, empty texture channels, exact geometry-length checks, path-containment rejection, and a headless synthetic package load through the real .NET renderer;
- exact known-name versus related-hint classification, categorized extension facets, configurable file-grid columns, and server-side sorting for every displayed field;
- contained atomic export, skip-on-collision, preserved virtual paths, and manifests;
- JSON snake-case protocol serialization; and
- a real named-pipe worker process that opens and queries a synthetic PAMT/PAZ archive, shuts down cleanly, and leaves source bytes unchanged.

## Release/package gate

```powershell
.\apps\Cdmw.ArchiveLite\scripts\build_archive_lite.ps1
```

In addition to rerunning the focused checks in Release, this gate publishes the app, worker, and .NET/Vortice renderer self-contained for `win-x64`, includes the native archive, preview, and item-name-index helpers, writes a SHA-256 package-content manifest, and calls:

```powershell
.\apps\Cdmw.ArchiveLite\scripts\verify_archive_lite_artifact.ps1 -ArtifactDirectory <published-folder>
```

The artifact guard rejects Python source/bytecode/extensions/runtimes, Python-named runtime folders, and PE files that reference a Python DLL. It also checks every native/application entry point is x64; runs the native preview-core and worker self-tests; loads and exports a synthetic native package through the packaged renderer without changing its source bytes; runs a hidden synthetic GPU smoke that requires `d3d11_vortice_shader`; constructs and lays out the real WPF `MainWindow` without showing it; exercises the application-to-worker protocol; and rejects an orphaned packaged worker.

## Proof boundaries

Passing these gates proves synthetic archive correctness, native package-to-renderer compatibility, hidden production-backend initialization, process lifecycle, packaging composition, and the absence of a packaged Python runtime/import. It does not prove visual fidelity for real PAC/PAM/PAMLOD content, provide an HKX visualizer, cover every DDS codec supported by Windows, or prove playback of proprietary BK2/WEM assets. Real-asset and visible model-fidelity validation remains a separately authorized gate.
