"""Build a whole archive directory from scratch: `0.pamt` + `0.paz` holding only the files
a mod changes.

The patcher writes into the shipped archives. That works, but a single new item touches
fifteen payload files across 0.62 GB, every one of them has to be backed up and
re-checksummed, and two mods that touch the same table have to be applied in order and
undone in order.

The game offers a cheaper route. `meta/0.papgt` lists the archive directories it mounts and
it takes the first directory that holds a path, so a directory listed ahead of the shipped
ones overrides them. A mod is then a few megabytes of its own beside a 132 GB install: the
files it changed, in its own directory, with the shipped archives untouched. That is what
this module builds; `cdmw.core.papgt_format` mounts it.

Both name blocks in a PAMT are prefix tries -- `u32 parent offset`, `u8 length`, bytes, and
a string is the walk from a record to the root -- and the shipped tables share prefixes
between siblings to save space. A fresh table does not have to: a record whose parent is
`0xFFFFFFFF` carries its whole string, which reads back the same way.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.archive_format import calculate_pa_checksum, hashlittle

__all__ = [
    "OverlayArchive",
    "OverlayFile",
    "PAZ_ALIGNMENT",
    "build_overlay_archive",
]

#: Payloads start on this boundary inside the PAZ, as they do in the shipped archives.
PAZ_ALIGNMENT = 16
#: The third u32 of a PAMT header; the same value on all 33 shipped tables.
PAMT_CONSTANT = 0x610E0232
#: Folder names are hashed with the seed the rest of the archive format uses.
FOLDER_HASH_SEED = 0xC5EDE

_NO_PARENT = 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class OverlayFile:
    """One file to put in the overlay: where the game looks for it and what it holds.

    `payload` is the bytes the game should read (already compressed and encrypted the way
    `flags` says, exactly as the archive stores them), `orig_size` the size it decompresses
    to. A caller holding a decompressed table asks the archive writer it already uses to
    process the payload, so this module never has to know about LZ4 or the DDS split.
    """

    path: str
    payload: bytes
    orig_size: int
    flags: int = 0


@dataclass(frozen=True, slots=True)
class OverlayArchive:
    """The two files of a built directory, and what went into them."""

    pamt_bytes: bytes
    paz_bytes: bytes
    pamt_checksum: int
    entries: Tuple[Tuple[str, int, int, int], ...] = field(default=())

    @property
    def file_count(self) -> int:
        return len(self.entries)


def _normalize(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").strip()


def _trie_block(strings: Sequence[str]) -> Tuple[bytes, Dict[str, int]]:
    """A name block holding each string as one flat record, and where each one starts."""

    block = bytearray()
    offsets: Dict[str, int] = {}
    for text in strings:
        if text in offsets:
            continue
        encoded = text.encode("utf-8")
        if len(encoded) > 255:
            raise ValueError(f"{text!r} is longer than a name record can hold (255 bytes)")
        offsets[text] = len(block)
        block += struct.pack("<IB", _NO_PARENT, len(encoded)) + encoded
    return bytes(block), offsets


def build_overlay_archive(
    files: Sequence[OverlayFile],
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> OverlayArchive:
    """`files` as one archive directory: the PAMT and the PAZ, ready to write side by side.

    Folders are written in path order and their file ranges tile the file table, which is
    what the reader checks; the files inside a folder are in byte order, as the shipped
    tables have them.
    """

    if not files:
        raise ValueError("an overlay needs at least one file")
    by_folder: Dict[str, List[OverlayFile]] = {}
    for item in files:
        clean = _normalize(item.path)
        if not clean:
            raise ValueError("an overlay file needs a path")
        folder, _sep, name = clean.rpartition("/")
        if not name:
            raise ValueError(f"{item.path!r} names no file")
        by_folder.setdefault(folder, []).append(OverlayFile(path=clean, payload=item.payload, orig_size=item.orig_size, flags=item.flags))

    paz = bytearray()
    folder_records: List[Tuple[int, str, int, int]] = []
    file_records: List[Tuple[str, int, int, int, int, int]] = []
    entries: List[Tuple[str, int, int, int]] = []
    for folder in sorted(by_folder):
        items = sorted(by_folder[folder], key=lambda item: item.path.rpartition("/")[2].encode("utf-8"))
        start = len(file_records)
        for item in items:
            name = item.path.rpartition("/")[2]
            if len(paz) % PAZ_ALIGNMENT:
                paz += b"\x00" * (PAZ_ALIGNMENT - (len(paz) % PAZ_ALIGNMENT))
            offset = len(paz)
            paz += item.payload
            file_records.append((name, offset, len(item.payload), int(item.orig_size), 0, int(item.flags)))
            entries.append((item.path, offset, len(item.payload), int(item.orig_size)))
        folder_records.append((hashlittle(folder.encode("utf-8"), FOLDER_HASH_SEED), folder, start, len(file_records) - start))

    # every shipped .paz is a whole number of sixteen-byte blocks: the payloads are aligned
    # to that between themselves and the file is padded out to it at the end. The entries
    # name their own sizes, so the tail is never read; it is there to look like what the
    # game ships rather than like something else.
    if len(paz) % PAZ_ALIGNMENT:
        paz += bytes(PAZ_ALIGNMENT - (len(paz) % PAZ_ALIGNMENT))

    dir_block, dir_offsets = _trie_block([folder for _hash, folder, _start, _count in folder_records if folder])
    name_block, name_offsets = _trie_block([name for name, *_rest in file_records])

    out = bytearray()
    out += struct.pack("<III", 0, 1, PAMT_CONSTANT)
    out += struct.pack("<III", 0, calculate_pa_checksum(bytes(paz)), len(paz))
    out += struct.pack("<I", len(dir_block)) + dir_block
    out += struct.pack("<I", len(name_block)) + name_block
    out += struct.pack("<I", len(folder_records))
    for folder_hash, folder, start, count in folder_records:
        out += struct.pack("<IIII", folder_hash, dir_offsets[folder] if folder else _NO_PARENT, start, count)
    out += struct.pack("<I", len(file_records))
    for name, offset, comp_size, orig_size, paz_index, flags in file_records:
        out += struct.pack("<IIIIHH", name_offsets[name], offset, comp_size, orig_size, paz_index, flags)
    checksum = calculate_pa_checksum(bytes(out[12:]))
    struct.pack_into("<I", out, 0, checksum)
    if on_log is not None:
        on_log(f"Overlay archive: {len(file_records)} file(s) in {len(folder_records)} folder(s), {len(paz):,} bytes of payload.")
    return OverlayArchive(pamt_bytes=bytes(out), paz_bytes=bytes(paz), pamt_checksum=checksum, entries=tuple(entries))
