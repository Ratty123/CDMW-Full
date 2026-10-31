"""Reads the media table of a Wwise sound bank.

A `.bnk` is a flat sequence of RIFF-style chunks. `DIDX` lists the sounds
embedded in the `DATA` chunk that follows it, and a bank that only carries
events (`HIRC`) has no `DIDX` at all, because its audio streams from separate
`.wem` files. That table is what decides whether a bank can be played, and it is
also names embedded sounds by Wwise source ID rather than a path. Incoming
reference discovery additionally reads supported HIRC Sound source headers in
`archive_reverse_references`; that reader does not reconstruct event graphs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Tuple

BANK_HEADER_CHUNK = b"BKHD"
MEDIA_DIRECTORY_CHUNK = b"DIDX"

_DIRECTORY_RECORD_SIZE = 12
_MAXIMUM_EMBEDDED_MEDIA = 8192
_MAXIMUM_CHUNKS = 128


@dataclass(slots=True, frozen=True)
class WwiseEmbeddedMedia:
    """One embedded sound, as listed by the bank's DIDX table."""

    ordinal: int
    """The one-based position in DIDX, which is also the decoder's subsong number."""

    source_id: int
    """The Wwise source id, which is the name a streamed `.wem` copy would carry."""

    offset: int
    size: int

    @property
    def wem_basename(self) -> str:
        """The file name a loose copy of this sound carries in the archive."""

        return f"{self.source_id}.wem"


@dataclass(slots=True, frozen=True)
class WwiseBankChunk:
    identifier: str
    size: int
    offset: int
    """Where the chunk's payload starts, not where its header does."""


def is_sound_bank(data: bytes) -> bool:
    return len(data) >= 8 and bytes(data[:4]) == BANK_HEADER_CHUNK


def _is_chunk_identifier(identifier: bytes) -> bool:
    return all(0x41 <= byte <= 0x5A or 0x30 <= byte <= 0x39 for byte in identifier)


def read_bank_chunks(data: bytes, *, max_chunks: int = _MAXIMUM_CHUNKS) -> Tuple[Tuple[WwiseBankChunk, ...], int]:
    """Walks the chunk envelope, and reports how far the walk stayed well-formed.

    The walk stops at the first chunk that is truncated or is not a plain
    four-letter identifier, so a damaged bank cannot drive a reader off the end
    of the payload. Chunks are not padded to any alignment; advancing past a
    chunk's own end would silently skip the one that follows it.
    """

    chunks: List[WwiseBankChunk] = []
    offset = 0
    while offset + 8 <= len(data) and len(chunks) < max_chunks:
        identifier = bytes(data[offset : offset + 4])
        if not _is_chunk_identifier(identifier):
            break
        size = struct.unpack_from("<I", data, offset + 4)[0]
        payload_offset = offset + 8
        if size > len(data) - payload_offset:
            break
        chunks.append(
            WwiseBankChunk(
                identifier=identifier.decode("ascii", errors="replace"),
                size=int(size),
                offset=payload_offset,
            )
        )
        offset = payload_offset + int(size)
    return tuple(chunks), offset


def read_embedded_media(data: bytes) -> Tuple[WwiseEmbeddedMedia, ...]:
    """Lists the sounds embedded in the bank, in decoder subsong order.

    Returns nothing when the bank carries no audio of its own, which is the
    normal shape for an event-only bank rather than a defect.
    """

    if not is_sound_bank(data):
        return ()
    chunks, _consumed = read_bank_chunks(data)
    for chunk in chunks:
        if chunk.identifier != MEDIA_DIRECTORY_CHUNK.decode("ascii"):
            continue
        count = min(chunk.size // _DIRECTORY_RECORD_SIZE, _MAXIMUM_EMBEDDED_MEDIA)
        media: List[WwiseEmbeddedMedia] = []
        for record in range(count):
            start = chunk.offset + record * _DIRECTORY_RECORD_SIZE
            source_id, offset, size = struct.unpack_from("<III", data, start)
            media.append(
                WwiseEmbeddedMedia(
                    ordinal=record + 1,
                    source_id=int(source_id),
                    offset=int(offset),
                    size=int(size),
                )
            )
        return tuple(media)
    return ()


def embedded_media_wem_basenames(data: bytes) -> Tuple[str, ...]:
    """The `.wem` names a bank's embedded sounds would carry as loose files.

    A sound stored outside the bank carries its source id as its file name, so
    reading the media table links a bank to the loose sounds that belong with it,
    which nothing written in the bank spells out as a path.
    """

    seen: set[str] = set()
    basenames: List[str] = []
    for media in read_embedded_media(data):
        basename = media.wem_basename
        if basename in seen:
            continue
        seen.add(basename)
        basenames.append(basename)
    return tuple(basenames)


#: HIRC object types as Wwise numbers them for bank versions 128 and later.
HIRC_OBJECT_TYPES = {
    1: "State", 2: "Sound", 3: "Action", 4: "Event", 5: "Random/Sequence container", 6: "Switch container",
    7: "Actor-Mixer", 8: "Audio bus", 9: "Blend container", 10: "Music segment", 11: "Music track",
    12: "Music switch container", 13: "Music playlist container", 14: "Attenuation", 15: "Dialogue event",
    16: "Effect share set", 17: "Custom effect", 18: "Auxiliary bus", 19: "LFO modulator",
    20: "Envelope modulator", 21: "Audio device", 22: "Time modulator",
}
#: How Wwise loads a Sound's media. "In memory" does not mean inside this bank:
#: in game 1.0.0.3446, 95,314 of the 125,904 codec-backed Sounds play a loose
#: numeric `.wem`, 30,490 their own bank's media, 10 another bank's.
HIRC_STREAM_TYPES = {0: "in memory", 1: "prefetched stream", 2: "streamed"}
#: Codec plugin IDs of the sources this game ships; others are shown as hex.
WWISE_CODECS = {0x00010001: "PCM", 0x00020001: "ADPCM", 0x00040001: "Vorbis", 0x00080001: "external source"}


def is_codec_plugin(plugin_id: int) -> bool:
    """Codec plugins decode media; source plugins (type 2) generate sound with none."""

    return plugin_id & 0xF == 1
_SOUND_SOURCE_VERSIONS = range(113, 155)
_MAXIMUM_HIRC_OBJECTS = 200_000


@dataclass(slots=True, frozen=True)
class WwiseHircObject:
    """One HIRC object; Sound objects also carry the media they play."""

    kind: int
    object_id: int
    size: int
    source_id: int = 0
    stream_type: int = -1
    plugin_id: int = 0


def read_hirc_objects(data: bytes) -> Tuple[int, Tuple[WwiseHircObject, ...]]:
    """The bank version and its HIRC objects, read as far as their framing holds.

    Every object is `u8 type, u32 size, u32 id, ...`. A Sound's source header,
    for bank versions 113-154, follows the id as `u32 plugin, u8 stream type,
    u32 source id` (the layout `archive_reverse_references` reads for IDs).
    """

    if not is_sound_bank(data):
        return 0, ()
    chunks, _consumed = read_bank_chunks(data)
    version = 0
    objects: List[WwiseHircObject] = []
    for chunk in chunks:
        start, end = chunk.offset, chunk.offset + chunk.size
        if chunk.identifier == "BKHD" and chunk.size >= 4:
            version = struct.unpack_from("<I", data, start)[0]
        elif chunk.identifier == "HIRC" and chunk.size >= 4:
            count = min(struct.unpack_from("<I", data, start)[0], _MAXIMUM_HIRC_OBJECTS)
            cursor = start + 4
            for _ in range(count):
                if cursor + 9 > end:
                    break
                kind, size = struct.unpack_from("<BI", data, cursor)
                cursor += 5
                if size < 4 or cursor + size > end:
                    break
                object_id = struct.unpack_from("<I", data, cursor)[0]
                minimum = 22 if version > 150 else 18
                if kind == 2 and version in _SOUND_SOURCE_VERSIONS and size >= minimum:
                    plugin, stream_type, source_id = struct.unpack_from("<IBI", data, cursor + 4)
                    objects.append(WwiseHircObject(kind, object_id, size, source_id, stream_type, plugin))
                else:
                    objects.append(WwiseHircObject(kind, object_id, size))
                cursor += size
    return version, tuple(objects)


__all__ = [
    "BANK_HEADER_CHUNK",
    "HIRC_OBJECT_TYPES",
    "HIRC_STREAM_TYPES",
    "MEDIA_DIRECTORY_CHUNK",
    "WWISE_CODECS",
    "WwiseBankChunk",
    "WwiseEmbeddedMedia",
    "WwiseHircObject",
    "embedded_media_wem_basenames",
    "is_codec_plugin",
    "is_sound_bank",
    "read_bank_chunks",
    "read_embedded_media",
    "read_hirc_objects",
]
