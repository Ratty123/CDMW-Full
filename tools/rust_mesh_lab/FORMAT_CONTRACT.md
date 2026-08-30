# Rust Mesh Lab format contract

This inventory records the local CDMW contracts examined at implementation time. “Proven” means backed by the current local owner and synthetic tests. It does not mean private real-game parity has run in Rust.

## Support matrix

| Format | Current Rust level | Local CDMW owner used as oracle | Limits and remaining proof |
|---|---|---|---|
| Archive `.pamt` index | Structural read | `cdmw/core/archive_format.py`, `cdmw/core/archive_scan_cache.py` | Header/table/path/payload bounds are checked; mount order from `meta/0.papgt` is not ported |
| Numbered `.paz` payload | Lazy read | `cdmw/core/archive_extraction.py` | Stored and LZ4 entries decode; supported type-1 DDS reconstructs from sibling `meta/0.pathc`, supported type-0 Sparse DDS pads to its validated declared size, and non-DDS type 1 remains classified as Partial raw; Partial PAR remains incomplete |
| PAC | Geometry read, proven LOD0-LOD3 mappings | `cdmw/modding/mesh_parser.py`, `native/cdmw_preview_core/src/owners/geometry_pac.cpp` | PAR sections, descriptors, candidate strides/UV offsets, packed normals, topology; skin palettes, extra influences, declared LOD4+, and appearance parity incomplete |
| PAM | Geometry read | `cdmw/modding/mesh_parser.py`, `native/cdmw_preview_core/src/owners/geometry_static.cpp` | Proven quantized candidate layouts; global/scan fallback variants incomplete |
| PAMLOD | Geometry read | same static owners | Declared LOD groups and proven quantized groups; unsupported groups fail visibly |
| DDS | Metadata read, supported archive reconstruction, and direct 2D GPU upload | `cdmw/core/archive_extraction.py`, `cdmw/core/dds_resource_limits.py` | Legacy/DX10 metadata and common BC/R/RG/RGBA/BGRA formats; bounded Partial and Sparse reconstruction is synthetically proven for supported 2D entries, while arrays/cubes and fallback transcode remain incomplete |
| PAC XML / PAM XML / PAMLOD XML | Bounded texture/material-parameter read | material sidecar owners | Wrapper/submesh/shader/texture provenance plus typed/unknown parameter names, raw values, attributes, and explicit/incomplete confidence are native. Base, normal, packed/separate surface, occlusion, emissive, metallic-only Specular or legacy Glossiness/Smoothness through one shared response slot, explicit-cutout Opacity, and exact global `_heightTexture` references are sampled per material owner. Glossiness retains its declared role and is not inverted into roughness because the production selector declares no component contract. Height is linear and uses R-channel fragment-normal/roughness relief around neutral 0.5; unique finite `_screenSpaceDisplacementScale`, `_detailScreenSpaceDisplacementScale`, or `_heightIntensity` values clamp to 0–1, otherwise the preview uses the current 0.025 default. Explicit zero disables the effect. Wrinkle, detail, parallax, and layer displacement references remain unbound; no vertex displacement is claimed. Unique explicit Float/Byte4 roughness, metallic/metalness, and specular factors are sampled per owner; hex emissive color and finite float intensity are sampled with a bound emissive texture. Explicit `AlphaTest`/`AlphaClip`/`AlphaCutout`/`Cutout` enable state selects the current approximate 0.08 cutout threshold and Opacity red-channel coverage, falling back to base-color alpha. Remaining scalar/vector factors, layers/dyes, channel-authoritative opacity, blend transparency, and non-global displacement semantics remain incomplete |
| PAMI / APP XML / Prefab-data XML | Relationship target only | appearance/material owners | Native semantic parsing not implemented |
| PAB | Unsupported in Rust | `cdmw/modding/skeleton_parser.py` | No skeleton overlay parity yet |
| PABC | Unsupported in Rust | `cdmw/modding/skeleton_variation_parser.py` | No variation application parity yet |
| Morph-target PAMT | Explicitly distinct, unsupported | `cdmw/core/archive_mesh_appearance.py` | Never passed to the archive-index decoder based on extension alone |
| Meshinfo | Unsupported metadata | current preview owners | No unproven table authority is claimed |

## Archive index contract

The current archive-index role is accepted only through structural parsing:

1. Three little-endian `u32` values: header checksum, PAZ count, reserved value.
2. `paz_count` records of three little-endian `u32` values. CDMW currently skips their semantics; Rust preserves them as checksum, file-count candidate, and reserved fields without using them as authority.
3. A length-prefixed directory path-record block.
4. A length-prefixed file-name path-record block.
5. A `u32` folder count followed by 16-byte records: hash, path-record offset, first file index, file count.
6. A `u32` file count followed by 20-byte records: path-record offset, PAZ byte offset, stored size, original size, PAZ index, flags.

Path records contain a parent `u32`, one-byte part length, and UTF-8 bytes. `0xffffffff` is the root sentinel. Rust rejects path cycles, out-of-range offsets, traversal, drive-qualified components, excessive depth, and excessive path bytes.

The low flag nibble is compression type; the next nibble is encryption type. Current labels are:

| Value | Compression | Rust behavior |
|---:|---|---|
| 0 | None | Stored bytes when sizes agree; a `.dds` size mismatch reconstructs as Sparse DDS by validating its header and zero-padding to the bounded declared original size; other mismatches fail closed |
| 1 | Partial | A `.dds` entry reconstructs from its exact virtual-path record in sibling `meta/0.pathc`; non-DDS data remains classified as Partial raw, and Partial PAR remains incomplete |
| 2 | LZ4 block | Native `lz4_flex` decode with exact expected size |
| 3 | Zlib | Unsupported, fail closed |
| 4 | QuickLZ | Unsupported, fail closed |

Encryption type 3 uses the current filename-derived ChaCha20 contract. Rust uses the maintained RustCrypto `chacha20` implementation in legacy mode, ports only the proven lookup3 seed/key/nonce derivation, and does not implement its own cipher primitive. Types 1, 2, and unknown values fail closed.

Archive discovery recursively finds `.pamt` index candidates, ignores top-level `cdmods`, sorts deterministically, validates every numbered payload identity and range, and does not read entry payloads during browsing. `meta/0.papgt` mount ordering remains a parity gap.

Partial DDS reconstruction parses the bounded PATHC fixed header, texture-header, checksum, entry, collision, and filename tables; resolves the exact normalized virtual path with the current lookup3 contract; validates the legacy/DX10 2D header and mip plan; and decodes the supported single-chunk or first-four-mip LZ4 layout. Payload chunk sizes override stale PATHC block-size metadata only under the same bounded plausibility rule as current CDMW. Missing or ambiguous PATHC records, malformed tables, unsupported texture shapes, truncated blocks, and outputs above the caller's active limit fail before publication. Reconstruction is in memory and leaves the PAZ and PATHC files byte-exact. Synthetic cross-implementation fixtures require exact reconstructed SHA-256 values `c9096e57e46707bd071a94b7274c6e8af0ddf01766137a186b58e993893b21a5` (Partial) and `2880a12980fe3145ebafbe2a3d9cf177337608e9037db99a9d5e717ecfc522cb` (Sparse); private archive-corpus parity is not yet proven.

## PAC contract

The Rust PAC reader currently requires:

- `PAR ` magic and a complete 0x50-byte header;
- up to eight structurally bounded internal sections;
- in-memory LZ4 normalization when a section declares a compressed size;
- section 0 with a LOD count from 1 through 10;
- descriptor patterns currently proven by the native preview core;
- finite bounds and counts below 200,000 vertices and 20,000,000 indices per descriptor;
- one validated geometry section and candidate vertex layout for every accepted section 4→LOD0 through section 1→LOD3 mapping;
- every index inside its submesh vertex count;
- finite decoded positions, UVs, and normals.

Candidate vertex strides are 32, 36, 40, 44, and 48 bytes with the locally accepted UV-offset family and the packed normal at byte 16. Positions use the existing PAC extent decoder; packed 10:10:10 normals use the current component reorder.

This is not yet PAC skinning parity. Bone indices, weights, palettes, rigid attachment context, and extra influence gates remain explicit readiness blockers.

## PAM and PAMLOD contract

PAM uses the local fixed header locations:

- mesh count at byte 16;
- bounding-box minimum at byte 20 and maximum at byte 32;
- geometry offset at byte 60;
- submesh table at byte 1040 with a 536-byte record stride;
- count/offset fields in the first 16 bytes, a 256-byte texture name at byte 16, and a 256-byte material name at byte 272.

PAMLOD uses declared LOD count at byte 0, geometry offset at byte 4, bounds at bytes 16 and 28, and scans only structurally valid descriptor/name records before geometry. Candidate layouts validate every index before decoding.

Static positions are quantized `u16` values over the declared bounds. UVs are binary16 values when the accepted stride carries them. Missing normals are recomputed deterministically from validated triangles.

## Resource limits

- Archive index: 512 MiB default maximum.
- Archive entry: 2 GiB configurable default maximum.
- Archive entries: 20,000,000 default maximum.
- Virtual path: 256 parent records and 32,768 bytes.
- Mesh: 10,000,000 vertices and 60,000,000 indices per submesh.
- DDS: 16,384 pixels per dimension and 512 MiB payload.
- Lasso: 4,096 retained points.
- Archive UI query: 20,000 displayed identities; full match count retained.

All offsets, table lengths, buffer sizes, and decoded sizes use checked arithmetic before allocation or slicing.
