from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MeshService:
    settings: object | None = None
