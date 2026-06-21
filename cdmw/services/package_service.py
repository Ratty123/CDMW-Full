from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PackageService:
    settings: object | None = None
