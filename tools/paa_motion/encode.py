"""Writer for the Crimson Desert `.paa` motion clip format.

This is the exact inverse of `format.parse_paa`. Re-encoding a parsed clip without
editing it reproduces the source bytes, which is what makes an edited clip
trustworthy: the only differences in the output are the ones that were asked for.
`tests/test_paa_motion_encode.py` asserts that over the shipped corpus.

Two things make the round trip exact rather than approximate.

The value formats are all lossless in this direction. A half read into a Python float
converts back to the same half because every half has an exact float value and
round-to-nearest returns it; the same holds for float32. Packed components are stored
as `signed_byte / 64`, and 64 is a power of two, so the division is exact and
multiplying back lands on the original integer.

The spans the reader does not interpret -- the bounds frames, the packed codec's
leading word, the table filler, the trailing pad -- travel on `MotionClip.passthrough`
and are written back verbatim. Nothing is invented and nothing is dropped.

Authoring a clip from scratch is the same call with a hand-built `MotionClip`. Leave
`passthrough` at its default and the encoder emits the canonical minimal layout for
the flags that are set; `canonical_flags` works out which those are.
"""

from __future__ import annotations

import struct
from typing import Sequence

from .format import (
    _COMPONENTS,
    _FLOAT,
    _HALF,
    _HEADER_SIZE,
    _HEADER_TAIL,
    FLAG_BOUNDS,
    FLAG_BOUNDS_SECOND,
    FLAG_PACKED,
    FLAG_SKELETON_PATH,
    FLAG_TAG,
    FLAG_UNIT_SCALE,
    FLAG_WIDE_TABLE,
    FLAG_WORD_TABLE,
    PAA_VERSION,
    PACKED_UNIT,
    PAR_MAGIC,
    BoneTrack,
    Key,
    MotionClip,
    PaaFormatError,
)


class PaaEncodeError(ValueError):
    """Raised when a clip cannot be written as a valid `.paa`."""


def _check_keys(keys: Sequence[Key], components: int, what: str) -> None:
    previous = -1
    for frame, values in keys:
        if frame <= previous:
            raise PaaEncodeError(f"{what} key frames must ascend, got {frame} after {previous}")
        previous = frame
        if len(values) != components:
            raise PaaEncodeError(f"{what} key at frame {frame} needs {components} components, got {len(values)}")


def _encode_channel(
    keys: Sequence[Key], components: int, full_precision: bool, slot: bytes = b"\x00\x00"
) -> bytes:
    if len(keys) > 0xFFFF:
        raise PaaEncodeError(f"a channel holds at most 65,535 keys, got {len(keys):,}")
    out = bytearray(struct.pack("<H", len(keys)))
    if not keys:
        return bytes(out)
    _stride, fmt, pad = (_FLOAT if full_precision else _HALF)[components]
    filler = (slot or b"\x00\x00")[:pad].ljust(pad, b"\x00")
    for frame, values in keys:
        if not 0 <= frame <= 0xFFFF:
            raise PaaEncodeError(f"frame {frame} does not fit a u16")
        out += struct.pack("<H", frame)
        out += filler
        out += struct.pack(fmt, *values)
    return bytes(out)


def _encode_packed_channel(keys: Sequence[Key], components: int) -> bytes:
    if len(keys) > 0xFF:
        raise PaaEncodeError(f"a packed channel holds at most 255 keys, got {len(keys)}")
    out = bytearray(bytes([len(keys)]))
    for frame, values in keys:
        if not 0 <= frame <= 0xFF:
            raise PaaEncodeError(f"packed frame {frame} does not fit a u8")
        out.append(frame)
        for value in values:
            quantised = round(value * PACKED_UNIT)
            if not -128 <= quantised <= 127:
                raise PaaEncodeError(
                    f"packed component {value} quantises to {quantised}, outside a signed byte"
                )
            out += struct.pack("<b", quantised)
    return bytes(out)


def encode_track(track: BoneTrack) -> bytes:
    """One track record: the bone-name hash then its three channels."""

    if not 0 <= track.name_hash <= 0xFFFFFFFF:
        raise PaaEncodeError(f"bone name hash {track.name_hash} does not fit a u32")
    out = bytearray(struct.pack("<I", track.name_hash))
    for name, components in _COMPONENTS.items():
        keys: Sequence[Key] = getattr(track, name)
        _check_keys(keys, components, f"{name} on 0x{track.name_hash:08X}")
        if track.packed:
            out += _encode_packed_channel(keys, components)
            continue
        full = track.wide_translation and name == "translation"
        out += _encode_channel(keys, components, full, track.translation_pad)
    return bytes(out)


def canonical_flags(clip: MotionClip) -> int:
    """The flags a hand-built clip implies, for checking one that was set by hand.

    The presence bits and the fields have to agree or the file is unreadable: a tag bit
    with no tag shifts everything after it. This does not touch bits whose payload the
    reader carries rather than models.
    """

    flags = clip.flags
    for bit, present in (
        (FLAG_TAG, bool(clip.tag)),
        (FLAG_UNIT_SCALE, bool(clip.unit_scale)),
        (FLAG_SKELETON_PATH, bool(clip.skeleton_path)),
    ):
        flags = (flags | bit) if present else (flags & ~bit)
    return flags & 0xFFFFFFFF


def _prelude_bytes(clip: MotionClip) -> bytes:
    """The flag-driven fields between the flags word and the track table."""

    carried = clip.passthrough
    flags = clip.flags
    out = bytearray()
    if flags & FLAG_PACKED:
        # Unidentified, and never synthesised: a packed clip has to come from a parse.
        out += carried.packed_word or b"\x00\x00\x00\x00"
    if flags & FLAG_TAG:
        # The stored blob counts its own trailing NUL; the decoded string does not.
        blob = carried.tag or (clip.tag.encode("utf-8") + b"\x00")
        if len(blob) > 0xFFFF:
            raise PaaEncodeError(f"tag blob is {len(blob):,} bytes, past the u16 length")
        out += struct.pack("<H", len(blob)) + blob
    elif flags & FLAG_WORD_TABLE:
        out += carried.word_table or b"\x00\x00"
    if flags & FLAG_BOUNDS:
        span = 40 * (2 if flags & FLAG_BOUNDS_SECOND else 1)
        bounds = carried.bounds or bytes(span)
        if len(bounds) != span:
            raise PaaEncodeError(
                f"bounds span must be {span} bytes for these flags, got {len(bounds)}"
            )
        out += bounds
    if flags & FLAG_UNIT_SCALE:
        out += struct.pack("<f", clip.unit_scale)
    if flags & FLAG_SKELETON_PATH:
        if carried.skeleton_path:
            out += carried.skeleton_path
        else:
            path = clip.skeleton_path.encode("ascii")
            if len(path) > 0xFF:
                raise PaaEncodeError(f"skeleton path is {len(path)} bytes, past the u8 length")
            out += bytes([len(path)]) + path
    out += struct.pack("<f", clip.duration)
    out += carried.prelude_gap
    return bytes(out)


def _table_bytes(clip: MotionClip, key_bytes: int) -> bytes:
    """The track table header: bone counts, flag-driven filler, and the key-byte total."""

    packed = bool(clip.flags & FLAG_PACKED)
    wide = bool(clip.flags & FLAG_WIDE_TABLE)
    expected_filler = 4 if packed else (2 if wide else 0)
    filler = clip.passthrough.table_filler or bytes(expected_filler)
    if len(filler) != expected_filler:
        raise PaaEncodeError(
            f"table filler must be {expected_filler} bytes for these flags, got {len(filler)}"
        )
    out = bytearray()
    if packed:
        out += _packed_lead(clip)
    out += struct.pack("<HH", clip.skeletal_bone_count, clip.root_bone_count)
    out += filler
    out += struct.pack("<I", key_bytes)
    return bytes(out)


def _packed_lead(clip: MotionClip) -> bytes:
    """The u32 that opens a packed clip's table. Five in every shipped packed clip."""

    return clip.passthrough.table_lead or struct.pack("<I", 5)


def encode_paa(clip: MotionClip) -> bytes:
    """Serialise a `MotionClip` to `.paa` bytes.

    Re-encoding an unedited parse reproduces the source file byte for byte.
    """

    if clip.version != PAA_VERSION:
        raise PaaEncodeError(
            f"only .paa {PAA_VERSION[0]}.{PAA_VERSION[1]} is written, not "
            f"{clip.version[0]}.{clip.version[1]}"
        )
    total = clip.skeletal_bone_count + clip.root_bone_count
    if total != len(clip.tracks):
        raise PaaEncodeError(
            f"bone counts say {total} tracks but the clip carries {len(clip.tracks)}"
        )
    for bit, count in ((0xFFFF, clip.skeletal_bone_count), (0xFFFF, clip.root_bone_count)):
        if not 0 <= count <= bit:
            raise PaaEncodeError(f"bone count {count} does not fit a u16")

    body = bytearray()
    for index, track in enumerate(clip.tracks):
        is_root = index >= clip.skeletal_bone_count
        if track.root_motion != is_root:
            raise PaaEncodeError(
                f"track {index} is marked root_motion={track.root_motion} but the bone counts "
                f"put it in the {'root' if is_root else 'skeletal'} block"
            )
        body += encode_track(track)

    from .format import key_byte_total

    key_bytes = key_byte_total(clip)

    out = bytearray()
    out += PAR_MAGIC
    out += bytes(clip.version)
    out += _HEADER_TAIL
    assert len(out) == _HEADER_SIZE
    out += struct.pack("<I", clip.flags & 0xFFFFFFFF)
    out += _prelude_bytes(clip)
    out += _table_bytes(clip, key_bytes)
    out += body
    out += clip.passthrough.trailing
    return bytes(out)


def rebuild_is_exact(data: bytes, *, name: str = "") -> bool:
    """Parse then re-encode, and say whether the bytes came back identical.

    The gate the corpus test runs, exposed for callers that want to check one file
    before trusting an edit to it.
    """

    from .format import parse_paa

    try:
        clip = parse_paa(data, name=name)
    except PaaFormatError:
        return False
    return encode_paa(clip) == data
