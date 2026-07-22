# Full CDMW Standalone Archive Backend

This package is full CDMW's independently owned archive backend. It does not
reference Archive Lite projects, assemblies, settings, processes, or caches.

The self-contained Windows x64 worker uses newline-delimited JSON on standard
input and output. Protocol v3 caps each message at one MiB and carries request,
UI-generation, session, operation, and status fields. The worker loads only
`cdmw-full-archive-core.dll` for PAMT scanning, `.ali` construction, and entry
decode.

Persistent data lives beneath the cache root passed with `--cache-root`:

```text
index/
  catalogue_v2/<root-id>/
    current.json
    generations/<generation-id>/
      manifest.json
      archive.ali
      archive.adi
      lookups.bin
      names.bin
```

An existing top-level `catalogue_v2/` family is moved into `index/` on first
use when the destination is free. If migration cannot complete, the worker
continues from the legacy location instead of discarding or replacing it.

The base generation is staged and validated before `current.json` is replaced.
Mapped generations remain protected while a session owns them. Corrupt base
generations are quarantined; corrupt secondary indexes are rebuilt. The cache
family is capped at five GiB without pruning current or active generations.
`archive.adi` is the session-owned compact dependency index: two sorted
16-byte hash/entry-id arrays provide basename and same-stem lookup, while a
small persisted facet table serves initial Archive Browser filters. It is
memory-mapped and collision-checked against `archive.ali`; PAC preview
association therefore resolves only requested names without reconstructing the
general `lookups.bin` dictionaries. `lookups.bin` remains a lazy compatibility
index for explicit general lookup operations.

An unfiltered, unsorted query pages `archive.ali` in native entry order without
rescanning every row or materializing a second ID array. The PySide shell keeps
only remote pages and bounded compatibility snapshots; its flat presentation
uses a virtual table so publishing a million-row result does not trigger
`QTreeView`'s all-row layout pass.

Item Finder uses the fingerprint-owned native item catalogue on first open.
Search, category/material facets, paging, visible icon batches, and exact/related
scope resolution stay worker-side; bounded entry IDs are then applied through
the normal remote archive query. After catalogue publication, Full restores the
saved first page and then walks every catalogue page to warm durable icon PNGs
under `cache/preview/item-icons/` in small low-priority batches. Only a bounded
recent image window remains in memory. Failed catalogue loads remain retryable.

Raw export accepts bounded entry IDs, a server-side query token, a query-scoped
folder, or a worker-side family seed. The worker decodes into a sibling staging
directory before publication, can preserve the legacy PAMT-parent folder layout,
and supports skip, overwrite, rename, cancel, or confirmed whole-destination
replacement without writing to game archives. Item details stream in bounded
batches while the terminal result carries aggregate counts and manifest path.

Build and test from the repository root:

```powershell
cmake -S native/cdmw_full_archive_core -B native/cdmw_full_archive_core/build
cmake --build native/cdmw_full_archive_core/build --config Release --parallel
ctest --test-dir native/cdmw_full_archive_core/build -C Release --output-on-failure
dotnet build tools/dotnet_archive_backend/Cdmw.FullArchive.slnx -c Release --nologo --verbosity:minimal
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build
.venv\Scripts\python.exe tools/dotnet_archive_backend/probe_full_archive_backend.py --worker tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/bin/Release/net10.0-windows/win-x64/cdmw-full-archive-worker.exe
```

The Python probe is synthetic and headless. It exercises the frozen catalogue
contracts and resident `QProcess` client through cold/warm open, worker paging,
the latest-wins semantic preview-candidate provider with one bounded streamed
preparation batch for the selected input and its dependencies, text search,
streamed query-token export, package-root layout, rename collision handling,
.NET, an acknowledged refresh cancellation, clean worker shutdown, and the
renamed native DLL without opening the application or reading licensed game
data. The initial ping fails closed unless protocol v3, native ABI 1, and the
current index version all match.

`v2` is the application default for the stable transition release.
`CDMW_ARCHIVE_BACKEND=legacy|v2|shadow` remains a developer override, not a
saved setting. A startup or catalogue-publication failure is shown explicitly.
The dialog can retry v2, cancel, or switch to the retained legacy scanner for
the current process only; CDMW never changes the environment or silently
reconstructs the legacy catalogue. Legacy code and caches remain intact for
this release and are scheduled for removal in the following release.

Release builds publish the self-contained worker and
`cdmw-full-archive-core.dll` to
`native/cdmw_full_archive_backend/build/<Configuration>/`. PyInstaller places
the complete runtime under `archive_backend/` in onedir and onefile artifacts.
The release builder probes the published bundle and then the exact packaged
bundle. Both probes must handshake, cold/warm open a synthetic PAMT/PAZ,
create and page a query, acknowledge cancellation, shut down cleanly, and
leave no resident worker process.

In displayed v2 mode, Archive Browser retains at most four recent prepared
dependency snapshots. Archive preview, mesh-import preflight/preview, mesh
replacement builds, mesh export, material/PAC-XML preview-export, structured
binary sidecar decode, HKX document/placement workflows, and Associated Assets
enrichment reuse those bounded maps and materialized files instead of the
legacy process-wide catalogue indexes. Attachment authoring also keeps donor
search, item icons, socket/skeleton evidence, placement comparison, and native
placement-preview inputs inside the selected target's prepared candidate set.
The two-entry in-game mesh-swap flow merges the already prepared target and
source snapshots into one immutable request context capped at 8,192 entries;
both cancellable preflight phases consume that context instead of reading the
global catalogue or its path/basename maps. Legacy mode keeps passing its
existing catalogue references without copying the full list on the UI thread.
A standalone-v2 Research tab likewise consumes a bounded, paged prefix of the
current query, a query-wide bounded image/reference lookup, and a session-wide
sidecar/reference-source lookup. It materializes only text sources admitted by
explicit count and byte budgets and prepares other entries on demand for
preview, so Research never reconstructs the full Python catalogue. The three
bounded sets retain fewer than 10,000 compatibility entries. Truncation and
preparation limits are shown in Research status text.
A workflow fails closed until its selected entry has a complete prepared
snapshot; legacy mode keeps the existing catalogue behavior. Prepared files
are content-addressed with the current raw PAZ entry hash, so same-size,
same-timestamp source changes cannot reuse stale decoded bytes. Native model
preview keys also include the complete prepared dependency snapshot.

Regenerate a three-cycle synthetic timing report outside the repository with:

```powershell
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build -- --baseline-report "$env:TEMP/cdmw-full-archive-synthetic-v2.json"
```

For cache-performance work, run the three-cycle 200,000-entry synthetic scale
probe with the same Release binaries:

```powershell
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build -- --cache-scale-report "$env:TEMP/cdmw-full-archive-cache-scale.json"
```

The committed baseline and packaged probe are synthetic regression evidence
only. The scale probe measures cold build, warm open, forced refresh, and cache
bytes plus time to the first usable 64-row page without licensed files.
Real-game corpus and visible UI gates require separate explicit authorization.
