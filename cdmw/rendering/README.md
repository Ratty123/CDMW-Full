# Rendering

Owns native preview packaging, Rust host integration, material combiner rules,
preview payloads, texture source resolution, capture helpers, and rendering
fidelity checks.

Keep feature UI controls outside this package. UI packages host previews and
display state; rendering code owns resource contracts, material synthesis, and
native preview preparation.

Archive Browser, Model Library, Mesh Editor and Create New Item converge on the
same canonical package and material contracts. A caller may publish bare
geometry while Preview Core prepares canonical textures, but later package
promotion keeps the resident process and camera. `cdmw_mesh_lab` owns the
viewport, HDR studio lighting, and approximate effect-particle drawing; this
package owns the Python-side package, cache, material, and texture inputs rather
than a second renderer. Historical `d3d11_*`, `dotnet_*`, and
`native_preview_*` names are compatibility aliases only.

Related tests: native preview, model preview, and static replacement entries under `tests/`.
