# Rust Mesh Lab security and asset safety

## Threat model

Archive indexes, payloads, meshes, textures, sidecars, neutral packages, CDMW
session manifests, referenced session files, and JSONL control messages are
untrusted local input. A malformed file or message may attempt out-of-bounds
access, excessive allocation, decompression expansion, path traversal, ambiguity
substitution, cache poisoning, replay, stale-state publication, or denial of
service.

## Parser rules

- Parser, mesh, interaction, evidence, and application code forbids unsafe Rust.
- Archive-origin offsets, counts, lengths, ranges, and allocation sizes use checked arithmetic and bounded slice access.
- Index, entry, mesh, path, DDS, and interaction limits are explicit in `FORMAT_CONTRACT.md`.
- Invalid indices, non-finite geometry, path cycles, traversal, unsupported compression/encryption, and unknown layouts fail closed.
- RustCrypto supplies ChaCha20; the lab implements only the existing filename-derived key/nonce contract.
- LZ4 output must match the declared size.
- Ambiguous basenames produce an unresolved relation, never an arbitrary selection.

## Read-only source policy

In standalone mode archive roots and source meshes are opened only for reading.
That GUI has no archive-writer or source-mesh writeback command; edits use a
separate `WorkingMesh`. The verified archive read API can record before/after
source fingerprints for explicit safety evidence, while the normal browser path
avoids hashing an entire PAZ per entry and remains read-only.

In CDMW-managed mode Rust receives a disposable clone, not authority over source
PAMT/PAZ files. The Rust process never writes those archives directly. An
accepted Finish can update CDMW's authoritative in-memory edit session only
through CDMW's existing validated replacement/writer path.

## CDMW-managed session policy

- `--cdmw-session` cannot be combined with standalone mesh/archive options.
- Manifests must declare `cdmw_rust_mesh_authoring_package_v1`; control messages
  must declare `cdmw_rust_mesh_editor_protocol_v1`.
- JSONL control messages are bounded, stdout carries protocol only, and stderr
  carries diagnostics.
- Every request is correlated by session ID, process generation, request ID, and
  revision. Stale, replayed, mismatched, and out-of-order work fails closed.
- Large payloads use relative file references with declared type, count, byte
  length, and SHA-256 under one CDMW-owned session root. Escapes, unexpected
  files, links/reparse points, hash mismatches, and per-file/tree/session limit
  violations are rejected.
- Rust-native gestures and typed service commands mutate only the shadow
  `MeshService`. Finish publishes once only after complete validation and
  authoritative mesh, Geometry Layers, and Morph & Refit revision/state checks.
- Rejection keeps authority unchanged. Cancel, close, crash, protocol failure,
  or forced termination discards only the owned shadow tree and process.

## Output policy

Standalone neutral oracle packages publish to a caller-selected new directory.
Existing destinations are refused. Complete output is staged beside the
destination and renamed only after binary buffers and the manifest are flushed.
The standalone GUI's neutral OBJ/MTL export also refuses destinations inside the
selected archive root, checks cancellation during serialization, reparses the
staged OBJ, compares vertex/face counts and the structural fingerprint, and
embeds no source texture.

CDMW-managed Finish instead prepares the complete shadow snapshot through the
selected Exact Game Asset or Free Edit policy. It atomically commits one
reversible `Rust Edit Session` only if all output and compare-and-swap checks
pass; it has no automatic Vortice fallback and no partial publication path.

## Proprietary assets

- Do not commit game archives, meshes, textures, skeletons, sidecars, decoded buffers, screenshots, or private evidence.
- Do not upload game data or metadata.
- Do not place evidence in the repository.
- Manifests use virtual paths and content hashes; they do not need absolute source paths.
- There is no telemetry, network processing, analytics, or crash upload.

## Cache

No persistent decoded cache exists in this slice. Cargo build output is ignored. A future cache must be user-local, versioned, checksummed, size-bounded, atomically published, and keyed by source SHA-256 plus decoder and GPU capability identity.

## Dependency and unsafe inventory

Workspace code contains no unsafe blocks. Graphics/window crates necessarily contain platform code outside this repository. Direct dependencies are locked in `Cargo.lock`; `deny.toml` permits common MIT/Apache/BSD/ISC/Unicode/Zlib licenses and rejects unknown registries, unknown Git sources, wildcards, and yanked advisories.

`cargo deny`, `cargo audit`, and fuzzing remain unexecuted unless those tools are installed and invoked explicitly. Their absence must not be reported as a pass.
