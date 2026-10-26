"""What the exact PAC skin writer can store in place, without Qt or a session.

The writer patches only the LOD 0 skin lanes of unchanged 40-byte
``pac_slot_u10x6`` records. A Part qualifies when its topology, source vertex
map, offsets and palette are those of the original parse, and every row uses
one to its record's capacity of unique in-palette slots with finite,
non-negative weights summing to one. A record holds six skeletal influences, or
four when its cloth gate marks it as simulated.
"""

from __future__ import annotations

import math

from cdmw.modding.mesh_parser import (
    PAC_SKIN_GATE_DISABLED,
    PAC_SKIN_GATE_MASK,
    PAC_SKIN_GATE_OFFSET,
    PAC_SKIN_PALETTE_SLOTS,
    PAC_SKIN_WEIGHT_LAYOUT,
)


def pac_skin_row_capacity(original_data: bytes, offset: int) -> int:
    """Skeletal influences the record at ``offset`` holds."""
    gate = original_data[offset + PAC_SKIN_GATE_OFFSET] & PAC_SKIN_GATE_MASK
    return PAC_SKIN_PALETTE_SLOTS if gate == PAC_SKIN_GATE_DISABLED else 4


def pac_skin_part_layout_matches(original: object, current: object, original_data: bytes) -> bool:
    """``current`` keeps ``original``'s topology, identity source map, palette and 40-byte records."""
    original_vertices = tuple(getattr(original, "vertices", ()) or ())
    vertices = tuple(getattr(current, "vertices", ()) or ())
    if not vertices or len(vertices) != len(original_vertices):
        return False
    if tuple(getattr(current, "faces", ()) or ()) != tuple(getattr(original, "faces", ()) or ()):
        return False
    identity = tuple(range(len(vertices)))
    if tuple(getattr(original, "source_vertex_map", ()) or ()) != identity:
        return False
    if tuple(getattr(current, "source_vertex_map", ()) or ()) != identity:
        return False
    if tuple(getattr(current, "source_bone_palette", ()) or ()) != tuple(
        getattr(original, "source_bone_palette", ()) or ()
    ):
        return False
    for part in (original, current):
        if str(getattr(part, "source_skin_weight_layout", "") or "") != PAC_SKIN_WEIGHT_LAYOUT:
            return False
        if int(getattr(part, "source_vertex_stride", 0) or 0) != 40:
            return False
    original_offsets = tuple(getattr(original, "source_vertex_offsets", ()) or ())
    current_offsets = tuple(getattr(current, "source_vertex_offsets", ()) or ())
    if current_offsets != original_offsets or len(original_offsets) != len(vertices):
        return False
    try:
        return not any(int(offset) < 0 or int(offset) + 40 > len(original_data) for offset in original_offsets)
    except (TypeError, ValueError, OverflowError):
        return False


def pac_skin_rows_safe(submesh: object, vertex_count: int, palette_size: int, original_data: bytes) -> bool:
    """Every row of ``submesh`` fits its record and the palette."""
    index_rows = tuple(getattr(submesh, "bone_indices", ()) or ())
    weight_rows = tuple(getattr(submesh, "bone_weights", ()) or ())
    offsets = tuple(getattr(submesh, "source_vertex_offsets", ()) or ())
    if not len(index_rows) == len(weight_rows) == len(offsets) == vertex_count:
        return False
    for raw_indices, raw_weights, raw_offset in zip(index_rows, weight_rows, offsets):
        try:
            indices = tuple(int(value) for value in tuple(raw_indices or ()))
            weights = tuple(float(value) for value in tuple(raw_weights or ()))
            offset = int(raw_offset)
        except (TypeError, ValueError, OverflowError):
            return False
        if offset < 0 or offset + 40 > len(original_data):
            return False
        if not 1 <= len(indices) == len(weights) <= pac_skin_row_capacity(original_data, offset):
            return False
        if len(set(indices)) != len(indices):
            return False
        if any(index < 0 or index > 1023 or index >= palette_size for index in indices):
            return False
        if any(not math.isfinite(weight) or weight < 0.0 for weight in weights):
            return False
        if not math.isclose(sum(weights), 1.0, rel_tol=1.0e-6, abs_tol=1.0e-6):
            return False
    return True


__all__ = ["pac_skin_part_layout_matches", "pac_skin_row_capacity", "pac_skin_rows_safe"]
