"""Reduce PAC vertex jiggle contributions without changing other record lanes."""

from __future__ import annotations

from collections.abc import Mapping
import math

from cdmw.domain.mesh.jiggle import PacJiggleRule
from .pac_cloth import pac_cloth_lods


PAC_JIGGLE_OFFSET = 38
PAC_JIGGLE_MASK = 0x0F


def reduce_pac_jiggle_byte(value: int, retained: float) -> int:
    """Reduce the low-nibble blend without changing the upper four bits.

    The skinned-mesh CPU setup selects the shader's low-nibble branch:
    (15-(value&15))/15. Round to the nearest representable numerator, with
    half steps retaining more influence. Zero source contribution stays zero.
    """
    numerator = PAC_JIGGLE_MASK - (value & PAC_JIGGLE_MASK)
    return (value & 0xF0) | (PAC_JIGGLE_MASK - math.floor(numerator * retained + 0.5))


def apply_pac_jiggle_rules(data: bytes, rules: Mapping[int, PacJiggleRule], *, appearance=None) -> bytes:
    """Set only byte 38 in validated records at every LOD of the output baseline.

    Reset/undo and repeated edits rebuild from the retained source. Do not
    manufacture an enable value or amplify an already disabled source record.
    The shared LOD reader validates record ownership without requiring cloth.
    """
    if not rules:
        return data
    levels = pac_cloth_lods(data)
    if any(type(index) is not int or not 0 <= index < len(levels[0].submeshes)
           or not isinstance(rule, PacJiggleRule) for index, rule in rules.items()):
        raise ValueError("Jiggle settings refer to an invalid PAC part.")
    result = bytearray(data)
    for level in levels:
        displayed = appearance.to_neutral(level) if appearance is not None else level
        for index, rule in rules.items():
            part = level.submeshes[index]
            amounts = dict(rule.bone_retained)
            if rule.bone_retained and (len(part.bone_indices) != len(part.vertices)
                                      or len(part.bone_weights) != len(part.vertices)):
                raise ValueError("Regional jiggle requires complete skin weights at every LOD.")
            for vertex, (position, offset) in enumerate(zip(displayed.submeshes[index].vertices,
                                        part.source_vertex_offsets, strict=True)):
                if not math.isfinite(position[1]):
                    raise ValueError("Jiggle selection requires finite vertex heights.")
                if rule.below_y is None or position[1] < rule.below_y:
                    result[offset + PAC_JIGGLE_OFFSET] = reduce_pac_jiggle_byte(
                        data[offset + PAC_JIGGLE_OFFSET],
                        rule.contribution(part.bone_indices[vertex], part.bone_weights[vertex], amounts=amounts)
                        if rule.bone_retained else rule.retained,
                    )
    return bytes(result)
