# Archive Domain

Owns archive safety, role, selection, filter, attachment, prefab, relationship,
weapon-swap, extension, and text-payload rules used by UI, services, and workers.

`mutation.py` owns shared patch request/result contracts. Core patching and
the archive mutation service re-export those exact classes, so importing the
service container does not load the archive writer.
`mesh_contracts.py` similarly owns archive/mesh preview, supplemental-file,
loose-export, and authority-audit result shapes without importing mesh parsers.
`constants.py` owns archive media/mesh extension and companion-file policy.
`format.py` owns extension normalization, sidecar classification, and bounded
text-payload detection. `attachments.py`, `prefab.py`, `relationships.py`, and
`weapon_swap.py` own immutable contracts re-exported by legacy core owners.

Keep binary parsing, archive IO, extraction, patching, and preview construction
outside this package. Those belong in `cdmw/core/`, `cdmw/services/`, and
`cdmw/workers/`.

Related docs: `docs/features/archive-safety-model.md`.
Related tests: archive and architecture entries in `docs/test-matrix.md`.
