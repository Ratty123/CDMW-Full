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

## Adding and removing collection elements

`cdmw/core/prefab_array_edit.py` changes how much of a file there is, rather
than what it says. A collection is a kind byte, an optional extra byte, a u32
count and then that many element bodies end to end, so growing one means writing
a larger count and splicing another body in.

Three measured facts make the splice tractable:

- **Pointers are self-relative**, so a copied pointer is recomputed from the
  copy's own position. Nothing inside a duplicated element refers outward.
- **Pointee length fields are distances.** Both ends of a pointee inside a moved
  or copied element shift together, so those fields keep their values. A pointee
  spanning the splice point would break this; it is checked for and refused.
- **Owner fields are not offsets.** This was the hazard worth ruling out. Over
  1,500 shipped prefabs an owner is either `NULL_OWNER` or a small ordinal, and
  not one of the 706 non-null owners fell inside the data blob. They are
  indices, so the splice does not touch them.

The primitives are **duplicate element N** and **remove element N**, not
"insert a new element". An element body's layout depends on that element's own
member mask, so there is nothing to synthesise from; a copy of a sibling is by
construction valid for the same collection, and retargeting it afterwards
through the path rewriter is what the edit was for.

### Element spans come from the walk

`PrefabDocument.collections` records each collection's header offset, header
width, declared count and every element's `(start, end)`. None of this is
recoverable afterwards: a header is only distinguishable from surrounding bytes
by having been arrived at, and an element ends wherever the previous one stopped
being read. The walk knows both and now keeps them.

### The collection header width

The header's extra byte is what decides whether the count sits at +1 or +2.
Reading a wide header as narrow yields the true count shifted up a byte -- still
small enough to look plausible -- and the walk then *finishes anyway*, because
it stops on the trailer when the elements run out. The file looks read while the
count is fiction.

The tell is that the misread count is a **multiple of 256**. Over 1,949
collections in completed walks, no correct narrow count was ever a multiple of
256, and where wide was the correct reading the extra byte was zero in 85 of 87
cases. But the signal is necessary, not sufficient: one file in 1,500 carries it
at a header where *neither* reading matches the elements that follow, and
forcing the wide form there costs 5,234 bytes of walk.

So the decoder does not decide per header. It reads the file, and only if a
collection over-declares *and* carries the signal does it read again with those
headers taken wide -- keeping the second reading only if it both completes and
leaves fewer collections over-declared. Judging the retry on the whole file is
what leaves that one file alone. Measured over 1,500 prefabs: 66 fewer
over-declared collections, no completion lost.

### Validation

No two shipped prefabs differ by exactly one collection element -- that was
searched for, and the six near-pairs are unrelated assets whose names coincide.
So there is no ground truth to diff a resize against, and validation is internal:

- **Duplicate then remove the duplicate returns the original bytes.** Over a
  1,500-file sample, **687 of 687 round trips are byte-exact, none differing.**
- Every result is **read back before it is returned** and refused unless the
  walk completes, the collection carries the new count, the file is the size the
  splice implies, every pointer still satisfies the identity, and the copy reads
  back as the same size as its source. That last check is not redundant: one
  corpus file passed all the others while its re-walk resynchronised a few bytes
  inside the copy.

Neither proves the game accepts the file. They prove it is the same kind of
object it was, which is the strongest claim available without the engine.

### In the Inspector

Right-click an object heading: **Duplicate this object** / **Remove this
object**. Object headings carry their group's byte offset (`OBJECT_ROLE`), and
`locate_element` turns that into the collection element behind the row by exact
offset match -- not by containment, because an object nested *inside* an element
is not itself one and offering to delete it would delete its parent.

Structural changes are applied **immediately**, unlike every other edit the
Inspector makes. Path and value edits are pending and keyed by byte offset; a
splice moves every byte after it, so a pending edit's offset would then point at
the wrong field -- and at a field that still looks like a plausible target. So:

- the dialog keeps `_opened` (the file as it arrived) alongside `_original` (the
  bytes the current rows were read from), and **Undo all changes** restores the
  first;
- the tree is rebuilt by re-decoding, never patched, because every offset the
  old rows held came from the old bytes;
- a structural change is **refused while row edits are pending**, with a dialog
  saying to save or undo them first. Migrating them across a splice is possible
  in principle and is not worth the failure mode.

Removing the last element of a collection is offered but disabled, with the
reason on the tooltip -- refusing in the menu explains itself, refusing after
the click does not.

## Coverage

Measured on 12,000 archive-extracted prefabs:

| | |
|---|---|
| header, type table, pool, data header | 12,000 / 12,000 |
| structural heap walk completes | 61.9% overall |
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

One caveat on the oracle, worth stating because it bounds what the number
proves: its admission filter imports `_length_field_candidates` and
`_string_byte_mask` from the writer to decide which pairs are comparable. A
layout those helpers mis-handle would be *excluded from the evidence* rather
than fail it. The exact reproductions are real for every admitted layout; they
are not an unconditional statement about every layout in the archives.

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
2. **38.1% of prefabs do not walk to completion**, down from 45.6% once the
   trailer was understood as a run of records rather than one.
   `scripts/prefab_walk_failure_census.py` groups what is left by cause and by
   how far through the data section each got:

   | files | share | median progress | p90 | objs | cause |
   | ---: | ---: | ---: | ---: | ---: | --- |
   | 1,417 | 31.0% | 1% | 6% | 0 | mask exceeds every candidate component |
   | 1,002 | 21.9% | 19% | 97% | 3 | collection count N (kind N) |
   | 772 | 16.9% | 5% | 89% | 1 | no pointer record near … |
   | 729 | 15.9% | 73% | 97% | 3 | walk ended N bytes short |
   | 260 | 5.7% | 12% | 75% | 1 | blob string length N at … |
   | 225 | 4.9% | 98% | 100% | 4 | no element header near … |
   | 99 | 2.2% | 22% | 94% | 2 | pointee length N != N |
   | 63 | 1.4% | 97% | 100% | 3 | blob read of N past end |

   **These are one problem, not eight.** Completion tracks a single variable --
   how many candidate component types the file declares:

   | candidates | files | complete | rate |
   | ---: | ---: | ---: | ---: |
   | 1 | 6,458 | 6,427 | **99.5%** |
   | 2 | 912 | 408 | 44.7% |
   | 3 | 399 | 38 | 9.5% |
   | 4-6 | 1,381 | 304 | 22.0% |
   | 7-10 | 466 | 105 | 22.5% |
   | 11-20 | 2,099 | 127 | 6.1% |
   | 21+ | 284 | 17 | 6.0% |

   With nothing to choose between, the walk is essentially perfect. It fails as
   soon as it has to choose, because marker=1 groups state no component type and
   the declaration-order fallback is a guess -- one that is nearly free with a
   single candidate and nearly hopeless with twelve. Files that fail early
   declare 18.8 types and 12.7 candidates on average; files that complete
   declare 5.3 and 1.6.

   That is why the messages differ while the shape does not: a wrong component
   means a wrong member layout, the cursor desynchronises, and whichever check
   trips first supplies the wording. It is also why none of the individual
   causes yielded to a targeted fix, and why the mask-width variants could not
   help -- the mask is not what is wrong.

   **Any real gain has to come from a discriminator for marker=1 groups**, which
   is the known-unknowable below. Nothing downstream of the choice will do it.

   Three of the symptoms were chased individually first, and none is what its
   message suggests:

   - **"Collection count N (kind N)" is misalignment, not an unhandled kind.**
     The rejected kind bytes are scattered (0x30, 0x04, 0x62, 0x0c, 0x02, …)
     with counts like 1,867,710,464, and the bytes at the cursor are
     length-prefixed strings -- `09 00 00 00 "Socket_01"`, `11 00 00 00
     "Basic_Chil…"`. The walk is reading a string as a collection header. The
     message names a kind, which invites an enumeration that does not exist.
   - **"Walk ended N bytes short" is real unconsumed structure**, not padding:
     the leftovers hold owner fields and object names. But only 37 of 729 parse
     as further groups when the walk is allowed to resume from the stop, so
     resume-parsing is not the answer and was not kept.
   - **The presence mask's width was re-tested against this baseline and the
     full `u16` still wins.** The earlier width result was measured at 54.3%,
     before the trailer fix, so it was not settled. Re-run at 61.88%: reading
     the low byte only scores 31.46%, narrowing to `u8` for marker=1 scores
     61.41%, and narrowing for marker<=2 scores 58.89%. Every variant is worse,
     including the one the mask-exceeds evidence pointed at.
   - **"Mask exceeds every candidate" fails on the first *child* group.** The
     root mask parses correctly every time (2 bits set, 2 members selected).
     The child's mask needs more members than any candidate type has -- but the
     root type usually does fit, since a child scene object is itself a
     `SceneObject`. Offering the root as a peer candidate is *worse*
     (61.9% → 59.4%): it has enough members to fit most masks and displaces the
     right component. Offering it only when nothing else fits gains 6 files and
     merely relocates the failure to "blob string length" at the same 1%
     progress. Both point at the mask's *width* being misread rather than at the
     candidate list, which rejoins the mask-width dead end below.

   The known-unknowable part remains: marker=1 groups do not state their
   component type anywhere. Markers 2 and 3 put the type index at `owner-3`;
   for marker=1 that byte is the mask's own high byte. The search for a byte
   holding the resolved index has now been re-run on **5,003 anchors** rather
   than the original 375, the trailer fix having produced far more completed
   walks. The best position, `owner+7`, scores 14.9% -- which looks like a jump
   from the earlier 4.0% and is not one. Both the resolved index and that byte
   cluster on small values (indices 2, 3 and 4; bytes 2, 0 and 1), and the
   agreement expected from that overlap alone is **11.8%**. The 3-point excess
   is not a discriminator, and the apparent improvement is a change in the
   anchor set's composition, not a finding. Anyone re-running this should
   compare against the independence baseline, not against 4.0%.

   Retrying the alternative component when a group fails was also tried, on the
   reasoning that a *binary* choice is not exponential. It is: nested groups
   each retry in turn, so the cost multiplies down the tree, and a corpus pass
   that normally takes about a minute did not finish in ten. Reverted.

   Incomplete walks are not dead weight: their asset paths are recovered from
   pointer records without the walk, and same-length retargets are allowed
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
   Reading more files made this slightly worse rather than better: the prefabs
   the trailer fix unlocked carry proportionally more name-record pointers, so
   the share of pointer sites whose length field the walk knows exactly fell
   from 50.5% to 47.8%, and sites with more than one surviving candidate rose
   from 6.5% to 8.9%, affecting 12.3% of files rather than 5.6%. Those edits are
   declined, never guessed, and the files concerned could not be edited at all
   before. Deriving the name record's extent would fix it, and cannot be done
   cheaply: the distance from the end of the name text to the length field is
   scattered (86, 108, 112, 132, 242 bytes and so on), because the pointee
   encloses the whole object rather than just the name.
   The length field is found by scanning for a position whose u32 equals its own
   distance from the pointee start. That test is necessary but not sufficient:
   6.5% of pointees have more than one position satisfying it, and nothing in
   the file resolves which is real -- a nesting-consistency rule resolved 0 of
   244. Where a pointee opens with a decoded string the field is *computed*
   rather than scanned, which covers every resource-path pointee; where it does
   not, and an edit falls inside, the rewriter refuses. Measured on the shipped
   archives, that declines about 4% of files rather than writing them.
7. **The pointer test is necessary, not sufficient -- but it has now been
   measured.** `value == offset + 4` is an exact identity, and arbitrary inline
   bytes can satisfy it by coincidence, so it cannot be proved sufficient. It
   can be checked against the walk, which knows exactly which pointers it
   consumed. Over 1,261 complete-walk prefabs and **18,503 pointer sites**, the
   identity test and the walk agree exactly on 99.0% of files. The 37 sites the
   test found but the walk never traversed are not evidently coincidences: 35
   of them open with the zero word a populated pointee begins with, which is
   what an unvisited pointer looks like. One site went the other way, and the
   harness can manufacture that -- it runs its own footer search before the
   real one -- so it is not established as a genuine miss.

   That replaces "could in principle be wrong" with a number. It is still not a
   proof, and the rewriter's safety does not rest on one: pointer values are
   recomputed from their own relocated positions, so a coincidental site would
   have to also sit where a relocation applies.

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
- **Allowing the root type as a group's component does not unblock "mask
  exceeds every candidate".** That cause is the single largest, and the
  arithmetic invites the fix: the failing masks need 9 or more bits, no declared
  component has that many members, and the root `SceneObject` has 13. Since
  `_childSceneObjects` holds child scene objects, resolving those groups to the
  root type looks obviously right. It is not. Over 1,500 prefabs the cause
  disappears completely -- 158 files down to zero -- and **completion moves
  878 to 880**, with objects recovered up 78 and median partial progress up
  0.7 points. The wall simply moves: 83 of those files then fail on
  `blob string length 603980289` instead, a step later and no further through
  the file. The group header resolves and the body immediately does not, which
  says those groups are not root-shaped after all -- the correct type is
  probably not in the file's type table at all. Worth knowing before spending a
  session on the largest-looking cause: its size is not its cost.

Two measurement traps cost time here: a patch regex that appended rather than
replaced (stacked assignments, last one wins, every configuration scoring
identically), and comparing against a baseline captured with a different
setting. Identical numbers across supposedly different configurations is the
tell.
