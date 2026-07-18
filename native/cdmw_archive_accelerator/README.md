# Archive Accelerator

Owns the native archive acceleration helper built from `CMakeLists.txt` and
`src/main.cpp`.

Keep this helper focused on archive acceleration primitives called from the
full application and the Python-free Archive Lite worker. Shared native
diagnostics belong in `native/common/`; feature policy stays with the calling
application.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: runtime smoke and archive entries in `docs/test-matrix.md`.
