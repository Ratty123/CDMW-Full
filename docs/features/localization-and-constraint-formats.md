# `.paloc` string tables and `.papr` constraint rigs

Two formats decoded together because they close two of the gaps
`docs/features/format-decode-progress.md` ranked highest. They are unrelated in content
and very different in how far they got: `.paloc` is finished, `.papr` is not.

## `.paloc` — every line of text in the game

`gamedata/stringtable/binary__/localizationstring_<lang>.paloc`. Fourteen files, one per
language, 187,521 entries each — quest dialogue, item names, UI labels, subtitles.

    repeat count times:
        u32 category          one of 38 ids
        u32 reserved          zero in all 2,625,294 shipped records
        u32 key_length;   key   UTF-8
        u32 text_length;  text  UTF-8, may be empty
    u32 count                 the footer

The count is a **footer**, not a header. That is the detail that kept the format closed:
a reader that opens the file looking for a header finds a record immediately and has to
scan for something that looks like a string, which is what the old detection heuristic in
`cdmw/core/archive_format.py` does.

Keys are identifiers — `questdialog_main_01262`, `aidialogstringinfogroup_cheerup_36512`
— and about 30% are bare numbers. Both are UTF-8 and both round-trip.

Owner: `cdmw/core/paloc_format.py`. Tests: `tests/test_paloc_format.py`.

**Status: read and write, complete.** All 14 shipped tables rebuild byte for byte, and
the footer count agrees with the record walk in every one. Parsing 187,521 entries takes
0.2 s.

**What this opens.** Nothing in the file is offset-addressed or aligned, so a translated
line may be any length and rewriting the table is just re-emitting the records. That
makes `.paloc` the one game format where an edit cannot corrupt anything downstream —
there is no offset table to relocate, no padding to preserve, no checksum. Fan
translations, renamed items, rewritten quest text and joke localisations are all the same
one operation: `replace_text(table, {key: new_text})`.

The `category` id has no name in the file. `describe_categories` reports the dominant key
prefix per category from the data instead of inventing labels, so category 38 comes back
as `questdialog` because that is what its keys are called.

## `.papr` — driven bones

`character/model/**/<rig>.papr`, twenty files, one per character rig. This holds the
bones that follow *other bones* rather than an animation clip.

**It is mostly not what the `B_Jiggle_*` names suggest.** Counted across all 471 chains
in the twenty rigs: **259 are corrective deformation** (`UpperFMuscle`, `Bip01 L
Knee_Sub`, `Thigh_Front`, twist bones), 67 are pivots, 56 are exposed transforms, 29 are
mechanical parts on the golems and tanks, and **only 5 are jiggle** — on the dog and the
bear. No rig contains hair or cloth at all.

So on a player character `.papr` is the *deformation* rig: how a muscle bulges and how a
knee creases as the body moves. That is squarely what a physique or body mod needs, and
it is a different capability from the hair physics the naming implies. An earlier version
of this document generalised from those five jiggle chains and got it wrong.

    'PAR ' u8 0x35 u8 0x01 b'\x00\x01...\x09'   container header; 0x35 is ASCII '5'
    u32 zero
    u32 14
    u32 payload_bytes                          counted from 0x1C to the end
    u32 entry_count
    u32 unidentified
    entry_count x { u16 len; name  u16 len; parent  ...typed record... }

Strings are `u16 length` then that many bytes with no terminator — unlike `.paac`, where
the length counts a trailing NUL.

Owner: `cdmw/core/papr_format.py`. Tests: `tests/test_papr_format.py`.

**Status: entry structure decoded, writer complete, block contents still opaque.**

### How the entry chain was found

The obvious approach — find each block's closing `07 05 00` — does not work. Those three
bytes also occur inside float payloads and inside the expression strings some rigs carry
(`ExposeTransform_Bip01 R Forearm:5`, `-Local_Euler...`), so the first match is often too
early and the walk desyncs. Searching later matches does not help either, because the
error is in the other direction on other files.

What works is locating entry **starts** instead: two name-shaped strings followed by a
tail whose third byte is 0 or 1. Requiring that chain to be exactly `entry_count` long
and to tile the file is a strong constraint — **19 of the 20 shipped rigs tile exactly**.
Block extents then fall out as the gap between one entry's header and the next start.

Two other pieces fell out of this:

- The third tail byte selects a **40-byte transform frame** — `scale[3]`, `rotation[4]`,
  `translation[3]`, the same shape as the `.paa` bounds frame. 703 of them across the
  corpus, previously unread.
- `u32` at `0x20` is the **total tag-record count** across all blocks. Bear declares 12
  and has two blocks of six records; dog declares 30 and has five. It is an independent
  check on any future attempt at the block grammar.

`cd_m0001_00_circusmachine_boss` finds 236 starts against a declared 237 and is
**rejected rather than guessed at**.

### What is still opaque

Blocks are a stream of 3-byte `(tag, type, value)` records. Type `0x03` opens, `0x05`
closes, `0x01` is a scalar, and `0x04` introduces a member whose payload depends on the
member id — some carry nothing, some two bytes, some a `u8 count` and that many
`(u16 name, f32 weight)` driver pairs. Those rules are schema-driven and the schema is
not in the file, so this module does not interpret block contents. It carries them
verbatim, which means an edit can never corrupt a construct we do not understand.

### What can be edited

`encode_papr` rebuilds a rig from its parsed form, and **all 19 parsed rigs rebuild byte
for byte** across 2,734 bones, 703 transform frames and 1,632 weights. On top of that:

| Edit | Notes |
|---|---|
| Influence weights | Four-byte overwrite. `set_weights` refuses to write unless the caller states the value it expects to replace. |
| Bone and parent names | May change length: nothing is offset-addressed and `payload_bytes` is recomputed. |
| Transform frames | Ten floats in place. Adding a frame where there is none is refused — it would change the entry shape. |

What cannot be done is authoring a new constraint chain from nothing, because that needs
a block, and blocks can only come from a parse.

**One trap worth recording.** The first version of the weight-confidence rule accepted
"any whole number in 0..100", and denormals like `3.6e-43` — four bytes of a neighbouring
integer read as a float — passed it, because they round to zero. The rule now needs a
whole number of at least 1. A second trap follows from it: `scale_weights` rounds to
whole percent, because halving 15 to 7.5 would leave a value the locator no longer
offers, and the *second* edit in a session would silently find nothing. Both are tests,
not comments.

## Making mods with this

`tools/placement_studio/constraints.py` turns a rig into something a person can act on,
and `tools/placement_studio/window_constraints.py` is the panel over it.

**Chains, not bones.** A driven bone hangs off a parent that is often itself driven, so
entries are grouped by walking parent links up to the first bone that is not driven. That
turns `golem_imp_boss`'s 437 entries into 13 chains and `phm_01`'s 190 into 71. A muscle
group is one row, not six.

**Strength, not weights.** A chain's strength is the mean of its weights. Moving it
scales every weight in the chain proportionally. That is one number per chain instead of
1,632 across the corpus.

The export path reuses the Studio's existing packager: `changed_files()` returns
`{game path: bytes}`, which `packaging.build_package()` turns into a real mod package for
each supported manager. An unchanged rig exports nothing rather than an identical file.

### The panel

It lives in the Placement & Animation Studio as a **Driven bones** tab rather than in its
own tool, because a driven bone is only meaningful next to the rig, the armour on it, and
a clip playing — a standalone editor would have to rebuild all of that first.

- **Chain list**: name, what it is, bone count, strength, and how much of it is decoded.
  The *what it is* column is the important one — it says `deformation`, `jiggle`,
  `pivot`, `expose` or `mechanical` per row, so nobody has to infer from bone names that
  `Bip01 L UpperFMuscle` is a muscle bulge and not hair. Rows sort by category, most
  edit-worthy first.
- **Decoded column**: `full` when every byte of that chain's config is understood,
  `partial` otherwise. Editing is equally safe either way — undecoded bytes are written
  back unchanged — but a modder is entitled to know which is which.
- **Detail** on the right: every driven bone in the chain with what drives it and at what
  weight.
- **Softer / Stiffer / Off / Reset**, plus a strength slider in whole percent. The intent
  buttons come first because that is how people think about it; the slider is there when
  they want the number. The slider only writes on release, so dragging does not churn the
  document.
- **"What you can do here"**: two columns, can and cannot, generated from
  `constraints.CAPABILITIES` so the UI cannot promise something the code will not do. A
  test asserts every "can" has a function behind it and that adding a chain is listed as
  impossible.
- **Export**: mod name and author, then one button that writes a package per manager.
  Disabled until something actually changes.

**The panel says it cannot preview the result, and that is deliberate.** CDMW plays a
clip's baked bone tracks; these bones are solved by the game at runtime. There is no
honest way to show the change in the viewport, so the panel states that instead of
implying the opposite. A test asserts the notice is present.

## What is not decoded

`.ui` is in the capability manifest and **the shipped build contains zero `.ui` files**.
The game's UI is HTML and CSS: 160 `.html`, 176 `.css` and 27 `.thtml` under `ui/`, all of
which CDMW already reads and writes as text. There was never a binary widget format to
decode, and the entry that said otherwise had been carried for years without anyone
checking it against an archive. Chasing it would have produced nothing.
