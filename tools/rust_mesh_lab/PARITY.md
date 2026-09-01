# Rust Mesh Lab parity contract

## Oracle boundary

`cdmw_oracle` is development-only. Standalone Rust Mesh Lab and its archive/mesh
runtime do not depend on Python, C#, C++, or the production CDMW renderer.
CDMW-managed Rust Edit Mesh is a different boundary: the Rust executable keeps
its `wgpu` renderer and local gestures but deliberately exchanges authoring
transactions and service-owned commands with CDMW's shadow `MeshService`.

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

## Integrated parity boundary

`--cdmw-session <manifest>` selects the managed
`cdmw_rust_mesh_authoring_package_v1` path. Bounded JSONL uses
`cdmw_rust_mesh_editor_protocol_v1`; large arrays remain hash-checked,
file-backed values under the CDMW-owned session directory. Accepted operations
change only the shadow service until **Finish Edit Mesh** passes the existing
exact or Free Edit preparation and the authoritative mesh, Geometry Layers, and
Morph & Refit revisions/state are still current. The final publication is one
atomic reversible transaction.

The integrated editor keeps Select, Move, Rotate, Scale, Grab, Smooth, Inflate,
and Pinch local to Rust. Numeric translation/rotation/scale steps use the same
one-gesture history boundary. Inflate uses a signed strength so one tool can
inflate or deflate. Grab, Smooth, Inflate, and Pinch expose deterministic
Off/X/Y/Z object-space symmetry within each Part; explicit selection clips both
sides, mirror-plane vertices apply once, and unmatched vertices remain untouched.
Cleanup/repair, mirror, normals/tangents, UV0, and rig-weight actions cross the
typed command lane with an explicit selection and current output-policy check;
Loop Cut, Refine Smooth, Weld, and face or edge Extrude carry their UI parameters
rather than fixed defaults, including Extrude's world-X/Y/Z offset. Geometry
Layer visibility filters both the GPU draw snapshot and the viewport projection
used for picking/selection, while the base layer remains visible. A Bones overlay
requires a complete bounded acyclic linked hierarchy, and the Rig page exposes a
bounded selected-vertex influence/value/total readout. Weight adjustment and
normalization require explicit Vertex targets; source transfer accepts explicit
vertices or Parts. All three are enabled only for Exact PAC LOD 0 targets with a
resolved PAB palette, unchanged topology/source mapping, and the proven 40-byte,
six-slot `pac_slot_u10x6` layout. PAM, PAMLOD, Free Edit OBJ,
unresolved palettes, generated vertices, and protected extra-influence lanes
remain disabled. Successful no-ops and operation diagnostics are displayed
instead of being reported as completed edits. Refit controls hydrate from the
selected bound garment's saved settings before applying changes.

Integrated CDMW sessions carry already-resolved DDS inputs as bounded,
hash-checked owned resources with explicit roles and per-LOD material ranges;
Rust validates and rebinds them whenever a shadow document revision is
installed. Bevel/chamfer, UV1 editing and a 2D UV workspace, a true weight-paint
heatmap and brush, normal-direction extrusion, and full layered/dye material
composition are not part of the current contract. The Bones overlay is hierarchy inspection, not
skinned deformation or pose preview, and selected-weight rows are a bounded
numeric readout rather than weight paint. Missing capabilities are not hidden by
enabled placeholder controls; protected channels still remain inside the
versioned authoring package and validated Finish path.

Finish returns an accepted revision to CDMW. **Run validation** must then pass
for that revision before **Build Mod** can publish a DMM, JMM, CDUMM, or Crimson
Sharp loose package or a DMM archive group. **Install as Overlay** is gated by
the same revision and retains its existing confirmed backup/rollback lifecycle.
Package outputs are staged and published atomically. The source PAMT/PAZ bytes
are not rewritten.

`--control-contract-json <path>` emits
`cdmw_rust_mesh_editor_control_contract_v2`. The report merges the former
compatibility and Rust-extension rows into one Rust-owned product contract and
fails unless every enabled row has both a painted UI anchor and compiled
dispatch target, while every disabled row has a reason. No Vortice report,
executable, hash, or environment variable participates. This proves compiled
surface binding, not pixel-identical rendering or visible usability.

## Tolerances

No floating-point tolerance comparator is published yet. The current structural fingerprint is intentionally exact for one implementation and unsuitable as the only cross-language floating-point parity criterion. Future parity must compare positions, UVs, normals, tangents, and weights with documented absolute/relative tolerances while keeping topology, ordering, indices, bone palette, and referenced paths exact.

## Corpus state

Synthetic Rust unit tests cover archive tables/path cycles/payload indexes, DDS metadata/color space and mip planning, relationship ambiguity, PAC/PAM/PAMLOD fixtures, mesh handle invalidation, topology subdivision, history, lasso winding, stale snapshot rejection, 100 cancellation restores, and a deterministic 1,000-event replay.

Separate CDMW integration fixtures cover shadow isolation, protocol ordering,
owned file bounds, exact-output refusal, typed MeshService authoring actions,
rig-weight state, Morph & Refit concurrency, atomic history restore, process
lifecycle, embedded HWND ownership, and merged Rust v2 control binding.

Private Crimson Desert archive, PAC, PAM, PAMLOD, DDS, skeleton, variation, and morph parity has not run. Consequently:

- native archive parity is not READY;
- PAC skinning and appearance parity are not READY;
- textured GPU parity is not READY;
- the current renderer does not claim pixel-identical parity with the retained
  `d3d11_vortice_shader` Archive Preview renderer;
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
