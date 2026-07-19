# Full CDMW Standalone Archive Backend

This package is full CDMW's independently owned archive backend. It does not
reference Archive Lite projects, assemblies, settings, processes, or caches.

The self-contained Windows x64 worker uses newline-delimited JSON on standard
input and output. Protocol v2 caps each message at one MiB and carries request,
UI-generation, session, operation, and status fields. The worker loads only
`cdmw-full-archive-core.dll` for PAMT scanning, `.ali` construction, and entry
decode.

Persistent data lives beneath the cache root passed with `--cache-root`:

```text
catalogue_v2/<root-id>/
  current.json
  generations/<generation-id>/
    manifest.json
    archive.ali
    lookups.bin
    names.bin
```

The base generation is staged and validated before `current.json` is replaced.
Mapped generations remain protected while a session owns them. Corrupt base
generations are quarantined; corrupt secondary indexes are rebuilt. The cache
family is capped at five GiB without pruning current or active generations.

Build and test from the repository root:

```powershell
cmake -S native/cdmw_full_archive_core -B native/cdmw_full_archive_core/build
cmake --build native/cdmw_full_archive_core/build --config Release --parallel
ctest --test-dir native/cdmw_full_archive_core/build -C Release --output-on-failure
dotnet build tools/dotnet_archive_backend/Cdmw.FullArchive.slnx -c Release --nologo --verbosity:minimal
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build
```

Regenerate a three-cycle synthetic timing report outside the repository with:

```powershell
dotnet run --project tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/Cdmw.FullArchive.Tests.csproj -c Release --no-build -- --baseline-report "$env:TEMP/cdmw-full-archive-synthetic-v2.json"
```

The committed baseline is synthetic regression evidence only. Real-game corpus,
visible UI, packaging, and release gates require their separately authorized
workflows.
