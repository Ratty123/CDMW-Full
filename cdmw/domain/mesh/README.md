# Mesh Domain

Owns pure mesh session and validation rules.

Keep mesh parsing, replacement building, native preview packaging, and PySide
controls outside this package. Use `cdmw/modding/` for mesh/material operations,
`cdmw/rendering/` for preview packaging, and `cdmw/ui/mesh_editor/` for UI.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: mesh and static replacement entries in `docs/test-matrix.md`.
