# Prefab Structural Decoding

Last reviewed: 2026-07-27

## Purpose

Read a `.prefab` by parsing the format's own grammar, so the app can show what
a prefab contains, retarget its assets at any path length, and move what it
places. A prefab is self-describing: it carries a type table naming every
member with its declared type and byte size.

Not to be confused with **Placement Studio**, which retargets character
attachment sockets in `.paac` and `.sockets.xml`. That answers "which bone does
this sword hang off"; this answers "where in the world does this rock sit". A
prefab's `_socketFileName` references the data Placement Studio edits, so they
meet, but they are different layers.

## Ownership

- `cdmw/core/prefab_binary.py`: the decoder. Header, type table, string pool,
  data header, and the heap walk that recovers objects, references and values.
- `cdmw/core/prefab_binary_edit.py`: length-changing path edits with exact
  pointer relocation, and fixed-size placement writes.
- `cdmw/core/prefab_asset_catalog.py`: archive paths grouped by extension, for
  existence checks and the asset picker.
- `cdmw/domain/archives/prefab_glossary.py`: plain-English field names, asset
  roles.
- `cdmw/domain/archives/prefab_values.py`: numeric values and transforms.
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
pointer := u64 owner, u32 selfOffset, pointee(N), u32 N
```

Things that are easy to get wrong, each of which passes on a narrow corpus:

- The type table is **flat**. Nested types are appended after the referencing
  type's complete member list; parsing it as a tree fails immediately.
- The string pool is **variable-length**, so the data header is not at a fixed
  offset. An empty pool makes it look fixed.
- Version 3 has no content hash; revision 13 has no string pool.
- `flags == 0x0004` serialises exactly like `0x0005`, not as an inline value.
- The element header **states the component's type index** at `owner-3`
  (6940/6940 sampled groups). Inferring the type from the presence mask cannot
  work: two components can both accommodate the same mask. Guessing wrong
  surfaces downstream as a bogus string length or collection count, which reads
  like a grammar bug and is not one.
- Markers 1, 2 and 3 all occur, and the mask's position moves with the marker.
  Its **width does not** -- see Dead Ends.

`Transform` is 40 bytes: scale, rotation as a quaternion (x, y, z, w), then
position. `TiledTransform` adds a tile index. Rotation displays as yaw/pitch/roll
degrees; the composition order is yaw about Y, then pitch about X, then roll
about Z.

## Why length-changing edits are safe here

The blob stores **absolute file offsets**, so resizing a string moves every
following byte. The offsets are not guessed: a u32 at blob-relative `k` is a
pointer if and only if it stores `blobOffset + k + 4`, addressing the byte just
past itself. That identity survives relocation, so each pointer's new value is
its own new offset plus four -- arithmetic, not inference.

`crimson_formats.rebuild_prefab_resized_strings` instead scanned preserved
bytes for u32s that happened to equal a known string offset, which cannot tell
a pointer from a coincidence. On a real prefab it dropped one. It now verifies
its own output against the exact test and refuses rather than returning
corrupted bytes.

Placement writes are simpler still: transforms are fixed size, so nothing moves
and no pointer needs relocating. Placements are applied **before** path edits,
because path edits move bytes and would invalidate the offsets.

## Coverage

Measured on 12,000 archive-extracted prefabs:

| | |
|---|---|
| header, type table, pool, data header | 12,000 / 12,000 |
| structural heap walk completes | 54.3% overall |
| ... of files declaring one component type | 93.2% |
| objects recovered | 125,419 |
| numeric values recovered | 143,917 |
| length-changing round-trips re-decoding cleanly | 1,500 / 1,500 |

A partial walk is reported, never hidden: `walk_complete` is false,
`walk_note` says where it stopped, and the Inspector disables editing.

## Safety Rules

- Editing requires a complete walk. Partial decodes are read-only.
- Replacement paths may be any length; pointers, pointee length fields and the
  data header are all updated.
- Placement writes are checked against the bytes currently at the offset, so a
  stale decode is refused rather than splicing over live data.
- Existence checks are three-valued. `None` means no index covers that asset
  kind and must not be reported as missing.
- Game archives are read-only inputs. Edits leave through the loose mod package
  path.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prefab_binary.py tests/test_prefab_binary_edit.py tests/test_prefab_values.py tests/test_prefab_glossary.py tests/test_prefab_companions.py tests/test_prefab_asset_catalog.py tests/test_prefab_inspector_dialog.py --basetemp="$env:TEMP\cdmw-pytest-prefab"
```

## What is left

Roughly in order of value:

1. **Nothing is confirmed to load in the game.** Every check is internal
   consistency, which a systematically wrong assumption would also pass. This
   matters more now that placement is editable: a wrong rotation convention
   would produce files that pass every test and sit at wrong angles in world.
   Needs a human with the game installed.
2. **46% of prefabs do not walk to completion**, and the reason is now known:
   **marker=1 groups do not state their component type anywhere in the header.**
   Markers 2 and 3 put the type index at `owner-3`; for marker=1 that byte is
   the mask's own high byte, and anchoring against 375 marker=1 groups from
   completed walks found no byte position holding the resolved index -- the
   best candidate scored 4.0%, i.e. noise. Those groups only decode when the
   fallback heuristic (smallest candidate type whose member count fits the
   mask) happens to guess right, which is why every mask-width variation
   reshuffles which files pass without a net gain. Closing this needs a
   discriminator from outside the element header. Editing is disabled for
   incomplete walks, so this costs coverage, not safety.
3. **Glossary descriptions are inferred** from field names and declared types,
   not from documentation. 87 entries cover 98.8% of set-field occurrences;
   entries whose names do not support a confident reading carry a label only.
4. **Only paths and placements are editable.** Other numeric values (opacity,
   flags, material variant) are decoded and displayed but read-only.
5. **No property-based testing of the rewriter.** The 1,500 round-trips used
   one substitution pattern; randomised multi-edit fuzzing would attack it
   harder.

## Dead Ends

Recorded so they are not re-run:

- **Companions are not same-stem siblings.** That guess scores 0/12,962. They
  live under a parallel role directory: `character/model/…/x.pac` implies
  `character/modelproperty/…/x.pac_xml` and `character/bin__/meshphysics/…/x.hkx`.
- **The presence mask's width is not the marker.** Four hand-analysed groups
  fit that rule perfectly; across the corpus `width=marker` and
  `width=min(marker,2)` both score ~53% complete walks against 54.3% for a
  fixed `u16`. A correct rule would not trade completions for objects. Measured
  per file rather than in aggregate, the narrow read gains 120 files and loses
  275: both widths are right on some marker=1 groups and wrong on others.
- **Picking the marker=1 mask width by which reading fits the stated type**
  scores 53.0%, no better than always-narrow, because the type index those
  files resolve to is not in the header either.
- **`.pami` is not a material.** It is an XML `<StaticMeshInstance>` naming a
  mesh and carrying its material data -- 300/300 sampled files. Classing it as
  a material sends a modder looking for a texture.

Two measurement traps cost time here: a patch regex that appended rather than
replaced (stacked assignments, last one wins, every configuration scoring
identically), and comparing against a baseline captured with a different
setting. Identical numbers across supposedly different configurations is the
tell.
