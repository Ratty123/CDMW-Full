"""Reader for the Crimson Desert `.paa` motion clip format.

`.paa` is a `PAR ` container at version 2.3 — the same container family as the `.pab`
skeleton (version 1.5). A clip is a flat list of per-bone track records; there is no
name table, because every record is keyed by the same 32-bit bone-name hash the `.pab`
stores next to each bone name.

    'PAR '  u8 major  u8 minor  b'\\x00\\x01\\x02...\\x09'      16-byte container header
    u32 flags
    if flags & PACKED:   u32 unidentified
    if flags & TAG:      u16 byte_len; utf8 tag_blob            ';'-separated, NUL-terminated
    if flags & FRAMES:   2 x { f32 scale[3]; f32 rot[4]; f32 pos[3] }
    if flags & UNIT:     f32 unit_scale                          ~0.9722, the rig hip height
    if flags & SKELETON: u8 len; ascii skeleton_path
    f32 duration                                                 seconds; == last_frame / 30
    u16 skeletal_bones  u16 root_bones  ...filler...  u32 key_bytes
    (skeletal_bones + root_bones) x:
        u32 bone_name_hash
        u16 n; n x key   scale        (3 components)
        u16 n; n x key   rotation     (4 components, unit quaternion xyzw)
        u16 n; n x key   translation  (3 components)

Every key is `u16 frame` followed by the components, with the natural C struct padding for
the component type: half keys are 2-byte aligned and pack tight, float keys are 4-byte
aligned and carry two bytes of padding after the frame index. The first `skeletal_bones`
records are half precision throughout; the trailing `root_bones` records — `Bip01`,
`B_MoveControl_01` and the `B_TL_Position_*` locators — store *translation* as float32,
because they carry root motion and a half would quantise a 10 m run to visible steps.

Track values are deltas from the skeleton's bind pose, expressed in the bone's own local
axes, not absolute local transforms: an unrotated bone keys the identity quaternion even
where its bind rotation is not identity. `pose.py` is what composes them.

Frames are integers at a fixed 30 fps and are sparse — a keyframe reducer drops frames a
linear interpolation would have reproduced, so the gaps are meaningful.

Roughly half the shipped clips set `FLAG_PACKED` and quantise their skeletal records to
signed bytes with `u8` frame indices; `_read_packed_channel` covers that. Their trailing
root records stay in the standard half encoding, so root motion survives LOD intact.

`key_bytes` in the header is the reader's integrity gate: it is recomputed from the parsed
tracks, and a disagreement fails the parse rather than returning a wrong shape that happened
to consume the buffer.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence, Tuple

PAR_MAGIC = b"PAR "
PAA_VERSION = (2, 3)

#: The container header is followed by ten bytes that count 0..9 in every shipped file.
_HEADER_TAIL = bytes(range(10))
_HEADER_SIZE = 0x10

#: Clip frame indices are integers on this timeline. `duration * FPS` is the last frame.
FPS = 30.0

# Prelude presence bits in the u32 at 0x10.
FLAG_BOUNDS = 0x00000001  #: one 40-byte f32 scale/rotation/translation frame
FLAG_UNIT_SCALE = 0x00000002  #: f32 rig unit scale
#: Adds a second 40-byte frame to the `FLAG_BOUNDS` block. Clips that clear it carry
#: one frame, not two: 18 of the 54 `aim_add` bow clips ship as flags 0x1 or 0x191 and
#: stop after 40 bytes. Reading a fixed 80 there put `duration` 40 bytes late, which
#: only escaped notice because the track scan recovered the tracks anyway.
#:
#: The bit is attributed to 0x4 rather than 0x2 because 0x2 is independently pinned as
#: the unit scale -- it reads ~0.97222, the bind-pose hip height, and mis-attributing
#: it would make that read garbage. The two are set together in every shipped clip, so
#: this is the one reading consistent with both, not two independent observations.
FLAG_BOUNDS_SECOND = 0x00000004
#: Selects the byte-quantised track codec used by the `*_lod.paa` distance copies. It also
#: adds a u32 at the head of the prelude and widens the track table.
FLAG_PACKED = 0x00000010
FLAG_SKELETON_PATH = 0x00000040  #: u8-length-prefixed skeleton resource path
#: Widens the track table by one u16 between the bone counts and `key_bytes`. Zero in every
#: shipped clip, and it does not change how the tracks themselves are encoded.
FLAG_WIDE_TABLE = 0x00000100
#: `u16 count` then that many *bytes* — the ';'-separated UTF-8 tag blob.
FLAG_TAG = 0x40000000
#: `u16 count` then that many *u16 entries*. Only meaningful on its own: shipped clips
#: nearly always set both top bits, and there the field is the byte-wise tag blob. A
#: handful set bit 31 alone, and reading those as bytes lands mid-prelude and yields a
#: garbage duration.
FLAG_WORD_TABLE = 0x80000000

_COMPONENTS = {"scale": 3, "rotation": 4, "translation": 3}

# (stride, struct format, bytes of padding after the frame index) per component count.
_HALF = {3: (8, "<3e", 0), 4: (10, "<4e", 0)}
_FLOAT = {3: (16, "<3f", 2), 4: (20, "<4f", 2)}

#: Packed keys store each component as a signed byte in units of 1/64. Proven for rotation:
#: 19,650 keys sampled across the install all decode to unit quaternions to within 0.011.
#: Scale and translation are assumed to share the fixed-point format. Packed translation is
#: used almost only by IK helper bones, whose values saturate at +-127, so the corpus offers
#: no way to confirm their scale — treat packed translation as indicative, not exact.
PACKED_UNIT = 64.0

Key = Tuple[int, Tuple[float, ...]]


class PaaFormatError(ValueError):
    """Raised when a buffer is not a `.paa` clip this reader understands."""


@dataclass(frozen=True)
class Passthrough:
    """Byte spans the reader locates but does not interpret.

    Playback needs none of these. `encode.py` needs all of them: a clip that only
    re-emits the fields we understand would drop the bounds frames and the packed
    codec's leading word, so a no-edit rebuild could never be byte-identical and the
    round-trip gate would have nothing to assert. Keeping the spans verbatim is what
    lets an authored edit ride on top of a file we do not fully model.
    """

    #: The u32 at the head of the prelude, present only under `FLAG_PACKED`.
    packed_word: bytes = b""
    #: The tag blob exactly as stored, including its trailing NUL.
    tag: bytes = b""
    #: `FLAG_WORD_TABLE` without `FLAG_TAG`: the count and its u16 entries.
    word_table: bytes = b""
    #: The two 40-byte scale/rotation/translation frames under `FLAG_BOUNDS`.
    bounds: bytes = b""
    #: The skeleton resource path with its u8 length, kept because the reader decodes
    #: it with `errors="replace"` and that is not reversible.
    skeleton_path: bytes = b""
    #: Anything between the end of the modelled prelude and the track table. Non-empty
    #: only when `_scan_for_tracks` had to find the table, which means a prelude bit we
    #: do not model added bytes.
    prelude_gap: bytes = b""
    #: The u32 that opens a packed clip's track table, distinct from `packed_word`
    #: above: that one sits in the prelude, this one at the head of the table. Five in
    #: every shipped packed clip.
    table_lead: bytes = b""
    #: Filler between the bone counts and `key_bytes`, whose width the flags decide.
    table_filler: bytes = b""
    #: The 0-3 bytes of even-size padding after the last track.
    trailing: bytes = b""


@dataclass(frozen=True)
class BoneTrack:
    """Every key one bone contributes, keyed by the hash the `.pab` records for its name."""

    name_hash: int
    scale: Tuple[Key, ...] = ()
    rotation: Tuple[Key, ...] = ()
    translation: Tuple[Key, ...] = ()
    #: True for the trailing root-motion records, whose translation is float32.
    root_motion: bool = False
    #: True when the values came from the byte-quantised LOD codec.
    packed: bool = False
    #: True when translation was stored as float32 rather than half.
    wide_translation: bool = False
    #: The two bytes the exporter leaves between the frame index and a float32
    #: translation key. They are not padding it zeroed: across the shipped corpus they
    #: are constant within a track, differ between tracks, never match any 16 bits of
    #: the bone hash, and the same bone carries different values in different files.
    #: That is an uninitialised stack slot, so there is nothing to derive -- it is kept
    #: per track only so a rebuild can put the same bytes back.
    translation_pad: bytes = b"\x00\x00"

    @property
    def animated(self) -> bool:
        return bool(self.scale or self.rotation or self.translation)

    @property
    def last_frame(self) -> int:
        frames = [keys[-1][0] for keys in (self.scale, self.rotation, self.translation) if keys]
        return max(frames) if frames else 0


@dataclass(frozen=True)
class MotionClip:
    """A parsed `.paa`."""

    version: Tuple[int, int]
    flags: int
    tag: str
    unit_scale: float
    skeleton_path: str
    duration: float
    key_bytes: int
    skeletal_bone_count: int
    root_bone_count: int
    tracks: Tuple[BoneTrack, ...]
    #: Spans carried verbatim so `encode.py` can rebuild the file exactly. A clip built
    #: by hand leaves this at its default and encodes to the canonical minimal layout.
    passthrough: Passthrough = Passthrough()

    @property
    def fps(self) -> float:
        return FPS

    @property
    def last_frame(self) -> int:
        return max((track.last_frame for track in self.tracks), default=0)

    @property
    def frame_count(self) -> int:
        return self.last_frame + 1

    @property
    def tags(self) -> Tuple[str, ...]:
        return tuple(part for part in self.tag.split(";") if part)

    def track_for(self, name_hash: int) -> BoneTrack | None:
        for track in self.tracks:
            if track.name_hash == name_hash:
                return track
        return None


def _read_channel(
    data: bytes, pos: int, components: int, full_precision: bool
) -> tuple[Tuple[Key, ...], int, bytes]:
    """Returns the keys, the new position, and the bytes in the float alignment slot."""

    if pos + 2 > len(data):
        raise PaaFormatError(f"channel count runs past the end of the buffer at 0x{pos:X}")
    count = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    if count == 0:
        return (), pos, b""
    stride, fmt, pad = (_FLOAT if full_precision else _HALF)[components]
    end = pos + count * stride
    if end > len(data):
        raise PaaFormatError(f"{count} keys at 0x{pos:X} run past the end of the buffer")
    keys: list[Key] = []
    previous = -1
    for index in range(count):
        offset = pos + index * stride
        frame = struct.unpack_from("<H", data, offset)[0]
        if frame <= previous:
            raise PaaFormatError(f"key frames are not ascending at 0x{offset:X}")
        previous = frame
        keys.append((frame, struct.unpack_from(fmt, data, offset + 2 + pad)))
    # Constant across a track's keys in every shipped clip, so the first one stands in.
    slot = data[pos + 2: pos + 2 + pad] if pad else b""
    return tuple(keys), end, slot


def _read_packed_channel(data: bytes, pos: int, components: int) -> tuple[Tuple[Key, ...], int]:
    """`u8 count`, then that many `u8 frame` + one signed byte per component."""

    if pos >= len(data):
        raise PaaFormatError(f"packed channel count runs past the end at 0x{pos:X}")
    count = data[pos]
    pos += 1
    stride = 1 + components
    if pos + count * stride > len(data):
        raise PaaFormatError(f"{count} packed keys at 0x{pos:X} run past the end")
    keys: list[Key] = []
    previous = -1
    for index in range(count):
        offset = pos + index * stride
        frame = data[offset]
        if frame <= previous and keys:
            raise PaaFormatError(f"packed key frames are not ascending at 0x{offset:X}")
        previous = frame
        values = struct.unpack_from(f"<{components}b", data, offset + 1)
        keys.append((frame, tuple(value / PACKED_UNIT for value in values)))
    return tuple(keys), pos + count * stride


def _read_track(
    data: bytes, pos: int, root_motion: bool, packed: bool = False, root_full: bool = True
) -> tuple[BoneTrack, int]:
    if pos + 4 > len(data):
        raise PaaFormatError(f"track header runs past the end of the buffer at 0x{pos:X}")
    name_hash = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    channels: dict[str, Tuple[Key, ...]] = {}
    # Only the trailing root records widen, and only their translation.
    wide = root_full and root_motion and not packed
    slot = b"\x00\x00"
    for name, components in _COMPONENTS.items():
        if packed:
            channels[name], pos = _read_packed_channel(data, pos, components)
            continue
        channels[name], pos, found = _read_channel(
            data, pos, components, wide and name == "translation"
        )
        if found:
            slot = found
    track = BoneTrack(
        name_hash=name_hash,
        root_motion=root_motion,
        packed=packed,
        wide_translation=wide,
        translation_pad=slot,
        **channels,
    )
    return track, pos


def _read_prelude(data: bytes, flags: int) -> tuple[dict, int]:
    """Read the flag-driven fields between the flags word and the track table."""

    pos = _HEADER_SIZE + 4
    fields: dict = {"tag": "", "unit_scale": 0.0, "skeleton_path": ""}
    raw: dict = {}
    if flags & FLAG_PACKED:
        raw["packed_word"] = data[pos: pos + 4]  # unidentified u32, packed codec only
        pos += 4
    if flags & FLAG_TAG:
        length = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        blob = data[pos: pos + length]
        if len(blob) != length:
            raise PaaFormatError("tag blob is truncated")
        fields["tag"] = blob.rstrip(b"\x00").decode("utf-8", "replace")
        raw["tag"] = blob
        pos += length
    elif flags & FLAG_WORD_TABLE:
        count = struct.unpack_from("<H", data, pos)[0]
        raw["word_table"] = data[pos: pos + 2 + 2 * count]
        pos += 2 + 2 * count
    if flags & FLAG_BOUNDS:
        span = 40 * (2 if flags & FLAG_BOUNDS_SECOND else 1)
        raw["bounds"] = data[pos: pos + span]  # unused for playback
        pos += span
    if flags & FLAG_UNIT_SCALE:
        fields["unit_scale"] = struct.unpack_from("<f", data, pos)[0]
        pos += 4
    if flags & FLAG_SKELETON_PATH:
        length = data[pos]
        raw["skeleton_path"] = data[pos: pos + 1 + length]
        pos += 1
        fields["skeleton_path"] = data[pos: pos + length].decode("ascii", "replace")
        pos += length
    if pos + 4 > len(data):
        raise PaaFormatError("prelude runs past the end of the buffer")
    fields["duration"] = struct.unpack_from("<f", data, pos)[0]
    fields["passthrough"] = raw
    return fields, pos + 4


def _read_tracks(
    data: bytes, pos: int, *, wide: bool = False, packed: bool = False, root_full: bool = True
) -> tuple[MotionClip, int] | None:
    """Read the track table at `pos`, or return None if it does not describe this buffer.

    The table always ends with `u32 key_bytes` and always starts with the two bone counts;
    what varies is the filler between them. The packed codec adds a leading u32 as well, so
    its counts sit four bytes in.
    """

    width = 16 if packed else (10 if wide else 8)
    lead = 4 if packed else 0
    if pos + width > len(data):
        return None
    skeletal, roots = struct.unpack_from("<HH", data, pos + lead)
    key_bytes = struct.unpack_from("<I", data, pos + width - 4)[0]
    lead_raw = data[pos: pos + lead]
    filler = data[pos + lead + 4: pos + width - 4]
    total = skeletal + roots
    # Zero is legitimate: the autofacial clips ship as a header and nothing else.
    if not (0 <= total <= 4096):
        return None
    pos += width
    tracks: list[BoneTrack] = []
    try:
        for index in range(total):
            # Packed clips quantise the skeletal records but leave the trailing root
            # records in the standard half-precision encoding.
            is_root = index >= skeletal
            track, pos = _read_track(
                data, pos,
                root_motion=is_root,
                packed=packed and not is_root,
                root_full=root_full,
            )
            tracks.append(track)
    except PaaFormatError:
        return None
    # A correct read lands on the end of the buffer; the writer pads to an even size.
    if not 0 <= len(data) - pos <= 3:
        return None
    # The header's own key-byte total is an independent check on the whole walk. Without it
    # an ambiguous reading can consume the buffer exactly and still be the wrong shape.
    if _key_bytes_of(tracks) != key_bytes:
        return None
    return tracks, (skeletal, roots, key_bytes), (lead_raw, filler, data[pos:])


def parse_paa(data: bytes, *, name: str = "") -> MotionClip:
    """Parse a `.paa` motion clip, standard or packed.

    Raises `PaaFormatError` when no track table reads the buffer consistently. The header's
    own `key_bytes` total has to agree, so an ambiguous walk fails loudly instead of
    returning a plausible-looking wrong answer.
    """

    where = f" ({name})" if name else ""
    if len(data) < _HEADER_SIZE + 8 or data[:4] != PAR_MAGIC:
        raise PaaFormatError(f"not a PAR container{where}")
    version = (data[4], data[5])
    if data[6:_HEADER_SIZE] != _HEADER_TAIL:
        raise PaaFormatError(f"unexpected container header{where}")
    if version != PAA_VERSION:
        raise PaaFormatError(f"unsupported .paa version {version[0]}.{version[1]}{where}")

    flags = struct.unpack_from("<I", data, _HEADER_SIZE)[0]
    prelude, table = _read_prelude(data, flags)
    wide = bool(flags & FLAG_WIDE_TABLE)
    packed = bool(flags & FLAG_PACKED)
    # Standard clips widen root translation to float32; packed clips leave it half. Try the
    # expected shape first and fall back, so a mixed file still lands rather than mis-decodes.
    read = None
    table_at = table
    for root_full in (not packed, packed):
        read = _read_tracks(data, table, wide=wide, packed=packed, root_full=root_full)
        if read is not None:
            break
    if read is None:
        # An unrecognised prelude bit shifts the table; find it rather than guess wrong.
        read, table_at = _scan_for_tracks(data, table, wide, packed)
    if read is None:
        raise PaaFormatError(f"no track table decodes this buffer{where}")
    tracks, (skeletal, roots, key_bytes), (lead_raw, filler, trailing) = read
    return MotionClip(
        version=version,
        flags=flags,
        tag=prelude["tag"],
        unit_scale=prelude["unit_scale"],
        skeleton_path=prelude["skeleton_path"],
        duration=prelude["duration"],
        key_bytes=key_bytes,
        skeletal_bone_count=skeletal,
        root_bone_count=roots,
        tracks=tuple(tracks),
        passthrough=Passthrough(
            prelude_gap=data[table:table_at],
            table_lead=lead_raw,
            table_filler=filler,
            trailing=trailing,
            **prelude["passthrough"],
        ),
    )


def _scan_for_tracks(data: bytes, expected: int, wide: bool, packed: bool):
    """Fallback for prelude layouts this reader does not model bit-for-bit.

    Returns the read and where the table turned out to start, so the bytes the modelled
    prelude did not account for can be carried through a rebuild rather than dropped.
    """

    limit = min(len(data), max(expected, _HEADER_SIZE) + 0x200)
    for pos in range(_HEADER_SIZE + 4, limit):
        for root_full in (not packed, packed):
            read = _read_tracks(data, pos, wide=wide, packed=packed, root_full=root_full)
            if read is not None:
                return read, pos
    return None, expected


def key_byte_total(clip: MotionClip) -> int:
    """Recompute the header's `key_bytes` from the tracks, for round-trip checking."""

    return _key_bytes_of(clip.tracks)


def _key_bytes_of(tracks: Sequence[BoneTrack]) -> int:
    total = 0
    for track in tracks:
        for name, components in _COMPONENTS.items():
            keys: Sequence[Key] = getattr(track, name)
            if not keys:
                continue
            if track.packed:
                stride = 1 + components
            else:
                full = track.wide_translation and name == "translation"
                stride = (_FLOAT if full else _HALF)[components][0]
            total += len(keys) * stride
    return total
