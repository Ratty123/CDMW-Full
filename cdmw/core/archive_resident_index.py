"""Read-only, generation-bound view of the Full backend's published FAI3 index.

Workers build shared path/extension lookups once. ArchiveEntry objects are decoded
only for requested rows; tools never need another full archive listing. The mmap
and its generation stay alive for as long as any consumer retains this view.
"""
from __future__ import annotations

from array import array
from collections import OrderedDict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import json
import mmap
from pathlib import Path
import struct
import threading
import time
from types import SimpleNamespace

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry

_HEADER = struct.Struct("<8sIIQQQQ")
_RECORD = struct.Struct("<6Q8I")
_OFFSET = struct.Struct("<Q")
_LENGTH = struct.Struct("<I")
_DOTNET_EPOCH_TICKS = 621355968000000000
_CACHE: OrderedDict[tuple[str, str], ResidentArchiveIndex] = OrderedDict()
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class ResidentArchiveSource:
    package_root: str
    fingerprint: str
    index_path: str
    entry_count: int

    @classmethod
    def capture(cls, service, package_root) -> ResidentArchiveSource | None:
        """GUI-thread capture only; opening/validation happen on the worker."""
        session = getattr(service, "current_session", None)
        if session is None or not getattr(session, "index_path", ""):
            return None
        if Path(session.package_root) != Path(package_root):
            return None
        return cls(session.package_root, session.fingerprint, session.index_path, session.entry_count)

    def open(self, stop_event=None, *, package_root=None) -> ResidentArchiveIndex:
        if package_root is not None and Path(package_root) != Path(self.package_root):
            raise ValueError("Archive root changed; reopen the workspace with the current catalogue.")
        if callable(stop_event):
            stop_event = SimpleNamespace(is_set=stop_event)
        key = (self.index_path, self.fingerprint)
        while not _CACHE_LOCK.acquire(timeout=.05):
            raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
        try:
            raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
            index = _CACHE.get(key)
            if index is None:
                index = ResidentArchiveIndex(self, stop_event=stop_event)
                _CACHE[key] = index
            else:
                index.validate_sources(stop_event)
            _CACHE.move_to_end(key)
            while len(_CACHE) > 2:
                # Consumers own strong references. Eviction never closes their mmap.
                _CACHE.popitem(last=False)
            return index
        finally:
            _CACHE_LOCK.release()


def _append(rows, key, row):
    previous = rows.get(key)
    if previous is None:
        rows[key] = row
    elif isinstance(previous, int):
        rows[key] = array("Q", (previous, row))
    else:
        previous.append(row)


def _rows(value):
    return (value,) if isinstance(value, int) else value


class ResidentArchiveIndex(Sequence[ArchiveEntry]):
    def __init__(self, source: ResidentArchiveSource, *, stop_event=None):
        self.source = source
        self._mapping = None
        path = Path(source.index_path)
        manifest_path = path.with_name("manifest.json")
        if manifest_path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Archive catalogue manifest is unexpectedly large.")
        manifest = json.loads(manifest_path.read_bytes())
        if (manifest.get("fingerprint") != source.fingerprint
                or Path(manifest.get("package_root", "")) != Path(source.package_root)
                or manifest.get("entry_count") != source.entry_count
                or manifest.get("index_version") != 3):
            raise ValueError("Archive catalogue generation changed; refresh the archives.")
        root = Path(source.package_root).resolve()
        if root.is_file():
            root = root.parent
        self.source_files = []
        for row in manifest.get("source_files", ()):
            file = (root / row["relative_path"]).resolve()
            if not file.is_relative_to(root):
                raise ValueError("Archive catalogue source escapes its package root.")
            self.source_files.append((file, int(row["size"]), int(row["modified_utc_ticks"])))
        if not self.source_files:
            raise ValueError("Archive catalogue has no source provenance.")
        self.validate_sources(stop_event)
        try:
            with path.open("rb") as handle:
                self._mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            data = self._mapping
            if len(data) < 64:
                raise ValueError("Archive catalogue header is truncated.")
            magic, version, record_size, count, records, strings, strings_size = _HEADER.unpack_from(data)
            if (magic != b"CDMWFAI3" or version != 3 or record_size != _RECORD.size
                    or count != source.entry_count or records < 64
                    or strings < records + count * record_size
                    or strings > len(data) or strings_size > len(data) - strings):
                raise ValueError("Archive catalogue ranges/version are invalid.")
            self._count, self._records, self._strings, self._strings_size = count, records, strings, strings_size
            self._paths = {}
            self._basenames = {}
            self._extensions = {}
            self._source_paths = {}
            self._source_packages = {}
            self._active = bytearray(count)
            mounts = None
            mount_path = root / "meta" / "0.papgt"
            if mount_path.is_file():
                from cdmw.core.papgt_format import parse_papgt
                if mount_path.stat().st_size > 1024 * 1024:
                    raise ValueError("Archive mount table is unexpectedly large.")
                mount_rows = parse_papgt(mount_path.read_bytes())
                packages = {file.parent.name.casefold() for file, *_ in self.source_files if file.suffix.lower() == ".pamt"}
                mounts = {}
                for rank, mount in enumerate(mount_rows):
                    if mount.name.casefold() not in packages:
                        if mount.flags & 0xff:
                            continue
                        raise ValueError(f"Mounted archive is missing: {mount.name}")
                    mounts[str(root / mount.name).replace("\\", "/").casefold()] = rank
            for row in range(count):
                if row % 4096 == 0:
                    raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
                    if row:
                        # Python's default GIL handoff can repeatedly favour
                        # this CPU-bound worker over queued Qt input. Yield a
                        # bounded slice while building a large shared index.
                        time.sleep(.001)
                record = records + row * record_size
                text = self._string(_OFFSET.unpack_from(data, record)[0], _LENGTH.unpack_from(data, record + 48)[0])
                text = text.replace("\\", "/").strip("/").lower()
                previous = self._paths.get(text)
                if mounts is None:
                    flags = _LENGTH.unpack_from(data, record + 68)[0]
                    self._active[row] = not (flags & 2) or bool(flags & 1)
                elif self._package_for_row(row) in mounts:
                    rank = mounts[self._package_for_row(row)]
                    winner = next((prior for prior in _rows(previous if previous is not None else ()) if self._active[prior]), None)
                    if winner is None or rank < mounts[self._package_for_row(winner)]:
                        self._active[row] = 1
                        if winner is not None:
                            self._active[winner] = 0
                _append(self._paths, text, row)
                basename = text.rsplit("/", 1)[-1]
                _append(self._basenames, basename, row)
                extension = "." + basename.rsplit(".", 1)[1] if "." in basename else ""
                _append(self._extensions, extension, row)
            self.by_path = _EntryGroups(self, self._paths)
            self.by_basename = _EntryGroups(self, self._basenames)
            self.by_extension = _EntryGroups(self, self._extensions)
            self.validate_sources(stop_event)
        except BaseException:
            if self._mapping is not None:
                self._mapping.close()
            raise

    def __len__(self):
        return self._count

    def _string(self, offset, length):
        if offset > self._strings_size or length > self._strings_size - offset:
            raise ValueError("Archive catalogue string is out of bounds.")
        start = self._strings + offset
        return self._mapping[start:start + length].decode("utf-8")

    def _source_path(self, offset, length):
        key = (offset, length)
        result = self._source_paths.get(key)
        if result is None:
            result = Path(self._string(offset, length))
            self._source_paths[key] = result
        return result

    def __getitem__(self, row):
        if isinstance(row, slice):
            return tuple(self[index] for index in range(*row.indices(len(self))))
        if row < 0:
            row += len(self)
        if not 0 <= row < len(self):
            raise IndexError(row)
        fields = _RECORD.unpack_from(self._mapping, self._records + row * _RECORD.size)
        path, pamt, paz, offset, stored, original, path_size, pamt_size, paz_size, flags, paz_index, *_ = fields
        return ArchiveEntry(
            path=self._string(path, path_size).replace("\\", "/").strip("/"),
            pamt_path=self._source_path(pamt, pamt_size), paz_file=self._source_path(paz, paz_size),
            offset=offset, comp_size=stored, orig_size=original, flags=flags, paz_index=paz_index,
        )

    def validate_sources(self, stop_event=None):
        for file, size, ticks in self.source_files:
            raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
            stat = file.stat()
            if stat.st_size != size or stat.st_mtime_ns // 100 + _DOTNET_EPOCH_TICKS != ticks:
                raise ValueError(f"Archive source changed: {file}. Refresh the archives.")

    @property
    def source_paths(self):
        return tuple(file for file, _size, _ticks in self.source_files)

    def item_metadata(self):
        for extension in (".pabgb", ".pabgh", ".staticinfobody", ".staticinfoheader", ".paloc"):
            yield from self.by_extension.get(extension, ())

    def selected_paths(self, sources):
        return _SelectedEntries(self.by_path, sources)

    def active_entry(self, path):
        key = str(path).replace("\\", "/").strip("/").lower()
        return next((self[row] for row in _rows(self._paths.get(key, ())) if self._active[row]), None)

    def index_maps(self, sources):
        if not sources.obsolete_packages:
            return self.by_path, self.by_basename
        return _FilteredGroups(self.by_path, sources), _FilteredGroups(self.by_basename, sources)

    def _package_for_row(self, row):
        record = self._records + row * _RECORD.size
        key = (_OFFSET.unpack_from(self._mapping, record + 8)[0],
               _LENGTH.unpack_from(self._mapping, record + 52)[0])
        package = self._source_packages.get(key)
        if package is None:
            package = str(self._source_path(*key)).replace("\\", "/").rsplit("/", 1)[0].casefold()
            self._source_packages[key] = package
        return package

    def matching(self, extensions, *, active_only=True, contains="") -> Iterator[ArchiveEntry]:
        """Worker-side filtered enumeration, retaining the backend's mount winner."""
        for extension in extensions:
            for row in _rows(self._extensions.get(extension, ())):
                if active_only and not self._active[row]:
                    continue
                entry = self[row]
                if not contains or contains in entry.path.replace("\\", "/").lower():
                    yield entry


class _EntryGroups(Mapping[str, Sequence[ArchiveEntry]]):
    def __init__(self, index, rows):
        self.index, self.rows = index, rows

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, key):
        return _EntryRows(self.index, _rows(self.rows[key]))

    def candidate_keys(self, *, contains="", suffix=""):
        """Filter shared names before decoding any archive records."""
        return (key for key in self.rows if contains in key and key.endswith(suffix))


class _EntryRows(Sequence[ArchiveEntry]):
    def __init__(self, index, rows):
        self.index, self.rows = index, rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return _EntryRows(self.index, self.rows[index])
        return self.index[self.rows[index]]


class _SelectedEntries(Mapping[str, ArchiveEntry]):
    def __init__(self, groups, sources):
        self.groups, self.sources = groups, sources
        self._count = None

    def __getitem__(self, key):
        from cdmw.core.item_sources import active_item_source
        entry = active_item_source(self.groups[key], self.sources)
        if entry is None:
            raise KeyError(key)
        return entry

    def __iter__(self):
        if not self.sources.obsolete_packages:
            yield from self.groups
            return
        for key in self.groups:
            if any(self.groups.index._package_for_row(row) not in self.sources.obsolete_packages
                   for row in _rows(self.groups.rows[key])):
                yield key

    def __len__(self):
        if self._count is None:
            self._count = len(self.groups) if not self.sources.obsolete_packages else sum(1 for _ in self)
        return self._count

    def __bool__(self):
        return next(iter(self), None) is not None


class _FilteredGroups(_SelectedEntries):
    def candidate_keys(self, *, contains="", suffix=""):
        # Source filtering belongs in __getitem__, after the cheap name test.
        # A candidate containing only excluded records returns no group on get.
        return self.groups.candidate_keys(contains=contains, suffix=suffix)

    def __getitem__(self, key):
        rows = tuple(row for row in _rows(self.groups.rows[key])
                     if self.groups.index._package_for_row(row) not in self.sources.obsolete_packages)
        if not rows:
            raise KeyError(key)
        return _EntryRows(self.groups.index, rows)
