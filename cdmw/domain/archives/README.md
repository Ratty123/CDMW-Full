# Archive Domain

Owns archive safety, role, selection, and filter rules used by UI, services, and
workers.

Keep binary parsing, archive IO, extraction, patching, and preview construction
outside this package. Those belong in `cdmw/core/`, `cdmw/services/`, and
`cdmw/workers/`.

Related docs: `docs/archive_safety_model.md`.
Related tests: archive and architecture entries in `docs/test-matrix.md`.
