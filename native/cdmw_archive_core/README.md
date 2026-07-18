# CDMW Archive Core

`cdmw-archive-core.dll` is the read-only native archive backend for CDMW Archive
Lite. It scans PAMT metadata into the versioned `archive_index_v1` binary format
and decodes selected PAZ entry bytes through a narrow C ABI.

The ABI has no archive mutation, replacement, patch, or restore functions. The
source archive tree is opened read-only. Index publication is staged beside the
cache destination and then replaced atomically.

Build and test:

```powershell
cmake -S native/cdmw_archive_core -B native/cdmw_archive_core/build
cmake --build native/cdmw_archive_core/build --config Release
ctest --test-dir native/cdmw_archive_core/build -C Release --output-on-failure
```
