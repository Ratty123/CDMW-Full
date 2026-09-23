"""Independent, opt-in surface edits for imported material parts."""
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SurfaceEdit:
    color: tuple[float, float, float] | None = None
    roughness: float | None = None
    metallic: float | None = None

    def validate(self):
        if self.color is not None and len(self.color) != 3:
            raise ValueError("Surface colour needs three RGB channels.")
        values = (*(self.color or ()), self.roughness, self.metallic)
        if any(value is not None and (not math.isfinite(value) or not 0 <= value <= 1) for value in values):
            raise ValueError("Surface colour, roughness and metallic values must be between 0 and 1.")

    @property
    def wanted(self):
        return self.color is not None or self.roughness is not None or self.metallic is not None


def validate_surface_settings(choices):
    seen = set()
    for name, choice in choices:
        if not isinstance(name, str) or not name.strip() or name.casefold() in seen:
            raise ValueError("Surface settings must name unique material parts.")
        if not isinstance(choice, SurfaceEdit):
            raise ValueError("Invalid surface settings.")
        choice.validate()
        seen.add(name.casefold())
