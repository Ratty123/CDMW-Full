# cd_hkx

Native Crimson Desert HKX parser core.

This crate is the first Rust layer for the HKX converter. It currently covers the stable tagfile foundation:

- `TAG0`/section discovery
- `SDKV` version extraction
- `TST1` type string table extraction
- `TNA1` packed type registry decoding
- `ITEM` record table decoding
- DATA payload span calculation for each ITEM record
- Read-only object layout hints for arrays, refs, vectors, convex topology buffers, mass properties, and hknp float candidates
- Experimental object reference candidates where payload words match another ITEM data offset, now categorized as object, array data, string, or type/class references where owner context is known
- Read-only `INDX`/`TPAD` fixup observations with nested `ITEM` descriptor decoding, nested `PTCH` marker/payload classification, null/data/type/string match counts, and reference category totals
- Native physics tuning groups for known fixed-size hknp body, constraint, shared-motion, and motor float slots
- Native model graph output with ITEM nodes, PTCH-backed object/null references, inferred offset references, owner-array rows, root/container hints, and stable graph ordering
- JSON output for Python/PySide integration

Build:

```powershell
cd native\cd_hkx
cargo build --release
```

Run:

```powershell
target\release\cd-hkx.exe summary-json C:\path\to\file.hkx
```

Native no-edit rebuild:

```powershell
target\release\cd-hkx.exe roundtrip-noedit input.hkx output.hkx
```

`roundtrip-noedit` parses the HKX into the native model, writes it back through the
raw-preserving no-edit writer, and fails unless the output is byte-for-byte
identical to the input. The JSON report exposes `native_read_model_write_available`,
`byte_identical_no_edit_rebuild_supported`, parsed section/item/object counts, and
the first mismatch offset if a future semantic writer regresses byte identity.

Safe fixed-float patch:

```powershell
target\release\cd-hkx.exe patch-fixed-f32 input.hkx output.hkx 182 0 0x28 0.6
```

The patch command only writes if the record/item/offset is present in the native fixed-size physics tuning map. It is intended for mod-ready loose HKX output, not in-place archive edits.

Corpus scan:

```powershell
target\release\cd-hkx.exe corpus-json C:\path\to\hkx_corpus 250 > hkx-corpus.json
target\release\cd-hkx.exe corpus-stats-json C:\path\to\hkx_corpus 1000 > hkx-stats.json
target\release\cd-hkx.exe verify-noedit C:\path\to\hkx_corpus 250 > hkx-verify.json
```

The optional numeric argument limits scanned `.hkx` files. This matters for full extracted trees; one local tree contained more than 57,000 `.hkx` files.

`verify-noedit` runs the same native no-edit writer over a file or folder and
reports aggregate byte-identity counts. This proves the raw-preserving
read -> model -> write path, but Havok-style XML import remains blocked until
representative corpus coverage and a semantic object/reference writer also pass.

The Python app treats this as an optional backend and falls back to the existing Python parser when the binary is not present.

Current scope supports read-only conversion, validated fixed-float patching for decoded physics tuning slots, a partial native object graph, and byte-identical no-edit rebuilding through the raw-preserving native model. The next Rust milestones are broader byte patch maps, true hkClass metadata tables, schema-specific hknp body/constraint decoders, full tagfile fixup semantics, semantic no-edit reserialization over representative files, and a native preview/simulation helper that can feed the app's model viewer.
