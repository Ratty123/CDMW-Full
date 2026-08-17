from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from cdmw.models import ArchiveEntry


@dataclass(slots=True)
class ArchivePatchRequest:
    entry: ArchiveEntry
    payload_data: bytes


@dataclass(slots=True)
class ArchiveAddRequest:
    """A brand-new archive entry: a virtual path the package does not ship yet.

    `pamt_path` names the package group's index the entry joins; `flags` are the
    storage flags (compression in the low nibble, encryption in the high nibble)
    and are normally copied from a sibling entry of the same kind, which is what
    `from_template` does.
    """

    pamt_path: Path
    path: str
    payload_data: bytes
    flags: int = 0

    @classmethod
    def from_template(cls, template: ArchiveEntry, path: str, payload_data: bytes) -> "ArchiveAddRequest":
        return cls(
            pamt_path=Path(template.pamt_path),
            path=str(path or "").replace("\\", "/").strip("/"),
            payload_data=bytes(payload_data),
            flags=int(template.flags),
        )

    @property
    def basename(self) -> str:
        return self.path.replace("\\", "/").rsplit("/", 1)[-1]

    @property
    def compression_type(self) -> int:
        return int(self.flags) & 0x0F

    @property
    def encryption_type(self) -> int:
        return (int(self.flags) >> 4) & 0x0F


@dataclass(slots=True)
class MetaFileWrite:
    """A whole-file rewrite of one of the game's loose index files beside the archives
    (`meta/0.pathc`, the texture registry), backed up and restored with the same
    mutation as the archive entries it belongs with.

    `path` is relative to the package root the mutation targets, POSIX-style.
    """

    path: str
    payload_data: bytes

    def __post_init__(self) -> None:
        self.path = str(self.path or "").replace("\\", "/").strip("/")
        if not self.path or ".." in self.path.split("/"):
            raise ValueError("A meta file write needs a relative path inside the package root.")
        self.payload_data = bytes(self.payload_data)


@dataclass(slots=True)
class ArchivePatchResult:
    backup_dir: Path
    changed_entries: Dict[str, ArchiveEntry]
    changed_paths: List[str]
    warnings: List[str]
    #: Virtual paths that did not exist before this mutation (a subset of `changed_paths`).
    added_paths: List[str] = field(default_factory=list)
    #: Loose meta files rewritten (relative to the package root).
    meta_paths: List[str] = field(default_factory=list)


__all__ = ["ArchiveAddRequest", "ArchivePatchRequest", "ArchivePatchResult", "MetaFileWrite"]
