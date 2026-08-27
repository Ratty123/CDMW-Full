# Rendering

Owns native preview packaging, D3D11 host integration, material combiner rules,
preview payloads, texture source resolution, capture helpers, and rendering
fidelity checks.

Keep feature UI controls outside this package. UI packages host previews and
display state; rendering code owns resource contracts, material synthesis, and
native preview preparation.

Archive Browser, Model Library, Mesh Editor and New Item Studio converge on the
same schema-v8 package and material contracts. A caller may publish bare
geometry while Preview Core prepares canonical textures, but the later package
promotion must keep the resident process and camera. The .NET/Vortice host owns
HDR studio lighting and effect-particle drawing; this package owns the
Python-side package, cache, material, and texture inputs rather than a second
renderer.

Related tests: native preview, model preview, and static replacement entries under `tests/`.
