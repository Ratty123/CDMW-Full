"""Source-relative PAC jiggle contribution edits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class PacJiggleRule:
    # A boundary selects strictly lower vertices; None selects the whole part.
    below_y: float | None = None
    retained: float = 0.0

    def __post_init__(self):
        if self.below_y is not None and (
            type(self.below_y) not in {int, float} or not math.isfinite(self.below_y)
        ):
            raise ValueError("Jiggle height must be a finite number.")
        if type(self.retained) not in {int, float} or not math.isfinite(self.retained) or not 0 <= self.retained <= 1:
            raise ValueError("Retained jiggle must be between zero and one.")

    @classmethod
    def from_dict(cls, value: object) -> "PacJiggleRule":
        if not isinstance(value, Mapping) or set(value) not in ({"below_y"}, {"below_y", "retained"}):
            raise ValueError("Invalid jiggle settings.")
        return cls(**value)

    def to_dict(self) -> dict[str, object]:
        # Keep the original disable-only representation readable by older apps.
        return {"below_y": self.below_y, **({"retained": self.retained} if self.retained else {})}
