"""Experimental PAC jiggle disabling; the strength encoding is still unknown."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True, slots=True)
class PacJiggleRule:
    # None disables the whole part. A boundary selects strictly lower vertices.
    below_y: float | None = None

    def __post_init__(self):
        if self.below_y is not None and (
            type(self.below_y) not in {int, float} or not math.isfinite(self.below_y)
        ):
            raise ValueError("Jiggle height must be a finite number.")

    @classmethod
    def from_dict(cls, value: object) -> "PacJiggleRule":
        if not isinstance(value, Mapping) or set(value) != {"below_y"}:
            raise ValueError("Invalid jiggle settings.")
        return cls(**value)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
