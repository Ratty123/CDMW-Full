"""Read and reduce existing PAC render-cloth bindings without editing physics."""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping

from cdmw.domain.mesh.cloth import PacClothRule
from .mesh_parser import (
    PAC_SKIN_EXTRA_INDEX_SENTINEL,
    _find_pac_descriptors, _parse_pac_geometry_section, _parse_par_sections,
    _validated_pac_descriptor_prefix,
)


def pac_cloth_binding(data: bytes, offset: int):
    """Return (skeletal blend, guide indices, raw guide weights), or None.

    Four guide indices are fetched even when their individual weight is zero.
    They deliberately never enter the decoded skeleton's bone-weight list.
    """
    if offset < 0 or offset + 40 > len(data):
        raise ValueError("Cloth binding is outside its PAC vertex record.")
    blend = data[offset + 39] & 63
    if blend == 63:
        return None
    group = struct.unpack_from("<I", data, offset + 24)[0]
    extra = struct.unpack_from("<2e", data, offset + 12)
    if any(not math.isfinite(v) or v < 0 or v > 1023 for v in extra):
        raise ValueError("The PAC contains an invalid cloth-guide index.")
    indices = ((group >> 10) & 1023, (group >> 20) & 1023,
               *(math.floor(v + 0.5) for v in extra))
    weights = tuple(data[offset + 32:offset + 36])
    if not sum(weights) or not sum(data[offset + 28:offset + 32]):
        raise ValueError("Cloth editing requires both skeletal and guide weights.")
    return blend, indices, weights


def pac_cloth_lods(data: bytes):
    """Require the known 40-byte PAC layout at every stored LOD."""
    if data[:4] != b"PAR ":
        raise ValueError("Cloth editing requires an original PAC mesh.")
    sections = _parse_par_sections(data)
    by_index = {row["index"]: row for row in sections}
    for section in sections:
        if section["index"] > 4:
            continue
        stored_size = struct.unpack_from("<I", data, 0x10 + section["index"] * 8)[0]
        if (stored_size not in (0, section["size"])
                or section["offset"] + section["size"] > len(data)):
            raise ValueError("Cloth editing requires complete, decoded PAC sections at every LOD.")
    metadata = by_index.get(0)
    if metadata is None or metadata["size"] < 5:
        raise ValueError("Cloth editing requires readable PAC descriptors.")
    count = data[metadata["offset"] + 4]
    if not 1 <= count <= 4:
        raise ValueError("This PAC LOD layout does not support cloth editing.")
    descriptors = _validated_pac_descriptor_prefix(
        _find_pac_descriptors(data, metadata["offset"], metadata["size"], count),
        sections, filename="cloth.pac",
    )
    if not descriptors:
        raise ValueError("Cloth editing requires the known 40-byte PAC layout.")
    levels = []
    seen_offsets = set()
    for lod in range(count):
        section = by_index.get(4 - lod)
        if section is None:
            raise ValueError(f"Cloth editing cannot read PAC LOD {lod}.")
        mesh = _parse_pac_geometry_section(data, "cloth.pac", descriptors, section, lod)
        if len(mesh.submeshes) != len(descriptors):
            raise ValueError(f"Cloth editing cannot map every part in PAC LOD {lod}.")
        for part, descriptor in zip(mesh.submeshes, descriptors, strict=True):
            if (part.source_vertex_stride != 40 or len(part.vertices) != descriptor.vertex_counts[lod]
                    or len(part.source_vertex_offsets) != len(part.vertices)):
                raise ValueError(f"Cloth editing cannot prove the vertex records in PAC LOD {lod}.")
            offsets = set(part.source_vertex_offsets)
            if len(offsets) != len(part.vertices) or offsets & seen_offsets:
                raise ValueError("Cloth editing does not support shared PAC vertex records.")
            seen_offsets.update(offsets)
        levels.append(mesh)
    return tuple(levels)


def apply_pac_cloth_rules(data: bytes, rules: Mapping[int, PacClothRule], *, appearance=None) -> bytes:
    """Patch only the cloth-owned lanes, against an unmodified output baseline.

    Rebuilding always starts from the retained source. Reset, undo and draft
    reopening therefore restore original guide bindings rather than inventing
    them from the zeroed fields of a disabled output record.
    """
    if not rules:
        return data
    levels = pac_cloth_lods(data)
    if any(type(index) is not int or not 0 <= index < len(levels[0].submeshes)
           or not isinstance(rule, PacClothRule) for index, rule in rules.items()):
        raise ValueError("Cloth settings refer to an invalid PAC part.")
    result = bytearray(data)
    bound = {index: 0 for index in rules}
    for level in levels:
        displayed = appearance.to_neutral(level) if appearance is not None else level
        for index, rule in rules.items():
            part = level.submeshes[index]
            for position, offset in zip(displayed.submeshes[index].vertices, part.source_vertex_offsets, strict=True):
                binding = pac_cloth_binding(data, offset)
                if binding is None:
                    continue
                bound[index] += 1
                blend = rule.blend(binding[0], position[1])
                if blend == binding[0]:
                    continue
                if blend == 63:
                    # The ordinary branch can read six skeletal slots. Clear
                    # both reinterpreted guide slots, including zero-weight
                    # fetches, while preserving bone four and the foreign bits.
                    group = struct.unpack_from("<I", data, offset + 24)[0]
                    struct.pack_into("<I", result, offset + 24, group & 0xC00003FF)
                    result[offset + 12:offset + 16] = PAC_SKIN_EXTRA_INDEX_SENTINEL
                    result[offset + 32:offset + 36] = bytes(4)
                result[offset + 39] = (data[offset + 39] & 0xC0) | blend
    if any(not count for count in bound.values()):
        raise ValueError("A selected part has no retained cloth bindings in its output. Restore its source skinning before editing cloth.")
    return bytes(result)
