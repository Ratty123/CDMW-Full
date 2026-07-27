# Prefab Structural Decoding

Last reviewed: 2026-07-27

## Purpose

Read a `.prefab` by parsing the format's own grammar, so the app can show what
a prefab contains and retarget its assets at any path length. This replaces
guesswork with parsing: a prefab is self-describing, carrying its own type
table with every member's name, declared type and byte size.

## Ownership

- `cdmw/core/prefab_binary.py`: the decoder. Header, type table, string pool,
  data header, and the heap walk that recovers objects, references and values.
- `cdmw/core/prefab_binary_edit.py`: length-changing path edits with exact
  pointer relocation.
- `cdmw/core/prefab_asset_catalog.py`: archive paths grouped by extension, for
  existence checks and the asset picker.
- `cdmw/domain/archives/prefab_glossary.py`: plain-English field names and
  asset roles.
- `cdmw/domain/archives/prefab_values.py`: numeric values, above all transforms.
- `cdmw/domain/archives/prefab_companions.py`: files a mesh resolves by path
  convention rather than by reference.
- `cdmw/ui/archive_browser/prefab_inspector_dialog.py` and
  `prefab_inspector_actions.py`: the Prefab Inspector.
- `cdmw/services/prefab_structure_service.py`: the facade the UI imports.

## Format

```
file    := header typedef*N pool datahdr(28) blob
header  := u16 magic=0xFFFF, u16 version, u16 ?, [u64 hash if v4],
           u32 revision, u16 N
typedef := u32 len, TypeName, u16 memberCount, member*memberCount
member  := u32 len, _name, u32 len, TypeName,
           u16 flags, u16 valueSize, u16 attrFlags, u16 extra
pool    := u32 count, (u32 len, string)*count        -- revision >= 14 only
datahdr := u32 instanceCount, u32 fileSize, u32 ?, u64 ffff..,
           u32 blobOffset, u32 blobLength

blob    := u16 tag(=2), u48 rootPresenceMask, group*, trailer(5..6)
group   := elementHeader nameRecord componentMembers
header  := u16 marker, u16 componentMask, (marker+1) tail
           marker is 1, 2 or 3; the byte at owner-3 is the component's index
           into the type table
pointer := u64 owner, u32 selfOffset, pointee(N), u32 N
```

Four things are easy to get wrong:

- The type table is **flat**. Nested types are appended after the referencing
  type's complete member list; parsing it as a tree fails immediately.
- The string pool is **variable-length**, so the data header is not at a fixed
  offset. An empty pool makes it look fixed, which passes on every character
  prefab and fails on world prefabs.
- Version 3 has no content hash, and revision 13 has no string pool.
- `flags == 0x0004` serialises exactly like `0x0005`, not as an inline value.

`Transform` is 40 bytes: scale, rotation as a quaternion (x, y, z, w), then
position. `TiledTransform` adds a tile index. Measured, not assumed --
floats[3:7] is unit-length in 74,190 of 74,225 sampled transforms.

## Why length-changing edits are safe here

The blob stores **absolute file offsets**, so resizing a string moves every
following byte. The offsets are not guessed: a u32 at blob-relative `k` is a
pointer if and only if it stores `blobOffset + k + 4`, addressing the byte just
past itself. That identity survives relocation, so each pointer's new value is
its own new offset plus four -- arithmetic, not inference.

Contrast `crimson_formats.rebuild_prefab_resized_strings`, which scanned
preserved bytes for u32s that happened to equal a known string offset. That
rewrites any coincidental match. It now refuses rather than guessing.

## Coverage

Measured on 12,000 archive-extracted prefabs:

- header, type table, pool and data header: 12,000 / 12,000
- structural heap walk completes: 54.3% overall, 93.2% of files declaring a
  single component type
- 125,419 objects and 143,917 numeric values recovered
- 1,500 length-changing round-trips re-decode with the walk still completing

A partial walk is reported, never hidden: `walk_complete` is false,
`walk_note` says where it stopped, and the Inspector disables editing so an
edit is never written to a file that is only partly understood.

## Safety Rules

- Editing requires a complete walk. Partial decodes are read-only.
- Replacement paths may be any length; pointers and pointee length fields are
  relocated and the data header is rewritten.
- Existence checks are three-valued. `None` means no index covers that asset
  kind, and must not be reported as missing.
- Game archives are read-only inputs. Edits leave through the normal loose mod
  package path.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prefab_binary.py tests/test_prefab_binary_edit.py tests/test_prefab_values.py tests/test_prefab_glossary.py tests/test_prefab_companions.py tests/test_prefab_asset_catalog.py tests/test_prefab_inspector_dialog.py --basetemp="$env:TEMP\cdmw-pytest-prefab"
```

## Known Limits

- 46% of prefabs do not walk to completion; the dominant failure is a component
  type index that does not resolve.
- Glossary descriptions are inferred from field names and declared types, not
  from engine documentation.
- Rotations display as Euler degrees for reading only. They are ambiguous and
  degenerate at the poles, so the quaternion stays authoritative.
- **No edited prefab has been confirmed to load in the game.** Every check so
  far is internal consistency, which a systematically wrong assumption would
  also pass.
