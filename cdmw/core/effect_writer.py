"""Structural effect serialization with typed values and rebuilt self pointers.

The type table and collection metadata travel with a decoded graph. Unknown
collection lookup tables may round-trip, but cannot be resized speculatively.
"""
from __future__ import annotations

import struct

from cdmw.core.effect_binary import (
    ATTR_NOT_SERIALISED, CONTAINER_KINDS, EffectBinaryError, EffectDocument,
    ReflectNode, ReflectValue, decode_effect_binary,
)
from cdmw.core.prefab_binary import STRING_POOL_MIN_REVISION, read_reflect_header
from cdmw.core.prefab_component_graft import encode_prefab_type


def _text(value: str) -> bytes:
    raw = value.encode("utf-8", "strict")
    if len(raw) > 4096:
        raise EffectBinaryError("Effect strings cannot exceed 4096 bytes.")
    return struct.pack("<I", len(raw)) + raw


class _Writer:
    def __init__(self, types, base: int):
        self.types = {t.type_name: (i, t) for i, t in enumerate(types)}
        if len(self.types) != len(types):
            raise EffectBinaryError("Effect type names must be unique.")
        self.base = base
        self.out = bytearray()
        self.nodes = 0

    def node(self, node: ReflectNode, *, root=False, with_ids=False, depth=0):
        self.nodes += 1
        if self.nodes > 100000 or depth > 64:
            raise EffectBinaryError("Effect graph exceeds its node or nesting limit.")
        if node.type_name not in self.types:
            raise EffectBinaryError(f"Undeclared effect type: {node.type_name}")
        type_index, kind = self.types[node.type_name]
        values, children = {v.name: v for v in node.values}, dict(node.children)
        if len(values) != len(node.values) or len(children) != len(node.children):
            raise EffectBinaryError("An effect member cannot appear twice.")
        known = {m.name for m in kind.members}
        if (set(values) | set(children)) - known:
            raise EffectBinaryError(f"{node.type_name} contains undeclared members.")
        mask = node.mask
        for i, member in enumerate(kind.members):
            if member.attr_flags & ATTR_NOT_SERIALISED or member.flags in CONTAINER_KINDS:
                continue
            if member.name in values or member.name in children:
                mask |= 1 << i
            elif member.flags not in CONTAINER_KINDS:
                mask &= ~(1 << i)
        width = max(int(node.wire.get("width", 1)), max(1, (mask.bit_length() + 7) // 8))
        if width > 8:
            raise EffectBinaryError("Effect presence mask exceeds 64 fields.")
        self.out += struct.pack("<H", width) + mask.to_bytes(width, "little") + struct.pack("<HB", type_index, node.override)
        if root:
            self.out += b"\x00"
            pointee = None
        else:
            if with_ids:
                self.out += struct.pack("<I", node.wire.get("element_id") or 0)
            self.out += struct.pack("<Q", node.wire.get("owner", 0xffffffffffffffff))
            self.out += struct.pack("<I", self.base + len(self.out) + 4)
            pointee = len(self.out)
            has_name = bool(node.name) or node.wire.get("has_name", False)
            self.out += struct.pack("<HH", node.wire.get("z", 0), int(has_name))
            if has_name:
                self.out += struct.pack("<H", node.wire.get("name_tag", 0)) + _text(node.name)
        for i, member in enumerate(kind.members):
            if member.attr_flags & ATTR_NOT_SERIALISED:
                continue
            key, flag = member.name, member.flags
            value, child = values.get(key), children.get(key)
            if flag in CONTAINER_KINDS:
                info = node.wire.get(key, {})
                null = child is None if flag in (6, 7) else value is None or info.get("null", False)
                self.out += bytes([int(null)])
                if null:
                    continue
                if flag in (3, 10):
                    count = value.count
                    if not 0 <= count <= 100000 or (flag == 3 and len(value.raw) != count * member.value_size):
                        raise EffectBinaryError(f"Invalid array size for {key}.")
                    self.out += struct.pack("<I", count) + value.raw
                else:
                    if not isinstance(child, tuple) or len(child) > 100000:
                        raise EffectBinaryError(f"Invalid collection {key}.")
                    pairs = info.get("pairs", b"")
                    if pairs and len(child) != info.get("count", len(child)):
                        raise EffectBinaryError(f"{key} has a collection lookup table whose resize is not understood.")
                    if pairs and any(a >= len(child) or b >= len(child) for a, b in struct.iter_unpack('<II', pairs)):
                        raise EffectBinaryError(f'{key} contains unrecognized collection lookup metadata.')
                    ids = info.get("with_ids", 0)
                    self.out += struct.pack("<IBIII", len(child), ids, info.get("a", 0), info.get("b", 0), len(pairs) // 8) + pairs
                    for item in child:
                        self.node(item, with_ids=bool(ids), depth=depth + 1)
            elif mask & (1 << i):
                if flag in (0, 2):
                    if value is None or value.kind != flag or len(value.raw) != member.value_size:
                        raise EffectBinaryError(f"Invalid typed value for {key}.")
                    self.out += value.raw
                elif flag == 1:
                    if value is None:
                        raise EffectBinaryError(f"Missing string {key}.")
                    self.out += _text(str(value.value))
                elif flag in (4, 5):
                    if flag == 5:
                        self.out += bytes([int(child is not None)])
                    if child is not None:
                        self.node(child, depth=depth + 1)
                    elif flag == 4:
                        raise EffectBinaryError(f"Missing object {key}.")
                else:
                    raise EffectBinaryError(f"Unsupported effect member kind {flag}.")
        if pointee is not None:
            self.out += struct.pack("<I", len(self.out) - pointee)


def serialize_effect(source: bytes, document: EffectDocument) -> bytes:
    """Serialize an edited graph, including variable strings, arrays and collections."""
    if not document.walk_complete:
        raise EffectBinaryError("An incomplete effect graph cannot be serialized.")
    original = decode_effect_binary(source)
    if not original.walk_complete:
        raise EffectBinaryError(original.walk_note)
    if original.blob_offset + original.blob_length != len(source):
        raise EffectBinaryError('Trailing effect data has no verified relocation contract.')
    base = original.container_offset
    header = read_reflect_header(source[base:])
    type_start = 20 if header.version == 4 else 12
    prefix = bytearray(source[base:base + type_start - 2])
    if not 0 < len(document.types) <= 65535:
        raise EffectBinaryError("Invalid number of effect types.")
    prefix += struct.pack("<H", len(document.types))
    prefix += b"".join(encode_prefab_type(t) for t in document.types)
    if header.revision >= STRING_POOL_MIN_REVISION:
        prefix += struct.pack("<I", len(document.string_pool))
        prefix += b"".join(_text(s) for s in document.string_pool)
    data_header = bytearray(source[original.blob_offset - 28:original.blob_offset])
    blob_start = len(prefix) + 28
    writer = _Writer(document.types, blob_start)
    writer.node(document.root, root=True)
    struct.pack_into("<I", data_header, 4, blob_start + len(writer.out))
    struct.pack_into("<II", data_header, 20, blob_start, len(writer.out))
    result = source[:base] + prefix + data_header + writer.out
    checked = decode_effect_binary(result)
    if not checked.walk_complete:
        raise EffectBinaryError(f"Serialized effect failed readback: {checked.walk_note}")
    return bytes(result)


def set_typed_value(document: EffectDocument, node: ReflectNode, name: str, value) -> bool:
    """Set a declared value, including an absent override. Return False if undeclared."""
    kind = next((t for t in document.types if t.type_name == node.type_name), None)
    member = next((m for m in kind.members if m.name == name), None) if kind else None
    if member is None or member.attr_flags & ATTR_NOT_SERIALISED:
        return False
    formats = {"float": "f", "float2": "2f", "float3": "3f", "float4": "4f", "bool": "?", "int": "i", "int32": "i", "uint": "I", "uint32": "I"}
    if member.flags == 1:
        raw = str(value).encode("utf-8")
    elif member.type_name in formats:
        args = value if isinstance(value, (tuple, list)) else (value,)
        if member.type_name in ("int", "int32", "uint", "uint32"):
            args = tuple(int(round(v)) for v in args)
        raw = struct.pack("<" + formats[member.type_name], *args)
    else:
        raise EffectBinaryError(f"{name} is not an editable numeric or string field.")
    entry = ReflectValue(name, member.type_name, member.flags, raw, 0)
    node.values[:] = [v for v in node.values if v.name != name] + [entry]
    return True
