from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from cdmw.models import ArchiveEntry


@dataclass(slots=True)
class ArchivePatchRequest:
    entry: ArchiveEntry
    payload_data: bytes


@dataclass(slots=True)
class ArchivePatchResult:
    backup_dir: Path
    changed_entries: Dict[str, ArchiveEntry]
    changed_paths: List[str]
    warnings: List[str]


__all__ = ["ArchivePatchRequest", "ArchivePatchResult"]
