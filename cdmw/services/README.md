# Services

Owns business coordination boundaries shared by UI features. `ServiceContainer`
constructs archive, archive mutation, asset authoring, cache, diagnostics,
filesystem, mesh, package, settings, and texture workflow services.

Services may coordinate domain, core, modding, rendering, filesystem, and worker
code. They must not import PySide widgets or mutate UI state directly. Archive
mutation flows stay explicit, confirmable, backed up, and recoverable.

`asset_authoring_service.py` owns optional helper discovery, Material Maker
command handoff, review-only texture-set ingest, source scene import reports,
UV/tangent authoring reports, pre-mutation mesh health reports, and OpenImageIO
source image handoff commands for asset-authoring tools. Missing helpers are
reported as unavailable/configured-missing and must not break startup.
Generated/source maps stay intermediates; DDS output remains on the existing
CDMW/DirectXTex paths. Exact helper versions are opt-in discovery probes so
normal startup does not run external tools.

Related docs: `docs/architecture.md`, `docs/archive_safety_model.md`,
`docs/worker_lifecycle.md`, `docs/asset-authoring-integrations.md`.
Related tests: `tests/test_services.py`, `tests/test_diagnostics_service.py`,
and service entries in `docs/test-matrix.md`.
