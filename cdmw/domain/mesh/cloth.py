"""Cloth influence reduction, independent of the game's simulation anchors."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class PacClothRule:
    amount: float = 1.0
    fixed_above: float | None = None
    fade: float = 0.0

    def __post_init__(self):
        for name in ("amount", "fade", "fixed_above"):
            value = getattr(self, name)
            if value is None and name == "fixed_above":
                continue
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError(f"Cloth {name} must be a finite number.")
        if not 0.0 <= self.amount <= 1.0 or self.fade < 0.0:
            raise ValueError("Cloth amount must be between 0 and 1, and fade must be non-negative.")
        if self.fixed_above is None and self.fade != 0.0:
            raise ValueError("Cloth fade requires a height boundary.")

    @classmethod
    def from_dict(cls, value: object) -> "PacClothRule":
        if not isinstance(value, Mapping) or set(value) != {"amount", "fixed_above", "fade"}:
            raise ValueError("Invalid cloth influence settings.")
        return cls(**value)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def blend(self, original: int, height: float) -> int:
        """Reduce original guide influence; never enable a previously rigid row."""
        if not 0 <= original <= 63 or not math.isfinite(height):
            raise ValueError("Invalid cloth vertex input.")
        scale = self.amount
        if self.fixed_above is not None:
            distance = self.fixed_above - height
            scale *= (max(0.0, min(1.0, distance / self.fade)) if self.fade else float(distance > 0.0))
        return max(original, min(63, round(63 - (63 - original) * scale)))
