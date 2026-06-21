from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FilesystemService:
    settings: object | None = None

    def expand_path(self, value: str | Path) -> Path:
        return Path(value).expanduser()
