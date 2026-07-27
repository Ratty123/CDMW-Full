# `.paa` motion clip format

Crimson Desert stores skeletal animation in `.paa` files under
`character/motion/<class>/<model>/`. This document records the on-disk layout and the
conventions needed to replay a clip. The reader lives in `tools/paa_motion/`.

Weapon *placement* and draw-animation *routing* are a separate concern and touch no `.paa`
payload — see `tools/placement_studio/animation.py`. This document is about the clip data
itself: the keys that move the bones.

## Container

`.paa` is a `PAR ` container, the same family as the `.pab` skeleton (version 1.5) and the
`.paac` action chart. Motion clips are version 2.3.

```
offset  size  field
0x00    4     'PAR '
0x04    1     major version (2)
0x05    1     minor version (3)
0x06    10    0x00 0x01 0x02 ... 0x09, constant in every shipped file
0x10    4     u32 flags
```

## Prelude

The flags word says which optional fields follow. Every combination observed in the shipped
corpus is covered by four bits:

| Bit | Field |
|---|---|
| `0x00000001` | One 40-byte transform frame: `f32 scale[3]`, `f32 rotation[4]`, `f32 translation[3]`. Not needed for playback. |
| `0x00000002` | `f32` rig unit scale, ~0.97222 — the bind-pose hip height. |
| `0x00000004` | A **second** 40-byte transform frame. |
| `0x00000010` | Selects the byte-quantised track codec (below). Also adds a `u32` at the head of the prelude and widens the track table. |
| `0x00000040` | Skeleton resource path: `u8 length`, then that many ASCII bytes, **no** terminator. |
| `0x00000100` | Widens the track table by one `u16`. Nothing else changes. |
| `0xC0000000` | Tag blob: `u16 byte length`, then UTF-8 including a trailing NUL. `;`-separated, e.g. `남자;맨손;달리기;738400079;`. |

The `0x10` prelude `u32` comes first, before the tag blob. Bits `0x08` and `0x80` are set
in shipped clips but add no bytes.

`0x04` was previously believed to be one of those inert bits, and the bounds block was
read as a fixed 80 bytes. It is not: 18 of the 54 `aim_add` bow clips ship as flags `0x1`
or `0x191` with `0x04` clear and stop after a single 40-byte frame. Reading 80 there put
`duration` 40 bytes past where it lives, and that went unnoticed because the track-table
scan recovered the tracks anyway and the mis-read float happened to be `0.0`. With the
bit honoured, those clips report a duration of exactly `31/30` s, and every one of the 18
lands on a whole frame count — which is the check that says the field is now being read
in the right place.

Attributing the second frame to `0x04` rather than `0x02` is a deduction, not a direct
observation: the two are set together in every shipped clip. `0x02` is independently
pinned as the unit scale, because the float it selects reads ~0.97222 across the corpus
and moving it would make that read garbage. `0x04` is the only assignment consistent with
both.

The two string fields use different length encodings. That is not a mistake in the reader:
the tag blob counts its NUL and the resource path does not.

A `f32 duration` in seconds always follows the optional fields. It is exactly
`last_frame / 30`, which is the only place the frame rate is recorded.

## Track table

The table always begins with the two bone counts and always ends with `u32 key_bytes`; the
flags decide what sits between them.

```
                          plain (8)   +0x100 (10)  +0x10 (16)
u32 leading word              -            -          5
u16 skeletal_bone_count       x            x          x
u16 root_bone_count           x            x          x
u16 filler                    -            0          0
u16 filler                    -            -          0
u32 key_bytes                 x            x          x
```

`key_bytes` counts every key payload and excludes the per-record header — 10 bytes for a
standard record (`u32 hash` plus three `u16` counts), 7 for a packed one (three `u8`
counts). Recompute it from the parsed tracks and it matches to the byte on every clip, so
the reader treats a disagreement as a failed parse rather than trusting an ambiguous walk.

Both counts may be zero: the `99_autofacial` clips ship as a header and nothing else.

Then `skeletal_bone_count + root_bone_count` track records follow, each:

```
u32 bone_name_hash
u16 n; n x key   scale        (3 components)
u16 n; n x key   rotation     (4 components, unit quaternion xyzw)
u16 n; n x key   translation  (3 components)
```

There is no name table. `bone_name_hash` is the same 32-bit hash the `.pab` skeleton stores
immediately before each bone name, as `[u32 hash][u8 name length][ascii name]` — so bone
names come from the skeleton the clip references, not from the clip.

## Keys

A key is a `u16` frame index followed by its components, laid out with the natural C struct
alignment for the component type:

| Precision | Components | Stride | Layout |
|---|---|---|---|
| half | 3 | 8 | `u16 frame`, `half[3]` |
| half | 4 | 10 | `u16 frame`, `half[4]` |
| float | 3 | 16 | `u16 frame`, 2 bytes padding, `f32[3]` |
| float | 4 | 20 | `u16 frame`, 2 bytes padding, `f32[4]` |

Precision is positional, not flagged. The first `skeletal_bone_count` records are half
throughout. The trailing `root_bone_count` records — `Bip01`, `B_MoveControl_01`, and the
`B_TL_Position_*` locators — store **translation** as `f32`; a half would quantise a ten
metre run into visible steps. Their rotation and scale stay half.

The two bytes before a float key's components are not padding the exporter zeroed. They
hold a value that is **constant across every key in a track** and differs between tracks;
it matches no 16 bits of the bone hash, and the same bone carries different values in
different files. That is an uninitialised stack slot, so there is nothing to derive from
it — but a writer that zeroes it produces a file that differs from the original, so
`BoneTrack.translation_pad` carries the track's value through a rebuild.

Frame indices are `u16` integers on a fixed 30 fps timeline (the packed codec narrows them
to `u8`) and they are sparse: a keyframe reducer drops frames that linear interpolation
reproduces, so a bone can hold 8 keys over 60 frames. The first key of a non-empty channel
is always frame 0.

## Values are deltas from the bind pose

This is the part that silently produces nonsense if you get it wrong. A track does **not**
hold a bone's local transform. It holds the delta from the skeleton's bind pose, expressed
in the bone's own local axes:

```
M_local = M_delta . M_bind_local            (row-vector, as the .pab stores matrices)
```

`Bip01 Pelvis` keys the identity quaternion in a standing clip even though its bind local
rotation is `(0.5, 0.5, 0.5, 0.5)`. Treat the key as an absolute local rotation and the
whole rig collapses.

As TRS in the column-vector convention a 3D format expects:

```
rotation    = q_bind * q_delta               delta applies first
translation = t_bind + scale_bind * rotate(q_bind, t_delta)
scale       = scale_bind * scale_delta
```

The translation rule is what makes `Bip01` and `B_MoveControl_01` agree about a run clip.
Their bind rotations differ by 90 degrees about Y, and their raw deltas differ by exactly
that rotation: `Bip01` ends a run at `(9.945, -0.134, -0.002)` and `B_MoveControl_01` at
`(0, 0, -9.945)`. Rotate either into the parent frame and they describe the same 9.94 m of
forward travel over 65 frames — about 4.7 m/s.

Because the bind pose is constant, right-multiplying by `q_bind` commutes with slerp and
the translation rule is affine in `t_delta`. A baked export can therefore keep the source's
sparse keys instead of resampling every frame, and stay exact.

## Coordinate system

Y is up (`Bip01` binds at y = 0.972, the hip height) and forward is -Z, matching glTF. A
decoded run clip puts the hips at 0.84 m, the head at ~1.45 m, and the feet alternating
between 0.09 m and 0.62 m across the stride.

## The packed codec (flags & `0x10`)

Roughly half the shipped `.paa` files — the `*_lod.paa` distance copies and the facial
clips — quantise their skeletal records to bytes. The record order and the bone-name hash
are unchanged; only the counts, the frame indices, and the values shrink:

```
u32 bone_name_hash
u8 n; n x ([u8 frame][s8 x][s8 y][s8 z])          scale
u8 n; n x ([u8 frame][s8 x][s8 y][s8 z][s8 w])    rotation
u8 n; n x ([u8 frame][s8 x][s8 y][s8 z])          translation
```

Every component is a signed byte in units of **1/64**, so `64` is `1.0`. This is proven for
rotation: 19,650 packed rotation keys sampled across the install all decode to unit
quaternions within 0.011, and a packed key checked against its full-precision sibling
matched to three decimals — `d8 0a f6 30` decodes to `(-0.625, 0.156, -0.156, 0.75)` against
a reference of `(-0.6221, 0.1573, -0.1552, 0.7515)`.

Two caveats worth knowing before trusting packed output:

- **Frames are `u8`**, so a packed clip cannot key past frame 255.
- **The translation scale is assumed, not proven.** Packed translation is used almost only
  by IK helper bones (`B_IK_*`, `B_CatchMe_00`, `B_EnemyCatch_00`) whose values saturate at
  ±127, so the corpus offers no clean pair to fit against; per-bone estimates ranged from
  1/5 to 1/161. The reader applies the same 1/64 as rotation. Root motion is unaffected —
  see below — and ordinary skeletal bones barely use translation, so the pose is sound
  either way, but treat packed translation as indicative. `format.PACKED_UNIT` is the one
  place to change if better evidence turns up.

Packed clips keep their **trailing root records in the standard half-precision encoding**,
so root motion stays exact even at LOD. Note the asymmetry: standard clips widen root
translation to `f32`, packed clips leave it half.

## Using it

```bash
python -m tools.paa_motion.cli info <clip.paa>
python -m tools.paa_motion.cli tracks <clip.paa> --skeleton <phm_01.pab>
python -m tools.paa_motion.cli pose <clip.paa> --skeleton <phm_01.pab> --frame 20
python -m tools.paa_motion.cli export <clip.paa> --skeleton <phm_01.pab> -o draw.glb
python -m tools.paa_motion.cli survey <motion directory>
```

`export` writes a self-contained `.glb`: the skeleton as a node hierarchy, the clip as one
animation, and a small cube on each animated joint so viewers render something. Import it
into Blender or any glTF viewer to play the animation back.

The install ships 316,059 `.paa` files. A random sample of 15,400 read straight out of the
`.paz` archives decodes with no failures and no `key_bytes` disagreements, across 1,020,688
bone tracks.

Tests are in `tests/test_paa_motion_format.py`. The synthetic fixtures encode both codecs by
hand and run anywhere; the corpus gate over the extracted vanilla motion tree is behind the
`real_game` marker.

## Writing clips

`tools/paa_motion/encode.py` is the inverse of the reader. `encode_paa(clip)` takes a
`MotionClip` and returns bytes; `rebuild_is_exact(data)` parses and re-encodes one buffer
and says whether the result is identical.

The gate is that a clip written back unedited reproduces its source byte for byte. It
holds on **12,000 clips sampled from the archives across 45 distinct flag words**, and on
all 188 in the extracted tree, with no failures. That is what makes an edit trustworthy:
the only bytes that differ in the output are the ones that were changed.

Three things make the round trip exact rather than close.

- **The value formats are lossless in this direction.** A half read into a Python float
  converts back to the same half, because every half has an exact float value and
  round-to-nearest returns it. The same holds for `f32`. Packed components are
  `signed_byte / 64`, and 64 is a power of two, so the division is exact and multiplying
  back lands on the original integer.
- **`key_bytes` is recomputed, not copied.** The header total is derived from the tracks
  being written, so a clip whose keys changed gets a header that agrees with them.
- **What the reader does not model, it carries.** The bounds frames, the packed codec's
  two lead words, the table filler, the trailing pad and the float-key slot travel on
  `MotionClip.passthrough` and `BoneTrack.translation_pad` and are written back verbatim.

Authoring a clip from nothing is the same call with a hand-built `MotionClip`; leave
`passthrough` at its default and the encoder emits the canonical minimal layout for the
flags that are set. The one thing that cannot be synthesised is a packed clip's
unidentified prelude word, so a packed clip has to start from a parse.

What is *not* checked here is whether the game accepts an edited clip. Byte-exactness
proves the writer is faithful to the format, not that a retimed animation looks right in
the engine — that needs a build and a look.

## Playback in Placement & Animation Studio

`tools/placement_studio/playback.py` poses the rig from a clip, and the Animation tab carries
the transport (load, play/pause, scrub, loop, back-to-bind). The join is one line of intent:
`pose.world_matrices` returns matrices in the row-vector layout the `.pab` already stores, so
swapping each bone's bind matrix for its animated world matrix is enough. Everything
downstream — `BoneHierarchy.place`, attachment markers, the mesh proxy, the gizmo anchor —
follows without knowing animation exists.

That is the point of the integration rather than a convenience: placement is otherwise judged
in the bind pose, which is the single frame where a bad placement is least likely to show. On
a longsword draw, 51 of 52 body sockets leave their bind position (the 52nd is world-space,
with no parent bone).

### The clip browser

`clips.py` indexes every `.paa` in the install — all 316,059 — and the browser sits beside
the chart view in the Animation tab. Reading the package tables takes about 4 seconds and
decompresses nothing, so the index is built once on a worker thread and held in memory;
there is no on-disk cache to go stale against a game patch. Without a game install it falls
back to the pinned baseline rather than showing an empty list.

Filters are rig, kind, and a space-separated name search where every term has to match. The
rig filter defaults to the rig the session actually loaded, since that is what will play.

Two details that matter more than they look:

- **Categories come from filename tokens, not directories.** The layout does not separate
  them — a draw, a sprint and a parry sit side by side in a model's root folder. Order is
  significant: `att_nor_move_run` is an attack that moves, not a run.
- **The list is capped at 800 rows and says what it is hiding.** A silently truncated result
  reads as "that clip is not in the game", which is the one wrong conclusion to invite.

### Skinned bodies and armour

`skinning.py` deforms the character with the pose. Two things make it work, and both are
easy to get wrong:

- **Only the primary influence decodes.** `mesh_parser` documents that a PAC vertex's four
  influence slots are not four bone indices — slot 0 decodes, bytes 21-23 are a packed
  field. Reading all four makes the index space look 253 wide with a weapon socket driving
  a chest vertex. The primary slot alone tops out at 74 and lands on sensible bones.
- **The slot table is derived, not read.** These meshes carry no `.pab` name hashes at all,
  so the mapping is recovered by clustering the vertices a slot drives and matching the
  cluster to the bone it sits on. `dominant_bone_drift` gates it: 0.046 m and 0.059 m on the
  body meshes against 0.46 m for every wrong ordering, and `MAX_DRIFT` refuses the rest.

The skin is therefore **rigid** — one bone per vertex — so joints crease where the game
rounds them. Armour comes from the archives via `armour.py`, since the pinned baseline holds
only the two body meshes.

Clipping is measured on request once a clip is loaded. Against a posed body the solve cannot
be cached, and running it per frame cost 325 ms — which read as the window hanging whenever
playback paused.

### Rules the implementation depends on

- **Pose from bind every time.** `PlacementSession` keeps the bind hierarchy and re-poses from
  it on each seek. Posing from the previous frame would compound the delta every tick.
- **Check bone coverage before playing.** A clip authored for another character parses
  perfectly and then animates nothing, which reads on screen as a broken decoder rather than a
  mismatched rig. `playback.coverage` is what the load path reports.
