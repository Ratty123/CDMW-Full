# CDMW Full Archive Core

`cdmw-full-archive-core.dll` is full CDMW's independently owned, read-only native
archive backend. It scans PAMT metadata into the versioned
`full_archive_index_v2` binary format and decodes selected PAZ entry bytes through
a narrow C ABI. It has no build-time or runtime dependency on Archive Lite.

The ABI has no archive mutation, replacement, patch, or restore functions. The
source archive tree is opened read-only. Index publication is staged beside the
cache destination and then replaced atomically.

Callers that need user-facing progress can use
`cdmw_full_archive_build_index_with_progress_utf8`. Its callback reports discovery,
PAMT parsing, entry sorting, index writing, and atomic publication. Phases with
known work expose exact completed/total counts; returning non-zero requests
cooperative cancellation and prevents publication of an incomplete index. The
non-progress `cdmw_full_archive_build_index_utf8` entry point remains available
for simple callers.

Build and test:

```powershell
cmake -S native/cdmw_full_archive_core -B native/cdmw_full_archive_core/build
cmake --build native/cdmw_full_archive_core/build --config Release
ctest --test-dir native/cdmw_full_archive_core/build -C Release --output-on-failure
```
