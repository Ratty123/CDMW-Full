"""Shell-level action descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ActionSpec:
    key: str
    text: str
    callback: Callable[[], None] | None = None


__all__ = ["ActionSpec"]
