"""Typed package manifest summaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PackageManifestSummary:
    root: Path
    file_count: int = 0
    metadata_path: Path | None = None


__all__ = ["PackageManifestSummary"]
