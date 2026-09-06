"""Read dependencies pinned to a New Item snapshot and its exported plan."""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry


class StaleNewItemSource(ValueError):
    pass


def _stamp(path: Path):
    try:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class PayloadRevision:
    entry: ArchiveEntry
    sha256: str


@dataclass(frozen=True)
class SourceRevision:
    payloads: tuple[PayloadRevision, ...]
    files: tuple[tuple[Path, object], ...]
    reader: Callable[[ArchiveEntry], bytes]

    def validate(self, stop_event=None) -> None:
        for path, stamp in self.files:
            raise_if_cancelled(stop_event, "New item source check cancelled.")
            if _stamp(path) != stamp:
                raise StaleNewItemSource(f"Source changed: {path}. Read the archives and build the plan again.")
        for source in self.payloads:
            raise_if_cancelled(stop_event, "New item source check cancelled.")
            if hashlib.sha256(self.reader(source.entry)).hexdigest() != source.sha256:
                raise StaleNewItemSource(f"Source changed: {source.entry.path}. Build the plan again.")
        # A writer racing a payload read must also invalidate the check.
        for path, stamp in self.files:
            if _stamp(path) != stamp:
                raise StaleNewItemSource(f"Source changed during validation: {path}. Build the plan again.")

    def manifest(self):
        return [{"path": p.entry.path, "archive": str(p.entry.pamt_path), "sha256": p.sha256}
                for p in self.payloads]


class SourceTracker:
    """Records actual reads, including lazily decoded optional authoring tables."""

    def __init__(self, reader):
        self.reader = reader
        self._files = {}
        self._payloads = {}
        self._lock = threading.RLock()

    def pin_file(self, path: Path):
        with self._lock:
            current = _stamp(path)
            prior = self._files.setdefault(path, current)
            if prior != current:
                raise StaleNewItemSource(f"Source changed while reading: {path}.")

    def read(self, entry):
        entry = replace(entry)
        paths = (Path(entry.pamt_path), Path(entry.paz_file))
        for path in paths:
            self.pin_file(path)
        data = bytes(self.reader(entry))
        for path in paths:
            self.pin_file(path)
        revision = PayloadRevision(entry, hashlib.sha256(data).hexdigest())
        with self._lock:
            key = entry.identity
            prior = self._payloads.setdefault(key, revision)
            if prior.sha256 != revision.sha256:
                raise StaleNewItemSource(f"Source changed while reading: {entry.path}.")
        return data

    def capture(self) -> SourceRevision:
        with self._lock:
            return SourceRevision(tuple(self._payloads.values()), tuple(self._files.items()), self.reader)

    def files_changed(self) -> bool:
        """Cheap worker-side invalidation before any cached planning data is reused."""
        with self._lock:
            return any(_stamp(path) != stamp for path, stamp in self._files.items())
