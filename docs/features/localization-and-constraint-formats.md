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

## `.papr` — secondary motion

`character/model/**/<rig>.papr`, twenty files, one per character rig. This is what drives
the bones an animation clip does not: hair, cloth, tassels, pistons, and the `B_Jiggle_*`
chains.

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

**Status: read at the surface, write constrained. The grammar is not solved.**

The per-entry record after the name/parent pair is a typed opcode stream — triplets like
`05 03 00 | 10 01 01 | 10 01 02` that vary between entries and select what follows. One
rig (`cd_m0001_00_bear`, the smallest at 357 bytes) walks cleanly on the simplest reading
and the other nineteen do not. There is deliberately no `encode_papr`: a writer built on
a guessed grammar would emit files that load and then misbehave, which is worse than no
writer at all.

What *is* solid is the part a modder wants. Inside those records the driver lists are
plain: a bone name followed immediately by an `f32` influence weight as a percentage.
Across the twenty rigs that locates 1,774 weights, and **every one is a whole number
between 1 and 100** — 98.6% of them multiples of five. That is what hand-authored
percentages look like and not what a misread float looks like.

Editing one is a four-byte overwrite. Nothing moves, nothing is relocated, and a no-op
edit is byte-identical on all twenty rigs. `set_weights` refuses to write unless the
caller states the value it expects to replace, so a site located against the wrong file
fails loudly instead of quietly corrupting a rig.

**What this opens.** Tuning secondary motion without touching HKX, whose structural edits
are correctly gated off: soften a cloak, stiffen a braid, take the jiggle out of armour
that flails, or `scale_weights(data, sites, 0.0)` to switch a chain off entirely.

**One trap worth recording.** The first version of the confidence rule accepted "any
whole number in 0..100", and denormals like `3.6e-43` — four bytes of a neighbouring
integer read as a float — passed it, because they round to zero. The rule now needs a
whole number of at least 1. That guard is a test, not a comment, because getting it wrong
silently offers garbage sites as editable weights.

## What is not decoded

`.ui` is in the capability manifest and **the shipped build contains zero `.ui` files**.
The game's UI is HTML and CSS: 160 `.html`, 176 `.css` and 27 `.thtml` under `ui/`, all of
which CDMW already reads and writes as text. There was never a binary widget format to
decode, and the entry that said otherwise had been carried for years without anyone
checking it against an archive. Chasing it would have produced nothing.
