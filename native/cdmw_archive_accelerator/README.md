# Archive Accelerator

Owns the native archive acceleration helper built from `CMakeLists.txt` and
`src/main.cpp`.

Keep this helper focused on archive acceleration primitives called from the
full application and the Python-free Archive Lite worker. Shared native
diagnostics belong in `native/common/`; feature policy stays with the calling
application.

Item indexing unwraps version-0 `paloc` containers and bounds their LZ4 expansion
to 256 MiB before scanning the localization records. Container errors name the
language payload. JSON output preserves valid UTF-8 and escapes each invalid byte
as a Unicode replacement character, so recovered text cannot invalidate a report.

The synthetic `--item-catalogue` check in `tools/dotnet_archive_backend/tests/`
exercises the rebuilt helper through the real catalogue builder and JSON reader;
see `docs/test-matrix.md`. Other archive tests live under `tests/`.
