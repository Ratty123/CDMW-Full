"""Explicit edits to collision volumes: the PAC's own set or a body/head PABV.

A volume is addressed by its ordinal in the source set the edit was made
against. The source is pinned by a SHA-256 of that set's bytes, so an edit can
never land on a different set whose ordinals happen to line up. Copies duplicate
an existing volume (same bone, shape, usage, flags and orientation) with their
own size and position; shapes are never converted.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

#: The PAC's own volume set. Any other source is a game-archive path to a .pabv.
MODEL_SOURCE = "model"
#: A set may not grow past this many volumes (a larger shipped set keeps its own count).
VOLUME_LIMIT = 128
#: Dimensions and positions are game units (metres); far outside any shipped value.
DIMENSION_LIMIT = 100.0
POSITION_LIMIT = 1000.0
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _finite(values, count_range, limit, *, positive, name):
    if not isinstance(values, tuple) or not count_range[0] <= len(values) <= count_range[1]:
        raise ValueError(f"Collision volume {name} has the wrong number of values.")
    for value in values:
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
            raise ValueError(f"Collision volume {name} must be finite and within ±{limit:g}.")
        if positive and value <= 0:
            raise ValueError("Collision volume sizes must be greater than zero.")


@dataclass(frozen=True, slots=True)
class CollisionVolumeChange:
    ordinal: int
    #: New shape dimensions in file order: sphere (radius), capsule/cylinder
    #: (radius, height), box (z, x, y). None keeps the authored size.
    parameters: tuple[float, ...] | None = None
    #: New bone-local centre (the volume matrix's translation row).
    position: tuple[float, float, float] | None = None
    removed: bool = False

    def __post_init__(self):
        if type(self.ordinal) is not int or not 0 <= self.ordinal < 0x10000:
            raise ValueError("Collision volume edits must name an existing volume.")
        if type(self.removed) is not bool:
            raise ValueError("Collision volume removal must be true or false.")
        if self.parameters is not None:
            _finite(self.parameters, (1, 3), DIMENSION_LIMIT, positive=True, name="size")
        if self.position is not None:
            _finite(self.position, (3, 3), POSITION_LIMIT, positive=False, name="position")
        if self.removed and (self.parameters is not None or self.position is not None):
            raise ValueError("A removed collision volume cannot also be resized or moved.")
        if not self.removed and self.parameters is None and self.position is None:
            raise ValueError("A collision volume edit must resize, move or remove the volume.")

    def to_dict(self):
        return {"ordinal": self.ordinal, "removed": self.removed,
                "parameters": None if self.parameters is None else list(self.parameters),
                "position": None if self.position is None else list(self.position)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != {"ordinal", "removed", "parameters", "position"}:
            raise ValueError("Invalid collision volume edit.")
        return cls(value["ordinal"], _tuple(value["parameters"]), _tuple(value["position"]), value["removed"])


@dataclass(frozen=True, slots=True)
class CollisionVolumeCopy:
    template: int
    parameters: tuple[float, ...] | None = None
    position: tuple[float, float, float] | None = None

    def __post_init__(self):
        if type(self.template) is not int or not 0 <= self.template < 0x10000:
            raise ValueError("A collision volume copy must name an existing volume.")
        if self.parameters is not None:
            _finite(self.parameters, (1, 3), DIMENSION_LIMIT, positive=True, name="size")
        if self.position is not None:
            _finite(self.position, (3, 3), POSITION_LIMIT, positive=False, name="position")

    def to_dict(self):
        return {"template": self.template,
                "parameters": None if self.parameters is None else list(self.parameters),
                "position": None if self.position is None else list(self.position)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != {"template", "parameters", "position"}:
            raise ValueError("Invalid collision volume copy.")
        return cls(value["template"], _tuple(value["parameters"]), _tuple(value["position"]))


def _tuple(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise ValueError("Invalid collision volume values.")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class CollisionVolumeEdit:
    source: str
    #: SHA-256 of the source set: the PAC's serialized volume block, or the whole PABV file.
    source_sha256: str
    changes: tuple[CollisionVolumeChange, ...] = ()
    copies: tuple[CollisionVolumeCopy, ...] = ()

    def __post_init__(self):
        if not isinstance(self.source, str) or not self.source or len(self.source) > 512:
            raise ValueError("Collision volume edits need their source set.")
        if self.source != MODEL_SOURCE:
            path = self.source.replace("\\", "/")
            if (path != self.source or path.startswith("/") or ":" in path or ".." in path.split("/")
                    or not path.casefold().endswith(".pabv")):
                raise ValueError("Collision volume edits outside the model need a game-archive .pabv path.")
        if not isinstance(self.source_sha256, str) or not _SHA256.fullmatch(self.source_sha256):
            raise ValueError("Collision volume edits need the source set's SHA-256.")
        if (not isinstance(self.changes, tuple) or not isinstance(self.copies, tuple)
                or any(not isinstance(row, CollisionVolumeChange) for row in self.changes)
                or any(not isinstance(row, CollisionVolumeCopy) for row in self.copies)):
            raise ValueError("Invalid collision volume edits.")
        ordinals = [row.ordinal for row in self.changes]
        if len(set(ordinals)) != len(ordinals) or ordinals != sorted(ordinals):
            raise ValueError("Collision volume edits must name each volume once, in order.")
        if len(self.copies) > VOLUME_LIMIT:
            raise ValueError(f"Collision volume sets hold at most {VOLUME_LIMIT} volumes.")
        if not self.changes and not self.copies:
            raise ValueError("A collision volume edit must change at least one volume.")

    @property
    def removed(self) -> frozenset[int]:
        return frozenset(row.ordinal for row in self.changes if row.removed)

    def to_dict(self):
        return {"source": self.source, "source_sha256": self.source_sha256,
                "changes": [row.to_dict() for row in self.changes],
                "copies": [row.to_dict() for row in self.copies]}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, Mapping) or set(value) != {"source", "source_sha256", "changes", "copies"}
                or not isinstance(value["changes"], (list, tuple)) or not isinstance(value["copies"], (list, tuple))):
            raise ValueError("Invalid collision volume edits.")
        return cls(value["source"], value["source_sha256"],
                   tuple(CollisionVolumeChange.from_dict(row) for row in value["changes"]),
                   tuple(CollisionVolumeCopy.from_dict(row) for row in value["copies"]))
