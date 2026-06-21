# Archive Accelerator

Owns the native archive acceleration helper built from `CMakeLists.txt` and
`src/main.cpp`.

Keep this helper focused on archive acceleration primitives called from Python
archive code. Shared native diagnostics belong in `native/common/`; Python
fallbacks and feature policy stay in `cdmw/core/` and `cdmw/domain/`.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: runtime smoke and archive entries in `docs/test-matrix.md`.
