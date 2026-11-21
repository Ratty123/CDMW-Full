"""Synthesised prefabs whose `_components` hold objects with speed values.

Written to the same grammar as tests/test_prefab_component_graft.py's builder: a root
SceneObject with one `_components` collection, one element per component.
"""

from __future__ import annotations

import struct

from cdmw.core.prefab_binary import KIND_COLLECTION


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _member(name: str, type_name: str, size: int) -> bytes:
    return _text(name) + _text(type_name) + struct.pack("<HHHH", 0, size, 0, 0)


def _type(name: str, *members: bytes) -> bytes:
    return _text(name) + struct.pack("<H", len(members)) + b"".join(members)


_FORMATS = {"float": ("<f", 4), "float3": ("<3f", 12)}


def build_speed_prefab(components, *, absent=()) -> bytes:
    """`components`: [(type name, [(member, "float" | "float3", value), ...]), ...].

    A member named in `absent` is declared by its type but not held by the object.
    """

    types = bytearray(_type("SceneObject", _text("_components") + _text("ReflectObjectPtr")
                            + struct.pack("<HHHH", KIND_COLLECTION, 0, 0, 0)))
    for type_name, members in components:
        types += _type(type_name, *(_member(name, kind, _FORMATS[kind][1]) for name, kind, _value in members))
    header = bytearray(struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8)
    header += struct.pack("<I", 15) + struct.pack("<H", 1 + len(components)) + types
    pool = struct.pack("<I", 0)
    base = len(header) + len(pool) + 28
    out = bytearray()
    out += struct.pack("<H", 2) + (0b1).to_bytes(6, "little")
    out += b"\x00" + struct.pack("<I", len(components))
    for number, (type_name, members) in enumerate(components):
        mask = sum(1 << bit for bit, (name, _kind, _value) in enumerate(members) if name not in absent)
        out += struct.pack("<H", 1) + bytes((mask, number + 1, 0, 0))
        out += b"\x00" * 8
        out += struct.pack("<I", base + len(out) + 4)
        name_start = base + len(out)
        out += struct.pack("<HHH", 0, 1, 0) + _text(f"{type_name}_{number}")
        for name, kind, value in members:
            if name in absent:
                continue
            fmt = _FORMATS[kind][0]
            out += struct.pack(fmt, *(value if isinstance(value, tuple) else (value,)))
        out += struct.pack("<I", base + len(out) - name_start)
    out += b"\x01"
    data_header = struct.pack("<III", 1, base + len(out), 0) + struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", base, len(out))
    return bytes(header + pool + data_header + out)
