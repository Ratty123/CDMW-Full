"""Archive browser tab state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ArchiveBrowserState:
    active_archive_path: Path | None = None
    filter_text: str = ""


__all__ = ["ArchiveBrowserState"]
