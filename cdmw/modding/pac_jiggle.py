"""Disable reported PAC jiggle on explicit parts/regions without changing skinning."""

from __future__ import annotations

from collections.abc import Mapping
import math

from cdmw.domain.mesh.jiggle import PacJiggleRule
from .pac_cloth import pac_cloth_lods


PAC_JIGGLE_OFFSET = 38
PAC_JIGGLE_DISABLED = 255


def apply_pac_jiggle_rules(data: bytes, rules: Mapping[int, PacJiggleRule], *, appearance=None) -> bytes:
    """Set only byte 38 in validated records at every LOD of the output baseline.

    As with cloth, reset/undo rebuild from the retained source. Never manufacture
    an enable value: non-255 values and their encoding have not been established.
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
            for position, offset in zip(displayed.submeshes[index].vertices,
                                        part.source_vertex_offsets, strict=True):
                if not math.isfinite(position[1]):
                    raise ValueError("Jiggle selection requires finite vertex heights.")
                if rule.below_y is None or position[1] < rule.below_y:
                    result[offset + PAC_JIGGLE_OFFSET] = PAC_JIGGLE_DISABLED
    return bytes(result)
