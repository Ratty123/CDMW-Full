# Archive Accelerator

Owns the native archive acceleration helper built from `CMakeLists.txt` and
`src/main.cpp`.

Keep this helper focused on archive acceleration primitives called from the
full application and the Python-free Archive Lite worker. Shared native
diagnostics belong in `native/common/`; feature policy stays with the calling
application.

`path-checksum-job <paths.bin> <checksums.bin>` batches PATHC identity hashes using
the existing lookup3 implementation with the PA seed. Its data-only binary protocol
has the eight-byte `CDPH\x01\0\0\0` header, a little-endian uint32 count, then
length-prefixed UTF-8 strings; the result repeats the header/count followed by uint32
hashes in input order. Inputs are bounded to 4,194,304 strings, 32 KiB per string and
512 MiB total text. These strings are never opened as filesystem paths. The Python
caller owns normalization, cancellation and complete-result validation; independent
item services continue to own collision policy.

Item indexing unwraps version-0 `paloc` containers and bounds their LZ4 expansion
to 256 MiB before scanning the localization records. Container errors name the
language payload. JSON output preserves valid UTF-8 and escapes each invalid byte
as a Unicode replacement character, so recovered text cannot invalidate a report.

The synthetic `--item-catalogue` check in `tools/dotnet_archive_backend/tests/`
exercises the rebuilt helper through the real catalogue builder and JSON reader;
see `docs/test-matrix.md`. Other archive tests live under `tests/`.
