from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PhaseResult:
    value: object
