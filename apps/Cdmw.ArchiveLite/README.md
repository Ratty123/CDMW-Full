# CDMW Archive Lite

CDMW Archive Lite is a separate, read-only Windows desktop application for browsing Crimson Desert PAMT/PAZ archives and searching text. Its application, worker, native archive and model-preview services, .NET/Vortice renderer, build, tests, and portable package do not embed or invoke Python.

## Included

- Modern resizable Windows 11 x64 WPF shell on .NET 10, localized in English, German, and Spanish, with immediate in-place language switching; six persistent Graphite, Midnight, Nord, Ember, Light, and Frost themes; four global font sizes; and compact, comfortable, or spacious layout density. The compact title row contains only the product name, Archive Browser/Text Search navigation, appearance controls, and window controls. Every launch starts in Archive Browser, regardless of which workspace was last used.
- Automatic Crimson Desert folder discovery from environment overrides, Steam libraries/registry data, and common Steam, Epic, Xbox, and standalone install locations. A manual Detect game action and folder picker remain available.
- Stable memory-mapped archive index with archive fingerprints and isolated caches. At startup, the selected or detected game root is checked and a current persistent cache is opened automatically without a prompt or rebuild. If no cache exists, the normal archive-loading choice opens so the user can build a persistent cache or load only for that session. A stale cache stays closed, clearly recommends **Refresh**, and cannot be opened until the user manually refreshes it. Persistent indexes are reused only for the same verified source fingerprint and manual rebuilds use atomic replacement; one-time indexes always rescan, never publish persistent freshness metadata, and are removed when the worker session closes. Builds and refreshes report native discovery plus real PAMT parse, entry-sort, index-write, and atomic-publication progress; cancellation is cooperatively forwarded into the native build.
- Flat, folder, category, and category-plus-folder navigation with focused path/extension/view/folder/sort filters and 256-row paging. Visible Archive and text-search filters, export options, font size, layout density, window placement/maximized state, workspace splitter widths, and result-column widths/order are restored from the portable settings file. The file grid supports click-to-sort on every column, freely resizing/reordering columns, and a persistent visible-column chooser.
- A categorized extension picker that expands every group into its individual extensions and per-extension counts, uses smooth pixel scrolling, and shares the full workbench's model/mesh/physics, texture/image, material/metadata, animation/scene, audio/video, UI/text, and other groups.
- Optional known in-game names from the archive's ItemInfo/localization tables. Exact localized names and related-name hints are shown separately so a guessed family match is never presented as exact evidence.
- An on-demand **Associated assets** drawer that opens as a compact docked column beside the preview instead of overlapping the native mesh viewport or consuming permanent vertical space. Its color-coded sections resolve explicit paths embedded in PAC/material/XML metadata, expected model/material companions, and same-family names; show only each file name in the list; group results as models, material sidecars, textures, physics, mesh metadata, prefabs, skeletons, animation, media, UI, or other; and keep the full path/evidence available on hover. Resolved families are remembered for the current worker session, so a discovered DDS can lead back to its PAC, sidecar, and sibling files. Selected associated rows can be exported together, **Export family** writes the source plus every resolved family member, and **Show in browser** opens a chosen result in the normal sortable file view.
- Full-file text and XML previews in a read-only AvalonEdit surface with theme-aware VS Code-style Dark+/Light+ syntax colors, muted line numbers, horizontal/vertical scrolling, selected search-result positioning, and in-file next/previous search. Switching any theme recolors both editors immediately. Text content is published through a bounded cache artifact rather than truncated to fit the named-pipe response.
- Image preview through Windows codecs plus the bundled native DirectXTex decoder for DDS. Metadata identifies DDS dimensions, texture/array kind, pixel format and compression, mip levels, color space, alpha mode, payload layout, and relevant DX10 or RGB-mask details. Common Windows Media Foundation audio/video formats play directly; Wwise `.wem` files are decoded to cached WAV with the pinned bundled vgmstream runtime. Proprietary media such as BK2 still requires a compatible Windows codec.
- Read-only PAC, PAM, and PAMLOD geometry preparation through `cdmw-preview-core.exe`, displayed by the embedded production `d3d11_vortice_shader` .NET renderer as a texture-free neutral clay mesh. Directional studio lighting and subtle per-part tone variation keep contours and adjacent pieces legible without implying game textures or materials. The Lite surface has one mesh viewport and omits Original/Imported selectors, the edit gizmo, and the grid. Package preparation is cancellable, cached by immutable archive identity, and reported in the UI.
- Read-only HKX/HKT visual preparation through the native Rust `cd-hkx.exe` parser. Recognized skeleton-bearing tagfiles are displayed as a texture-free joint-and-bone preview; supported box, sphere, capsule, and convex-hull physics records are rendered as solid collision geometry. Arbitrary object records are never presented as proxy bones or dots: an unsupported packed/unknown shape receives an honest no-preview explanation. The parser is isolated, cancellable, output-bounded, and never mutates the archive source.
- Native raw, LZ4, ChaCha20, partial PAR, and PATHC-backed partial DDS extraction.
- Literal or regular-expression text search across archives or loose folders, with bounded parallelism, per-pattern timeouts, result caps, line/column/context, cancellation, and Enter-to-search from the query field. Selecting a result asynchronously opens and highlights the complete source file in the same editor used by Archive Browser.
- Multi-selected file, selected-folder, filtered-set, associated-family, and search-result export. Raw archive output can either match the full CDMW extractor layout as `<PAMT parent folder>/<archive virtual path>` or place selected files directly in the chosen folder; every file is written through a sibling staging file, collisions default to skip, and JSON manifests record archive provenance.
- **Export selected** opens one choice dialog for the original file(s), the complete archive folder structure, or the selected file's resolved associated-asset family. A single PAC, PAM, or PAMLOD also offers Blender-friendly GLB, Wavefront OBJ, or binary FBX 7400. Geometry, normals, UVs, submesh boundaries, and material identities are retained for interchange output; textures, rigs, and animations are intentionally omitted. **Export family** is also available directly under **Export Options** and performs family discovery first when needed. Preparation and conversion run in the cancellable worker with determinate progress and atomic final-file publication.
- A versioned 1 MiB JSONL protocol over a private named pipe. Slow scan, query, preview, search, and export work runs in the owned worker process, never on the WPF dispatcher.
- Portable self-contained ZIP packaging with Python payload/import guards, x64 checks, application/worker/native self-tests, a synthetic native-package load, and a hidden Vortice GPU smoke.

Archive Lite has no archive-write, replacement, import-mesh, Modify Original, Build Mod, patch, backup, or restore authority. The native archive ABI intentionally exposes only scan and decode operations.

Unsupported specialized conversions (WAV, HKX JSON/XML, structured JSON, and dependency-set export) fail explicitly instead of silently exporting a different format. PAC/PAM/PAMLOD/HKX display and interchange export remain read-only: editing controls, source replacement, mesh import, and archive mutation are absent.

## Run from source

Requirements are Windows 11 x64, the .NET 10 SDK, a stable Rust toolchain, CMake 3.24 or newer, Visual Studio 2022 Build Tools with the Desktop C++ workload, and PowerShell.

```powershell
.\apps\Cdmw.ArchiveLite\scripts\test_archive_lite.ps1
dotnet run --project .\apps\Cdmw.ArchiveLite\src\Cdmw.ArchiveLite.App\Cdmw.ArchiveLite.App.csproj -c Debug
```

The second command launches a visible desktop window and is intentionally not part of automated validation.

## Build the standalone EXE and portable ZIP

```powershell
.\apps\Cdmw.ArchiveLite\scripts\build_archive_lite.ps1
```

The build writes both `CDMW-Archive-Lite-0.6.1-Standalone-win-x64.exe` and the conventional portable ZIP beneath `apps/Cdmw.ArchiveLite/artifacts/`. The standalone file is the simplest distribution: copy that one EXE and run it. On first launch it verifies and atomically extracts its worker, native codecs, exporters, and renderer into a content-addressed local runtime; later launches reuse that verified runtime. Separate worker and renderer processes remain intact after extraction because they provide crash isolation and responsive archive/preview work.

Packaging builds the native archive, preview, item-name-index, DDS, HKX, and mesh-interchange helpers; publishes the app, worker, and renderer self-contained for `win-x64`; scans every packaged PE for Python runtime references; verifies the x64 application/native entry points and the separately hosted pinned x86 vgmstream runtime; smokes binary FBX output; decodes a synthetic HKX skeleton; loads a synthetic native preview package in the packaged renderer; proves the hidden production Vortice backend; constructs and lays out the real WPF window without showing it; exercises the packaged application-to-worker connection; and checks that no worker remains. It then publishes the single-file Native AOT launcher, runs it once through first-run extraction and again through cached reuse, and requires both hidden application/worker self-tests to exit cleanly.

## Data isolation

Archive Lite stores its reusable archive, name, and preview caches beside the distributed executable:

```text
<folder containing the standalone EXE or portable CdmwArchiveLite.exe>\
  settings.json
  cache\index\
  cache\index\roots\
  cache\names\
  cache\preview\models\
  cache\preview\native\
  cache\preview\textures\
  cache\preview\hkx\
  cache\preview\media\
  cache\preview\text\
  cache\preview\runtime\
  logs\
  crash\
```

Only the standalone launcher's internally extracted worker/renderer runtime remains under:

```text
%LocalAppData%\Ratrider\CDMWArchiveLite\
  standalone\payloads\<payload-sha256>\
```

The executable's folder therefore needs to be writable for settings, logs, crash diagnostics, and persistent caches. `settings.json` retains the selected game root, filters, search inputs, export options, theme/language, font size, layout density, window placement, splitter widths, and result-grid layout; it intentionally does not retain the active workspace, so Archive Browser remains the startup view. The `standalone` Local AppData folder contains only the extracted runtime bundled inside the EXE; it does not contain settings, cache data, logs, game data, or exported assets. A damaged or incomplete runtime is never reused: it is quarantined under the same app-owned folder and replaced from the embedded, manifest-verified payload. Different standalone versions use different content hashes, so an application that is already running is not disrupted by launching a newer build.

It does not read or write the full workbench's settings, caches, restore points, mod workspace, or Python environment. PAMT, PAZ, and PATHC sources are opened read-only. Before export, the worker recomputes the source fingerprint and refuses stale sessions.

Choosing **Load this time only** creates one uniquely named `cdmw-archive-lite-session-*.ali` file under the current user's system temporary directory. It remains available only while the worker owns that archive session and is deleted during normal worker shutdown. It is never used as a later cache hit. A process or operating-system crash can leave a temporary file for normal OS temporary-file cleanup, but cannot publish it as a persistent Archive Lite cache.

The cache choice is shown for manual Open/Refresh and automatically at startup when a game root is available but no persistent index exists. Startup reuses a current persistent index silently and never rebuilds a stale one; stale sources require a manual Refresh. Bounded known-name and preview caches keep their existing behavior so repeated names and previews do not needlessly decode the same immutable content again. Associated-asset families are retained only in worker memory for the open session and do not create another persistent cache.

## Architecture

```text
CDMW-Archive-Lite-0.6.1-Standalone-win-x64.exe (single-file Native AOT launcher)
          |
          | verified, atomic first-run extraction; content-addressed reuse
          v
CdmwArchiveLite.exe (WPF dispatcher)
          |
          | private named pipe, protocol v1, request IDs + generations
          v
CdmwArchiveLite.Worker.exe (.NET 10, cancellable operations)
          +-- text search / preview cache / atomic export
          +-- game-install discovery / cache-health inspection
          +-- categorized extension scan
          +-- cancellable associated-asset reference/family discovery
          +-- cdmw-archive-accelerator.exe (C++17, item-name maps)
          +-- cdmw-preview-core.exe (C++20, PAC/PAM/PAMLOD package preparation)
          +-- cdmw-mesh-core.exe (C++17, production OBJ/FBX interchange writers)
          +-- cd-texture-dx.exe (C++20 + DirectXTex, DDS to PNG preview)
          +-- cd-hkx.exe (Rust, bounded HKX skeleton/collision-shape parser)
          +-- vgmstream-cli.exe (pinned Wwise audio to WAV preview runtime)
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
