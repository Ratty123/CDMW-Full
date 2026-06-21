from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ArchiveService:
    settings: object | None = None
