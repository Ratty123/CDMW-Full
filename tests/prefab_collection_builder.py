"""Build synthesised ``.prefab`` payloads that hold a collection.

Shared because two suites need it: the decoder guards, which care how a
collection header is read, and the array-edit guards, which care what happens
when elements are spliced in and out of one.

Nothing here is a fixture captured from the game. Every byte is written to the
documented grammar, so a test that fails here fails because the decoder changed
rather than because a shipped file did.
"""

from __future__ import annotations

import struct

from cdmw.core.prefab_binary import KIND_COLLECTION, KIND_STRING


def text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def member(name: str, type_name: str, flags: int, size: int) -> bytes:
    return text(name) + text(type_name) + struct.pack("<HHHH", flags, size, 0, 0)


def element(base: int, at: int, name: str, value: str) -> bytes:
    """One collection element: header, name record, then a single string member.

    ``at`` is the element's blob-relative start and ``base`` the blob's file
    offset, because the name record's pointer has to hold its own absolute
    position plus four.
    """
    out = bytearray()
    out += struct.pack("<H", 2)          # marker; tail is marker + 1 bytes
    out += struct.pack("<H", 0b1)        # component mask: member 0
    out += bytes((1, 0, 0))              # tail; type index 1 sits at owner-3
    out += b"\xff" * 8                   # owner
    pointer_at = at + len(out)
    out += struct.pack("<I", base + pointer_at + 4)
    out += struct.pack("<HHH", 0, 1, 0)  # name record: header, count, unknown
    out += text(name)
    out += text(value)                   # the component's one string member
    return bytes(out)


def build_with_collection(
    names=("Alpha", "Beta"),
    *,
    wide: bool = False,
    declared: int | None = None,
) -> bytes:
    """A prefab whose root holds a collection of ``len(names)`` elements.

    ``wide`` writes the header's extra byte, the form whose zero byte makes a
    narrow read of the count come out 256 times too large. ``declared`` writes a
    count other than the number of elements actually present, which is how a
    file that over-declares is reproduced without a shipped one.
    """
    types = bytearray()
    types += text("SceneObject") + struct.pack("<H", 1)
    types += member("_childSceneObjects", "ReflectObjectPtr", KIND_COLLECTION, 0)
    types += text("SceneObjectComponent") + struct.pack("<H", 1)
    types += member("_label", "IndexedStringA", KIND_STRING, 1)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8
    header += struct.pack("<I", 15) + struct.pack("<H", 2) + types
    pool = struct.pack("<I", 0)
    base = len(header) + len(pool) + 28

    blob = bytearray()
    blob += struct.pack("<H", 2) + (0b1).to_bytes(6, "little")
    blob += b"\x00"                       # collection kind byte
    if wide:
        blob += b"\x00"                   # the wide header's extra byte
    blob += struct.pack("<I", len(names) if declared is None else declared)
    for name in names:
        blob += element(base, len(blob), name, f"asset/{name.lower()}.pac")
    blob += b"\x01"                        # the terminator; see prefab_blob_tail

    data_header = struct.pack("<III", 1, base + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", base, len(blob))
    return bytes(header + pool + data_header + blob)
