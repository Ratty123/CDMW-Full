"""Small binding helper for static replacement dialog section namespaces."""

from __future__ import annotations

from typing import Sequence


def static_replacement_section_values(section: object, names: Sequence[str]) -> tuple[object, ...]:
    return tuple(getattr(section, name) for name in names)
