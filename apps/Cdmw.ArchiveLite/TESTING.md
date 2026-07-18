# Archive Lite validation matrix

All commands are Python-free and use system temporary directories for synthetic archives and exports. They do not launch the visible application, licensed game content, or real PAMT/PAC data.

## Focused validation

```powershell
.\apps\Cdmw.ArchiveLite\scripts\test_archive_lite.ps1 -Configuration Debug
```

This gate configures and builds `cdmw_archive_core`, runs its CTest executable, builds the .NET 10 solution with warnings as errors, and runs the managed console test runner. Covered behavior includes:

- versioned native index ABI and caller-owned decode buffers;
- raw, LZ4, filename-derived ChaCha20, and PATHC-backed partial DDS decode;
- safe virtual-path normalization and traversal/root rejection;
- archive scan/query/preview/text-search behavior and source-file SHA-256 immutability;
- contained atomic export, skip-on-collision, preserved virtual paths, and manifests;
- JSON snake-case protocol serialization; and
- a real named-pipe worker process that opens and queries a synthetic PAMT/PAZ archive, shuts down cleanly, and leaves source bytes unchanged.

## Release/package gate

```powershell
.\apps\Cdmw.ArchiveLite\scripts\build_archive_lite.ps1
```

In addition to rerunning the focused checks in Release, this gate publishes the app and worker self-contained for `win-x64`, merges the native decoder, writes a SHA-256 package-content manifest, and calls:

```powershell
.\apps\Cdmw.ArchiveLite\scripts\verify_archive_lite_artifact.ps1 -ArtifactDirectory <published-folder>
```

The artifact guard rejects Python source/bytecode/extensions/runtimes, Python-named runtime folders, and PE files that reference a Python DLL. It also checks the app, worker, and native decoder are x64 PE files; runs the worker ABI self-test; constructs and lays out the real WPF `MainWindow` without showing it; exercises the application-to-worker protocol; and rejects an orphaned packaged worker.

## Proof boundaries

Passing these gates proves synthetic archive correctness, process lifecycle, packaging composition, and the absence of a packaged Python runtime/import. It does not prove visual fidelity for real PAC/HKX models, every DDS codec supported by Windows, or playback of proprietary BK2/WEM assets. Those require separately authorized real-asset and visible-application validation after a preview-only native/Vortice model host is integrated.
