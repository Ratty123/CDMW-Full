"""Reproducible guide creation using an existing PAC LOD and bone palette."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping

#: Painted pins per rule; far above any part's vertex count the editor accepts.
PIN_LIMIT = 262_144
_KEYS = {"source_lod", "fixed_above", "bone_palette", "reduce_skinning"}


@dataclass(frozen=True, slots=True)
class PacClothGuideRule:
    source_lod: int
    #: Guides at or above this displayed height are pinned. None pins by paint only.
    fixed_above: float | None
    # Captured after resolving every hash against the session's skeleton. Drafts
    # retain this proof of palette identity without needing a mounted archive.
    bone_palette: tuple[int, ...]
    reduce_skinning: bool = False
    #: Displayed positions of the part's pinned LOD0 vertices when the rule was made.
    pinned_points: tuple[tuple[float, float, float], ...] = ()

    def __post_init__(self):
        if type(self.reduce_skinning) is not bool:
            raise ValueError("Guide skinning reduction must be explicitly enabled or disabled.")
        if type(self.source_lod) is not int or not 0 <= self.source_lod <= 3:
            raise ValueError("Choose a stored guide source LOD between 0 and 3.")
        if self.fixed_above is not None and (
                type(self.fixed_above) not in {float, int} or not math.isfinite(self.fixed_above)):
            raise ValueError("Guide pin height must be finite.")
        if (not isinstance(self.bone_palette, tuple) or not 1 <= len(self.bone_palette) <= 1024
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in self.bone_palette)
                or len(set(self.bone_palette)) != len(self.bone_palette)):
            raise ValueError("Guide creation requires an unambiguous existing bone palette.")
        if (not isinstance(self.pinned_points, tuple) or len(self.pinned_points) > PIN_LIMIT
                or any(not isinstance(point, tuple) or len(point) != 3
                       or any(type(v) not in {float, int} or not math.isfinite(v) for v in point)
                       for point in self.pinned_points)):
            raise ValueError("Guide pins must be finite positions.")
        if self.fixed_above is None and not self.pinned_points:
            raise ValueError("Pin the guides by height or paint pins before creating them.")

    def to_dict(self):
        value = {"source_lod": self.source_lod, "fixed_above": self.fixed_above,
                 "bone_palette": list(self.bone_palette), "reduce_skinning": self.reduce_skinning}
        if self.pinned_points:
            value["pinned_points"] = [list(point) for point in self.pinned_points]
        return value

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, Mapping)
                or set(value) not in (_KEYS, _KEYS | {"pinned_points"})
                or not isinstance(value["bone_palette"], (list, tuple))
                or not isinstance(value.get("pinned_points", []), (list, tuple))):
            raise ValueError("Invalid cloth guide settings.")
        points = value.get("pinned_points", [])
        if "pinned_points" in value and not points:
            raise ValueError("Invalid cloth guide settings.")
        if any(not isinstance(point, (list, tuple)) for point in points):
            raise ValueError("Invalid cloth guide settings.")
        return cls(value["source_lod"], value["fixed_above"], tuple(value["bone_palette"]),
                   value["reduce_skinning"], tuple(tuple(point) for point in points))

    @property
    def needs_new_draft_version(self) -> bool:
        """Older readers require a height and know nothing of painted pins."""
        return self.fixed_above is None or bool(self.pinned_points)
