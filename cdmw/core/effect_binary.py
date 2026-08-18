"""Decoder for Crimson Desert effect binaries: ``.pae`` (effects) and ``.paem`` (emitters).

Both are the reflection container :mod:`cdmw.core.prefab_binary` reads (type table,
string pool, data header, blob), wrapped in a 16-byte ``PARC`` header. The type table
is read with that module; the blob is walked here by a grammar the whole shipped
corpus obeys (6,855 of 6,855 effect and emitter files walk to the last byte,
2026-08-18):

::

    file     := "PARC" u32 version u64 0 | reflect container
    blob     := root                                   (the root object has no record header)
    root     := header, u8 0, members
    object   := header, record, members, u32 length    (length: from after the self pointer to here)
    element  := header, [u32 x if the collection says so], record, members, u32 length
    header   := u16 width, mask[width], u16 typeIndex, u8 override (0 base, 1 override)
    record   := u64 owner, u32 self (== its own offset + 4), u16 z (0|1), u16 nameCount,
                (u16 0, u32 len, name)?
    member   := kind 0/2 : value_size bytes inline
              | kind 1   : u32 len, chars
              | kind 4   : object                       (ReflectObject by value)
              | kind 5   : u8 present, object?          (ReflectObjectPtr)
              | kind 3   : u8 null | u32 count, count x value_size    (inline array)
              | kind 6/7 : u8 null | u32 count, preamble, count x element
              | kind 10  : u8 null | u32 count, count x (u32 len, chars)
    preamble := u8 withIds, u32 a, u32 b, u32 n, n x (u32, u32)

The presence mask gates every member except the container kinds (3, 6, 7, 10):
those always write their null byte, and the byte alone says whether a count follows;
their mask bit is informational. Members with attribute bit 0x80 (editor-only:
``_segmentList``, ``_annotationList``, ``_isEditLock``...) are never written. Objects
whose header says ``override`` are deltas over the emitter an effect embeds by path
(the effect's type table names the emitter file as a type); an override curve with an
empty mask keeps the base curve.

Every inline value comes back with its absolute file offset, so a float, colour or
flag can be written back in place; strings and collections are read, not resized.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator, Optional, Sequence, Tuple, Union

from cdmw.core.prefab_binary import PrefabBinaryError, PrefabMember, PrefabType, read_reflect_header

__all__ = [
    "PARC_MAGIC",
    "PARC_HEADER_SIZE",
    "EffectBinaryError",
    "ReflectValue",
    "ReflectNode",
    "EffectDocument",
    "decode_effect_binary",
    "write_value",
    "half_floats",
]

PARC_MAGIC = b"PARC"
PARC_HEADER_SIZE = 16

KIND_INLINE = 0
KIND_STRING = 1
KIND_ENUM = 2
KIND_ARRAY = 3
KIND_OBJECT = 4
KIND_POINTER = 5
KIND_VALUE_COLLECTION = 6
KIND_COLLECTION = 7
KIND_STRING_LIST = 10
CONTAINER_KINDS = frozenset({KIND_ARRAY, KIND_VALUE_COLLECTION, KIND_COLLECTION, KIND_STRING_LIST})
#: Members carrying this attribute bit are editor-only and never serialised.
ATTR_NOT_SERIALISED = 0x80

_MAX_COUNT = 100_000
_MAX_STRING = 4096
_MAX_DEPTH = 64


class EffectBinaryError(ValueError):
    """Raised when a payload does not follow the effect grammar."""


@dataclass(frozen=True, slots=True)
class ReflectValue:
    """One member value with the byte span that holds it. ``offset`` is absolute in
    the file (PARC header included), so a fixed-size value writes back in place."""

    name: str
    type_name: str
    kind: int
    raw: bytes
    offset: int
    #: For arrays: element count; for other members 1.
    count: int = 1

    @property
    def size(self) -> int:
        return len(self.raw)

    @property
    def end(self) -> int:
        return self.offset + len(self.raw)

    @property
    def value(self) -> object:
        """The decoded value: float/int/bool/tuple/str/bytes by the declared type."""

        return decode_value(self.type_name, self.kind, self.raw, self.count)


@dataclass(slots=True)
class ReflectNode:
    """One object of the graph: its type, name, values and children in member order."""

    type_name: str
    #: Absolute offset of the object's header.
    offset: int
    name: str = ""
    #: 1 when the header marks the object as an override of an embedded base object.
    override: int = 0
    #: The presence mask as read; container members ignore it (see the module doc).
    mask: int = 0
    values: list[ReflectValue] = field(default_factory=list)
    #: (member name, node) for by-value and pointer members; (member name, tuple of
    #: nodes) for collections; (member name, None) for a null pointer or null list.
    children: list[tuple[str, Union["ReflectNode", tuple["ReflectNode", ...], None]]] = field(default_factory=list)

    def value(self, name: str) -> Optional[ReflectValue]:
        for item in self.values:
            if item.name == name:
                return item
        return None

    def child(self, name: str) -> Union["ReflectNode", tuple["ReflectNode", ...], None]:
        for member_name, node in self.children:
            if member_name == name:
                return node
        return None

    def walk(self) -> Iterator["ReflectNode"]:
        """This node, then every descendant, depth first in member order."""

        yield self
        for _name, node in self.children:
            if isinstance(node, ReflectNode):
                yield from node.walk()
            elif isinstance(node, tuple):
                for item in node:
                    yield from item.walk()

    def find(self, type_name: str) -> Iterator["ReflectNode"]:
        for node in self.walk():
            if node.type_name == type_name:
                yield node

    def all_values(self) -> Iterator[ReflectValue]:
        for node in self.walk():
            yield from node.values


@dataclass(frozen=True, slots=True)
class EffectDocument:
    """A decoded ``.pae`` or ``.paem``."""

    root: ReflectNode
    types: Tuple[PrefabType, ...]
    string_pool: Tuple[str, ...]
    #: Bytes before the reflect container: 16 for a PARC file, 0 for a bare body.
    container_offset: int
    blob_offset: int
    blob_length: int
    byte_length: int
    walk_complete: bool
    walk_note: str = ""

    @property
    def root_type(self) -> str:
        return self.root.type_name

    def strings(self) -> Tuple[str, ...]:
        """Every string value in the graph, in walk order."""

        out: list[str] = []
        for value in self.root.all_values():
            if value.kind == KIND_STRING:
                out.append(str(value.value))
            elif value.kind == KIND_STRING_LIST:
                out.extend(str(item) for item in value.value)  # type: ignore[union-attr]
        return tuple(out)

    def resources(self) -> Tuple[str, ...]:
        """Paths the graph names (textures, meshes, vector fields, emitter files), deduplicated."""

        seen: list[str] = []
        for text in self.strings():
            lowered = text.lower()
            if "/" in text and lowered.endswith((".dds", ".pam", ".pac", ".paem", ".pae", ".effect")) and text not in seen:
                seen.append(text)
        return tuple(seen)

    def emitter_names(self) -> Tuple[str, ...]:
        """The emitters an effect instances (``emitter/<stem>``), in order, deduplicated."""

        seen: list[str] = []
        for value in self.root.all_values():
            if value.name == "_emitterDataName" and value.kind == KIND_STRING:
                text = str(value.value)
                if text and text not in seen:
                    seen.append(text)
        return tuple(seen)


# ---------------------------------------------------------------------------
# values


def decode_value(type_name: str, kind: int, raw: bytes, count: int = 1) -> object:
    """Decode ``raw`` by its declared type; unknown shapes come back as bytes."""

    if kind == KIND_STRING:
        return raw.decode("utf-8", "replace")
    if kind == KIND_STRING_LIST:
        return _split_string_list(raw)
    if kind == KIND_ARRAY:
        return raw
    size = len(raw)
    try:
        if type_name == "float" and size == 4:
            return struct.unpack("<f", raw)[0]
        if type_name in ("float2", "float3", "float4", "float4x4") and size % 4 == 0 and size:
            return tuple(struct.unpack(f"<{size // 4}f", raw))
        if type_name == "bool" and size == 1:
            return bool(raw[0])
        if type_name in ("uint", "uint32") and size == 4:
            return struct.unpack("<I", raw)[0]
        if type_name in ("int", "int32") and size == 4:
            return struct.unpack("<i", raw)[0]
        if type_name == "uint64" and size == 8:
            return struct.unpack("<Q", raw)[0]
        if type_name == "int64" and size == 8:
            return struct.unpack("<q", raw)[0]
        if type_name == "uint16" and size == 2:
            return struct.unpack("<H", raw)[0]
        if type_name == "int16" and size == 2:
            return struct.unpack("<h", raw)[0]
        if type_name == "uint8" and size == 1:
            return raw[0]
        if type_name == "Color" and size == 4:
            return "#" + raw.hex()
        if kind == KIND_ENUM and size in (1, 2, 4):
            return int.from_bytes(raw, "little")
    except struct.error:
        pass
    return raw


def _split_string_list(raw: bytes) -> Tuple[str, ...]:
    out: list[str] = []
    pos = 0
    while pos + 4 <= len(raw):
        length = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        out.append(raw[pos : pos + length].decode("utf-8", "replace"))
        pos += length
    return tuple(out)


def half_floats(raw: bytes) -> Tuple[float, ...]:
    """A baked curve's ``uint16`` samples read as IEEE half floats."""

    count = len(raw) // 2
    return tuple(struct.unpack(f"<{count}e", raw[: count * 2]))


def write_value(data: bytes, value: ReflectValue, new_raw: bytes) -> bytes:
    """Return ``data`` with ``value`` replaced in place; the size must not change."""

    if len(new_raw) != value.size:
        raise EffectBinaryError(f"{value.name}: {len(new_raw)} bytes cannot replace {value.size}")
    if value.offset < 0 or value.end > len(data):
        raise EffectBinaryError(f"{value.name}: span {value.offset}+{value.size} outside a {len(data)}-byte payload")
    return data[: value.offset] + bytes(new_raw) + data[value.end :]


# ---------------------------------------------------------------------------
# the walk


class _Walker:
    def __init__(self, data: bytes, base: int, types: Sequence[PrefabType], blob_offset: int, blob_length: int) -> None:
        self.data = data
        #: Absolute offset of the reflect container within ``data``.
        self.base = base
        self.types = tuple(types)
        self.pos = base + blob_offset
        self.end = base + blob_offset + blob_length

    # -- primitives ---------------------------------------------------------

    def _need(self, count: int, what: str) -> None:
        if self.pos + count > self.end:
            raise EffectBinaryError(f"{what} at 0x{self.pos:x} runs past the blob end 0x{self.end:x}")

    def u8(self) -> int:
        self._need(1, "byte")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self) -> int:
        self._need(2, "u16")
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def u32(self) -> int:
        self._need(4, "u32")
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def u64(self) -> int:
        self._need(8, "u64")
        value = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return value

    def text(self) -> Tuple[bytes, int]:
        at = self.pos
        length = self.u32()
        if length > _MAX_STRING:
            raise EffectBinaryError(f"string length {length} at 0x{at:x}")
        self._need(length, "string")
        raw = self.data[self.pos : self.pos + length]
        self.pos += length
        return raw, at

    # -- objects ------------------------------------------------------------

    def read_header(self, what: str) -> Tuple[int, PrefabType, int]:
        start = self.pos
        width = self.u16()
        if not 1 <= width <= 8:
            raise EffectBinaryError(f"{what} at 0x{start:x}: mask width {width}")
        self._need(width, "mask")
        mask = int.from_bytes(self.data[self.pos : self.pos + width], "little")
        self.pos += width
        type_index = self.u16()
        override = self.u8()
        if override not in (0, 1):
            raise EffectBinaryError(f"{what} at 0x{start:x}: header flag {override}")
        if type_index >= len(self.types):
            raise EffectBinaryError(f"{what} at 0x{start:x}: type index {type_index} of {len(self.types)}")
        return mask, self.types[type_index], override

    def read_record(self, what: str) -> Tuple[str, int]:
        """The owner, self pointer and name record; returns (name, pointee start)."""

        self.u64()  # owner / identity
        site = self.pos
        target = self.u32()
        # self pointers are container-relative: the offset of the byte after them
        expected = site + 4 - self.base
        if target != expected:
            raise EffectBinaryError(f"{what}: pointer at 0x{site:x} holds 0x{target:x}, not 0x{expected:x}")
        pointee = self.pos
        z = self.u16()
        count = self.u16()
        if z not in (0, 1) or count > 1:
            raise EffectBinaryError(f"{what}: name record ({z}, {count}) at 0x{pointee:x}")
        name = ""
        if count == 1:
            self.u16()
            raw, _at = self.text()
            name = raw.decode("utf-8", "replace")
        return name, pointee

    def read_length(self, pointee: int, what: str) -> None:
        declared = self.u32()
        actual = self.pos - 4 - pointee
        if declared != actual:
            raise EffectBinaryError(f"{what}: length {declared} at 0x{self.pos - 4:x}, walked {actual}")

    def read_root(self) -> ReflectNode:
        start = self.pos
        mask, kind, override = self.read_header("root")
        extra = self.u8()
        if extra != 0:
            raise EffectBinaryError(f"root at 0x{start:x}: extra byte {extra}")
        node = ReflectNode(type_name=kind.type_name, offset=start, override=override, mask=mask)
        self.read_members(node, kind, mask, 0)
        return node

    def read_object(self, path: str, depth: int) -> ReflectNode:
        start = self.pos
        mask, kind, override = self.read_header(path)
        name, pointee = self.read_record(f"{path} ({kind.type_name})")
        node = ReflectNode(type_name=kind.type_name, offset=start, name=name, override=override, mask=mask)
        self.read_members(node, kind, mask, depth)
        self.read_length(pointee, f"{path} ({kind.type_name})")
        return node

    def read_element(self, path: str, with_ids: bool, depth: int) -> ReflectNode:
        start = self.pos
        mask, kind, override = self.read_header(path)
        if with_ids:
            self.u32()
        name, pointee = self.read_record(f"{path} ({kind.type_name})")
        node = ReflectNode(type_name=kind.type_name, offset=start, name=name, override=override, mask=mask)
        self.read_members(node, kind, mask, depth)
        self.read_length(pointee, f"{path} ({kind.type_name})")
        return node

    def read_members(self, node: ReflectNode, kind: PrefabType, mask: int, depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise EffectBinaryError(f"{kind.type_name} nests deeper than {_MAX_DEPTH}")
        path = f"{kind.type_name}"
        for index, member in enumerate(kind.members):
            selected = bool((mask >> index) & 1)
            if member.flags in CONTAINER_KINDS:
                if member.attr_flags & ATTR_NOT_SERIALISED:
                    continue
                null = self.u8()
                if null == 1:
                    if member.flags in (KIND_ARRAY, KIND_STRING_LIST):
                        node.values.append(ReflectValue(member.name, member.type_name, member.flags, b"", self.pos - 1, 0))
                    else:
                        node.children.append((member.name, None))
                    continue
                if null != 0:
                    raise EffectBinaryError(f"{path}.{member.name}: container byte {null} at 0x{self.pos - 1:x}")
                self.read_container(node, member, path, depth)
                continue
            if selected:
                self.read_member(node, member, path, depth)

    def read_member(self, node: ReflectNode, member: PrefabMember, path: str, depth: int) -> None:
        at = self.pos
        kind = member.flags
        if kind in (KIND_INLINE, KIND_ENUM):
            self._need(member.value_size, f"{path}.{member.name}")
            raw = self.data[at : at + member.value_size]
            self.pos += member.value_size
            node.values.append(ReflectValue(member.name, member.type_name, kind, raw, at))
        elif kind == KIND_STRING:
            raw, _at = self.text()
            node.values.append(ReflectValue(member.name, member.type_name, kind, raw, at))
        elif kind == KIND_OBJECT:
            node.children.append((member.name, self.read_object(f"{path}.{member.name}", depth + 1)))
        elif kind == KIND_POINTER:
            present = self.u8()
            if present == 0:
                node.children.append((member.name, None))
            elif present == 1:
                node.children.append((member.name, self.read_object(f"{path}.{member.name}", depth + 1)))
            else:
                raise EffectBinaryError(f"{path}.{member.name}: pointer byte {present} at 0x{at:x}")
        else:
            raise EffectBinaryError(f"{path}.{member.name}: member kind {kind} is not readable")

    def read_container(self, node: ReflectNode, member: PrefabMember, path: str, depth: int) -> None:
        at = self.pos
        count = self.u32()
        if count > _MAX_COUNT:
            raise EffectBinaryError(f"{path}.{member.name}: count {count} at 0x{at:x}")
        if member.flags == KIND_ARRAY:
            size = count * member.value_size
            self._need(size, f"{path}.{member.name}")
            raw = self.data[self.pos : self.pos + size]
            self.pos += size
            node.values.append(ReflectValue(member.name, member.type_name, KIND_ARRAY, raw, at + 4, count))
            return
        if member.flags == KIND_STRING_LIST:
            start = self.pos
            for _ in range(count):
                self.text()
            node.values.append(ReflectValue(member.name, member.type_name, KIND_STRING_LIST, self.data[start : self.pos], start, count))
            return
        # kind 6 / 7: the preamble, then the elements
        with_ids = self.u8()
        if with_ids not in (0, 1):
            raise EffectBinaryError(f"{path}.{member.name}: preamble flag {with_ids} at 0x{self.pos - 1:x}")
        self.u32()
        self.u32()
        extra = self.u32()
        if extra > _MAX_COUNT:
            raise EffectBinaryError(f"{path}.{member.name}: preamble count {extra}")
        self._need(8 * extra, "preamble")
        self.pos += 8 * extra
        elements = tuple(
            self.read_element(f"{path}.{member.name}[{index}]", with_ids == 1, depth + 1) for index in range(count)
        )
        node.children.append((member.name, elements))


def decode_effect_binary(data: bytes) -> EffectDocument:
    """Decode a ``.pae`` / ``.paem`` payload (with or without its PARC header).

    The type table and data header must parse or :class:`EffectBinaryError` is
    raised; the blob walk is reported through ``walk_complete`` / ``walk_note`` and
    the nodes read before a stop are kept.
    """

    payload = bytes(data or b"")
    base = 0
    if payload[:4] == PARC_MAGIC:
        base = PARC_HEADER_SIZE
    body = payload[base:]
    try:
        header = read_reflect_header(body)
    except PrefabBinaryError as exc:
        raise EffectBinaryError(str(exc)) from exc
    blob_end = header.blob_offset + header.blob_length
    if blob_end > len(body):
        raise EffectBinaryError(f"blob {header.blob_offset}+{header.blob_length} outside a {len(body)}-byte body")
    walker = _Walker(payload, base, header.types, header.blob_offset, header.blob_length)
    complete, note = True, ""
    try:
        root = walker.read_root()
        remaining = walker.end - walker.pos
        if remaining:
            complete, note = False, f"walk ended {remaining} bytes short"
    except EffectBinaryError as exc:
        # keep what was read: the walker has no partial root, so report the failure
        root = ReflectNode(type_name=header.types[0].type_name if header.types else "", offset=base + header.blob_offset)
        complete, note = False, str(exc)
    return EffectDocument(
        root=root,
        types=header.types,
        string_pool=header.string_pool,
        container_offset=base,
        blob_offset=base + header.blob_offset,
        blob_length=header.blob_length,
        byte_length=len(payload),
        walk_complete=complete,
        walk_note=note,
    )
