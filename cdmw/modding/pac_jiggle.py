"""Reduce PAC vertex jiggle contributions without changing other record lanes."""

from __future__ import annotations

from collections.abc import Mapping
import math

from cdmw.domain.mesh.jiggle import PacJiggleRule
from .pac_cloth import pac_cloth_lods


PAC_JIGGLE_OFFSET = 38
PAC_JIGGLE_DISABLED = 255


def reduce_pac_jiggle_byte(value: int, retained: float) -> int:
    """Preserve the relative blend in both known shader branches for F0..FF.

    Full-byte decoding gives (255-value)/255; the low-nibble branch gives
    (15-(value&15))/15. In F0..FF both share the same numerator. Rounding is
    nearest representable numerator, with half steps retaining more influence.
    Other ranges can be disabled/restored but cannot safely use this scaling.
    """
    if retained == 0:
        return PAC_JIGGLE_DISABLED
    if retained == 1:
        return value
    if value < 0xF0:
        raise ValueError("Relative jiggle reduction requires source bytes F0-FF; use Disable or Restore for this part.")
    return 255 - math.floor((255 - value) * retained + 0.5)


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
            for position, offset in zip(displayed.submeshes[index].vertices,
                                        part.source_vertex_offsets, strict=True):
                if not math.isfinite(position[1]):
                    raise ValueError("Jiggle selection requires finite vertex heights.")
                if rule.below_y is None or position[1] < rule.below_y:
                    result[offset + PAC_JIGGLE_OFFSET] = reduce_pac_jiggle_byte(
                        data[offset + PAC_JIGGLE_OFFSET], rule.retained,
                    )
    return bytes(result)
