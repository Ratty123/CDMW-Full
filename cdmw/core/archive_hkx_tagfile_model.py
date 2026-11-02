"""Relocating codec for Crimson Desert's Havok 2024.2 tagfiles.

``parse_hkx_tagfile_model`` decodes a ``TAG0`` file into items, their payloads
and every reference between them: PTCH entries (DATA words holding an ITEM
index) and the self-relative fields listed in ``archive_hkx_tagfile_layout``.
``serialize_hkx_tagfile_model`` lays DATA out again from the model alone:
item offsets follow from data order, stride and alignment, references are
re-encoded from their targets, and ITEM/PTCH and every section size are
regenerated. The TYPE section is carried verbatim because no edit adds a type.

Parsing is strict. A file is refused (``HkxTagfileRefused``) when its section
tree, SDK version, item types, layout, padding or references fall outside what
the corpus measurement proved, so a rebuild never guesses.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_tagfile_layout import (
    HKX_DATA_END_ALIGNMENT,
    HKX_ITEM_KIND_ARRAY,
    HKX_ITEM_KIND_OBJECT,
    HKX_TAGFILE_SDK_VERSION,
    hkx_item_layout,
    hkx_relative_slots,
)

_LEAF = 1
_CONTAINER = 0
_EXPECTED_TREE = (
    ("TAG0", _CONTAINER),
    ("SDKV", _LEAF),
    ("DATA", _LEAF),
    ("TYPE", _CONTAINER),
    ("INDX", _CONTAINER),
    ("ITEM", _LEAF),
)


class HkxTagfileRefused(ValueError):
    """The file is outside the proven tagfile model; ``code`` names the reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class HkxTagfileItem:
    kind: int
    type_index: int
    count: int
    payload: bytearray
    offset: int = 0  # DATA offset in the source file; ignored by the serializer


@dataclass(frozen=True)
class HkxTagfileReference:
    """A DATA word that names another item.

    ``patch_type`` is set for PTCH entries (the word stores the target ITEM
    index); otherwise the word is a self-relative offset of ``width`` bytes and
    ``count_offset`` names the u32 that mirrors the target's element count.
    """

    source_item: int
    offset: int
    target_item: int
    width: int = 8
    patch_type: Optional[int] = None
    count_offset: Optional[int] = None

    @property
    def is_patch(self) -> bool:
        return self.patch_type is not None


@dataclass
class HkxTagfileModel:
    sdk_version: bytes
    type_section: bytes
    type_names: Tuple[str, ...]
    items: List[HkxTagfileItem]
    data_order: List[int]
    references: List[HkxTagfileReference]
    has_patch_section: bool

    def type_name(self, item_index: int) -> str:
        return self.type_names[self.items[item_index].type_index]

    def stride(self, item_index: int) -> int:
        item = self.items[item_index]
        return _layout_or_refuse(self.type_names[item.type_index], item.kind)[0]

    def references_to(self, item_index: int) -> List[HkxTagfileReference]:
        return [reference for reference in self.references if reference.target_item == item_index]

    def references_from(self, item_index: int) -> List[HkxTagfileReference]:
        return [reference for reference in self.references if reference.source_item == item_index]


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _layout_or_refuse(type_name: str, kind: int) -> Tuple[int, int]:
    layout = hkx_item_layout(type_name, kind)
    if layout is None:
        raise HkxTagfileRefused(
            "unproven_type",
            f"Item type {type_name!r} (kind 0x{kind:02X}) has no measured stride and alignment.",
        )
    return layout


def _read_sections(data: bytes, start: int, end: int) -> List[Tuple[str, int, int, int]]:
    sections = []
    offset = start
    while offset < end:
        if offset + 8 > end:
            raise HkxTagfileRefused("bad_section", f"Truncated section header at {offset}.")
        word = struct.unpack_from(">I", data, offset)[0]
        size = word & 0x3FFFFFFF
        tag = data[offset + 4 : offset + 8].decode("latin-1")
        if size < 8 or offset + size > end:
            raise HkxTagfileRefused("bad_section", f"Section {tag!r} at {offset} overruns its parent.")
        sections.append((tag, word >> 30, offset, offset + size))
        offset += size
    return sections


def _varint(payload: bytes, offset: int) -> Tuple[int, int]:
    if offset >= len(payload):
        raise HkxTagfileRefused("bad_type_table", "TNA1 ends inside a packed integer.")
    first = payload[offset]
    if first & 0x80 == 0:
        return first, offset + 1
    marker = first >> 3
    if 0x10 <= marker < 0x18:
        width = 2
    elif 0x18 <= marker < 0x1C:
        width = 3
    elif marker == 0x1C:
        width = 4
    else:
        raise HkxTagfileRefused("bad_type_table", f"Unsupported packed integer marker 0x{first:02X}.")
    if offset + width > len(payload):
        raise HkxTagfileRefused("bad_type_table", "TNA1 ends inside a packed integer.")
    if width == 2:
        return ((first << 8) | payload[offset + 1]) & 0x3FFF, offset + 2
    if width == 3:
        return ((first << 16) | (payload[offset + 1] << 8) | payload[offset + 2]) & 0x1FFFFF, offset + 3
    return int.from_bytes(payload[offset : offset + 4], "little") & 0x07FFFFFF, offset + 4


def _type_names(data: bytes, children: Dict[str, Tuple[int, int, int, int]]) -> Tuple[str, ...]:
    if "TST1" not in children or "TNA1" not in children:
        raise HkxTagfileRefused("bad_type_table", "TYPE has no TST1/TNA1 tables.")
    _, _, start, end = children["TST1"]
    strings = [raw.decode("latin-1") for raw in data[start + 8 : end].split(b"\0")]
    _, _, start, end = children["TNA1"]
    table = data[start + 8 : end]
    count, offset = _varint(table, 0)

    def string_at(index: int) -> str:
        if not 0 <= index < len(strings):
            raise HkxTagfileRefused("bad_type_table", f"TNA1 names string {index}; TST1 holds {len(strings)}.")
        return strings[index]

    raw_types: List[Tuple[str, List[Tuple[str, int]]]] = []
    for _ in range(max(0, count - 1)):
        name_index, offset = _varint(table, offset)
        template_count, offset = _varint(table, offset)
        templates = []
        for _ in range(template_count):
            template_name, offset = _varint(table, offset)
            template_value, offset = _varint(table, offset)
            templates.append((string_at(template_name), template_value))
        raw_types.append((string_at(name_index), templates))

    def full_name(index: int, depth: int = 0) -> str:
        name, templates = raw_types[index - 1]
        if not templates or depth > 8:
            return name
        arguments = []
        for template_name, value in templates:
            if template_name.startswith("t") and 0 < value <= len(raw_types):
                arguments.append(full_name(value, depth + 1))
            else:
                arguments.append(str(value))
        return f"{name}<{','.join(arguments)}>"

    return ("",) + tuple(full_name(index) for index in range(1, count))


def _parse_patches(data: bytes, start: int, end: int) -> List[Tuple[int, int]]:
    patches = []
    offset = start
    last_type = -1
    while offset + 8 <= end:
        patch_type, count = struct.unpack_from("<2I", data, offset)
        offset += 8
        if patch_type <= last_type or offset + 4 * count > end:
            raise HkxTagfileRefused("bad_patch_table", "PTCH groups are not in ascending type order.")
        last_type = patch_type
        words = struct.unpack_from(f"<{count}I", data, offset)
        offset += 4 * count
        if list(words) != sorted(words):
            raise HkxTagfileRefused("bad_patch_table", "PTCH offsets are not ascending.")
        patches.extend((patch_type, word) for word in words)
    if offset != end:
        raise HkxTagfileRefused("bad_patch_table", "PTCH has trailing bytes.")
    return patches


def _section_tree(data: bytes) -> Tuple[Dict[str, Tuple[int, int, int, int]], Dict[str, Tuple[int, int, int, int]]]:
    top = _read_sections(data, 0, len(data))
    if len(top) != 1 or top[0][0] != "TAG0" or top[0][3] != len(data):
        raise HkxTagfileRefused("bad_section", "The file is not one TAG0 section.")
    tag0 = top[0]
    level1 = _read_sections(data, tag0[2] + 8, tag0[3])
    if [section[0] for section in level1] != ["SDKV", "DATA", "TYPE", "INDX"]:
        raise HkxTagfileRefused("bad_section", f"Unexpected TAG0 layout {[section[0] for section in level1]}.")
    sections = {section[0]: section for section in level1}
    sections["TAG0"] = tag0
    index = _read_sections(data, sections["INDX"][2] + 8, sections["INDX"][3])
    if [section[0] for section in index] not in (["ITEM"], ["ITEM", "PTCH"]):
        raise HkxTagfileRefused("bad_section", f"Unexpected INDX layout {[section[0] for section in index]}.")
    sections.update({section[0]: section for section in index})
    type_children = {section[0]: section for section in _read_sections(data, sections["TYPE"][2] + 8, sections["TYPE"][3])}
    for tag, flags in _EXPECTED_TREE + (("PTCH", _LEAF),):
        if tag in sections and sections[tag][1] != flags:
            raise HkxTagfileRefused("bad_section", f"Section {tag} has unexpected flags {sections[tag][1]}.")
    return sections, type_children


def parse_hkx_tagfile_model(data: bytes, *, canonical_layout: bool = True) -> HkxTagfileModel:
    """Decode ``data``; ``canonical_layout=False`` accepts any non-overlapping item placement.

    Every malformed input ends in ``HkxTagfileRefused``; a truncated or inconsistent
    table never escapes as a low-level ``IndexError`` or ``struct.error``.
    """

    try:
        return _parse_hkx_tagfile_model(data, canonical_layout)
    except HkxTagfileRefused:
        raise
    except (IndexError, KeyError, struct.error, RecursionError, UnicodeDecodeError) as exc:
        raise HkxTagfileRefused("malformed", f"The file's tables are inconsistent ({type(exc).__name__}: {exc}).") from exc


def _parse_hkx_tagfile_model(data: bytes, canonical_layout: bool) -> HkxTagfileModel:
    sections, type_children = _section_tree(data)
    sdk = data[sections["SDKV"][2] + 8 : sections["SDKV"][3]]
    if sdk != HKX_TAGFILE_SDK_VERSION:
        raise HkxTagfileRefused("unsupported_sdk", f"SDK {sdk!r} is not the measured {HKX_TAGFILE_SDK_VERSION!r}.")
    type_names = _type_names(data, type_children)
    data_start, data_end = sections["DATA"][2] + 8, sections["DATA"][3]
    blob = data[data_start:data_end]
    item_start, item_end = sections["ITEM"][2] + 8, sections["ITEM"][3]
    if (item_end - item_start) % 12 or item_end - item_start < 24:
        raise HkxTagfileRefused("bad_item_table", "ITEM size is not a whole number of entries.")
    raw_items = [struct.unpack_from("<3I", data, offset) for offset in range(item_start, item_end, 12)]
    if raw_items[0] != (0, 0, 0):
        raise HkxTagfileRefused("bad_item_table", "ITEM 0 is not the null item.")
    items = [HkxTagfileItem(0, 0, 0, bytearray())]
    for word, offset, count in raw_items[1:]:
        kind, type_index = word >> 24, word & 0xFFFFFF
        if kind not in (HKX_ITEM_KIND_OBJECT, HKX_ITEM_KIND_ARRAY) or not 0 < type_index < len(type_names):
            raise HkxTagfileRefused("bad_item_table", f"ITEM word 0x{word:08X} is outside the measured kinds.")
        if count == 0 or (kind == HKX_ITEM_KIND_OBJECT and count != 1):
            raise HkxTagfileRefused("bad_item_table", f"ITEM count {count} is outside the measured range.")
        stride, _ = _layout_or_refuse(type_names[type_index], kind)
        if offset + stride * count > len(blob):
            raise HkxTagfileRefused("bad_layout", f"An item of {type_names[type_index]} overruns DATA.")
        items.append(HkxTagfileItem(kind, type_index, count, bytearray(blob[offset : offset + stride * count]), offset))
    data_order = sorted(range(1, len(items)), key=lambda index: (items[index].offset, index))
    _check_layout(items, data_order, type_names, blob, canonical_layout)
    references = _collect_references(data, sections, items, type_names, blob)
    model = HkxTagfileModel(
        sdk_version=sdk,
        type_section=data[sections["TYPE"][2] : sections["TYPE"][3]],
        type_names=type_names,
        items=items,
        data_order=data_order,
        references=references,
        has_patch_section="PTCH" in sections,
    )
    _check_reachability(model)
    return model


def _check_layout(
    items: Sequence[HkxTagfileItem], order: Sequence[int], type_names: Sequence[str], blob: bytes, canonical: bool
) -> None:
    cursor = 0
    for index in order:
        item = items[index]
        _, alignment = _layout_or_refuse(type_names[item.type_index], item.kind)
        expected = _align(cursor, alignment)
        if item.offset < cursor or item.offset % alignment:
            raise HkxTagfileRefused("bad_layout", f"Item {index} ({type_names[item.type_index]}) overlaps or is misaligned.")
        if canonical and item.offset != expected:
            raise HkxTagfileRefused(
                "unproven_layout",
                f"Item {index} ({type_names[item.type_index]}) starts at {item.offset}, the layout rule gives {expected}.",
            )
        if any(blob[cursor : item.offset]):
            raise HkxTagfileRefused("nonzero_padding", f"Padding before item {index} is not zero.")
        cursor = item.offset + len(item.payload)
    if (canonical and len(blob) != _align(cursor, HKX_DATA_END_ALIGNMENT)) or any(blob[cursor:]):
        raise HkxTagfileRefused("unproven_layout", "DATA does not end with zero padding to 16 bytes.")


def _collect_references(
    data: bytes,
    sections: Dict[str, Tuple[int, int, int, int]],
    items: Sequence[HkxTagfileItem],
    type_names: Sequence[str],
    blob: bytes,
) -> List[HkxTagfileReference]:
    starts = {}
    spans = []
    for index in range(1, len(items)):
        starts.setdefault(items[index].offset, index)
        spans.append((items[index].offset, items[index].offset + len(items[index].payload), index))
    spans.sort()

    def owner(word_offset: int, width: int) -> Tuple[int, int]:
        low, high = 0, len(spans)
        while low < high:
            middle = (low + high) // 2
            if spans[middle][0] <= word_offset:
                low = middle + 1
            else:
                high = middle
        if low:
            start, end, index = spans[low - 1]
            if word_offset + width <= end:
                return index, word_offset - start
        raise HkxTagfileRefused("bad_reference", f"Reference word at DATA {word_offset} lies outside every item.")

    references: List[HkxTagfileReference] = []
    patched: set[int] = set()
    if "PTCH" in sections:
        for patch_type, word_offset in _parse_patches(data, sections["PTCH"][2] + 8, sections["PTCH"][3]):
            source, local = owner(word_offset, 8)
            target = struct.unpack_from("<Q", blob, word_offset)[0]
            if not 0 <= target < len(items):
                raise HkxTagfileRefused("bad_reference", f"PTCH word at DATA {word_offset} names item {target}.")
            references.append(HkxTagfileReference(source, local, target, 8, patch_type=patch_type))
            patched.add(word_offset)
    for source in range(1, len(items)):
        item = items[source]
        specs = hkx_relative_slots(type_names[item.type_index])
        if not specs:
            continue
        stride = len(item.payload) // item.count
        for element in range(item.count):
            for spec in specs:
                local = element * stride + spec.offset
                word_offset = item.offset + local
                if word_offset in patched:
                    raise HkxTagfileRefused("bad_reference", f"Relative slot at DATA {word_offset} is also a PTCH entry.")
                value = struct.unpack_from("<q" if spec.width == 8 else "<i", blob, word_offset)[0]
                count = struct.unpack_from("<I", blob, item.offset + element * stride + spec.count_offset)[0] if spec.count_offset is not None else None
                count_local = element * stride + spec.count_offset if spec.count_offset is not None else None
                if value == 0:
                    if count:
                        raise HkxTagfileRefused("bad_reference", f"Null relative slot at DATA {word_offset} has count {count}.")
                    continue
                target = starts.get(word_offset + value)
                if target is None:
                    raise HkxTagfileRefused(
                        "bad_reference",
                        f"Relative slot {type_names[item.type_index]}+{spec.offset} at DATA {word_offset} does not land on an item.",
                    )
                if count is not None and count != items[target].count:
                    raise HkxTagfileRefused(
                        "bad_reference",
                        f"Relative array at DATA {word_offset} counts {count}, its item holds {items[target].count}.",
                    )
                references.append(HkxTagfileReference(source, local, target, spec.width, count_offset=count_local))
    return references


def _check_reachability(model: HkxTagfileModel) -> None:
    reached = {1}
    for reference in model.references:
        reached.add(reference.target_item)
    missing = [index for index in range(2, len(model.items)) if index not in reached]
    if missing:
        names = sorted({model.type_name(index) for index in missing})
        raise HkxTagfileRefused(
            "unreached_items",
            f"{len(missing)} item(s) are not reached by any known reference ({', '.join(names)}); "
            "an unlisted reference field may point at them.",
        )


def hkx_tagfile_item_offsets(model: HkxTagfileModel, extra_gap: int = 0) -> List[int]:
    offsets = [0] * len(model.items)
    cursor = 0
    for index in model.data_order:
        item = model.items[index]
        _, alignment = _layout_or_refuse(model.type_names[item.type_index], item.kind)
        offsets[index] = _align(cursor + extra_gap, alignment) if extra_gap else _align(cursor, alignment)
        cursor = offsets[index] + len(item.payload)
    return offsets


def _section(tag: str, flags: int, payload: bytes) -> bytes:
    size = len(payload) + 8
    return struct.pack(">I", (flags << 30) | size) + tag.encode("ascii") + payload


def serialize_hkx_tagfile_model(model: HkxTagfileModel, *, extra_gap: int = 0) -> bytes:
    """Lay the model out as a tagfile.

    ``extra_gap`` inserts that many zero bytes before every item; it exists so
    tests and the corpus harness can prove that references follow relocation.
    """

    validate_hkx_tagfile_model(model)
    offsets = hkx_tagfile_item_offsets(model, extra_gap)
    last = model.data_order[-1]
    end = offsets[last] + len(model.items[last].payload)
    blob = bytearray(_align(end, HKX_DATA_END_ALIGNMENT))
    for index in model.data_order:
        payload = model.items[index].payload
        blob[offsets[index] : offsets[index] + len(payload)] = payload
    patches: Dict[int, List[int]] = {}
    for reference in model.references:
        word_offset = offsets[reference.source_item] + reference.offset
        if reference.is_patch:
            struct.pack_into("<Q", blob, word_offset, reference.target_item)
            patches.setdefault(int(reference.patch_type), []).append(word_offset)
            continue
        relative = offsets[reference.target_item] - word_offset
        struct.pack_into("<q" if reference.width == 8 else "<i", blob, word_offset, relative)
        if reference.count_offset is not None:
            struct.pack_into("<I", blob, offsets[reference.source_item] + reference.count_offset, model.items[reference.target_item].count)
    item_table = bytearray(12)
    for index in range(1, len(model.items)):
        item = model.items[index]
        item_table += struct.pack("<3I", (item.kind << 24) | item.type_index, offsets[index], item.count)
    index_payload = _section("ITEM", _LEAF, bytes(item_table))
    if model.has_patch_section or patches:
        patch_table = bytearray()
        for patch_type in sorted(patches):
            words = sorted(patches[patch_type])
            patch_table += struct.pack("<2I", patch_type, len(words)) + struct.pack(f"<{len(words)}I", *words)
        index_payload += _section("PTCH", _LEAF, bytes(patch_table))
    body = (
        _section("SDKV", _LEAF, model.sdk_version)
        + _section("DATA", _LEAF, bytes(blob))
        + model.type_section
        + _section("INDX", _CONTAINER, index_payload)
    )
    return _section("TAG0", _CONTAINER, body)


def validate_hkx_tagfile_model(model: HkxTagfileModel) -> None:
    """Check the invariants the serializer relies on before any bytes are written."""

    if sorted(model.data_order) != list(range(1, len(model.items))):
        raise HkxTagfileRefused("bad_model", "Data order must name every item exactly once.")
    for index in range(1, len(model.items)):
        item = model.items[index]
        stride, _ = _layout_or_refuse(model.type_names[item.type_index], item.kind)
        if item.count < 1 or (item.kind == HKX_ITEM_KIND_OBJECT and item.count != 1):
            raise HkxTagfileRefused("bad_model", f"Item {index} has count {item.count}.")
        if len(item.payload) != stride * item.count:
            raise HkxTagfileRefused("bad_model", f"Item {index} payload is not count x stride bytes.")
    for reference in model.references:
        if not 0 < reference.source_item < len(model.items) or not 0 <= reference.target_item < len(model.items):
            raise HkxTagfileRefused("bad_model", "A reference names a missing item.")
        if reference.offset + reference.width > len(model.items[reference.source_item].payload):
            raise HkxTagfileRefused("bad_model", "A reference word lies outside its item.")
        if not reference.is_patch and reference.target_item == 0:
            raise HkxTagfileRefused("bad_model", "A relative reference cannot name the null item.")


def hkx_tagfile_reference_graph(model: HkxTagfileModel) -> List[Tuple[int, int, int, Optional[int], Optional[int]]]:
    """Layout-independent view of the references, used to compare relocated models."""

    return sorted(
        (reference.source_item, reference.offset, reference.target_item, reference.patch_type, reference.count_offset)
        for reference in model.references
    )


def hkx_tagfile_masked_payloads(model: HkxTagfileModel) -> List[bytes]:
    """Item payloads with every reference word (and mirrored count) zeroed."""

    masked = [bytearray(item.payload) for item in model.items]
    for reference in model.references:
        masked[reference.source_item][reference.offset : reference.offset + reference.width] = bytes(reference.width)
        if reference.count_offset is not None:
            masked[reference.source_item][reference.count_offset : reference.count_offset + 4] = bytes(4)
    return [bytes(payload) for payload in masked]


def copy_hkx_tagfile_model(model: HkxTagfileModel) -> HkxTagfileModel:
    return replace(
        model,
        items=[replace(item, payload=bytearray(item.payload)) for item in model.items],
        data_order=list(model.data_order),
        references=list(model.references),
    )


def iter_hkx_items_of_type(model: HkxTagfileModel, type_name: str) -> Iterable[int]:
    return (index for index in range(1, len(model.items)) if model.type_name(index) == type_name)
