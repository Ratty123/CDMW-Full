"""Reads the media table of a Wwise sound bank.

A `.bnk` is a flat sequence of RIFF-style chunks. `DIDX` lists the sounds
embedded in the `DATA` chunk that follows it, and a bank that only carries
events (`HIRC`) has no `DIDX` at all, because its audio streams from separate
`.wem` files. That table is what decides whether a bank can be played, and it is
also the only place a bank names the sounds that belong with it: a bank names
them by Wwise source id, so nothing inside one reads as a path.
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


__all__ = [
    "BANK_HEADER_CHUNK",
    "MEDIA_DIRECTORY_CHUNK",
    "WwiseBankChunk",
    "WwiseEmbeddedMedia",
    "embedded_media_wem_basenames",
    "is_sound_bank",
    "read_bank_chunks",
    "read_embedded_media",
]
