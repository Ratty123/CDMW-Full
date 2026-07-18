# CDMW Archive Lite

CDMW Archive Lite is a separate, read-only Windows desktop application for browsing Crimson Desert PAMT/PAZ archives and searching text. Its application, worker, native archive and model-preview services, .NET/Vortice renderer, build, tests, and portable package do not embed or invoke Python.

## Included

- Windows 11 x64 WPF shell on .NET 10, localized in English, German, and Spanish, with persistent Graphite, Midnight, and Light themes.
- Stable memory-mapped archive index with archive fingerprints and isolated caches.
- Flat, folder, category, and category-plus-folder navigation with server-side filters, sorting, and 256-row paging.
- Preview for text, metadata, binary hex, WIC-supported images (including supported DDS variants), and media formats supported by Windows Media Foundation.
- Read-only PAC, PAM, and PAMLOD scene preparation through `cdmw-preview-core.exe`, displayed by the embedded production `d3d11_vortice_shader` .NET renderer. Package preparation is cancellable, cached by immutable archive identity, and reported in the UI.
- Native raw, LZ4, ChaCha20, partial PAR, and PATHC-backed partial DDS extraction.
- Literal or regular-expression text search across archives or loose folders, with bounded parallelism, per-pattern timeouts, result caps, line/column/context, and cancellation.
- Selected-file, filtered-tree, and search-result export. Virtual folder structures are preserved, every file is written through a sibling staging file, collisions default to skip, and JSON manifests record archive provenance.
- A versioned 1 MiB JSONL protocol over a private named pipe. Slow scan, query, preview, search, and export work runs in the owned worker process, never on the WPF dispatcher.
- Portable self-contained ZIP packaging with Python payload/import guards, x64 checks, application/worker/native self-tests, a synthetic native-package load, and a hidden Vortice GPU smoke.

Archive Lite has no archive-write, replacement, import-mesh, Modify Original, Build Mod, patch, backup, or restore authority. The native archive ABI intentionally exposes only scan and decode operations.

HKX selections still receive bounded metadata and binary inspection; Archive Lite does not claim an HKX visualizer. Unsupported specialized conversions (OBJ, FBX, WAV, HKX JSON/XML, structured JSON, and dependency-set export) fail explicitly instead of silently exporting a different format. PAC/PAM/PAMLOD display is preview-only: editing controls, source replacement, mesh import, and archive mutation remain absent.

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

The package is written beneath `apps/Cdmw.ArchiveLite/artifacts/`. Packaging builds both native read-only services, publishes the app, worker, and renderer self-contained for `win-x64`, scans every packaged PE for Python runtime references, verifies x64 architecture, loads a synthetic native preview package in the packaged renderer, proves the hidden production Vortice backend, constructs and lays out the real WPF window without showing it, exercises the packaged application-to-worker connection, and checks that no worker remains.

## Data isolation

Archive Lite writes only to its chosen export destination and to:

```text
%LocalAppData%\Ratrider\CDMWArchiveLite\
  settings.json
  cache\index\
  cache\preview\models\
  cache\preview\native\
  cache\preview\runtime\
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
          +-- text search / preview cache / atomic export
          +-- cdmw-preview-core.exe (C++20, PAC/PAM/PAMLOD package preparation)
          |
          +-- memory-mapped archive_index_v1
          v
cdmw-archive-core.dll (C++17, read-only PAMT/PAZ/PATHC decode ABI)

CdmwArchiveLite.exe
          +-- preview-only child HWND + process/job ownership
          v
cdmw-mesh-dotnet-editor.exe (.NET 8 + Vortice D3D11, read-only scene display)
```

The app owns presentation and latest-selection acceptance. The worker owns expensive I/O and CPU work. The native archive DLL owns archive parsing and codecs; the native preview executable prepares immutable renderer packages. The app keeps the previous model visible until a replacement renderer is ready and rejects any renderer backend other than `d3d11_vortice_shader`. Closing the app requests cooperative shutdown and then closes Windows Job Objects so the owned worker, preview-core descendants, and renderer are terminated.

See [TESTING.md](TESTING.md) for the validation matrix and proof boundaries.
