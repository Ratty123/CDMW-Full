"""Read-only, generation-bound view of the Full backend's published FAI3 index.

Path and basename queries read the existing FAI3/ADI1 maps. Only a bounded working
set of names and row IDs is retained in Python. Extension scans stay on workers;
large groups use streaming cursors instead of resident row lists. The maps and
their generation stay alive as long as any consumer retains this view.
"""
from __future__ import annotations

from array import array
from collections import OrderedDict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import json
from itertools import islice
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
_DEPENDENCY_HEADER = struct.Struct("<8sII8Q")
_DEPENDENCY_RECORD = struct.Struct("<QQ")
_LOOKUP_CACHE_SIZE = 256
_CACHED_GROUP_ROWS = 1024
_EXTENSION_CACHE_SIZE = 128
_CACHED_EXTENSION_ROWS = 65536
_EXTENSION_ROW_BUDGET = 131072
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


def _normalize_path(value):
    return str(value).replace("\\", "/").strip("/").lower()


def _stop_token(stop_event):
    return SimpleNamespace(is_set=stop_event) if callable(stop_event) else stop_event


def _basename_hash(value):
    result = 14695981039346656037
    for byte in value.encode("utf-8").lower():
        result = ((result ^ byte) * 1099511628211) & 0xffffffffffffffff
    return result


class ResidentArchiveIndex(Sequence[ArchiveEntry]):
    def __init__(self, source: ResidentArchiveSource, *, stop_event=None):
        self.source = source
        self._mapping = None
        self._dependency_mapping = None
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
            self._lookup_lock = threading.RLock()
            self._extension_lock = threading.Lock()
            self._lookups = OrderedDict()
            self._row_paths = OrderedDict()
            self._source_paths = OrderedDict()
            self._source_packages = OrderedDict()
            self._extensions = None
            self._dependency_check_at = 0.
            self._mounts = None
            mount_path = root / "meta" / "0.papgt"
            if mount_path.is_file():
                from cdmw.core.papgt_format import parse_papgt
                if mount_path.stat().st_size > 1024 * 1024:
                    raise ValueError("Archive mount table is unexpectedly large.")
                mount_rows = parse_papgt(mount_path.read_bytes())
                packages = {file.parent.name.casefold() for file, *_ in self.source_files if file.suffix.lower() == ".pamt"}
                self._mounts = {}
                for rank, mount in enumerate(mount_rows):
                    if mount.name.casefold() not in packages:
                        if mount.flags & 0xff:
                            continue
                        raise ValueError(f"Mounted archive is missing: {mount.name}")
                    self._mounts[str(root / mount.name).replace("\\", "/").casefold()] = rank
            self.by_path = _EntryGroups(self, "path")
            self.by_basename = _EntryGroups(self, "basename")
            self.by_extension = _EntryGroups(self, "extension")
            self.validate_sources(stop_event)
        except BaseException:
            if self._mapping is not None:
                self._mapping.close()
            raise

    def __len__(self):
        return self._count

    def _string(self, offset, length):
        return self._bytes(offset, length).decode("utf-8")

    def _bytes(self, offset, length):
        if offset > self._strings_size or length > self._strings_size - offset:
            raise ValueError("Archive catalogue string is out of bounds.")
        start = self._strings + offset
        return self._mapping[start:start + length]

    def _cached(self, cache, key):
        with self._lookup_lock:
            result = cache.get(key)
            if result is not None:
                cache.move_to_end(key)
            return result

    def _remember(self, cache, key, value):
        with self._lookup_lock:
            cache[key] = value
            cache.move_to_end(key)
            while len(cache) > _LOOKUP_CACHE_SIZE:
                cache.popitem(last=False)
        return value

    def _path_bytes(self, row):
        record = self._records + row * _RECORD.size
        offset = _OFFSET.unpack_from(self._mapping, record)[0]
        length = _LENGTH.unpack_from(self._mapping, record + 48)[0]
        return self._bytes(offset, length).replace(b"\\", b"/").strip(b"/")

    def _path(self, row):
        result = self._cached(self._row_paths, row)
        if result is None:
            result = self._path_bytes(row).decode("utf-8")
            if len(result) <= 4096:
                self._remember(self._row_paths, row, result)
        return result

    def _source_path(self, offset, length):
        key = (offset, length)
        result = self._cached(self._source_paths, key)
        if result is None:
            result = Path(self._string(offset, length))
            self._remember(self._source_paths, key, result)
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
            path=self._path(row),
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

    def _dependency_index(self):
        # The backend may publish ADI1 after FAI3. Missing/invalid derived data
        # uses streaming queries and is retried without retaining another index.
        with self._lookup_lock:
            if self._dependency_mapping is not None:
                return self._dependency_mapping
            now = time.monotonic()
            if now < self._dependency_check_at:
                return None
            self._dependency_check_at = now + 1.
            mapping = None
            try:
                with Path(self.source.index_path).with_suffix(".adi").open("rb") as handle:
                    mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
                if len(mapping) < _DEPENDENCY_HEADER.size:
                    raise ValueError("Truncated dependency index.")
                magic, version, size, count, names, stems, facets, facet_size, source_count, source_size, _ = _DEPENDENCY_HEADER.unpack_from(mapping)
                if (magic != b"CDMWADI1" or version != 1 or size != 16
                        or count != self._count or source_count != self._count
                        or source_size != len(self._mapping) or names != 80
                        or stems != names + count * 16 or facets != stems + count * 16
                        or facets > len(mapping) or facet_size != len(mapping) - facets
                        or facet_size > 16 * 1024 * 1024):
                    raise ValueError("Dependency index does not match its catalogue.")
                self._dependency_mapping = mapping
                return mapping
            except (OSError, ValueError):
                if mapping is not None:
                    mapping.close()
                return None

    def _path_rows(self, key):
        if not key.isascii():
            # FAI3 sorts ASCII-folded UTF-8; retain Python's Unicode lowercase
            # lookup semantics without applying a different binary-search order.
            return array("Q", (row for row in self._scan_rows()
                               if self._path_bytes(row).decode("utf-8").lower() == key))
        target = key.encode("utf-8")
        low, high = 0, self._count
        while low < high:
            middle = (low + high) // 2
            if self._path_bytes(middle).lower() < target:
                low = middle + 1
            else:
                high = middle
        rows = array("Q")
        while low < self._count and self._path_bytes(low).lower() == target:
            rows.append(low)
            low += 1
        return rows

    def _basename_rows(self, key):
        data = self._dependency_index() if key.isascii() else None
        if data is None:
            return array("Q", (row for row in self._scan_rows()
                if self._path_bytes(row).decode("utf-8").lower().rsplit("/", 1)[-1] == key))
        target = _basename_hash(key)
        low, high = 0, self._count
        while low < high:
            middle = (low + high) // 2
            if _OFFSET.unpack_from(data, 80 + middle * 16)[0] < target:
                low = middle + 1
            else:
                high = middle
        rows = array("Q")
        while low < self._count:
            hashed, row = _DEPENDENCY_RECORD.unpack_from(data, 80 + low * 16)
            if hashed != target:
                break
            if row >= self._count:
                raise ValueError("Archive dependency row is out of bounds.")
            if self._path_bytes(row).decode("utf-8").lower().rsplit("/", 1)[-1] == key:
                rows.append(row)  # Verify names even when their hashes collide.
            low += 1
        return rows

    def _scan_rows(self, stop_event=None):
        stop_event = _stop_token(stop_event)
        for row in range(self._count):
            if row % 4096 == 0:
                raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
                if row:
                    time.sleep(.001)  # Let queued Qt input run during long scans.
            yield row
        raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")

    def _extension(self, row):
        basename = self._path_bytes(row).rsplit(b"/", 1)[-1]
        dot = basename.rfind(b".")
        return basename[dot:].decode("utf-8").lower() if dot >= 0 else ""

    def _prepare_extensions(self, stop_event=None):
        stop_event = _stop_token(stop_event)
        while not self._extension_lock.acquire(timeout=.05):
            raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
        try:
            raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
            if self._extensions is not None:
                return
            groups, overflow, retained_rows = {}, False, 0
            for row in self._scan_rows(stop_event):
                extension = self._extension(row)
                group = groups.get(extension)
                if group is None:
                    if len(groups) == _EXTENSION_CACHE_SIZE or len(extension) > 4096:
                        overflow = True
                        continue
                    group = groups[extension] = [0, array("Q")]
                group[0] += 1
                if group[1] is not None:
                    if group[0] > _CACHED_EXTENSION_ROWS or retained_rows >= _EXTENSION_ROW_BUDGET:
                        retained_rows -= len(group[1])
                        group[1] = None
                    else:
                        group[1].append(row)
                        retained_rows += 1
            # Publish only a complete scan; a cancelled worker leaves no partial
            # extension groups for another consumer of this shared generation.
            self._extension_overflow = overflow
            self._extensions = groups
        finally:
            self._extension_lock.release()

    def _extension_rows(self, key, stop_event=None):
        self._prepare_extensions(stop_event)
        group = self._extensions.get(key)
        if group is None:
            if not self._extension_overflow:
                return ()
            count = sum(1 for row in self._scan_rows(stop_event) if self._extension(row) == key)
            return _ExtensionRows(self, key, count, stop_event) if count else ()
        count, rows = group
        return rows if rows is not None else _ExtensionRows(self, key, count, stop_event)

    def _group_rows(self, kind, key):
        cache_key = (kind, key)
        rows = self._cached(self._lookups, cache_key)
        if rows is None:
            rows = (self._path_rows(key) if kind == "path" else self._basename_rows(key)
                    if kind == "basename" else self._extension_rows(key))
            if kind != "extension" and len(rows) <= _CACHED_GROUP_ROWS and len(key) <= 4096:
                self._remember(self._lookups, cache_key, rows)
        return rows

    def item_metadata(self, *, stop_event=None):
        stop_event = _stop_token(stop_event)
        for extension in (".pabgb", ".pabgh", ".staticinfobody", ".staticinfoheader", ".paloc"):
            for row in self._extension_rows(extension, stop_event):
                raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
                yield self[row]

    def selected_paths(self, sources):
        return _SelectedEntries(self.by_path, sources)

    def active_entry(self, path):
        return next((self[row] for row in self._active_rows(self._group_rows("path", _normalize_path(path)))), None)

    def index_maps(self, sources):
        if not sources.obsolete_packages:
            return self.by_path, self.by_basename
        return _FilteredGroups(self.by_path, sources), _FilteredGroups(self.by_basename, sources)

    def _package_for_row(self, row):
        record = self._records + row * _RECORD.size
        offset = _OFFSET.unpack_from(self._mapping, record + 8)[0]
        length = _LENGTH.unpack_from(self._mapping, record + 52)[0]
        key = (offset, length)
        package = self._cached(self._source_packages, key)
        if package is None:
            package = str(self._source_path(offset, length)).replace("\\", "/").rsplit("/", 1)[0].casefold()
            self._remember(self._source_packages, key, package)
        return package

    def _active_rows(self, rows):
        if self._mounts is None:
            for row in rows:
                flags = _LENGTH.unpack_from(self._mapping, self._records + row * _RECORD.size + 68)[0]
                if not (flags & 2) or flags & 1:
                    yield row
            return
        winner, best_rank = None, None
        for row in rows:
            rank = self._mounts.get(self._package_for_row(row))
            if rank is not None and (best_rank is None or rank < best_rank):
                winner, best_rank = row, rank
        if winner is not None:
            yield winner

    def matching(self, extensions, *, active_only=True, contains="", stop_event=None) -> Iterator[ArchiveEntry]:
        """Worker-side filtered enumeration, retaining the backend's mount winner."""
        stop_event = _stop_token(stop_event)
        for extension in extensions:
            previous, rows = None, []
            for row in self._extension_rows(extension, stop_event):
                raise_if_cancelled(stop_event, "Archive catalogue loading cancelled.")
                key = self._path_bytes(row).decode("utf-8").lower()
                if contains and contains not in key:
                    continue
                if active_only and not key.isascii() and row not in self._active_rows(self._group_rows("path", key)):
                    # Unicode case-equivalent paths need not be adjacent in
                    # FAI3's ASCII-folded order. Select their global mount winner.
                    continue
                if key != previous and rows:
                    yield from (self[item] for item in (self._active_rows(rows) if active_only else rows))
                    rows = []
                previous = key
                rows.append(row)
            yield from (self[item] for item in (self._active_rows(rows) if active_only else rows))

    def _keys(self, kind, *, contains="", suffix=""):
        if kind == "extension":
            self._prepare_extensions()
            if not self._extension_overflow:
                yield from (key for key in self._extensions if contains in key and key.endswith(suffix))
                return
        previous = None
        # ADI1 lets basename iteration identify the first occurrence without a
        # catalogue-wide seen-name set. If it is still being built, the set is
        # local to this explicitly requested enumeration, never retained here.
        derived = self._dependency_index() if kind == "basename" else None
        seen = set()
        needle = contains.encode("utf-8") if contains.isascii() else None
        ending = suffix.encode("utf-8") if suffix.isascii() else None
        for row in self._scan_rows():
            raw = self._path_bytes(row).lower()
            if kind == "basename":
                raw = raw.rsplit(b"/", 1)[-1]
            elif kind == "extension":
                raw = raw.rsplit(b"/", 1)[-1]
                dot = raw.rfind(b".")
                raw = raw[dot:] if dot >= 0 else b""
            if (needle is not None and needle not in raw
                    or ending is not None and not raw.endswith(ending)):
                continue
            key = raw.decode("utf-8").lower()
            if contains not in key or not key.endswith(suffix):
                continue
            if kind == "path" and key.isascii():
                if key == previous:
                    continue
                previous = key
            elif kind == "basename" and derived is not None and key.isascii():
                rows = self._group_rows(kind, key)
                if not rows or row != rows[0]:
                    continue
            else:
                if key in seen:
                    continue
                seen.add(key)
            yield key


class _EntryGroups(Mapping[str, Sequence[ArchiveEntry]]):
    def __init__(self, index, kind):
        self.index, self.kind = index, kind
        self._count = None

    def __len__(self):
        if self._count is None:
            self._count = sum(1 for _ in self)
        return self._count

    def __bool__(self):
        return bool(self.index)

    def __iter__(self):
        return self.candidate_keys()

    def row_ids(self, key):
        if not isinstance(key, str):
            raise KeyError(key)
        rows = self.index._group_rows(self.kind, key)
        if not rows:
            raise KeyError(key)
        return rows

    def __getitem__(self, key):
        return _EntryRows(self.index, self.row_ids(key))

    def candidate_keys(self, *, contains="", suffix=""):
        """Filter mapped names before decoding any archive records."""
        return self.index._keys(self.kind, contains=contains, suffix=suffix)


class _ExtensionRows(Sequence[int]):
    """A large extension group has a count and a cursor, not a retained row list."""
    def __init__(self, index, extension, count, stop_event=None):
        self.index, self.extension, self.count = index, extension, count
        self.stop_event = _stop_token(stop_event)

    def __len__(self):
        return self.count

    def __iter__(self):
        for row in self.index._scan_rows(self.stop_event):
            if self.index._extension(row) == self.extension:
                yield row

    def __getitem__(self, position):
        if isinstance(position, slice):
            selected = range(*position.indices(self.count))
            if not selected:
                return array("Q")
            if selected.step > 0:
                return array("Q", islice(self, selected.start, selected.stop, selected.step))
            rows = array("Q", islice(self, selected[-1], selected[0] + 1))
            return rows[::selected.step]
        if position < 0:
            position += self.count
        if not 0 <= position < self.count:
            raise IndexError(position)
        return next(islice(self, position, position + 1))


class _EntryRows(Sequence[ArchiveEntry]):
    def __init__(self, index, rows):
        self.index, self.rows = index, rows

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        for row in self.rows:
            yield self.index[row]

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
                   for row in self.groups.row_ids(key)):
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
        rows = tuple(row for row in self.groups.row_ids(key)
                     if self.groups.index._package_for_row(row) not in self.sources.obsolete_packages)
        if not rows:
            raise KeyError(key)
        return _EntryRows(self.groups.index, rows)
