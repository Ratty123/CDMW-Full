"""Read dependencies pinned to a New Item snapshot and its exported plan."""
from __future__ import annotations

import hashlib
import re
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


def _validate_indexes(indexes, stop_event=None):
    for path, expected in indexes:
        raise_if_cancelled(stop_event, "Archive index check cancelled.")
        checksum = hashlib.sha256()
        try:
            with path.open('rb') as source:
                while chunk := source.read(1024 * 1024):
                    raise_if_cancelled(stop_event, "Archive index check cancelled.")
                    checksum.update(chunk)
        except OSError as exc:
            raise StaleNewItemSource(f"Source index cannot be read: {path}.") from exc
        if checksum.hexdigest() != expected:
            raise StaleNewItemSource(f"Source index changed since parsing: {path}. Read the archives again.")


@dataclass(frozen=True)
class PayloadRevision:
    entry: ArchiveEntry
    sha256: str


@dataclass(frozen=True)
class SourceRevision:
    payloads: tuple[PayloadRevision, ...]
    files: tuple[tuple[Path, object], ...]
    reader: Callable[[ArchiveEntry], bytes]
    indexes: tuple[tuple[Path, str], ...] = ()

    def validate(self, stop_event=None) -> None:
        for path, stamp in self.files:
            raise_if_cancelled(stop_event, "New item source check cancelled.")
            if _stamp(path) != stamp:
                raise StaleNewItemSource(f"Source changed: {path}. Read the archives and build the plan again.")
        _validate_indexes(self.indexes, stop_event)
        for source in self.payloads:
            raise_if_cancelled(stop_event, "New item source check cancelled.")
            if hashlib.sha256(self.reader(source.entry)).hexdigest() != source.sha256:
                raise StaleNewItemSource(f"Source changed: {source.entry.path}. Build the plan again.")
        # A writer racing a payload read must also invalidate the check.
        for path, stamp in self.files:
            if _stamp(path) != stamp:
                raise StaleNewItemSource(f"Source changed during validation: {path}. Build the plan again.")
        _validate_indexes(self.indexes, stop_event)

    def manifest(self):
        return [{"path": p.entry.path, "archive": str(p.entry.pamt_path), "sha256": p.sha256}
                for p in self.payloads]


class SourceTracker:
    """Records actual reads, including lazily decoded optional authoring tables."""

    def __init__(self, reader):
        self.reader = reader
        self._files = {}
        self._payloads = {}
        self._indexes = {}
        self._lock = threading.RLock()

    def pin_file(self, path: Path):
        with self._lock:
            current = _stamp(path)
            prior = self._files.setdefault(path, current)
            if prior != current:
                raise StaleNewItemSource(f"Source changed while reading: {path}.")

    def pin_index(self, path: Path, checksum: str, stop_event=None):
        """Retain the digest computed from parsed bytes, never a replacement index."""
        path = Path(path)
        if not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise ValueError('Invalid parsed archive index digest.')
        self.pin_file(path)
        with self._lock:
            if self._indexes.setdefault(path, checksum) != checksum:
                raise StaleNewItemSource(f"Source index has conflicting parsed revisions: {path}.")
        _validate_indexes(((path, checksum),), stop_event)
        self.pin_file(path)

    def parse_index(self, path: Path, *, stop_event=None):
        from cdmw.core.archive_format import parse_archive_pamt_bytes
        path = Path(path)
        raise_if_cancelled(stop_event, "Archive index read cancelled.")
        self.pin_file(path)
        data = path.read_bytes()
        entries = parse_archive_pamt_bytes(data, path)
        self.pin_index(path, hashlib.sha256(data).hexdigest(), stop_event)
        return entries

    def fork(self, reader):
        """Give a derived snapshot independent reads with the same parsed indexes."""
        result = SourceTracker(reader)
        with self._lock:
            result._indexes = dict(self._indexes)
            result._files = {path: self._files[path] for path in self._indexes}
        return result

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
            return SourceRevision(tuple(self._payloads.values()), tuple(self._files.items()), self.reader,
                                  tuple(self._indexes.items()))

    def files_changed(self) -> bool:
        """Cheap worker-side invalidation before any cached planning data is reused."""
        with self._lock:
            return any(_stamp(path) != stamp for path, stamp in self._files.items())
