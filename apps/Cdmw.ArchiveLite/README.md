# CDMW Archive Lite

CDMW Archive Lite is a separate, read-only Windows desktop application for browsing Crimson Desert PAMT/PAZ archives and searching text. Its production executable, worker, native archive decoder, build, tests, and portable package do not embed or invoke Python.

## Included

- Windows 11 x64 WPF shell on .NET 10, localized in English, German, and Spanish.
- Stable memory-mapped archive index with archive fingerprints and isolated caches.
- Flat, folder, category, and category-plus-folder navigation with server-side filters, sorting, and 256-row paging.
- Preview for text, metadata, binary hex, WIC-supported images (including supported DDS variants), and media formats supported by Windows Media Foundation.
- Native raw, LZ4, ChaCha20, partial PAR, and PATHC-backed partial DDS extraction.
- Literal or regular-expression text search across archives or loose folders, with bounded parallelism, per-pattern timeouts, result caps, line/column/context, and cancellation.
- Selected-file, filtered-tree, and search-result export. Virtual folder structures are preserved, every file is written through a sibling staging file, collisions default to skip, and JSON manifests record archive provenance.
- A versioned 1 MiB JSONL protocol over a private named pipe. Slow scan, query, preview, search, and export work runs in the owned worker process, never on the WPF dispatcher.
- Portable self-contained ZIP packaging with a Python payload/import guard and application/worker self-tests.

Archive Lite has no archive-write, replacement, import-mesh, Modify Original, Build Mod, patch, backup, or restore authority. The native archive ABI intentionally exposes only scan and decode operations.

Model and HKX selections currently receive bounded metadata and binary inspection. The resident Vortice model renderer is not copied from the full application because it is still coupled to editor-owned scene preparation; it must be extracted behind a preview-only contract before Archive Lite can claim visual PAC/HKX parity. Unsupported specialized conversions (OBJ, FBX, WAV, HKX JSON/XML, structured JSON, and dependency-set export) fail explicitly instead of silently exporting a different format.

## Run from source

Requirements are Windows 11 x64, the .NET 10 SDK, CMake 3.24 or newer, Visual Studio 2022 Build Tools with the Desktop C++ workload, and PowerShell.

```powershell
.\apps\Cdmw.ArchiveLite\scripts\test_archive_lite.ps1
dotnet run --project .\apps\Cdmw.ArchiveLite\src\Cdmw.ArchiveLite.App\Cdmw.ArchiveLite.App.csproj -c Debug
```

The second command launches a visible desktop window and is intentionally not part of automated validation.

## Build the portable ZIP

```powershell
.\apps\Cdmw.ArchiveLite\scripts\build_archive_lite.ps1
```

The package is written beneath `apps/Cdmw.ArchiveLite/artifacts/`. Packaging runs native and managed tests, publishes both executables self-contained for `win-x64`, scans every packaged PE for Python runtime references, verifies x64 architecture, runs the packaged worker self-test, runs the packaged application-to-worker self-test, and checks that no worker remains.

## Data isolation

Archive Lite writes only to its chosen export destination and to:

```text
%LocalAppData%\Ratrider\CDMWArchiveLite\
  settings.json
  cache\index\
  cache\preview\
  logs\
  crash\
```

It does not read or write the full workbench's settings, caches, restore points, mod workspace, or Python environment. PAMT, PAZ, and PATHC sources are opened read-only. Before export, the worker recomputes the source fingerprint and refuses stale sessions.

## Architecture

```text
CdmwArchiveLite.exe (WPF dispatcher)
          |
          | private named pipe, protocol v1, request IDs + generations
          v
CdmwArchiveLite.Worker.exe (.NET 10, cancellable operations)
          |
          +-- memory-mapped archive_index_v1
          +-- text search / preview artifact cache / atomic export
          v
cdmw-archive-core.dll (C++17, read-only PAMT/PAZ/PATHC decode ABI)
```

The app owns presentation and latest-selection acceptance. The worker owns expensive I/O and CPU work. The native DLL owns archive parsing and codecs. Closing the app requests cancellation, allows two seconds for cooperative worker shutdown, and then closes a Windows Job Object so the entire owned process tree is terminated.

See [TESTING.md](TESTING.md) for the validation matrix and proof boundaries.
