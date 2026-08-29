# Rust Mesh Lab parity contract

## Oracle boundary

`cdmw_oracle` is development-only. The normal GUI and archive/mesh runtime do not depend on Python, C#, C++, or the production CDMW renderer.

The neutral package schema is version 1:

```text
manifest.json
mesh/positions.bin
mesh/normals.bin
mesh/uvs.bin
mesh/indices.bin
```

Each binary descriptor records relative path, scalar type, little-endian byte order, components, logical count, byte length, and SHA-256. Numeric arrays never appear in JSON.

## Current comparison fields

- source format;
- declared LOD count;
- submesh count;
- vertex count;
- index and face counts;
- structural fingerprint over ordered names, positions, and indices;
- per-buffer byte length and SHA-256 in the neutral manifest.

The standalone comparison command exits 0 for equality and 2 for a mismatch.

## Tolerances

No floating-point tolerance comparator is published yet. The current structural fingerprint is intentionally exact for one implementation and unsuitable as the only cross-language floating-point parity criterion. Future parity must compare positions, UVs, normals, tangents, and weights with documented absolute/relative tolerances while keeping topology, ordering, indices, bone palette, and referenced paths exact.

## Corpus state

Synthetic Rust unit tests cover archive tables/path cycles/payload indexes, DDS metadata/color space and mip planning, relationship ambiguity, PAC/PAM/PAMLOD fixtures, mesh handle invalidation, topology subdivision, history, lasso winding, stale snapshot rejection, 100 cancellation restores, and a deterministic 1,000-event replay.

Private Crimson Desert archive, PAC, PAM, PAMLOD, DDS, skeleton, variation, and morph parity has not run. Consequently:

- native archive parity is not READY;
- PAC skinning and appearance parity are not READY;
- textured GPU parity is not READY;
- the current renderer is not a replacement for `d3d11_vortice_shader`;
- existing CDMW heuristic results are not strict Rust requirements until independently proven.

## Mismatch classification

Future comparison evidence must classify each mismatch as one of:

- Rust defect;
- existing CDMW defect;
- heuristic difference;
- floating-point tolerance;
- unsupported local variant;
- oracle limitation;
- ambiguous relationship;
- unknown.
