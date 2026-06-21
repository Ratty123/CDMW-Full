# Services

Owns business coordination boundaries shared by UI features. `ServiceContainer`
constructs archive, archive mutation, cache, diagnostics, filesystem, mesh,
package, settings, and texture workflow services.

Services may coordinate domain, core, modding, rendering, filesystem, and worker
code. They must not import PySide widgets or mutate UI state directly. Archive
mutation flows stay explicit, confirmable, backed up, and recoverable.

Related docs: `docs/architecture.md`, `docs/archive_safety_model.md`,
`docs/worker_lifecycle.md`.
Related tests: `tests/test_services.py`, `tests/test_diagnostics_service.py`,
and service entries in `docs/test-matrix.md`.
