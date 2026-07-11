# Services

Owns business coordination boundaries shared by UI features. `ServiceContainer`
constructs archive, archive mutation, asset authoring, cache, diagnostics,
filesystem, Item Icon, mesh, Model Library, package, research, settings, and
texture workflow services.

Services may coordinate domain, core, modding, rendering, filesystem, and worker
code. They must not import PySide widgets or mutate UI state directly. Archive
mutation flows stay explicit, confirmable, backed up, and recoverable.

Archive UI coordination uses focused read, query, preview, extraction,
environment, and cached lazy workflow surfaces composed by `ArchiveService`.
UI modules never import archive implementation modules or the
`cdmw.core.archive` / `cdmw.core.archive_modding` compatibility facades.
Mutation commands and backup locations remain owned by
`ArchiveMutationService`; long-running calls are dispatched through workers.

`preview_workflow_service.py` and `preview_rendering_service.py` are cached,
lazy UI surfaces for preview preparation and low-level renderer/native host
operations. They preserve owner object identity without loading optional
preview stacks merely from importing the service modules.
`archive_workflow_service.py` applies the same identity-preserving lazy boundary
to archive export, attachment, model relationship, sidecar, audio, prefab,
weapon-swap, and index operations.

`mesh_workflow_service.py` and `texture_workflow_service.py` expose the UI's
mesh/native and texture/recolor coordination surfaces without eager imports.
Focused material-sidecar, text-search, Replace Assistant, HKX-edit, and startup
splash services provide the same boundary for their owning features. UI code
does not import `cdmw.core`, `cdmw.modding`, or `cdmw.rendering` directly.

`ResearchService` composes archive analysis, reference queries, texture
analysis/report export, preview preparation, and transactional note persistence.
Research UI code imports domain contracts and this service boundary; the
`cdmw.core.research` module is compatibility-only.

`ItemIconService` coordinates library indexes, preview/payload generation, and
loose-package patching. `ModelLibraryService` coordinates local scans, SQLite
catalogues, downloads, and ZIP/import-path resolution. Their UI callers keep
slow requests in existing cancellable workers.

`asset_authoring_service.py` owns optional helper discovery, Material Maker
command handoff, review-only texture-set ingest, source scene import reports,
UV/tangent authoring reports, pre-mutation mesh health reports, and OpenImageIO
source image handoff commands for asset-authoring tools. Missing helpers are
reported as unavailable/configured-missing and must not break startup.
Generated/source maps stay intermediates; DDS output remains on the existing
CDMW/DirectXTex paths. Exact helper versions are opt-in discovery probes so
normal startup does not run external tools.

Related docs: `docs/architecture.md`, `docs/features/archive-safety-model.md`,
`docs/runbooks/worker-lifecycle.md`,
`docs/features/asset-authoring-integrations.md`.
Related tests: `tests/test_services.py`, `tests/test_archive_service_boundaries.py`,
`tests/test_research_service_boundary.py`, `tests/test_diagnostics_service.py`,
and service entries in `docs/test-matrix.md`.
