from __future__ import annotations

from typing import Mapping, Tuple


_HKX_SCALAR_ARRAY_TYPES: Mapping[str, Tuple[str, str, str, int, str]] = {
    "unsigned char": (
        "uint8_values",
        "uint8[]",
        "B",
        1,
        "Read-only unsigned-byte array. These records commonly back compact flags, shape-key bytes, or mesh/physics index data.",
    ),
    "unsigned short": (
        "uint16_values",
        "uint16[]",
        "<H",
        2,
        "Read-only unsigned-short array. These records commonly store compact indices, flags, or mesh/physics lookup values.",
    ),
    "hkUint16": (
        "uint16_values",
        "uint16[]",
        "<H",
        2,
        "Read-only Havok hkUint16 array. Corpus scans show these often carry compact mesh, animation, or shape index streams.",
    ),
    "unsigned int": (
        "uint32_values",
        "uint32[]",
        "<I",
        4,
        "Read-only unsigned-int array. These records commonly store references, flags, counts, shape keys, or table words.",
    ),
    "hkUint32": (
        "uint32_values",
        "uint32[]",
        "<I",
        4,
        "Read-only Havok hkUint32 array. These records commonly store large index streams, table words, flags, or packed IDs.",
    ),
    "hkInt32": (
        "int32_values",
        "int32[]",
        "<i",
        4,
        "Read-only Havok hkInt32 array. These records commonly store signed animation, mesh, mapper, or sparse key values.",
    ),
    "float": (
        "float32_values",
        "float32[]",
        "<f",
        4,
        "Read-only float array. These records commonly store animation curves, weights, or mesh/user-channel values.",
    ),
    "hkBool": (
        "bool_values",
        "bool[]",
        "B",
        1,
        "Read-only Havok hkBool array. These records commonly store compact animation, visibility, or feature flags.",
    ),
    "unsigned long long": (
        "uint64_values",
        "uint64[]",
        "<Q",
        8,
        "Read-only unsigned 64-bit array. These records commonly store large identifiers, masks, or packed references.",
    ),
    "long long": (
        "int64_values",
        "int64[]",
        "<q",
        8,
        "Read-only signed 64-bit array. These records are exported for comparison and reference recovery.",
    ),
}


_HKX_ENUM_RECORD_TYPES: Mapping[str, str] = {
    "hknpShapeType::Enum": "Shape kind enum values used by hknp shapes.",
    "hknpCollisionDispatchType::Enum": "Collision dispatch enum values used by hknp broad/narrow phase routing.",
    "hknpShape::FlagsEnum": "Shape flag bitfields used by hknp shape records.",
    "hkcdSimdTreeNamespace::Node::FlagsEnum": "Spatial tree node flag bitfields.",
}
