"""Graft a component from one ``.prefab`` into another: the writer a weapon effect needs.

The shipped thrown lightning spear (``cd_phm_10_thrownspear_0001.prefab``) draws its
aura through an ``EffectComponent`` in its root ``SceneObject``'s ``_components``
list; a sword prefab has only a ``SkinnedMeshComponent`` there and declares no
effect types at all. :mod:`cdmw.core.prefab_array_edit` can duplicate an element
that a collection already holds; this takes an element out of a *donor* file and
puts it into a *target* file that has never seen its type, which needs three
things the duplicate did not:

* **the type declarations travel with it.** The donor's declaration of the
  component and of every declared type its members name (``EffectComponent``,
  ``EffectDataReferencePath``, ``SceneObjectSocketReference``) is appended to the
  target's type table, so the table grows and everything after it, the string
  pool, the data header and the whole blob, moves by that much;
* **the element's type indices are remapped.** Every pointer record in the blob is
  preceded by a small header, ``u16 width, mask (width bytes), u8 typeIndex,
  u16 0`` (the element header for a collection element's name record, and the
  same shape in front of a member pointee's record, where the index names the
  pointee's type); a copied element carries the donor's indices and gets the
  target's;
* **the element's true bytes are taken.** The walk's element spans put an
  element's trailing name-length field with the *next* element; the bytes copied
  run from the element header to the end of that field, which is what makes the
  copy a whole object.

Pointers are self-relative (a pointer stores its own offset plus four), so
every relocated and every copied pointer is recomputed from its new position;
pointee length fields are distances and keep their values unless a pointee spans
the splice point, which is checked. The result is read back and refused unless
the walk completes, the target's objects and strings are all still there in
order, and the grafted object reads back with the donor element's members.

Measured on the shipped files (2026-08-17): the spear's element carries
``_offsetTransform``, ``_effectFileName`` (an ``EffectDataReferencePath`` whose
``_path`` is ``<stem>.level.effect``, which resolves to
``effect/binary__/releasebin/<stem>.pae``), ``_immediatelyKill`` and an empty
``_effectTarget``; 3,123 shipped prefabs declare ``EffectComponent`` and 528 of
those walk completely with elements of the same shape.

Whether the game draws an effect grafted this way is unproven until seen there.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

from cdmw.core.prefab_binary import (
    PrefabBinaryError,
    PrefabDocument,
    PrefabType,
    decode_prefab_binary,
    pointer_sites,
    walk_is_determined,
)
from cdmw.core.prefab_binary_edit import PrefabEditError

_HEADER_WIDTHS = (1, 2, 3, 4)
_LENGTH_FIELD_SCAN = 64
_TRANSFORM_SIZE = 40


@dataclass(frozen=True, slots=True)
class PrefabGraftResult:
    data: bytes
    component_type: str
    #: Names of the type declarations appended to the target, in order.
    types_added: Tuple[str, ...]
    #: Absolute offset in the result where the grafted element starts.
    element_offset: int
    element_length: int
    #: The grafted object's resource strings (the effect path, for an EffectComponent).
    resources: Tuple[str, ...]
    proof_lines: Tuple[str, ...]


# --------------------------------------------------------------------------- helpers


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def encode_prefab_type(item: PrefabType) -> bytes:
    """The bytes of one type declaration, as :func:`_read_types` reads them."""

    out = bytearray(_text(item.type_name))
    out += struct.pack("<H", len(item.members))
    for member in item.members:
        out += _text(member.name) + _text(member.type_name)
        out += struct.pack("<HHHH", member.flags, member.value_size, member.attr_flags, member.extra)
    return bytes(out)


def _type_table_end(data: bytes, document: PrefabDocument) -> int:
    last = document.types[-1]
    end = last.offset + len(encode_prefab_type(last))
    for item in document.types:
        if data[item.offset: item.offset + len(encode_prefab_type(item))] != encode_prefab_type(item):
            raise PrefabEditError(f"type {item.type_name!r} does not re-encode to its own bytes; refusing to grow the type table")
    return end


def _type_count_offset(document: PrefabDocument) -> int:
    return (14 if document.version == 4 else 6) + 4


def _element_header_start(data: bytes, base: int, at: int, limit: int) -> int:
    """The first offset at or after `at` that starts an element header followed by a
    self-relative pointer record."""

    for probe in range(at, min(limit, len(data) - 24)):
        width = struct.unpack_from("<H", data, probe)[0]
        if width not in _HEADER_WIDTHS:
            continue
        owner_at = probe + 2 + width + 3
        if owner_at + 12 > len(data):
            continue
        if struct.unpack_from("<I", data, owner_at + 8)[0] == owner_at + 12:
            return probe
    raise PrefabEditError(f"no element header at or after 0x{at:x}")


def _element_end(data: bytes, walk_end: int, pointee_start: int) -> int:
    """Offset just past the element's name-length field (the u32 equal to its own
    distance from the name pointee), searched from where the walk left off."""

    for probe in range(walk_end, min(len(data) - 4, walk_end + _LENGTH_FIELD_SCAN)):
        if struct.unpack_from("<I", data, probe)[0] == probe - pointee_start:
            return probe + 4
    raise PrefabEditError(f"no name-length field after 0x{walk_end:x}")


def _element_bounds(data: bytes, document: PrefabDocument, collection_index: int, element_index: int) -> Tuple[int, int, int]:
    """(header start, end, name pointer site) of one collection element."""

    collection = document.collections[collection_index]
    span_start, walk_end = collection.elements[element_index]
    header = _element_header_start(data, document.blob_offset, span_start, walk_end)
    site = next((p.site for p in document.pointers if p.site >= header), None)
    if site is None or site >= walk_end:
        raise PrefabEditError(f"element at 0x{header:x} has no name record")
    return header, _element_end(data, walk_end, site + 4), site


def _pointer_header_index_offset(data: bytes, site: int) -> Optional[int]:
    """Offset of the type-index byte in the header that precedes the pointer record at `site`."""

    owner_at = site - 8
    for width in _HEADER_WIDTHS:
        start = owner_at - (2 + width + 3)
        if start >= 0 and struct.unpack_from("<H", data, start)[0] == width and data[owner_at - 2: owner_at] == b"\x00\x00":
            return owner_at - 3
    return None


def _needed_types(donor: PrefabDocument, component_type: str, referenced_indices: Sequence[int], target_names: Sequence[str]) -> Tuple[PrefabType, ...]:
    """The donor types the element needs that the target lacks, in donor order: the
    component itself, every type its pointer headers name by index (a member declared
    as the generic `ReflectObject` states its pointee's real type only there), and any
    declared type a member of those names outright."""

    declared = {item.type_name: item for item in donor.types}
    if component_type not in declared:
        raise PrefabEditError(f"the donor declares no type {component_type!r}")
    wanted: list[str] = []
    queue = [component_type] + [donor.types[index].type_name for index in referenced_indices if 0 <= index < len(donor.types)]
    while queue:
        name = queue.pop(0)
        if name in wanted:
            continue
        wanted.append(name)
        for member in declared[name].members:
            if member.type_name in declared and member.type_name not in wanted:
                queue.append(member.type_name)
    return tuple(item for item in donor.types if item.type_name in wanted and item.type_name not in target_names)


def find_component_elements(document: PrefabDocument, component_type: str, *, collection_member: str = "_components") -> Tuple[Tuple[int, int], ...]:
    """(collection index, element index) of every element whose object is `component_type`."""

    out = []
    for c_index, collection in enumerate(document.collections):
        if collection.member_name != collection_member:
            continue
        for e_index, (start, _end) in enumerate(collection.elements):
            obj = next((o for o in document.objects if o.offset == start), None)
            if obj is not None and obj.component_type == component_type:
                out.append((c_index, e_index))
    return tuple(out)


def encode_transform(scale: Sequence[float] = (1.0, 1.0, 1.0), rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0), position: Sequence[float] = (0.0, 0.0, 0.0)) -> bytes:
    """A 40-byte `Transform`: float3 scale, quaternion (x, y, z, w), float3 position, as
    the spear's `_offsetTransform` lays it out (0.7 scale, a 90-degree turn about Z)."""

    if len(scale) != 3 or len(rotation) != 4 or len(position) != 3:
        raise PrefabEditError("a transform is scale(3), rotation(4), position(3)")
    return struct.pack("<10f", *scale, *rotation, *position)


# --------------------------------------------------------------------------- the graft


def graft_prefab_component(
    target: bytes,
    donor: bytes,
    *,
    component_type: str = "EffectComponent",
    donor_index: int = 0,
    target_collection: int = 0,
    collection_member: str = "_components",
    path_replacements: Optional[Mapping[str, str]] = None,
    offset_transform: Optional[bytes] = None,
) -> PrefabGraftResult:
    """Copy the `donor_index`-th `component_type` element of `donor` into `target`'s
    `target_collection`-th `collection_member` collection, appended after its last element.

    `path_replacements` retargets resource paths inside the grafted element (any
    length; the effect path); `offset_transform` overwrites the element's
    `_offsetTransform` bytes in place when the element carries one.
    """

    target_data = bytes(target or b"")
    donor_data = bytes(donor or b"")
    tdoc = decode_prefab_binary(target_data)
    if not tdoc.walk_complete:
        raise PrefabEditError("the target prefab did not decode completely: " + (tdoc.walk_note or "unknown"))
    if not walk_is_determined(target_data):
        raise PrefabEditError("the target prefab's walk is not determined; refusing to splice into it")
    ddoc = decode_prefab_binary(donor_data)
    if not ddoc.walk_complete:
        raise PrefabEditError("the donor prefab did not decode completely: " + (ddoc.walk_note or "unknown"))

    candidates = find_component_elements(ddoc, component_type, collection_member=collection_member)
    if donor_index >= len(candidates):
        raise PrefabEditError(f"the donor has {len(candidates)} {component_type} element(s) in {collection_member}, none at index {donor_index}")
    d_collection, d_element = candidates[donor_index]
    d_start, d_end, _d_name_site = _element_bounds(donor_data, ddoc, d_collection, d_element)
    donor_object = next(o for o in ddoc.objects if o.offset == ddoc.collections[d_collection].elements[d_element][0])

    targets = [index for index, c in enumerate(tdoc.collections) if c.member_name == collection_member]
    if target_collection >= len(targets):
        raise PrefabEditError(f"the target has {len(targets)} {collection_member} collection(s), none at index {target_collection}")
    t_index = targets[target_collection]
    t_coll = tdoc.collections[t_index]
    if t_coll.count != len(t_coll.elements) or not t_coll.elements:
        raise PrefabEditError(f"the target's {collection_member} collection declares {t_coll.count} element(s) and walked {len(t_coll.elements)}; refusing")
    _last_start, insert_at, _site = _element_bounds(target_data, tdoc, t_index, len(t_coll.elements) - 1)
    for site, field_at in tdoc.pointee_length_fields:
        if site + 4 <= insert_at <= field_at:
            raise PrefabEditError(f"a pointee spans the splice point 0x{insert_at:x}; refusing")

    # -- types: the component's, plus every type the element's pointer headers name
    donor_sites = [p.site for p in ddoc.pointers if d_start <= p.site < d_end]
    header_index_offsets = {}
    for site in donor_sites:
        at = _pointer_header_index_offset(donor_data, site)
        if at is None:
            raise PrefabEditError(f"the donor pointer at 0x{site:x} has no readable header; refusing to remap its type")
        header_index_offsets[site] = at
    target_names = [item.type_name for item in tdoc.types]
    added = _needed_types(ddoc, component_type, [donor_data[at] for at in header_index_offsets.values()], target_names)
    type_end = _type_table_end(target_data, tdoc)
    new_types = b"".join(encode_prefab_type(item) for item in added)
    index_map: dict[int, int] = {}
    new_names = target_names + [item.type_name for item in added]
    for d_index, item in enumerate(ddoc.types):
        if item.type_name in new_names:
            index_map[d_index] = new_names.index(item.type_name)
    if len(new_names) > 0xFFFF:
        raise PrefabEditError("type table too large")

    # -- the element, with its type indices remapped
    element = bytearray(donor_data[d_start:d_end])
    for site in donor_sites:
        at = header_index_offsets[site]
        old_index = donor_data[at]
        if old_index not in index_map:
            raise PrefabEditError(f"the donor element names type index {old_index}, which the target does not declare")
        element[at - d_start] = index_map[old_index]
    if offset_transform is not None:
        number = next((n for n in donor_object.numbers if n.name == "_offsetTransform"), None)
        if number is None or len(number.raw) != _TRANSFORM_SIZE:
            raise PrefabEditError("the donor element carries no 40-byte _offsetTransform to overwrite")
        if len(offset_transform) != _TRANSFORM_SIZE:
            raise PrefabEditError("an offset transform is 40 bytes")
        element[number.offset - d_start: number.offset - d_start + _TRANSFORM_SIZE] = bytes(offset_transform)

    # -- resource paths inside the element, any length: every length field whose pointee
    #    spans the string grows with it (the element's own name record spans everything;
    #    the member's pointee spans its path), later positions shift, nothing else changes
    local_sites = [site - d_start for site in donor_sites]
    fields = [(_d_name_site + 4 - d_start, d_end - 4 - d_start)]
    fields += [(site + 4 - d_start, field - d_start) for site, field in ddoc.pointee_length_fields if d_start <= site < d_end]
    wanted = {str(old): str(new) for old, new in dict(path_replacements or {}).items() if str(old) and str(new)}
    resources = []
    edits = []
    for item in donor_object.resources:
        replacement = wanted.get(item.text)
        resources.append(replacement if replacement is not None else item.text)
        if replacement is not None and replacement != item.text:
            edits.append((item.offset - d_start, item.text.encode("utf-8"), replacement.encode("utf-8")))
    for at, old_raw, new_raw in sorted(edits, reverse=True):
        if struct.unpack_from("<I", element, at)[0] != len(old_raw) or bytes(element[at + 4: at + 4 + len(old_raw)]) != old_raw:
            raise PrefabEditError(f"the donor element does not hold {old_raw!r} at 0x{d_start + at:x}")
        delta = len(new_raw) - len(old_raw)
        for index, (pointee_start, field_at) in enumerate(fields):
            if pointee_start <= at < field_at:
                struct.pack_into("<I", element, field_at, struct.unpack_from("<I", element, field_at)[0] + delta)
        element[at: at + 4 + len(old_raw)] = struct.pack("<I", len(new_raw)) + new_raw
        fields = [(ps + (delta if ps > at else 0), f + (delta if f > at else 0)) for ps, f in fields]
        local_sites = [site + (delta if site > at else 0) for site in local_sites]

    # -- assemble
    shift = len(new_types)
    growth = len(element)
    out = bytearray()
    out += target_data[:type_end]
    out += new_types
    out += target_data[type_end:insert_at]
    out += element
    out += target_data[insert_at:]

    struct.pack_into("<H", out, _type_count_offset(tdoc), len(new_names))
    header_at = tdoc.blob_offset - 28 + shift
    struct.pack_into("<I", out, header_at + 4, len(out))
    struct.pack_into("<I", out, header_at + 20, tdoc.blob_offset + shift)
    struct.pack_into("<I", out, header_at + 24, tdoc.blob_length + growth)
    count_at = t_coll.header_offset + t_coll.header_width - 4 + shift
    struct.pack_into("<I", out, count_at, t_coll.count + 1)
    for site in pointer_sites(target_data, tdoc.blob_offset, tdoc.blob_length):
        moved = site + shift + (growth if site >= insert_at else 0)
        struct.pack_into("<I", out, moved, moved + 4)
    new_element_at = insert_at + shift
    for site in local_sites:
        moved = new_element_at + site
        struct.pack_into("<I", out, moved, moved + 4)
    result = bytes(out)
    _verify_graft(result, tdoc, donor_object, tuple(resources), len(added), len(donor_sites), growth)
    proof = [
        f"Appended {len(added)} type declaration(s): {', '.join(item.type_name for item in added) or 'none'}.",
        f"Grafted a {component_type} element of {growth} bytes with {len(donor_sites)} pointer(s) after element {len(t_coll.elements) - 1} of {collection_member}.",
        f"Relocated the blob by {shift} byte(s) for the type table.",
    ]
    return PrefabGraftResult(
        data=result, component_type=component_type, types_added=tuple(item.type_name for item in added),
        element_offset=new_element_at, element_length=growth, resources=tuple(resources), proof_lines=tuple(proof),
    )


def _verify_graft(result: bytes, before: PrefabDocument, donor_object, resources: Tuple[str, ...], types_added: int, donor_pointers: int, growth: int) -> None:
    try:
        after = decode_prefab_binary(result)
    except PrefabBinaryError as exc:
        raise PrefabEditError(f"the grafted prefab does not read back: {exc}") from exc
    if not after.walk_complete:
        raise PrefabEditError(f"the grafted prefab no longer reads all the way through: {after.walk_note}")
    if len(after.types) != len(before.types) + types_added:
        raise PrefabEditError("the grafted prefab declares the wrong number of types")
    if len(after.objects) != len(before.objects) + 1:
        raise PrefabEditError(f"the grafted prefab reads back {len(after.objects)} object(s), expected {len(before.objects) + 1}")
    grafted = [o for o in after.objects if o.component_type == donor_object.component_type and o.member_names == donor_object.member_names and tuple(r.text for r in o.resources) == tuple(resources)]
    if not grafted:
        raise PrefabEditError("the grafted object does not read back with the donor element's members and resources")
    # the target's own strings survive in order; the donor element's join them once each
    remaining = [item.text for item in after.all_strings()]
    for text in list(resources) + [item.text for item in donor_object.texts]:
        if text not in remaining:
            raise PrefabEditError(f"the grafted element's string {text!r} did not read back")
        remaining.remove(text)
    if remaining != [item.text for item in before.all_strings()]:
        raise PrefabEditError("the target's own strings did not survive the graft in order")
    if len(pointer_sites(result, after.blob_offset, after.blob_length)) != len(before.pointers) + donor_pointers:
        raise PrefabEditError("the grafted prefab has the wrong number of pointers")
    if after.blob_length != before.blob_length + growth:
        raise PrefabEditError("the grafted prefab's blob is not the size the graft implies")
    if struct.unpack_from("<I", result, after.blob_offset - 24)[0] != len(result):
        raise PrefabEditError("the grafted prefab declares the wrong file size")


__all__ = [
    "PrefabGraftResult",
    "encode_prefab_type",
    "encode_transform",
    "find_component_elements",
    "graft_prefab_component",
]
