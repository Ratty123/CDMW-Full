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
| structural heap walk completes | 54.4% overall |
| ... of files declaring one component type | 93.2% |
| objects recovered | 128,142 |
| numeric values recovered | 149,696 |
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

Randomised multi-edit fuzzing (`tests/test_prefab_rewriter_fuzz.py`) covers what
the original 1,500 round-trips could not: several resources per file, random
subsets edited at once, replacements shorter, longer and multi-byte, adjacent
edits, and first-plus-last together. It is seeded, so failures reproduce, and
it is mutation-tested -- breaking the shift table or the length scan is caught
by every case group.

**Differential validation against the game's own authoring tool**
(`scripts/prefab_vanilla_pair_oracle.py`) is the one check that does not rest on
our own decoder. The archives ship thousands of prefabs that are the same asset
with one path changed, so vanilla A rewritten to B's path must come out byte
identical to vanilla B. Result: **15,742 of 15,750 pairs reproduced exactly,
including 10,066 of 10,066 length-changing ones** -- the cases that exercise
pointer relocation, pointee length fields and the data header. The remaining 8
are refused as undecidable. Zero failures.

Selecting genuine pairs is most of that work; the filters are documented in the
script. It is mutation tested: turning the data-header patch into a no-op
produces 296 failures and a non-zero exit. An earlier version of the harness
classified residual differences as "not ours" when our output still matched A,
and that hid the same mutation completely -- a missing update looks exactly
like a faithful preservation, so the criterion is now plain byte equality.

Its synthetic fixtures are flat, though, so they cannot exercise nesting. The
run that matters is the same invariants over the shipped archives: 1,371
complete-walk prefabs with resources, random multi-edits, checking that the
result re-decodes, that untouched strings are unchanged, that pointer counts
hold, that the data header agrees with the file, and that undoing every edit
restores the original bytes exactly. That run found a corrupting bug the
synthetic tests could not reach; see Dead Ends.

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
2. **45.6% of prefabs do not walk to completion, and that is five problems, not
   one.** `scripts/prefab_walk_failure_census.py` groups them by cause and by
   how far through the data section each got, which matters more than the count:

   | files | share | median progress | p90 | cause |
   | ---: | ---: | ---: | ---: | --- |
   | 1,417 | 25.9% | 1% | 6% | mask exceeds every candidate component |
   | 1,036 | 18.9% | **99%** | 100% | no element header near … |
   | 1,002 | 18.3% | 19% | 97% | collection count N (kind N) |
   | 826 | 15.1% | **80%** | 100% | walk ended N bytes short |
   | 772 | 14.1% | 5% | 89% | no pointer record near … |
   | 260 | 4.7% | 12% | 75% | blob string length N at … |
   | 99 | 1.8% | 22% | 94% | pointee length N != N |
   | 59 | 1.1% | **97%** | 100% | blob read of N past end |

   Two groups, and they want opposite work. **"No element header", "walk ended
   short" and "read past end" together are 35% of the failures and sit at 80–99%
   of the way through** -- 1,921 files that are nearly read, most likely stopping
   on a terminator or trailing record the grammar does not model, not on a
   structural gap. That is the cheap target.

   **"Mask exceeds every candidate component" is the largest single cause at
   25.9% and stops at a median 1%, with zero objects read.** It fails
   immediately, which points at the root component selection being wrong from
   the first group rather than at anything deep in the file.

   The known-unknowable part remains: marker=1 groups do not state their
   component type anywhere. Markers 2 and 3 put the type index at `owner-3`;
   for marker=1 that byte is the mask's own high byte, and anchoring against 375
   marker=1 groups from completed walks found no byte position holding the
   resolved index -- the best candidate scored 4.0%, i.e. noise. The best
   discriminator found outside the header is declaration order, which held for
   301 of 304 completed walks.

   Incomplete walks are no longer dead weight: their asset paths are recovered
   from pointer records without the walk, and same-length retargets are allowed
   because they relocate nothing.
3. **Glossary descriptions are inferred** from field names and declared types,
   not from documentation. 87 entries cover 98.8% of set-field occurrences;
   entries whose names do not support a confident reading carry a label only.
4. **Only paths and placements are editable.** Other numeric values (opacity,
   flags, material variant) are decoded and displayed but read-only.
5. **No property-based testing of the rewriter.** The 1,500 round-trips used
   one substitution pattern; randomised multi-edit fuzzing would attack it
   harder.
6. **Some pointee length fields are undecidable, and those edits are refused.**
   The length field is found by scanning for a position whose u32 equals its own
   distance from the pointee start. That test is necessary but not sufficient:
   6.5% of pointees have more than one position satisfying it, and nothing in
   the file resolves which is real -- a nesting-consistency rule resolved 0 of
   244. Where a pointee opens with a decoded string the field is *computed*
   rather than scanned, which covers every resource-path pointee; where it does
   not, and an edit falls inside, the rewriter refuses. Measured on the shipped
   archives, that declines about 4% of files rather than writing them.
7. **The pointer test is necessary, not sufficient.** `value == offset + 4` is
   an exact identity, but arbitrary inline bytes can satisfy it by coincidence.
   No failure in the corpus fuzz. Hardening it means validating record structure
   rather than scanning, which is better attempted after a successful in-game
   canary than before one.

## Dead Ends

Recorded so they are not re-run:

- **Name-record pointees cannot be excluded from length-field fixups, and the
  walk cannot supply their field.** Only 50.5% of pointer sites have their
  length field recorded by the walk; the rest are name records, read by
  `_read_name_record`, which consumes a header, a count and the text but no
  trailing length. That looked like evidence the record has none: the u32
  immediately after it equals its own extent in just 24 of 10,137 cases, and
  8.2% have no position satisfying the length test within 260 bytes. Excluding
  those sites from the fixup pass on that basis broke **10,066 of 10,066**
  length-changing vanilla pairs -- every one. So the field exists and must be
  relocated; the record simply extends further than `_read_name_record` models,
  and the walk resynchronises past the remainder rather than parsing it. The
  masked scan finds the right field for these sites, which is why the oracle
  was clean before and clean again after reverting. Modelling the rest of the
  name record is the prerequisite for ever recording these, and nothing
  currently needs it.
- **The version-4 header field is not a content hash.** The decoder called those
  8 bytes a content hash on no evidence, which raised a real worry: neither
  rewriter touches them, so if the engine validated the field every edited v4
  file would be rejected in game. It does not, and it cannot. The field is two
  independent u32s, not one value -- files pair off sharing one half and
  differing in the other -- and, decisively, **six byte-identical bodies in the
  corpus carry different values there**, so nothing about the content determines
  it. No hash reproduces either half: crc32, adler32, FNV-1a/FNV-1 32, djb2,
  sdbm and md5 were tried over five ranges (whole file with the field removed,
  with it zeroed, everything after it, blob only, schema only) and against the
  archive path, the stem and their lowercased forms; zero matches. Nor is it a
  cross-reference: none of 1,467 sampled values appears inside any prefab body.
  It is near-unique (11,654 distinct across 11,996 files, with 143 values shared
  by 485 files) and clusters loosely by asset folder, which reads as an
  authoring-time identifier. Preserving it verbatim -- what both rewriters
  already do -- is therefore correct, and recomputing it would be the
  regression. Locked in by
  `test_the_version_4_header_identifier_survives_an_edit`.
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
- **The owning collection does not identify the type either.** Its `extra`
  matches the resolved type index 6.1% of the time and the group's position in
  the collection 6.0% -- both noise. `attr_flags` does separate the two *kinds*
  of collection (`0x1008` holds components, `0x1028` holds child scene objects
  and nested prefab instances), but restricting the candidate list accordingly
  changes no outcomes and costs ~600 objects, because the groups that need a
  fallback sit under `_components`, where the constraint is already implied.
- **`.pami` is not a material.** It is an XML `<StaticMeshInstance>` naming a
  mesh and carrying its material data -- 300/300 sampled files. Classing it as
  a material sends a modder looking for a texture.

Two measurement traps cost time here: a patch regex that appended rather than
replaced (stacked assignments, last one wins, every configuration scoring
identically), and comparing against a baseline captured with a different
setting. Identical numbers across supposedly different configurations is the
tell.
