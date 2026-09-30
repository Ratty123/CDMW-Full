# Full CDMW Standalone Archive Backend

This package is full CDMW's independently owned archive backend. It does not
reference Archive Lite projects, assemblies, settings, processes, or caches.

## Contents

- [Archive discovery exclusions](#archive-discovery-exclusions)
- [Worker protocol](#worker-protocol)
- [Persistent cache layout](#persistent-cache-layout)
- [Queries and exports](#queries-and-exports)
- [Build and focused checks](#build-and-focused-checks)
- [Application integration and release](#application-integration-and-release)
- [Prepared preview retention](#prepared-preview-retention)
- [Synthetic performance probes](#synthetic-performance-probes)

## Archive discovery exclusions

Directory scans skip the archive root's `backups/` and `Cdmods/` directories,
case-insensitively, before descending into them. Native discovery, source
fingerprints and the retained Python scanner use the same exclusions. Live
archive groups and overlays remain discoverable, including groups under
`game_files/`. A cached catalogue fingerprinted with backup sources becomes stale
and rebuilds automatically on the next archive open. An explicitly selected
`.pamt` file can still be inspected even when it is inside a backup directory.

## Worker protocol

The self-contained Windows x64 worker uses newline-delimited JSON on standard
input and output. Protocol v3 caps each message at one MiB and carries request,
UI-generation, session, operation, and status fields. The worker loads only
`cdmw-full-archive-core.dll` for PAMT scanning, `.ali` construction, and entry
decode.

## Persistent cache layout

Persistent data lives beneath the cache root passed with `--cache-root`:

### Hair registration probe

The read-only `probe_hair_registration.py` creates a cloned additional Damiane
barber-choice test package. `probe_hair_authoring.py` prepares the real Rust hair
handoff and reparses an authored package after the Rust production-render probe.
Both require explicit game/cache/output paths and never install their output.
See [the hair workflow and acceptance status](../../cdmw/ui/mesh_editor/README.md#hair-creation).

```text
index/
  c2/<root-id>/
    current.json
    g/<generation-id>/
      manifest.json
      archive.ali
      archive.adi
      lookups.bin
      names.bin
      p/<hash-prefix>/<full-hash>.<extension>
```

### Catalogue paths and upgrades

Fresh catalogue caches use `index/c2/`. Existing `index/catalogue_v2/` or top-level
`catalogue_v2/` families remain in place so live prepared paths stay valid; an existing
compact root takes precedence. Both `generations/` and `g/` are readable, while new
generations use `g/`. Existing `prepared/` payloads are reused and new payloads use
`p/`. Root IDs, generation IDs, full content hashes, checksums and leases are unchanged.
Directory labels save 27 characters for fresh prepared paths; temporary publications use
short unique sibling names.

Concurrent requests for a prepared artifact share bounded asynchronous gates through
decoding, metadata and optional content-analysis publication. Waiting requests reuse the
completed artifact instead of racing to replace its metadata; waiting remains
cancellable and each request still checks the source hash.

### Generation publication

The base generation is staged and validated before `current.json` is replaced. Mapped
generations remain protected while a session owns them. Corrupt base generations are
quarantined; corrupt secondary indexes are rebuilt. The cache family is capped at five
GiB without pruning current or active generations. `archive.adi` is the session-owned
compact dependency index: two sorted 16-byte hash/entry-id arrays provide basename and
same-stem lookup, while a small persisted facet table serves initial Archive Browser
filters. It is memory-mapped and collision-checked against `archive.ali`.

Preview association scans PAMI and supported XML/material companions, following newly
resolved material documents once so cross-package DDS references reach the prepared
snapshot. Cycles are deduplicated, texture payloads remain leaves, and the existing
candidate, scan-count, byte, and cancellation bounds remain enforced. Symbolic PBD
material names in model properties resolve through the exact
`character/descriptors/pbd/pbdconfig.xml` catalogue and its declared profile paths,
including profiles stored in other packages. Only referenced profiles are prepared;
unrelated catalogue entries and same-basename files are excluded. Malformed XML or a
reached traversal limit leaves the dependency set incomplete.

The Body/Face character catalogue separately recovers malformed hyphens in closed XML
comments in memory, including shipped wrinkle descriptors. It preserves CDATA and source
bytes, records the recovery, and still rejects malformed elements and unclosed comments.
Its cache revision forces existing incomplete catalogue results to rebuild after this
parser update. It resolves only requested names without reconstructing the general
`lookups.bin` dictionaries. `lookups.bin` remains a lazy compatibility index for
explicit general lookup operations.

## Queries and exports

An unfiltered, unsorted query pages `archive.ali` in native entry order without
rescanning every row or materializing a second ID array. The PySide shell keeps
only remote pages and bounded compatibility snapshots; its flat presentation
uses a virtual table so publishing a million-row result does not trigger
`QTreeView`'s all-row layout pass.

### Extension indexes

The first file-extension query builds compact in-memory entry-ID lists from
catalogue paths, once per mapped catalogue. Later searches and extension changes
reuse those lists and read/enrich only the selected file types. This preparation
runs in the query worker, is cancellable, and publishes only a complete index.
Explicit entry scopes retain their order; text/name matching, other filters,
sorting and paging keep their existing behavior. No cache-file format changes
or archive payload reads are required.

### Item Finder catalogue

Item Finder uses the fingerprint-owned native item catalogue on first open.
Search, category/material facets, paging, visible icon batches, and exact/related
scope resolution stay worker-side; bounded entry IDs are then applied through
the normal remote archive query. After catalogue publication, Full restores the
saved first page and then walks every catalogue page to warm durable icon PNGs
under `cache/preview/item-icons/` in small low-priority batches. Only a bounded
recent image window remains in memory. Failed catalogue loads remain retryable.

### Raw export and diagnostics

Raw export accepts bounded entry IDs, a server-side query token, a query-scoped
folder, or a worker-side family seed. The worker decodes into a sibling staging
directory before publication, can preserve the legacy PAMT-parent folder layout,
and supports skip, overwrite, rename, cancel, or confirmed whole-destination
replacement without writing to game archives. Item details stream in bounded
batches while the terminal result carries aggregate counts and manifest path.

## Build and focused checks

Build and test from the repository root:

```powershell
cmake -S native/cdmw_full_archive_core -B native/cdmw_full_archive_core/build
cmake --build native/cdmw_full_archive_core/build --config Release --parallel
ctest --test-dir native/cdmw_full_archive_core/build -C Release --output-on-failure
dotnet build tools/dotnet_archive_backend/Cdmw.FullArchive.slnx -c Release --nologo --verbosity:minimal
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build
.venv\Scripts\python.exe tools/dotnet_archive_backend/probe_full_archive_backend.py --worker tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/bin/Release/net10.0-windows/win-x64/cdmw-full-archive-worker.exe
```

### Discovery and extraction checks

For focused backup-discovery, folder-extraction and existing-cache upgrade checks:

```powershell
cmake --build native/cdmw_full_archive_core/build --config Release --target cdmw_full_archive_core
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests -c Release -- --archive-discovery
.\.venv\Scripts\python.exe -m pytest tests/test_archive_discovery.py -p no:cacheprovider --basetemp="$env:TEMP\cdmw-pytest-archive-discovery"
```

### Query regression checks

For focused query regression checks, including compilation:

```powershell
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests -c Release -- --archive-query
```

### Preview dependency checks

For focused preview dependency checks, including symbolic PBD profiles, prepared
source delivery, reference cycles, bounds and cancellation:

```powershell
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests -c Release -- --preview-dependencies
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

## Application integration and release

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

## Prepared preview retention

In displayed v2 mode, Archive Browser retains at most four recent prepared dependency
snapshots. Archive preview, mesh-import preflight/preview, mesh replacement builds, mesh
export, material/PAC-XML preview-export, structured binary sidecar decode, HKX
document/placement workflows, and Associated Assets enrichment reuse those bounded maps
and materialized files instead of the legacy process-wide catalogue indexes. Attachment
authoring also keeps donor search, item icons, socket/skeleton evidence, placement
comparison, and native placement-preview inputs inside the selected target's prepared
candidate set.

For model previews, the worker repairs only registered path extensions followed by one
printable prefab length byte, derives the base DDS beside explicit `_sp`/`_n`
references, resolves selected-mesh `CD_*` material names as DDS basename hints,
including player-family tokens embedded in NPC equipment names, and includes the shared
identity skeleton. The Python mesh loader verifies the candidate PAB against the PAC
palette before attaching it. Archive existence still validates every derived candidate,
so an unmatched binary fragment cannot enter the snapshot.

A complete snapshot is the native preview core's in-memory archive index; it does not
trigger a second full-PAMT parse. The two-entry in-game mesh-swap flow merges the
already prepared target and source snapshots into one immutable request context capped
at 8,192 entries; both cancellable preflight phases consume that context instead of
reading the global catalogue or its path/basename maps. Legacy mode keeps passing its
existing catalogue references without copying the full list on the UI thread.

A standalone-v2 Research tab likewise consumes a bounded, paged prefix of the current
query, a query-wide bounded image/reference lookup, and a session-wide
sidecar/reference-source lookup. It materializes only text sources admitted by explicit
count and byte budgets and prepares other entries on demand for preview, so Research
never reconstructs the full Python catalogue. The three bounded sets retain fewer than
10,000 compatibility entries. Truncation and preparation limits are shown in Research
status text.

A workflow fails closed until its selected entry has a complete prepared snapshot;
legacy mode keeps the existing catalogue behavior. Prepared files are content-addressed
with the current raw PAZ entry hash, so same-size, same-timestamp source changes cannot
reuse stale decoded bytes. Native model preview keys also include the complete prepared
dependency snapshot.

## Synthetic performance probes

Regenerate a three-cycle synthetic timing report outside the repository with:

```powershell
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build -- --baseline-report "$env:TEMP/cdmw-full-archive-synthetic-v2.json"
```

For cache-performance work, run the three-cycle 200,000-entry synthetic scale
probe with the same Release binaries:

```powershell
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build -- --cache-scale-report "$env:TEMP/cdmw-full-archive-cache-scale.json"
```

### Native cache build order

Native cache builds preserve sorted PAMT merge order while parsing through a
bounded four-task window. Entries share immutable per-PAMT source metadata,
source paths are encoded once, and the stable path sort avoids redundant case
folding. Repeated builds must remain byte-identical for both `archive.ali` and
the derived `archive.adi`.

### Evidence boundary

The committed baseline and packaged probe are synthetic regression evidence
only. The scale probe measures cold build, warm open, forced refresh, and cache
bytes plus time to the first usable 64-row page without licensed files.
Real-game corpus and visible UI gates require separate explicit authorization.
