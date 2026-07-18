# CDMW Archive Lite

CDMW Archive Lite is a separate, read-only Windows desktop application for browsing Crimson Desert PAMT/PAZ archives and searching text. Its application, worker, native archive and model-preview services, .NET/Vortice renderer, build, tests, and portable package do not embed or invoke Python.

## Included

- Modern resizable Windows 11 x64 WPF shell on .NET 10, localized in English, German, and Spanish, with immediate in-place language switching and persistent Graphite, Midnight, and Light themes.
- Automatic Crimson Desert folder discovery from environment overrides, Steam libraries/registry data, and common Steam, Epic, Xbox, and standalone install locations. A manual Detect game action and folder picker remain available.
- Stable memory-mapped archive index with archive fingerprints and isolated caches. The selected root is checked at startup and labeled as current, missing, stale, or invalid before it is opened. Every Open or Refresh asks whether to use a reusable persistent index or build a one-time session index. Persistent indexes are reused only for the same verified source fingerprint and are rebuilt through an atomic replacement; one-time indexes always rescan, never publish persistent freshness metadata, and are removed when the worker session closes.
- Flat, folder, category, and category-plus-folder navigation with server-side filters and 256-row paging. The file grid supports click-to-sort on every column, column resizing/reordering, and a persistent visible-column chooser.
- A categorized extension picker that expands every group into its individual extensions and per-extension counts, using the same model/mesh/physics, texture/image, material/metadata, animation/scene, audio/video, UI/text, and other groups as the full workbench.
- Optional known in-game names from the archive's ItemInfo/localization tables. Exact localized names and related-name hints are shown separately so a guessed family match is never presented as exact evidence.
- Preview for text, metadata, binary hex, WIC-supported images (including supported DDS variants), and media formats supported by Windows Media Foundation.
- Read-only PAC, PAM, and PAMLOD geometry preparation through `cdmw-preview-core.exe`, displayed by the embedded production `d3d11_vortice_shader` .NET renderer as a texture-free neutral clay mesh. Directional studio lighting and subtle per-part tone variation keep contours and adjacent pieces legible without implying game textures or materials. The Lite surface has one mesh viewport and omits Original/Imported selectors, the edit gizmo, and the grid. Package preparation is cancellable, cached by immutable archive identity, and reported in the UI.
- Native raw, LZ4, ChaCha20, partial PAR, and PATHC-backed partial DDS extraction.
- Literal or regular-expression text search across archives or loose folders, with bounded parallelism, per-pattern timeouts, result caps, line/column/context, cancellation, and Enter-to-search from the query field.
- Selected-file, filtered-tree, and search-result export. Virtual folder structures are preserved, every file is written through a sibling staging file, collisions default to skip, and JSON manifests record archive provenance.
- Mesh-only PAC, PAM, and PAMLOD export to Blender-friendly GLB (the default), Wavefront OBJ, and binary FBX 7400. Geometry, normals, UVs, submesh boundaries, and material identities are retained; textures, rigs, and animations are intentionally omitted. Preparation and conversion run in the cancellable worker with determinate progress and atomic final-file publication.
- A versioned 1 MiB JSONL protocol over a private named pipe. Slow scan, query, preview, search, and export work runs in the owned worker process, never on the WPF dispatcher.
- Portable self-contained ZIP packaging with Python payload/import guards, x64 checks, application/worker/native self-tests, a synthetic native-package load, and a hidden Vortice GPU smoke.

Archive Lite has no archive-write, replacement, import-mesh, Modify Original, Build Mod, patch, backup, or restore authority. The native archive ABI intentionally exposes only scan and decode operations.

HKX selections still receive bounded metadata and binary inspection; Archive Lite does not claim an HKX visualizer. Unsupported specialized conversions (WAV, HKX JSON/XML, structured JSON, and dependency-set export) fail explicitly instead of silently exporting a different format. PAC/PAM/PAMLOD display and interchange export remain read-only: editing controls, source replacement, mesh import, and archive mutation are absent.

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

The package is written beneath `apps/Cdmw.ArchiveLite/artifacts/`. Packaging builds the native archive, preview, item-name-index, and mesh-interchange helpers; publishes the app, worker, and renderer self-contained for `win-x64`; scans every packaged PE for Python runtime references; verifies x64 architecture; smokes binary FBX output; loads a synthetic native preview package in the packaged renderer; proves the hidden production Vortice backend; constructs and lays out the real WPF window without showing it; exercises the packaged application-to-worker connection; and checks that no worker remains.

## Data isolation

Archive Lite writes only to its chosen export destination and to:

```text
%LocalAppData%\Ratrider\CDMWArchiveLite\
  settings.json
  cache\index\
  cache\index\roots\
  cache\names\
  cache\preview\models\
  cache\preview\native\
  cache\preview\runtime\
  logs\
  crash\
```

It does not read or write the full workbench's settings, caches, restore points, mod workspace, or Python environment. PAMT, PAZ, and PATHC sources are opened read-only. Before export, the worker recomputes the source fingerprint and refuses stale sessions.

Choosing **Load this time only** creates one uniquely named `cdmw-archive-lite-session-*.ali` file under the current user's system temporary directory. It remains available only while the worker owns that archive session and is deleted during normal worker shutdown. It is never used as a later cache hit. A process or operating-system crash can leave a temporary file for normal OS temporary-file cleanup, but cannot publish it as a persistent Archive Lite cache.

This choice controls the main archive-list index. Bounded known-name and preview caches keep their existing behavior so repeated names and previews do not needlessly decode the same immutable content again.

## Architecture

```text
CdmwArchiveLite.exe (WPF dispatcher)
          |
          | private named pipe, protocol v1, request IDs + generations
          v
CdmwArchiveLite.Worker.exe (.NET 10, cancellable operations)
          +-- text search / preview cache / atomic export
          +-- game-install discovery / cache-health inspection
          +-- categorized extension scan
          +-- cdmw-archive-accelerator.exe (C++17, item-name maps)
          +-- cdmw-preview-core.exe (C++20, PAC/PAM/PAMLOD package preparation)
          +-- cdmw-mesh-core.exe (C++17, production OBJ/FBX interchange writers)
          |
          +-- memory-mapped archive_index_v1
          v
cdmw-archive-core.dll (C++17, read-only PAMT/PAZ/PATHC decode ABI)

CdmwArchiveLite.exe
          +-- preview-only child HWND + process/job ownership
          v
cdmw-mesh-dotnet-editor.exe (.NET 8 + Vortice D3D11, read-only scene display)
```

The app owns presentation and latest-selection acceptance. The worker owns expensive I/O and CPU work. The native archive DLL owns archive parsing and codecs; the native preview executable prepares immutable renderer packages; the bundled production mesh core writes OBJ and FBX while the managed worker writes GLB 2.0. The app keeps the previous model visible until a replacement renderer is ready and rejects any renderer backend other than `d3d11_vortice_shader`. Closing the app requests cooperative shutdown and then closes Windows Job Objects so the owned worker, native-helper descendants, and renderer are terminated.

See [TESTING.md](TESTING.md) for the validation matrix and proof boundaries.
