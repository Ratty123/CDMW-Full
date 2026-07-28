"""Structural decoder for Crimson Desert ``.prefab`` binaries.

Unlike :mod:`cdmw.core.crimson_formats`, which recovers length-prefixed strings
and preserves every other byte opaquely, this module parses the format's own
grammar. A ``.prefab`` is self-describing: it carries a type table naming every
member and its byte size, followed by a heap of pointer-addressed object
records.

::

    file    := header typedef*N pool datahdr(28) blob
    header  := u16 magic=0xFFFF, u16 version, u16 ?, [u32 id, u32 id if v4],
               u32 revision, u16 N
    typedef := u32 len, TypeName, u16 memberCount, member*memberCount
    member  := u32 len, _name, u32 len, TypeName,
               u16 flags, u16 valueSize, u16 attrFlags, u16 extra
    pool    := u32 count, (u32 len, string)*count        -- revision >= 14
    datahdr := u32 instanceCount, u32 fileSize, u32 ?, u64 ffff..,
               u32 blobOffset, u32 blobLength

    blob    := u16 tag(=2), u48 rootPresenceMask, group*, trailer(5..6)
    group   := elementHeader nameRecord componentMembers
    header  := u16 marker, u16 componentMask, (marker+1) bytes tail
    pointer := u64 owner, u32 selfOffset, pointee(N), u32 N
    pointee := u32 0, [u32 len, string]
    name    := pointer -> (u16 0, u16 count, [u16 0, u32 len, name])

The type table is flat -- nested types are appended after the referencing
type's complete member list, not inlined -- and the string pool is
variable-length, so the data header is not at a fixed offset.

``selfOffset`` values are absolute file offsets. A u32 at blob-relative ``k``
is a pointer if and only if it equals ``blobOffset + k + 4``, which makes
pointer relocation exact rather than heuristic.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator, Mapping, Sequence

MAGIC = 0xFFFF
SUPPORTED_VERSIONS = (3, 4)
STRING_POOL_MIN_REVISION = 14

# Member ``flags`` values, i.e. how a member's value is serialised.
KIND_INLINE = 0x0000
KIND_STRING = 0x0001
KIND_ENUM = 0x0002
KIND_INLINE_12 = 0x0003
KIND_OBJECT = 0x0004
KIND_POINTER = 0x0005
KIND_COLLECTION = 0x0007

POINTER_KINDS = frozenset({KIND_OBJECT, KIND_POINTER})
INLINE_KINDS = frozenset({KIND_INLINE, KIND_ENUM, KIND_INLINE_12})

NULL_OWNER = 0xFFFFFFFFFFFFFFFF
_MAX_STRING = 4096
_MAX_MEMBERS = 1024
_MAX_TYPES = 4096
_MAX_COUNT = 4096
_FOOTER_SEARCH = 17
_MAX_DEPTH = 32
_MAX_GROUPS = 100_000
_MARKER_SEARCH = 512


class PrefabBinaryError(ValueError):
    """Raised when a payload does not match the known prefab grammar."""


@dataclass(frozen=True, slots=True)
class PrefabMember:
    """One declared member of a prefab type."""

    name: str
    type_name: str
    flags: int
    value_size: int
    attr_flags: int
    extra: int

    @property
    def is_pointer(self) -> bool:
        return self.flags in POINTER_KINDS

    @property
    def is_string(self) -> bool:
        return self.flags == KIND_STRING

    @property
    def is_collection(self) -> bool:
        return self.flags == KIND_COLLECTION

    @property
    def kind_label(self) -> str:
        if self.flags == KIND_STRING:
            return "text"
        if self.flags in POINTER_KINDS:
            return "reference"
        if self.flags == KIND_COLLECTION:
            return "list"
        if self.flags == KIND_ENUM:
            return "enum"
        return "value"


@dataclass(frozen=True, slots=True)
class PrefabType:
    """A declared type and its members, in serialisation order."""

    type_name: str
    members: tuple[PrefabMember, ...]
    offset: int

    @property
    def is_nested_prefab(self) -> bool:
        """True when this "type" is really a reference to another prefab."""
        return self.type_name.startswith("/")


@dataclass(frozen=True, slots=True)
class PrefabString:
    """A string stored in the blob, with the byte span that holds it."""

    text: str
    offset: int
    length: int

    @property
    def end(self) -> int:
        return self.offset + self.length


@dataclass(frozen=True, slots=True)
class PrefabNumber:
    """One inline numeric value, with the byte span that holds it.

    ``offset`` is absolute, so a fixed-size value can be written straight back
    without moving anything around it.
    """

    name: str
    type_name: str
    raw: bytes
    offset: int

    @property
    def end(self) -> int:
        return self.offset + len(self.raw)


@dataclass(frozen=True, slots=True)
class PrefabObject:
    """One scene object recovered from the heap."""

    index: int
    name: str
    component_type: str
    member_names: tuple[str, ...]
    resources: tuple[PrefabString, ...]
    texts: tuple[PrefabString, ...]
    values: tuple[tuple[str, PrefabString], ...]
    numbers: tuple[PrefabNumber, ...]
    parent: int
    #: ``"stated"`` when the file named this object's component type, and
    #: ``"inferred"`` when the walk had to work it out from declaration order.
    #: An inferred object can be entirely wrong while still looking complete.
    type_source: str = "stated"

    @property
    def type_is_inferred(self) -> bool:
        return self.type_source != "stated"


@dataclass(frozen=True, slots=True)
class PrefabPointer:
    """A pointer record. ``site`` is the absolute offset of the offset field."""

    site: int
    owner: int
    target: int


@dataclass(frozen=True, slots=True)
class PrefabDocument:
    """A decoded prefab."""

    version: int
    revision: int
    types: tuple[PrefabType, ...]
    string_pool: tuple[str, ...]
    blob_offset: int
    blob_length: int
    root_type: str
    root_members: tuple[str, ...]
    objects: tuple[PrefabObject, ...]
    root_resources: tuple[PrefabString, ...]
    root_texts: tuple[PrefabString, ...]
    root_values: tuple[tuple[str, PrefabString], ...]
    root_numbers: tuple[PrefabNumber, ...]
    pointers: tuple[PrefabPointer, ...]
    walk_complete: bool
    walk_note: str
    byte_length: int
    #: ``(pointer site, offset of that pointee's trailing length field)``, as
    #: read by the walk rather than searched for. The field records the
    #: pointee's byte count, and a search for "a u32 equal to its own distance
    #: from the pointee start" can land on a nested string's length prefix
    #: instead -- which corrupted 63 of 1,371 shipped prefabs before this
    #: existed. The walk consumes and validates the real one, so it knows.
    pointee_length_fields: tuple[tuple[int, int], ...] = ()

    @property
    def inferred_objects(self) -> tuple[PrefabObject, ...]:
        """Objects whose component type was worked out rather than read.

        A completed walk is not the same as a correct one: these decoded
        cleanly but their identity is a guess, so nothing should present them
        with the same confidence as the rest.
        """
        return tuple(item for item in self.objects if item.type_is_inferred)

    @property
    def component_types(self) -> tuple[PrefabType, ...]:
        return tuple(
            item
            for item in self.types
            if item.type_name != self.root_type
            and not item.type_name.startswith("ResourceReferencePath")
            and not item.is_nested_prefab
        )

    def resource_strings(self) -> tuple[PrefabString, ...]:
        """Every resource path in the file, root-level ones included."""
        seen: dict[int, PrefabString] = {item.offset: item for item in self.root_resources}
        for obj in self.objects:
            for item in obj.resources:
                seen[item.offset] = item
        return tuple(seen[key] for key in sorted(seen))

    def all_strings(self) -> tuple[PrefabString, ...]:
        """Resource paths plus free text (socket names, tags)."""
        seen: dict[int, PrefabString] = {
            item.offset: item for item in self.root_resources + self.root_texts
        }
        for obj in self.objects:
            for item in tuple(obj.resources) + tuple(obj.texts):
                seen[item.offset] = item
        return tuple(seen[key] for key in sorted(seen))


class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def u16(self) -> int:
        if self.pos + 2 > len(self.data):
            raise PrefabBinaryError(f"u16 past end at 0x{self.pos:x}")
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def u32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise PrefabBinaryError(f"u32 past end at 0x{self.pos:x}")
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def text(self, limit: int = _MAX_STRING) -> str:
        start = self.pos
        length = self.u32()
        if length > limit or self.pos + length > len(self.data):
            raise PrefabBinaryError(f"bad string length {length} at 0x{start:x}")
        raw = self.data[self.pos : self.pos + length]
        self.pos += length
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PrefabBinaryError(f"non-utf8 string at 0x{start:x}") from exc


def _read_types(reader: _Reader, count: int) -> tuple[PrefabType, ...]:
    types: list[PrefabType] = []
    for _ in range(count):
        offset = reader.pos
        type_name = reader.text(limit=256)
        if not type_name or type_name.startswith("_"):
            raise PrefabBinaryError(f"bad type name {type_name!r} at 0x{offset:x}")
        member_count = reader.u16()
        if member_count > _MAX_MEMBERS:
            raise PrefabBinaryError(f"implausible member count {member_count} for {type_name}")
        members: list[PrefabMember] = []
        for _index in range(member_count):
            member_offset = reader.pos
            name = reader.text(limit=256)
            if not name.startswith("_"):
                raise PrefabBinaryError(f"member {name!r} at 0x{member_offset:x} lacks leading underscore")
            member_type = reader.text(limit=256)
            if not member_type or member_type.startswith("_"):
                raise PrefabBinaryError(f"bad member type {member_type!r} at 0x{member_offset:x}")
            members.append(
                PrefabMember(
                    name=name,
                    type_name=member_type,
                    flags=reader.u16(),
                    value_size=reader.u16(),
                    attr_flags=reader.u16(),
                    extra=reader.u16(),
                )
            )
        types.append(PrefabType(type_name=type_name, members=tuple(members), offset=offset))
    return tuple(types)


@dataclass(slots=True)
class _Header:
    version: int
    revision: int
    types: tuple[PrefabType, ...]
    string_pool: tuple[str, ...]
    blob_offset: int
    blob_length: int
    declared_size: int


def _read_header(data: bytes) -> _Header:
    reader = _Reader(data)
    magic = reader.u16()
    if magic != MAGIC:
        raise PrefabBinaryError(f"unexpected magic 0x{magic:04x}")
    version = reader.u16()
    if version not in SUPPORTED_VERSIONS:
        raise PrefabBinaryError(f"unsupported prefab version {version}")
    reader.u16()
    if version == 4:
        # Version 4 inserts 8 bytes before the revision field. Two independent
        # u32s, not one value, and measurably *not* a checksum of the file: six
        # bodies in the corpus are byte-identical yet carry different values
        # here. No byte-range or string hash tried reproduces either half, and
        # no prefab body references another's value, so it reads as an
        # authoring-time identifier. Both rewriters preserve it untouched,
        # which this evidence says is right -- the engine cannot be validating
        # it against content that does not determine it.
        reader.pos = 14
    revision = reader.u32()
    type_count = reader.u16()
    if not 0 < type_count <= _MAX_TYPES:
        raise PrefabBinaryError(f"implausible type count {type_count}")

    types = _read_types(reader, type_count)

    pool: list[str] = []
    if revision >= STRING_POOL_MIN_REVISION:
        pool_count = reader.u32()
        if pool_count > 100_000:
            raise PrefabBinaryError(f"implausible string pool count {pool_count}")
        pool = [reader.text(limit=1024) for _ in range(pool_count)]

    if reader.pos + 28 > len(data):
        raise PrefabBinaryError("truncated data header")
    _instances, declared_size, _unknown = struct.unpack_from("<III", data, reader.pos)
    blob_offset, blob_length = struct.unpack_from("<II", data, reader.pos + 20)
    return _Header(
        version=version,
        revision=revision,
        types=types,
        string_pool=tuple(pool),
        blob_offset=blob_offset,
        blob_length=blob_length,
        declared_size=declared_size,
    )


def pointer_sites(data: bytes, blob_offset: int, blob_length: int) -> tuple[int, ...]:
    """Absolute offsets of every pointer field in the blob.

    A u32 at blob-relative ``k`` is a pointer exactly when it stores
    ``blob_offset + k + 4`` -- it addresses the byte just past itself. This is
    an identity, not a heuristic, so relocation never has to guess.
    """
    sites: list[int] = []
    for local in range(max(0, blob_length - 3)):
        absolute = blob_offset + local
        if struct.unpack_from("<I", data, absolute)[0] == absolute + 4:
            sites.append(absolute)
    return tuple(sites)


class _BlobCursor:
    """Cursor over the data blob, in blob-relative coordinates."""

    __slots__ = ("blob", "base", "pos", "type_table", "used_types", "pointee_fields")

    def __init__(self, blob: bytes, base: int, type_table: Sequence[PrefabType] = ()) -> None:
        self.blob = blob
        self.base = base
        self.pos = 0
        self.type_table = tuple(type_table)
        # site -> offset of that pointee's trailing length field. The walk
        # reads and validates that field, so its position is known exactly;
        # an editor that has to search for it instead can land on a string's
        # own length prefix by coincidence.
        self.pointee_fields: dict[int, int] = {}
        # Types already claimed by a group, so an unstated one can take the
        # next declared type instead of guessing by size.
        self.used_types: set[str] = set()

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.blob):
            raise PrefabBinaryError(f"blob read of {count} past end at 0x{self.pos:x}")
        raw = self.blob[self.pos : self.pos + count]
        self.pos += count
        return raw

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def text(self) -> PrefabString:
        offset = self.pos
        length = self.u32()
        if length > _MAX_STRING:
            raise PrefabBinaryError(f"blob string length {length} at 0x{offset:x}")
        raw = self.take(length)
        return PrefabString(
            text=raw.decode("utf-8", "replace"),
            offset=self.base + offset,
            length=length,
        )

    def at_pointer(self) -> bool:
        """True when the cursor sits on a pointer record's owner field."""
        if self.pos + 12 > len(self.blob):
            return False
        return struct.unpack_from("<I", self.blob, self.pos + 8)[0] == self.base + self.pos + 12


@dataclass(slots=True)
class _Collected:
    resources: list[PrefabString] = field(default_factory=list)
    texts: list[PrefabString] = field(default_factory=list)
    # Each recovered string paired with the member it came from, in order.
    ordered: list[tuple[str, PrefabString]] = field(default_factory=list)
    numbers: list[PrefabNumber] = field(default_factory=list)


def _read_pointer(cursor: _BlobCursor, into: _Collected, member_name: str = "") -> None:
    """Consume a pointer record and its inline pointee.

    Records are closed by a short footer whose width follows the component
    family (7 bytes for SkinnedMeshComponent, 6 for MeshComponent), so the
    cursor resynchronises onto the next pointer rather than assuming a width.
    """
    for _ in range(_FOOTER_SEARCH):
        if cursor.at_pointer():
            break
        cursor.take(1)
    else:
        raise PrefabBinaryError(f"no pointer record near 0x{cursor.pos:x}")
    cursor.take(8)  # owner
    site = cursor.base + cursor.pos
    target = cursor.u32()
    if target != cursor.base + cursor.pos:
        raise PrefabBinaryError(f"pointer at 0x{cursor.pos:x} is not self-relative")
    start = cursor.pos
    if cursor.u32() != 0:
        raise PrefabBinaryError(f"unexpected pointee header at 0x{start:x}")
    # A populated pointee carries a length-prefixed path. The trailing length
    # equals the bytes consumed since ``start``, which disambiguates an empty
    # pointee from a path whose length happens to match.
    if cursor.pos + 4 <= len(cursor.blob):
        probe = struct.unpack_from("<I", cursor.blob, cursor.pos)[0]
        consumed = cursor.pos - start
        if probe != consumed and 0 < probe <= _MAX_STRING and cursor.pos + 4 + probe <= len(cursor.blob):
            recovered = cursor.text()
            into.resources.append(recovered)
            into.ordered.append((member_name, recovered))
    field_at = cursor.base + cursor.pos
    declared = cursor.u32()
    actual = cursor.pos - start - 4
    if declared != actual:
        raise PrefabBinaryError(f"pointee length {declared} != {actual}")
    cursor.pointee_fields[site] = field_at


def _read_collection_count(cursor: _BlobCursor) -> int:
    """Read a collection's element count.

    The header is a one-byte kind followed by a u32 count, except that some
    collections (``_childSceneObjects`` and friends) carry an extra byte
    between the two. The count is small, so an implausible read means the
    wider form.
    """
    kind = cursor.take(1)[0]
    if cursor.pos + 4 > len(cursor.blob):
        raise PrefabBinaryError("truncated collection header")
    count = struct.unpack_from("<I", cursor.blob, cursor.pos)[0]
    if count > _MAX_COUNT and cursor.pos + 5 <= len(cursor.blob):
        wider = struct.unpack_from("<I", cursor.blob, cursor.pos + 1)[0]
        if wider <= _MAX_COUNT:
            cursor.take(5)
            return wider
    if count > _MAX_COUNT:
        raise PrefabBinaryError(f"collection count {count} (kind {kind})")
    cursor.take(4)
    return count


def _read_member(cursor: _BlobCursor, member: PrefabMember, into: _Collected, group_reader) -> None:
    flags = member.flags
    if flags in INLINE_KINDS:
        start = cursor.pos
        raw = cursor.take(member.value_size)
        if member.value_size:
            into.numbers.append(
                PrefabNumber(
                    name=member.name,
                    type_name=member.type_name,
                    raw=bytes(raw),
                    offset=cursor.base + start,
                )
            )
        return
    if flags == KIND_STRING:
        recovered = cursor.text()
        into.texts.append(recovered)
        into.ordered.append((member.name, recovered))
        return
    if flags in POINTER_KINDS:
        _read_pointer(cursor, into, member.name)
        return
    if flags == KIND_COLLECTION:
        count = _read_collection_count(cursor)
        for _ in range(count):
            group_reader(cursor)
        return
    raise PrefabBinaryError(f"unsupported member kind 0x{flags:04x} on {member.name}")


def _find_element_header(cursor: _BlobCursor) -> tuple[int, int]:
    """Locate the element header and return ``(mask, componentTypeIndex)``.

    The header is ``u16 marker, u16 componentMask, (marker + 1) tail bytes``
    followed by the name record's pointer; the marker encodes its own tail
    width, so both component families share one rule.

    The tail's third-from-last byte is the component's index into the type
    table -- it matched the resolved component in 6,940 of 6,940 sampled
    groups. Reading it beats inferring the type from the mask, which cannot
    distinguish two components whose member counts both accommodate it.
    """
    base = cursor.pos
    for skip in range(_MARKER_SEARCH):
        probe = base + skip
        if probe + 24 > len(cursor.blob):
            break
        marker = struct.unpack_from("<H", cursor.blob, probe)[0]
        # Markers 1, 2 and 3 all occur; wider values add no coverage and only
        # widen the chance of a false match.
        if marker not in (1, 2, 3):
            continue
        tail = marker + 1
        owner_at = probe + 4 + tail
        if owner_at + 12 > len(cursor.blob):
            continue
        if struct.unpack_from("<I", cursor.blob, owner_at + 8)[0] != cursor.base + owner_at + 12:
            continue
        cursor.pos = probe
        cursor.u16()
        mask = cursor.u16()
        cursor.take(tail)
        # Only markers 2 and 3 leave room for a type index. With marker 1 the
        # byte at owner-3 is the mask's own high byte -- confirmed on all 376
        # marker-1 groups in the corpus -- so reading it would be reading the
        # mask twice. It has never been accepted downstream, because the member
        # count check rejects it; refusing it here means that is by design
        # rather than by luck.
        type_index = -1 if marker == 1 else (cursor.blob[cursor.pos - 3] if cursor.pos >= 3 else -1)
        return mask, type_index
    raise PrefabBinaryError(f"no element header near 0x{base:x}")


def _read_name_record(cursor: _BlobCursor) -> str:
    """Consume the name record. ``count`` of 0 means the object is unnamed."""
    for _ in range(_FOOTER_SEARCH):
        if cursor.at_pointer():
            break
        cursor.take(1)
    else:
        raise PrefabBinaryError(f"no name record near 0x{cursor.pos:x}")
    cursor.take(8)  # owner
    target = cursor.u32()
    if target != cursor.base + cursor.pos:
        raise PrefabBinaryError("name pointer is not self-relative")
    if cursor.u16() != 0:
        raise PrefabBinaryError("unexpected name record header")
    count = cursor.u16()
    if count == 0:
        return ""
    if count != 1:
        raise PrefabBinaryError(f"unsupported name count {count}")
    cursor.u16()
    return cursor.text().text


def _component_for(
    cursor: _BlobCursor,
    type_index: int,
    mask: int,
    components: Sequence[PrefabType],
    highest: int,
) -> tuple[PrefabType, bool]:
    """Resolve a group's component type, and say whether the file stated it.

    Markers 2 and 3 state the type's index at ``owner-3``; marker 1 has no room
    for it, since that byte is the mask's own high byte. For those, fall back to
    declaration order: nested types appear in the schema in the order they are
    first referenced, which held for 301 of 304 completed walks.

    The second element is ``True`` only when the index came out of the file.
    Everything else is inference, and the caller has to be able to tell the
    difference -- a wrong guess still produces a tidy, complete-looking object.
    """
    used = getattr(cursor, "used_types", None)
    declared = getattr(cursor, "type_table", ())
    if 0 <= type_index < len(declared):
        named = declared[type_index]
        if highest <= len(named.members):
            if used is not None:
                used.add(named.type_name)
            return named, True
    candidates = [item for item in components if highest <= len(item.members)]
    if not candidates:
        raise PrefabBinaryError(f"mask 0x{mask:04x} exceeds every candidate component")
    if used is not None:
        for item in candidates:
            if item.type_name not in used:
                used.add(item.type_name)
                return item, False
    # Every declared type is spoken for: guess deterministically. Backtracking
    # over candidates is exponential in nesting depth, and a wrong guess is
    # reported as a partial walk rather than hanging the caller.
    chosen = min(candidates, key=lambda item: (len(item.members), item.type_name))
    if used is not None:
        used.add(chosen.type_name)
    return chosen, False


def _walk_group(
    cursor: _BlobCursor,
    components: Sequence[PrefabType],
    sink: list[PrefabObject],
    depth: int = 0,
) -> None:
    """Walk one object group.

    A prefab may declare several component types and the group header does not
    name which one it uses, so each candidate whose mask bits are all valid
    member indices is attempted in turn and the first that parses is taken.
    """
    if depth > _MAX_DEPTH:
        raise PrefabBinaryError(f"group nesting deeper than {_MAX_DEPTH}")
    if len(sink) > _MAX_GROUPS:
        raise PrefabBinaryError(f"more than {_MAX_GROUPS} groups")
    mask, type_index = _find_element_header(cursor)
    owner_before = cursor.pos
    parent = int.from_bytes(cursor.blob[max(0, owner_before) : owner_before + 8], "little")
    name = _read_name_record(cursor)
    if not components:
        raise PrefabBinaryError("no component type for group")
    highest = mask.bit_length()
    component, type_stated = _component_for(cursor, type_index, mask, components, highest)
    collected = _Collected()
    selected: list[str] = []
    depth_index = len(sink)

    def nested(inner: _BlobCursor) -> None:
        _walk_group(inner, components, sink, depth + 1)

    for index, member in enumerate(component.members):
        if not (mask >> index) & 1:
            continue
        selected.append(member.name)
        _read_member(cursor, member, collected, nested)
    sink.insert(
        depth_index,
        PrefabObject(
            index=depth_index,
            name=name,
            component_type=component.type_name,
            member_names=tuple(selected),
            resources=tuple(collected.resources),
            texts=tuple(collected.texts),
            values=tuple(collected.ordered),
            numbers=tuple(collected.numbers),
            parent=parent if parent != NULL_OWNER else -1,
            type_source="stated" if type_stated else "inferred",
        ),
    )


def _walk_blob(
    blob: bytes,
    base: int,
    root: PrefabType,
    components: Sequence[PrefabType],
    all_types: Sequence[PrefabType] = (),
) -> tuple[tuple[str, ...], list[PrefabObject], bool, str, _Collected, dict[int, int]]:
    cursor = _BlobCursor(blob, base, all_types)
    objects: list[PrefabObject] = []
    cursor.take(2)
    mask = int.from_bytes(cursor.take(6), "little")
    selected = tuple(
        member.name for index, member in enumerate(root.members) if (mask >> index) & 1
    )
    collected = _Collected()

    def nested(inner: _BlobCursor) -> None:
        _walk_group(inner, components, objects, 1)

    try:
        for index, member in enumerate(root.members):
            if not (mask >> index) & 1:
                continue
            # Collections at the root read exactly as they do anywhere else, so
            # let _read_member own that in one place.
            _read_member(cursor, member, collected, nested)
    except PrefabBinaryError as exc:
        return selected, objects, False, str(exc), collected, cursor.pointee_fields
    # The blob closes with the final record's footer plus a terminator; its
    # width follows the component family.
    remaining = len(blob) - cursor.pos
    if 5 <= remaining <= 6:
        cursor.pos += remaining
        remaining = 0
    if remaining:
        return selected, objects, False, f"walk ended {remaining} bytes short", collected, cursor.pointee_fields
    return selected, objects, True, "", collected, cursor.pointee_fields


def decode_prefab_binary(data: bytes) -> PrefabDocument:
    """Decode a ``.prefab`` payload.

    The type table, string pool and data header are always parsed; a failure
    there raises :class:`PrefabBinaryError`. The heap walk is best-effort:
    when it cannot complete, ``walk_complete`` is ``False`` and ``walk_note``
    explains why, while the objects recovered so far are still returned.
    """
    payload = bytes(data or b"")
    header = _read_header(payload)
    blob_end = header.blob_offset + header.blob_length
    if header.blob_offset < 0 or blob_end > len(payload):
        raise PrefabBinaryError(
            f"blob {header.blob_offset}+{header.blob_length} outside a {len(payload)}-byte payload"
        )
    blob = payload[header.blob_offset : blob_end]
    root = header.types[0]
    components = [
        item
        for item in header.types
        if item.type_name != root.type_name
        and not item.type_name.startswith("ResourceReferencePath")
        and not item.is_nested_prefab
    ]
    selected, objects, complete, note, root_values, pointee_fields = _walk_blob(
        blob, header.blob_offset, root, tuple(components), header.types
    )
    pointers = tuple(
        PrefabPointer(
            site=site,
            owner=int.from_bytes(payload[max(0, site - 8) : site], "little"),
            target=site + 4,
        )
        for site in pointer_sites(payload, header.blob_offset, header.blob_length)
    )
    return PrefabDocument(
        version=header.version,
        revision=header.revision,
        types=header.types,
        string_pool=header.string_pool,
        blob_offset=header.blob_offset,
        blob_length=header.blob_length,
        root_type=root.type_name,
        root_members=selected,
        objects=tuple(objects),
        root_resources=tuple(root_values.resources),
        root_texts=tuple(root_values.texts),
        root_values=tuple(root_values.ordered),
        root_numbers=tuple(root_values.numbers),
        pointers=pointers,
        walk_complete=complete,
        walk_note=note,
        byte_length=len(payload),
        pointee_length_fields=tuple(sorted(pointee_fields.items())),
    )
