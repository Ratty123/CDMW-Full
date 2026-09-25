# CDMW Full Archive Core

`cdmw-full-archive-core.dll` is full CDMW's independently owned, read-only native
archive backend. It scans PAMT metadata into the versioned
`full_archive_index_v3` binary format and decodes selected PAZ entry bytes through
a narrow C ABI. It has no build-time or runtime dependency on Archive Lite.

The ABI has no archive mutation, replacement, patch, or restore functions. The
source archive tree is opened read-only. Index publication is staged beside the
cache destination and then replaced atomically.

Partial PAM geometry (versions `0x1802` and `0x01001806`) and aligned PAMLOD LOD
blocks are decoded by `native/common/partial_static_mesh.hpp`, shared with Preview
Core. Mixed compressed/plain LODs retain their metadata and material descriptors;
offset, block-size and total decoded-size inconsistencies are rejected.

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

For an explicitly authorized installed-archive audit, use the existing v3 index
with `tools/scan_archive_format_corpus.py`. It inventories every extension,
samples each extension/compression-flag combination, checks every material
sidecar and partially compressed static mesh, and audits sampled geometry:

```powershell
.\.venv\Scripts\python.exe tools/scan_archive_format_corpus.py --index <archive.ali> --decoder native/cdmw_full_archive_core/build/Release/cdmw-full-archive-core.dll --preview-core native/cdmw_preview_core/build/Release/cdmw-preview-core.exe --output "$env:TEMP\cdmw-format-audit"
```

Keep reports outside the game directory. Reports distinguish decode failures,
geometry rejections and DDS references absent at their exact declared path;
the last category can include optional or stale game references. This is a
read-only structural scan, not a rendering or gameplay test. It compares PAMT
SHA-256 hashes and PAZ sizes/modification times before and after the scan.
