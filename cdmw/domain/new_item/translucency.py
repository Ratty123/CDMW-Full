"""Opt-in absorption controls for imported New Item materials."""

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class TranslucencyChoice:
    parts: tuple[str, ...] = ()
    thickness: float = 0.1
    extinction: float = 0.3

    def validate(self) -> None:
        if not self.parts or any(not isinstance(name, str) or not name.strip() for name in self.parts):
            raise ValueError("Select at least one material part for translucency.")
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in (self.thickness, self.extinction)):
            raise ValueError("Translucency thickness and extinction must be between 0 and 1.")

    def matches(self, *names: str) -> bool:
        return bool({name.casefold() for name in self.parts} & {str(name).casefold() for name in names})
