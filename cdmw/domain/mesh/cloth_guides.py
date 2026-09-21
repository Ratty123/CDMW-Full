"""Reproducible guide creation using an existing PAC LOD and bone palette."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class PacClothGuideRule:
    source_lod: int
    fixed_above: float
    # Captured after resolving every hash against the session's skeleton. Drafts
    # retain this proof of palette identity without needing a mounted archive.
    bone_palette: tuple[int, ...]
    reduce_skinning: bool = False

    def __post_init__(self):
        if type(self.reduce_skinning) is not bool:
            raise ValueError("Guide skinning reduction must be explicitly enabled or disabled.")
        if type(self.source_lod) is not int or not 0 <= self.source_lod <= 3:
            raise ValueError("Choose a stored guide source LOD between 0 and 3.")
        if type(self.fixed_above) not in {float, int} or not math.isfinite(self.fixed_above):
            raise ValueError("Guide pin height must be finite.")
        if (not isinstance(self.bone_palette, tuple) or not 1 <= len(self.bone_palette) <= 1024
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in self.bone_palette)
                or len(set(self.bone_palette)) != len(self.bone_palette)):
            raise ValueError("Guide creation requires an unambiguous existing bone palette.")

    def to_dict(self):
        return {"source_lod": self.source_lod, "fixed_above": self.fixed_above,
                "bone_palette": list(self.bone_palette), "reduce_skinning": self.reduce_skinning}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, Mapping)
                or set(value) != {"source_lod", "fixed_above", "bone_palette", "reduce_skinning"}
                or not isinstance(value["bone_palette"], (list, tuple))):
            raise ValueError("Invalid cloth guide settings.")
        return cls(value["source_lod"], value["fixed_above"], tuple(value["bone_palette"]), value["reduce_skinning"])
