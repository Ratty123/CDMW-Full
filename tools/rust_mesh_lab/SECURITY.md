# Rust Mesh Lab security and asset safety

## Threat model

Archive indexes, payloads, meshes, textures, sidecars, and neutral packages are untrusted local input. A malformed file may attempt out-of-bounds access, excessive allocation, decompression expansion, path traversal, ambiguity substitution, cache poisoning, or denial of service.

## Parser rules

- Parser, mesh, interaction, evidence, and application code forbids unsafe Rust.
- Archive-origin offsets, counts, lengths, ranges, and allocation sizes use checked arithmetic and bounded slice access.
- Index, entry, mesh, path, DDS, and interaction limits are explicit in `FORMAT_CONTRACT.md`.
- Invalid indices, non-finite geometry, path cycles, traversal, unsupported compression/encryption, and unknown layouts fail closed.
- RustCrypto supplies ChaCha20; the lab implements only the existing filename-derived key/nonce contract.
- LZ4 output must match the declared size.
- Ambiguous basenames produce an unresolved relation, never an arbitrary selection.

## Read-only source policy

Archive roots and source meshes are opened only for reading. The GUI has no archive-writer or source-mesh writeback command. In-memory edits use a separate `WorkingMesh`. The verified archive read API can record before/after source fingerprints for explicit safety evidence; the normal browser path avoids hashing an entire PAZ per entry and remains read-only.

## Output policy

Neutral oracle packages publish to a caller-selected new directory. Existing destinations are refused. Complete output is staged beside the destination and renamed only after binary buffers and the manifest are flushed. The GUI's neutral OBJ/MTL export also refuses destinations inside the selected archive root, checks cancellation during serialization, reparses the staged OBJ, compares vertex/face counts and the structural fingerprint, and embeds no source texture.

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
