# Rendering

Owns native preview packaging, D3D11 host integration, material combiner rules,
preview payloads, texture source resolution, capture helpers, and rendering
fidelity checks.

Keep feature UI controls outside this package. UI packages host previews and
display state; rendering code owns resource contracts, material synthesis, and
native preview preparation.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: native preview, model preview, and static replacement entries in
`docs/test-matrix.md`.
