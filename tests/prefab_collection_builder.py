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


def member(name: str, type_name: str, flags: int, size: int, extra: int = 0) -> bytes:
    return text(name) + text(type_name) + struct.pack("<HHHH", flags, size, 0, extra)


def element(
    base: int,
    at: int,
    name: str,
    value: str,
    index: int | None = None,
    aliases=(),
    name_length: bool = False,
) -> bytes:
    """One collection element: header, name record, then a single string member.

    ``at`` is the element's blob-relative start and ``base`` the blob's file
    offset, because the name record's pointer has to hold its own absolute
    position plus four. ``name_length`` closes the name record with the u32 every
    shipped element ends with: its distance from the record's start. The walk
    leaves that field with the next element, which is what a resize has to get
    right.
    """
    out = bytearray()
    out += struct.pack("<H", 2)          # marker; tail is marker + 1 bytes
    out += struct.pack("<H", 0b1)        # component mask: member 0
    out += bytes((1, 0, 0))              # tail; type index 1 sits at owner-3
    out += b"\xff" * 8                   # owner
    if index is not None:
        out += struct.pack("<I", index)  # an indexed object list's element index
    pointer_at = at + len(out)
    out += struct.pack("<I", base + pointer_at + 4)
    out += struct.pack("<HH", 0, 1 + len(aliases))  # name record: header, count
    for position, label in enumerate((name, *aliases)):
        out += struct.pack("<H", position) + text(label)  # each name after its index
    out += text(value)                   # the component's one string member
    if name_length:
        out += struct.pack("<I", len(out) - (pointer_at - at) - 4)
    return bytes(out)


def build_with_collection(
    names=("Alpha", "Beta"),
    *,
    wide: bool = False,
    declared: int | None = None,
    indexed: bool = False,
    indexes=None,
    aliases=(),
    name_lengths: bool = False,
) -> bytes:
    """A prefab whose root holds a collection of ``len(names)`` elements.

    ``wide`` writes the header's extra byte, the form whose zero byte makes a
    narrow read of the count come out 256 times too large. ``declared`` writes a
    count other than the number of elements actually present, which is how a
    file that over-declares is reproduced without a shipped one. ``indexed``
    declares the collection the way ``SocketComponent._socketList`` is declared
    (member ``extra`` 0x100): a reference after the count and an index in each
    element; ``indexes`` overrides the indexes written. ``name_lengths`` writes
    the trailing name-length field shipped elements carry.
    """
    types = bytearray()
    types += text("SceneObject") + struct.pack("<H", 1)
    types += member("_childSceneObjects", "ReflectObjectPtr", KIND_COLLECTION, 0, 0x100 if indexed else 0)
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
    if indexed and names:
        blob += b"\x01" + struct.pack("<I", 8) + bytes(8)  # the list's reference
    written = list(indexes) if indexes is not None else list(range(len(names)))
    for position, name in enumerate(names):
        blob += element(base, len(blob), name, f"asset/{name.lower()}.pac",
                        written[position] if indexed else None, aliases, name_lengths)
    blob += b"\x01"                        # the terminator; see prefab_blob_tail

    data_header = struct.pack("<III", 1, base + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", base, len(blob))
    return bytes(header + pool + data_header + blob)


#: Attribute flags of a list member that is still written when unselected
#: (``_components``), and of a type that holds lists.
LIST_ATTR = 0x1008


def typed_member(name: str, type_name: str, flags: int, size: int = 0, attr: int = 0, extra: int = 0) -> bytes:
    return text(name) + text(type_name) + struct.pack("<HHHH", flags, size, attr, extra)


class GroupBlob:
    """A blob written to the group grammar the shipped prefabs use.

    Each object is ``header, owner, name pointer``, then its name pointee: the
    name record, the selected members, an unselected list as the byte 01, and
    finally the u32 that closes the pointee -- its own distance from the
    pointee start. That closing field is what makes an object's bytes its own.
    """

    def __init__(self, base: int) -> None:
        self.base = base
        self.out = bytearray()
        self.out += struct.pack("<H", 2) + (0b1).to_bytes(6, "little")  # root: member 0

    def element(self, type_index: int, mask: int, name: str, members) -> tuple[int, int]:
        """Write one object; ``members(self)`` writes its body. Returns its span."""
        start = len(self.out)
        self.out += struct.pack("<H", 1) + bytes((mask, type_index, 0, 0))
        self.out += b"\xff" * 8
        self.out += struct.pack("<I", self.base + len(self.out) + 4)
        name_start = len(self.out)
        self.out += struct.pack("<HHH", 0, 1, 0) + text(name)
        members(self)
        self.out += struct.pack("<I", len(self.out) - name_start)
        return self.base + start, self.base + len(self.out)

    def collection(self, writers) -> None:
        self.out += b"\x00" + struct.pack("<I", len(writers))
        for write in writers:
            write(self)


def build_nested_groups(leaves=("Alpha", "Beta"), *, nested_type: str = "Holder", holder_mask: int = 0b011) -> bytes:
    """A root ``_childSceneObjects`` holding one object that holds ``leaves``.

    The holder declares ``_label``, ``_components`` and an unselected
    ``_tags`` list, written as the byte 01 after the nested collection.
    ``holder_mask`` 0b001 leaves ``_components`` unselected too: a nested
    prefab instance (``nested_type`` starting ``/``) still writes it in full.
    """
    types = bytearray()
    types += text("SceneObject") + struct.pack("<H", 1)
    types += typed_member("_childSceneObjects", "ReflectObjectPtr", KIND_COLLECTION, attr=0x1028)
    types += text(nested_type) + struct.pack("<H", 3)
    types += typed_member("_label", "IndexedStringA", KIND_STRING, 1)
    types += typed_member("_components", "ReflectObjectPtr", KIND_COLLECTION, attr=LIST_ATTR)
    types += typed_member("_tags", "ReflectObjectPtr", KIND_COLLECTION, attr=LIST_ATTR)
    types += text("Leaf") + struct.pack("<H", 1)
    types += typed_member("_path", "IndexedStringA", KIND_STRING, 1)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8
    header += struct.pack("<I", 15) + struct.pack("<H", 3) + types
    pool = struct.pack("<I", 0)
    base = len(header) + len(pool) + 28

    blob = GroupBlob(base)

    def leaf(label: str):
        return lambda b: b.element(2, 0b1, label, lambda inner: inner.out.extend(text(f"asset/{label.lower()}.pac")))

    def holder(b: GroupBlob) -> None:
        b.out += text("holder")
        b.collection([leaf(label) for label in leaves])
        b.out += b"\x01"  # the unselected _tags

    blob.collection([lambda b: b.element(1, holder_mask, "Holder", holder)])
    data = blob.out
    data_header = struct.pack("<III", 1, base + len(data), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", base, len(data))
    return bytes(header + pool + data_header + data)
