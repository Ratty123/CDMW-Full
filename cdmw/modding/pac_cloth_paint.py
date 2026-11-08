"""Bind painted render vertices to a PAC's existing cloth guides.

A cloth paint value is per vertex, 0 to 1: 0 follows the skeleton only, 1 follows
the cloth guides only, and values between blend the two through the record's
skeletal-blend byte (byte 39, 63 = skeleton only). The guide mesh, its constraints,
the physics profile and every other byte stay as the template shipped them; only
the render vertices' guide lanes and blend change.

Lower LODs carry no paint of their own: each vertex takes the value of the nearest
painted sample in the same part, so a LOD0 paint carries down to every stored LOD.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .mesh_parser import PAC_SKIN_EXTRA_INDEX_SENTINEL
from .pabv_parser import decode_pac_embedded_volumes
from .pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from .pac_cloth_guide_builder import _bindings, _skin
from .pac_cloth_guides import decode_pac_cloth_guides


@dataclass(frozen=True, slots=True)
class ClothPaintSamples:
    """Painted points of one PAC part, in the PAC's own model space."""

    positions: tuple[tuple[float, float, float], ...]
    values: tuple[float, ...]

    def __post_init__(self):
        if len(self.positions) != len(self.values) or not self.positions:
            raise ValueError("Cloth paint needs one value per painted point.")
        if any(not math.isfinite(v) or not 0.0 <= v <= 1.0 for v in self.values):
            raise ValueError("Cloth paint values must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class ClothPaintReport:
    cloth_vertices: int
    rigid_vertices: int
    reduced_vertices: int
    guide_count: int


def blend_for_paint(value: float) -> int:
    """Byte-39 skeletal blend for a paint value: 0 = cloth only, 63 = skeleton only."""
    return max(0, min(63, round(63 * (1.0 - float(value)))))


def _skeletal(data, offset, palette_count):
    """Up to four skeletal (slot, weight) pairs, reading the record in its own mode.

    A cloth record keeps four skeletal slots and reuses the next two for guides, so
    the ordinary six-slot reader would take guide indices for bones.
    """
    if data[offset + 39] & 63 == 63:
        slots, weights = _skin(data, offset, palette_count, True)
        return tuple(zip(slots, weights)), sum(1 for w in data[offset + 28:offset + 34] if w) > 4
    group0, group1 = struct.unpack_from("<2I", data, offset + 20)
    slots = (group0 & 1023, (group0 >> 10) & 1023, (group0 >> 20) & 1023, group1 & 1023)
    live = [(slot, weight) for slot, weight in zip(slots, data[offset + 28:offset + 32]) if weight]
    if not live or any(slot >= palette_count for slot, _ in live) or sum(w for _, w in live) != 255:
        raise ValueError("Cloth paint requires valid existing bone influences at every LOD.")
    live += [(live[0][0], 0)] * (4 - len(live))
    return tuple(live), False


def _nearest_values(points, samples: ClothPaintSamples):
    import numpy as np
    source = np.asarray(samples.positions, dtype=np.float64)
    values = np.asarray(samples.values, dtype=np.float64)
    out, distances = [], []
    for start in range(0, len(points), 256):
        delta = np.asarray(points[start:start + 256], dtype=np.float64)[:, None, :] - source[None, :, :]
        squared = np.einsum("vsi,vsi->vs", delta, delta)
        nearest = np.argmin(squared, axis=1)
        out.extend(float(values[i]) for i in nearest)
        distances.extend(math.sqrt(float(squared[row, i])) for row, i in enumerate(nearest))
    return out, distances


def apply_pac_cloth_paint(
    data: bytes,
    paint: Mapping[int, ClothPaintSamples],
    *,
    max_sample_distance: float | None = None,
) -> tuple[bytes, ClothPaintReport]:
    """Rewrite every part's guide lanes from paint; unpainted parts follow bones only.

    ``max_sample_distance`` refuses a paint whose samples do not sit on the built
    geometry, rather than painting the wrong vertices.
    """
    guides = decode_pac_cloth_guides(data)
    if guides is None or not guides.vertices:
        raise ValueError("This model has no cloth guides to bind painted cloth to. Choose a template with cloth.")
    levels = pac_cloth_lods(data)
    if any(type(i) is not int or not 0 <= i < len(levels[0].submeshes) for i in paint):
        raise ValueError("Cloth paint refers to an invalid PAC part.")
    if not any(v > 0 for samples in paint.values() for v in samples.values):
        raise ValueError("Paint at least one area as cloth.")
    palette_count = len(decode_pac_embedded_volumes(data).bone_palette)
    result = bytearray(data)
    cloth = rigid = reduced = 0
    for level in levels:
        for index, part in enumerate(level.submeshes):
            if not part.source_vertex_offsets:
                continue
            samples = paint.get(index)
            if samples is None:
                values = [0.0] * len(part.vertices)
            else:
                values, distances = _nearest_values(part.vertices, samples)
                if max_sample_distance is not None and distances and max(distances) > max_sample_distance:
                    raise ValueError(
                        f"Cloth paint for {part.name or index} does not line up with the built model "
                        f"({max(distances):.4g} from the nearest painted point). Apply placement again, then rebuild.")
            painted = [i for i, value in enumerate(values) if blend_for_paint(value) < 63]
            bindings = dict(zip(painted, _bindings([part.vertices[i] for i in painted], guides.vertices)))
            for vertex, offset in enumerate(part.source_vertex_offsets):
                blend = blend_for_paint(values[vertex])
                group0, group1 = struct.unpack_from("<2I", data, offset + 20)
                if blend == 63:
                    rigid += 1
                    if data[offset + 39] & 63 == 63:
                        continue  # Already skeleton only: keep all six skeletal slots as they are.
                    # Cloth record turned skeleton only: clear both reinterpreted
                    # guide slots, as apply_pac_cloth_rules does, keeping the
                    # four skeletal slots and the foreign bits.
                    struct.pack_into("<I", result, offset + 24, group1 & 0xC00003FF)
                    result[offset + 12:offset + 16] = PAC_SKIN_EXTRA_INDEX_SENTINEL
                    result[offset + 32:offset + 36] = bytes(4)
                    result[offset + 39] = (data[offset + 39] & 0xC0) | 63
                    continue
                live, was_reduced = _skeletal(data, offset, palette_count)
                reduced += was_reduced
                slots = [slot for slot, _ in live]
                ids, weights = bindings[vertex]
                struct.pack_into("<2I", result, offset + 20,
                                 (group0 & 0xC0000000) | slots[0] | slots[1] << 10 | slots[2] << 20,
                                 (group1 & 0xC0000000) | slots[3] | ids[0] << 10 | ids[1] << 20)
                struct.pack_into("<2e", result, offset + 12, ids[2], ids[3])
                result[offset + 28:offset + 32] = bytes(weight for _, weight in live)
                result[offset + 32:offset + 36] = bytes(weights)
                result[offset + 39] = (data[offset + 39] & 0xC0) | blend
                cloth += 1
    output = bytes(result)
    for level in levels:
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                binding = decode_pac_cloth_binding(output, offset)
                if binding is not None and (any(i >= len(guides.vertices) for i in binding[1]) or sum(binding[2]) != 255):
                    raise ValueError("A painted cloth binding did not decode back to the template's guides.")
    return output, ClothPaintReport(cloth, rigid, reduced, len(guides.vertices))
