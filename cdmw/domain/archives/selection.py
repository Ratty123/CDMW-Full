"""Typed archive selection state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArchiveSelection:
    archive_path: Path | None = None
    member_path: str = ""


__all__ = ["ArchiveSelection"]
