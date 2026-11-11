"""Constrained PASEQ decal edits; preserve the sequence's original wire bytes.

The supplied metadata-3 / serialization-13,14 sequences have a 16-byte prefix,
an indexed shared-string table and an empty trailing reflection container.
Only present decal values are editable. Strings get their own pool reference;
editing one reference never changes other users of the same pooled string.

Collection revision boundaries were cross-checked with LukeFZ/pycrimson's
MIT-licensed reflection parser; the walk reuses CDMW's existing effect grammar.
"""
from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass
from typing import Mapping

from cdmw.core.effect_binary import (
    EffectBinaryError, ReflectNode, ReflectValue, _Walker,
)
from cdmw.core.prefab_binary import PrefabBinaryError, _Reader, _read_types


class SkinnedDecalError(ValueError):
    """The sequence or requested edit is outside the proven writer contract."""


_OWNERS = frozenset({"GameSkinnedDecalEventData", "SkinnedDecalProperty", "SkinnedDecalDynamicProperty"})
_TEXTURES = frozenset({"_decalDiffuseTexture", "_decalNormalTexture", "_decalMaterialTexture", "_decalMaskTexture"})
_FORMATS = {"float": "f", "float2": "2f", "float3": "3f", "float4": "4f", "Transform": "10f",
            "int32": "i", "uint32": "I", "int16": "h", "uint16": "H", "int8": "b", "uint8": "B"}


@dataclass(frozen=True)
class DecalField:
    path: str
    owner: str
    name: str
    type_name: str
    kind: int
    offset: int
    wire_size: int
    raw: bytes
    value: object

    def text(self) -> str:
        return self.value if isinstance(self.value, str) else json.dumps(self.value, allow_nan=False)


@dataclass(frozen=True)
class SkinnedDecalDocument:
    source: bytes
    revision: int
    fields: tuple[DecalField, ...]


class _SequenceWalker(_Walker):
    def __init__(self, data, types, offset, length, pool, revision):
        super().__init__(data, 16, types, offset, length, container_flags=False)
        self.pool = pool
        self.revision = revision
        self.pointer_sites: list[int] = []
        self.length_sites: list[tuple[int, int]] = []
        self.string_spans: dict[int, int] = {}

    def text(self):
        at = self.pos
        key = self.u32()
        if key == 0xFFFFFFFF:
            raw, _ = super().text()
            self.string_spans[at] = self.pos - at
            return raw, at
        if key not in self.pool:
            raise EffectBinaryError(f"Unknown shared string {key} at {at}.")
        self.string_spans[at] = 4
        return self.pool[key].encode("utf-8"), at

    def read_record(self, what):
        self.pointer_sites.append(self.pos + 8)
        return super().read_record(what)

    def read_length(self, pointee, what):
        self.length_sites.append((self.pos, pointee))
        return super().read_length(pointee, what)

    def read_member(self, node, member, path, depth):
        if member.flags == 1:
            at = self.pos
            raw, _ = self.text()
            node.values.append(ReflectValue(member.name, member.type_name, 1, raw, at))
            return
        return super().read_member(node, member, path, depth)

    def read_container(self, node, member, path, depth):
        if self.revision >= 14 or member.flags not in (6, 7):
            return super().read_container(node, member, path, depth)
        count = self.u32()
        if count > 100000:
            raise EffectBinaryError("Sequence collection exceeds its limit.")
        a, b, lookup_count = self.u32(), self.u32(), self.u32()
        if lookup_count > 100000:
            raise EffectBinaryError("Sequence collection lookup exceeds its limit.")
        self._need(lookup_count * 8, "collection lookup")
        self.pos += lookup_count * 8
        node.wire[member.name] = {"count": count, "a": a, "b": b}
        node.children.append((member.name, tuple(
            self.read_element(f"{path}.{member.name}[{i}]", False, depth + 1) for i in range(count))))


def _nodes(node, path="[0]"):
    yield path, node
    for name, child in node.children:
        if isinstance(child, ReflectNode):
            yield from _nodes(child, path + "." + name)
        elif isinstance(child, tuple):
            for index, item in enumerate(child):
                yield from _nodes(item, f"{path}.{name}[{index}]")


def _signature(root):
    return tuple((path, node.type_name, node.name, node.mask, node.override,
                  tuple((v.name, v.type_name, v.kind, v.count, v.raw) for v in node.values),
                  tuple((name, None if child is None else len(child) if isinstance(child, tuple) else 1)
                        for name, child in node.children)) for path, node in _nodes(root))


def _value(value):
    if value.kind == 1:
        return value.raw.decode("utf-8", "strict")
    if value.type_name == "Color" and len(value.raw) == 4:
        return "#" + value.raw.hex()
    if value.type_name == "bool" and value.raw in (b"\x00", b"\x01"):
        return bool(value.raw[0])
    if value.kind == 2 and len(value.raw) in (1, 2, 4):
        return int.from_bytes(value.raw, "little")
    fmt = _FORMATS.get(value.type_name)
    if fmt and struct.calcsize("<" + fmt) == len(value.raw):
        result = struct.unpack("<" + fmt, value.raw)
        if all(not isinstance(v, float) or math.isfinite(v) for v in result):
            return result[0] if len(result) == 1 else result
    return None


def _parse(source):
    if len(source) > 8 * 1024 * 1024 or len(source) < 44:
        raise SkinnedDecalError("Sequence size is outside the supported range.")
    reader = _Reader(source, 16)
    magic, version, flags, revision = reader.u16(), reader.u16(), reader.u16(), reader.u32()
    if (magic, version, flags) != (0xFFFF, 3, 0) or revision not in (13, 14):
        raise SkinnedDecalError("Only metadata 3, serialization 13/14 PASEQ decals are supported.")
    count = reader.u16()
    if not 0 < count <= 4096:
        raise SkinnedDecalError("Invalid sequence type count.")
    types = _read_types(reader, count)
    if types[0].type_name != "Sequencer":
        raise SkinnedDecalError("The selected file is not a supported sequence.")
    if revision == 14 and reader.u32() != 0:
        raise SkinnedDecalError("Named-object tables are not supported for decal editing.")
    pool_count_site = reader.pos
    count = reader.u32()
    if not 0 < count <= 100000:
        raise SkinnedDecalError("Invalid sequence string count.")
    pool = {}
    for _ in range(count):
        key, text = reader.u32(), reader.text(limit=4096)
        if key in pool or key >= 0x7FFFFFFF:
            raise SkinnedDecalError("Invalid or duplicate shared-string identifier.")
        pool[key] = text
    header_site = reader.pos
    if header_site + 28 > len(source):
        raise SkinnedDecalError("Truncated sequence object directory.")
    roots, end, root_type, owner, offset, length = struct.unpack_from("<IIIQII", source, header_site)
    if (roots, root_type, owner) != (1, 0, 0xFFFFFFFFFFFFFFFF) or offset != header_site + 28 - 16 or end != offset + length:
        raise SkinnedDecalError("Unsupported sequence object directory.")
    trailer = struct.pack("<HHHIH", 0xFFFF, 3, 0, revision, 0)
    trailer += bytes(12 if revision == 14 else 8) + struct.pack("<I", 28 if revision == 14 else 24)
    if source[16 + end:] != trailer:
        raise SkinnedDecalError("The sequence has an unsupported trailing container.")
    walker = _SequenceWalker(source, types, offset, length, pool, revision)
    root = walker.read_root()
    if walker.pos != walker.end:
        raise SkinnedDecalError("Sequence data was not completely decoded.")
    kinds = {kind.type_name: kind for kind in types}
    fields = []
    for path, node in _nodes(root):
        texture = node.type_name == "ResourceReferencePath_ITexture" and any(
            path.endswith("._skinnedDecalProperty." + name) for name in _TEXTURES)
        if node.type_name not in _OWNERS and not texture:
            continue
        members = {m.name: m for m in kinds[node.type_name].members}
        for value in node.values:
            member = members[value.name]
            decoded = _value(value)
            if decoded is None or member.attr_flags & 0x82 or (texture and value.name != "_path"):
                continue
            fields.append(DecalField(path + "." + value.name, node.type_name, value.name,
                                     value.type_name, value.kind, value.offset,
                                     walker.string_spans.get(value.offset, len(value.raw)), value.raw, decoded))
    if not fields:
        raise SkinnedDecalError("No editable skinned decal settings were found in this sequence.")
    return SkinnedDecalDocument(source, revision, tuple(fields)), root, walker, pool, pool_count_site, header_site


def read_skinned_decal(source: bytes) -> SkinnedDecalDocument:
    try:
        return _parse(bytes(source))[0]
    except (EffectBinaryError, PrefabBinaryError, struct.error, UnicodeError) as exc:
        raise SkinnedDecalError(f"Cannot edit this sequence: {exc}") from exc


def encode_decal_value(field: DecalField, text: str) -> bytes:
    """Validate one editor value without walking or writing the sequence."""
    if field.kind == 1:
        raw = text.encode("utf-8", "strict")
        if not raw or len(raw) > 4096 or any(c in text for c in ("\x00", "\n", "\r")):
            raise SkinnedDecalError("Texture references must be nonempty single-line UTF-8 paths of at most 4096 bytes.")
        if field.name == "_path" and (not text.lower().endswith(".dds") or "\\" in text or ":" in text or text.startswith("/") or ".." in text.split("/")):
            raise SkinnedDecalError("Use a relative game texture path ending in .dds, with forward slashes.")
        return raw
    if field.type_name == "Color":
        if not re.fullmatch(r"#[0-9a-fA-F]{8}", text):
            raise SkinnedDecalError("Color must contain eight hexadecimal digits: #RRGGBBAA.")
        return bytes.fromhex(text[1:])
    try:
        value = json.loads(text)
        if field.type_name == "bool":
            if type(value) is not bool:
                raise ValueError("Expected true or false.")
            return bytes([value])
        values = value if isinstance(value, list) else [value]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError("Values must be finite numbers.")
        if field.kind == 2:
            if len(values) != 1 or type(value) is not int:
                raise ValueError("Expected an integer.")
            return value.to_bytes(len(field.raw), "little")
        fmt = _FORMATS[field.type_name]
        if not fmt.endswith("f") and any(type(v) is not int for v in values):
            raise ValueError("Expected an integer.")
        raw = struct.pack("<" + fmt, *values)
        if fmt.endswith("f") and not all(math.isfinite(v) for v in struct.unpack("<" + fmt, raw)):
            raise ValueError("Value is outside the float32 range.")
        return raw
    except (ValueError, TypeError, OverflowError, struct.error) as exc:
        raise SkinnedDecalError(f"Invalid value for {field.name}: {exc}") from exc


def write_skinned_decal(document: SkinnedDecalDocument, changes: Mapping[str, str]) -> bytes:
    """Edit existing fields only; no record insertion or default materialization."""
    parsed, root, walker, pool, pool_site, header_site = _parse(document.source)
    fields = {f.path: f for f in parsed.fields}
    if changes.keys() - fields.keys():
        raise SkinnedDecalError("An edited setting is absent or not editable in the original sequence.")
    source = document.source
    patches = []
    additions = bytearray()
    expected = {f.path: f.raw for f in parsed.fields}
    for path, text in changes.items():
        field = fields[path]
        raw = encode_decal_value(field, text)
        if raw == field.raw:
            continue
        expected[path] = raw
        if field.kind == 1:
            value = raw.decode("utf-8")
            key = next((key for key, entry in pool.items() if entry == value), None)
            if key is None:
                key = max(pool) + 1
                pool[key] = value
                additions += struct.pack("<II", key, len(raw)) + raw
            patches.append((field.offset, field.wire_size, struct.pack("<I", key)))
        else:
            patches.append((field.offset, len(field.raw), raw))
    shift = len(additions)
    if shift:
        patches.append((pool_site, 4, struct.pack("<I", len(pool))))
        patches.append((header_site, 0, bytes(additions)))
    resized = [(at, len(raw) - size) for at, size, raw in patches if len(raw) != size]

    def displacement(site):
        return sum(delta for at, delta in resized if at < site)

    if resized:
        for site in walker.pointer_sites:
            patches.append((site, 4, struct.pack("<I", site + displacement(site) + 4 - 16)))
        for site, start in walker.length_sites:
            patches.append((site, 4, struct.pack("<I", site - start + displacement(site) - displacement(start))))
        for site, delta in ((header_site + 4, sum(d for _, d in resized)),
                            (header_site + 20, shift),
                            (header_site + 24, sum(d for _, d in resized) - shift)):
            patches.append((site, 4, struct.pack("<I", struct.unpack_from("<I", source, site)[0] + delta)))
    output = bytearray()
    cursor = 0
    for at, size, raw in sorted(patches):
        if at < cursor:
            raise SkinnedDecalError("Sequence edits overlap.")
        output.extend(source[cursor:at])
        output.extend(raw)
        cursor = at + size
    output.extend(source[cursor:])
    result = bytes(output)
    check, new_root, *_ = _parse(result)
    if {f.path: f.raw for f in check.fields} != expected:
        raise SkinnedDecalError("The saved sequence did not retain the requested settings.")
    # Compare every decoded record, including omitted/present masks, against the
    # original with only the requested leaf values substituted.
    for path, node in _nodes(root):
        for i, value in enumerate(node.values):
            key = path + "." + value.name
            if key in expected:
                node.values[i] = ReflectValue(value.name, value.type_name, value.kind, expected[key], value.offset, value.count)
    if _signature(root) != _signature(new_root):
        raise SkinnedDecalError("An unrelated sequence property changed during saving.")
    return result
