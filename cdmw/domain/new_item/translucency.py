"""Opt-in absorption controls for imported New Item materials."""

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class TranslucencyChoice:
    parts: tuple[str, ...] = ()
    thickness: float = 0.1
    extinction: float = 0.3
    # Existing choices keep their shared pair; only differing parts need an override.
    part_settings: tuple[tuple[str, float, float], ...] = ()

    def validate(self) -> None:
        if not self.parts or any(not isinstance(name, str) or not name.strip() for name in self.parts):
            raise ValueError("Select at least one material part for translucency.")
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in (self.thickness, self.extinction)):
            raise ValueError("Translucency thickness and extinction must be between 0 and 1.")
        selected = {name.casefold() for name in self.parts}
        seen = set()
        for name, thickness, extinction in self.part_settings:
            key = name.casefold()
            if key not in selected or key in seen:
                raise ValueError("Translucency settings must name unique selected parts.")
            seen.add(key)
            if any(not math.isfinite(value) or not 0 <= value <= 1 for value in (thickness, extinction)):
                raise ValueError("Translucency thickness and extinction must be between 0 and 1.")

    @classmethod
    def from_settings(cls, settings):
        """Keep the legacy representation when all selected parts share a pair."""
        parts = tuple(settings)
        if not parts:
            return None
        thickness, extinction = settings[parts[0]]
        return cls(parts, thickness, extinction, tuple(
            (name, *settings[name]) for name in parts
            if settings[name] != (thickness, extinction)
        ))

    def values_for(self, *names: str) -> tuple[float, float] | None:
        overrides = {name.casefold(): (thickness, extinction) for name, thickness, extinction in self.part_settings}
        selected = {name.casefold() for name in self.parts} & {str(name).casefold() for name in names}
        values = {overrides.get(name, (self.thickness, self.extinction)) for name in selected}
        if len(values) > 1:
            raise ValueError("Parts sharing one material cannot use different translucency settings. Keep them as separate materials.")
        return next(iter(values), None)

    def matches(self, *names: str) -> bool:
        return bool({name.casefold() for name in self.parts} & {str(name).casefold() for name in names})
