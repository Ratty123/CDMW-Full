"""Versioned memory-mapped storage for archive catalogue rows."""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import struct
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from cdmw.core.atomic_file import atomic_publish_directory
from cdmw.core.common import raise_if_cancelled
from cdmw.models import ArchiveEntry


ARCHIVE_ENTRY_STORE_SCHEMA = 1
_MANIFEST_NAME = "manifest.json"
_PATH_BYTES_NAME = "paths.utf8"
_PATH_OFFSETS_NAME = "path_offsets.u64"
_ROWS_NAME = "rows.bin"
_EXTENSION_ROWS_NAME = "extension_rows.u32"
_PATH_HASH_ROWS_NAME = "path_hash_rows.bin"
_ROW = struct.Struct("<IHQQQII")
_U64 = struct.Struct("<Q")
_U32 = struct.Struct("<I")
_PATH_HASH_ROW = struct.Struct("<QI")


def _normalized_archive_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def _path_hash(value: object) -> int:
    encoded = _normalized_archive_path(value).encode("utf-8", errors="surrogatepass")
    return int.from_bytes(hashlib.blake2b(encoded, digest_size=8).digest(), "little")


def write_archive_entry_store(
    target_dir: Path | str,
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: object | None = None,
) -> Path:
    """Write a complete sibling-staged store and publish it atomically."""

    target = Path(target_dir).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=target.parent))
    published = False
    try:
        pamt_ids: dict[str, int] = {}
        pamt_paths: list[str] = []
        extension_ids: dict[str, int] = {}
        extensions: list[str] = []
        extension_rows: dict[str, list[int]] = defaultdict(list)
        path_hash_rows: list[tuple[int, int]] = []
        path_offset = 0
        with (
            (staging / _PATH_BYTES_NAME).open("wb") as path_stream,
            (staging / _PATH_OFFSETS_NAME).open("wb") as offset_stream,
            (staging / _ROWS_NAME).open("wb") as row_stream,
        ):
            offset_stream.write(_U64.pack(0))
            for row_id, entry in enumerate(entries):
                if row_id % 4096 == 0:
                    raise_if_cancelled(stop_event)
                path_text = str(entry.path or "")
                path_bytes = path_text.encode("utf-8", errors="surrogatepass")
                path_stream.write(path_bytes)
                path_offset += len(path_bytes)
                offset_stream.write(_U64.pack(path_offset))

                pamt_text = str(entry.pamt_path or "")
                pamt_id = pamt_ids.get(pamt_text)
                if pamt_id is None:
                    pamt_id = len(pamt_paths)
                    pamt_ids[pamt_text] = pamt_id
                    pamt_paths.append(pamt_text)
                extension = str(entry.extension or "")
                extension_id = extension_ids.get(extension)
                if extension_id is None:
                    extension_id = len(extensions)
                    if extension_id > 0xFFFF:
                        raise ValueError("Archive entry store has too many extension values.")
                    extension_ids[extension] = extension_id
                    extensions.append(extension)
                extension_rows[extension].append(row_id)
                path_hash_rows.append((_path_hash(path_text), row_id))
                row_stream.write(
                    _ROW.pack(
                        pamt_id,
                        extension_id,
                        int(entry.offset),
                        int(entry.comp_size),
                        int(entry.orig_size),
                        int(entry.flags),
                        int(entry.paz_index),
                    )
                )

        extension_ranges: dict[str, tuple[int, int]] = {}
        extension_cursor = 0
        with (staging / _EXTENSION_ROWS_NAME).open("wb") as stream:
            for extension in extensions:
                row_ids = extension_rows.get(extension, ())
                extension_ranges[extension] = (extension_cursor, len(row_ids))
                for row_id in row_ids:
                    stream.write(_U32.pack(row_id))
                extension_cursor += len(row_ids)

        path_hash_rows.sort()
        with (staging / _PATH_HASH_ROWS_NAME).open("wb") as stream:
            for path_digest, row_id in path_hash_rows:
                stream.write(_PATH_HASH_ROW.pack(path_digest, row_id))

        manifest = {
            "schema_version": ARCHIVE_ENTRY_STORE_SCHEMA,
            "entry_count": len(entries),
            "pamt_paths": pamt_paths,
            "extensions": extensions,
            "extension_ranges": extension_ranges,
            "row_size": _ROW.size,
            "path_bytes": path_offset,
        }
        (staging / _MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise_if_cancelled(stop_event)
        atomic_publish_directory(staging, target)
        published = True
        return target
    finally:
        if not published and staging.exists():
            import shutil

            shutil.rmtree(staging, ignore_errors=True)


class ArchiveEntryStore:
    """Read-only mmap view that materializes ArchiveEntry objects on demand."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        manifest = json.loads((self.root / _MANIFEST_NAME).read_text(encoding="utf-8"))
        if not isinstance(manifest, Mapping):
            raise ValueError("Archive entry store manifest is invalid.")
        if int(manifest.get("schema_version", 0) or 0) != ARCHIVE_ENTRY_STORE_SCHEMA:
            raise ValueError("Archive entry store schema is unsupported.")
        self.entry_count = int(manifest.get("entry_count", -1))
        if self.entry_count < 0 or int(manifest.get("row_size", 0) or 0) != _ROW.size:
            raise ValueError("Archive entry store row contract is invalid.")
        self._declared_path_bytes = int(manifest.get("path_bytes", -1))
        self._pamt_paths = tuple(Path(str(value)) for value in tuple(manifest.get("pamt_paths", ())))
        self._extensions = tuple(str(value) for value in tuple(manifest.get("extensions", ())))
        ranges = manifest.get("extension_ranges")
        self._extension_ranges = {
            str(key): (int(value[0]), int(value[1]))
            for key, value in (ranges.items() if isinstance(ranges, Mapping) else ())
            if isinstance(value, Sequence) and len(value) == 2
        }
        self._files = []
        self._maps = []
        self._path_bytes = self._open_map(_PATH_BYTES_NAME, allow_empty=True)
        self._path_offsets = self._open_map(_PATH_OFFSETS_NAME)
        self._rows = self._open_map(_ROWS_NAME, allow_empty=True)
        self._extension_rows = self._open_map(_EXTENSION_ROWS_NAME, allow_empty=True)
        self._path_hash_rows = self._open_map(_PATH_HASH_ROWS_NAME, allow_empty=True)
        self._validate_sizes()

    def _open_map(self, name: str, *, allow_empty: bool = False) -> mmap.mmap | None:
        stream = (self.root / name).open("rb")
        self._files.append(stream)
        size = os.fstat(stream.fileno()).st_size
        if size == 0 and allow_empty:
            return None
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        self._maps.append(mapped)
        return mapped

    def _validate_sizes(self) -> None:
        if self._path_offsets is None or (self.entry_count > 0 and self._path_bytes is None):
            raise ValueError("Archive entry store is incomplete.")
        if len(self._path_offsets) != (self.entry_count + 1) * _U64.size:
            raise ValueError("Archive entry store path offsets are invalid.")
        path_bytes = len(self._path_bytes) if self._path_bytes is not None else 0
        final_path_offset = _U64.unpack_from(
            self._path_offsets,
            self.entry_count * _U64.size,
        )[0]
        if self._declared_path_bytes != path_bytes or final_path_offset != path_bytes:
            raise ValueError("Archive entry store path bytes are invalid.")
        if (len(self._rows) if self._rows is not None else 0) != self.entry_count * _ROW.size:
            raise ValueError("Archive entry store rows are invalid.")
        if (len(self._extension_rows) if self._extension_rows is not None else 0) != self.entry_count * _U32.size:
            raise ValueError("Archive entry store extension index is invalid.")
        if sum(count for _start, count in self._extension_ranges.values()) != self.entry_count or any(
            start < 0 or count < 0 or start + count > self.entry_count
            for start, count in self._extension_ranges.values()
        ):
            raise ValueError("Archive entry store extension ranges are invalid.")
        if self._path_hash_rows is not None and len(self._path_hash_rows) != self.entry_count * _PATH_HASH_ROW.size:
            raise ValueError("Archive entry store path index is invalid.")

    def __len__(self) -> int:
        return self.entry_count

    def path(self, row_id: int) -> str:
        index = self._checked_row_id(row_id)
        start = _U64.unpack_from(self._path_offsets, index * _U64.size)[0]  # type: ignore[arg-type]
        end = _U64.unpack_from(self._path_offsets, (index + 1) * _U64.size)[0]  # type: ignore[arg-type]
        return bytes(self._path_bytes[start:end]).decode("utf-8", errors="surrogatepass")  # type: ignore[index]

    def entry(self, row_id: int) -> ArchiveEntry:
        index = self._checked_row_id(row_id)
        if self._rows is None:
            raise IndexError(index)
        pamt_id, _extension_id, offset, comp_size, orig_size, flags, paz_index = _ROW.unpack_from(
            self._rows, index * _ROW.size  # type: ignore[arg-type]
        )
        if pamt_id >= len(self._pamt_paths):
            raise ValueError("Archive entry store PAMT id is invalid.")
        pamt_path = self._pamt_paths[pamt_id]
        return ArchiveEntry(
            path=self.path(index),
            pamt_path=pamt_path,
            paz_file=pamt_path.parent / f"{paz_index}.paz",
            offset=offset,
            comp_size=comp_size,
            orig_size=orig_size,
            flags=flags,
            paz_index=paz_index,
        )

    def iter_entries(self, row_ids: Iterable[int] | None = None) -> Iterator[ArchiveEntry]:
        source = range(self.entry_count) if row_ids is None else row_ids
        for row_id in source:
            yield self.entry(int(row_id))

    def row_ids_for_extension(self, extension: str) -> tuple[int, ...]:
        start_count = self._extension_ranges.get(str(extension).strip().lower())
        if start_count is None or self._extension_rows is None:
            return ()
        start, count = start_count
        return tuple(
            _U32.unpack_from(self._extension_rows, (start + offset) * _U32.size)[0]
            for offset in range(count)
        )

    def row_ids_for_path(self, path: str) -> tuple[int, ...]:
        if self._path_hash_rows is None:
            return ()
        target_hash = _path_hash(path)
        low = 0
        high = self.entry_count
        while low < high:
            middle = (low + high) // 2
            digest, _row_id = _PATH_HASH_ROW.unpack_from(
                self._path_hash_rows, middle * _PATH_HASH_ROW.size
            )
            if digest < target_hash:
                low = middle + 1
            else:
                high = middle
        normalized = _normalized_archive_path(path)
        matches = []
        cursor = low
        while cursor < self.entry_count:
            digest, row_id = _PATH_HASH_ROW.unpack_from(
                self._path_hash_rows, cursor * _PATH_HASH_ROW.size
            )
            if digest != target_hash:
                break
            if _normalized_archive_path(self.path(row_id)) == normalized:
                matches.append(row_id)
            cursor += 1
        return tuple(matches)

    def _checked_row_id(self, row_id: int) -> int:
        index = int(row_id)
        if index < 0 or index >= self.entry_count:
            raise IndexError(index)
        return index

    def close(self) -> None:
        for mapped in reversed(self._maps):
            mapped.close()
        self._maps.clear()
        for stream in reversed(self._files):
            stream.close()
        self._files.clear()

    def __enter__(self) -> ArchiveEntryStore:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


__all__ = [
    "ARCHIVE_ENTRY_STORE_SCHEMA",
    "ArchiveEntryStore",
    "write_archive_entry_store",
]
