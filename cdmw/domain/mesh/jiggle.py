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
    # PAC palette slots, not skeleton ordinals. Values blend through the
    # source skin weights, so adjacent regions keep their authored falloff.
    bone_retained: tuple[tuple[int, float], ...] = ()

    def __post_init__(self):
        if self.below_y is not None and (
            type(self.below_y) not in {int, float} or not math.isfinite(self.below_y)
        ):
            raise ValueError("Jiggle height must be a finite number.")
        if type(self.retained) not in {int, float} or not math.isfinite(self.retained) or not 0 <= self.retained <= 1:
            raise ValueError("Retained jiggle must be between zero and one.")
        if (not isinstance(self.bone_retained, tuple) or len(self.bone_retained) > 1024
                or any(not isinstance(row, tuple) or len(row) != 2 for row in self.bone_retained)):
            raise ValueError("Invalid regional jiggle settings.")
        seen = set()
        for slot, amount in self.bone_retained:
            if (type(slot) is not int or not 0 <= slot <= 1023 or slot in seen
                    or type(amount) not in {int, float} or not math.isfinite(amount) or not 0 <= amount <= 1):
                raise ValueError("Invalid regional jiggle settings.")
            seen.add(slot)

    @classmethod
    def from_dict(cls, value: object) -> "PacJiggleRule":
        if (not isinstance(value, Mapping) or "below_y" not in value
                or set(value) - {"below_y", "retained", "bone_retained"}):
            raise ValueError("Invalid jiggle settings.")
        payload = dict(value)
        if "bone_retained" in payload:
            rows = payload["bone_retained"]
            if (not isinstance(rows, (list, tuple)) or not rows or "retained" not in payload
                    or any(not isinstance(row, (list, tuple)) or len(row) != 2 for row in rows)):
                raise ValueError("Invalid regional jiggle settings.")
            payload["bone_retained"] = tuple(tuple(row) for row in rows)
        return cls(**payload)

    def to_dict(self) -> dict[str, object]:
        # Keep the original disable-only representation readable by older apps.
        return {"below_y": self.below_y, **({"retained": self.retained} if self.retained or self.bone_retained else {}),
                **({"bone_retained": [list(row) for row in self.bone_retained]} if self.bone_retained else {})}

    def contribution(self, slots, weights, *, amounts=None) -> float:
        """Blend independent bone amounts; never create extra source influence."""
        if not self.bone_retained:
            return self.retained
        if (not slots or len(slots) != len(weights)
                or any(type(slot) is not int or not 0 <= slot <= 1023 for slot in slots)
                or any(not math.isfinite(weight) or weight < 0 for weight in weights)):
            raise ValueError("Regional jiggle requires complete valid skin weights.")
        total = sum(weights)
        if not math.isfinite(total) or total <= 0:
            raise ValueError("Regional jiggle requires a positive skin-weight sum.")
        amounts = dict(self.bone_retained) if amounts is None else amounts
        value = sum(weight * amounts.get(slot, self.retained) for slot, weight in zip(slots, weights, strict=True)) / total
        return max(0.0, min(1.0, value))
