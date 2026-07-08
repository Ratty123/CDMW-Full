from __future__ import annotations

from array import array
from collections.abc import Iterator, Mapping, Sequence
from typing import TypeAlias

from cdmw.core.archive_format import normalize_archive_extension_filter
from cdmw.models import ArchiveEntry

ArchiveRowIds: TypeAlias = int | Sequence[int]
MutableArchiveRowIds: TypeAlias = int | array


def archive_path_key(path: object) -> str:
    text = str(path or "")
    stripped = text.strip()
    if not stripped:
        return ""
    if "\\" not in stripped and stripped == text and stripped.lower() == stripped:
        return stripped
    return stripped.replace("\\", "/").lower()


def archive_basename_key(path: object) -> str:
    normalized_path = str(path or "").replace("\\", "/").strip()
    basename = normalized_path.rsplit("/", 1)[-1].strip().lower()
    return basename


def append_archive_row_id(
    rows_by_key: dict[str, MutableArchiveRowIds],
    key: str,
    row_id: int,
) -> None:
    if not key:
        return
    row_id = int(row_id)
    current = rows_by_key.get(key)
    if current is None:
        rows_by_key[key] = row_id
        return
    if isinstance(current, int):
        bucket = array("I", (int(current), row_id))
        rows_by_key[key] = bucket
        return
    current.append(row_id)


def compact_archive_row_ids(value: object) -> int | array | tuple[int, ...] | None:
    if isinstance(value, int):
        return int(value)
    if isinstance(value, array):
        if not value:
            return None
        if len(value) == 1:
            return int(value[0])
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        row_ids: list[int] = []
        for raw_id in value:
            try:
                row_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        if not row_ids:
            return None
        if len(row_ids) == 1:
            return row_ids[0]
        return tuple(row_ids)
    return None


def compact_archive_rows_mapping(
    rows_by_key: Mapping[str, object],
) -> dict[str, int | array | tuple[int, ...]]:
    compacted: dict[str, int | array | tuple[int, ...]] = {}
    for key, raw_ids in rows_by_key.items():
        normalized_key = str(key or "")
        if not normalized_key:
            continue
        row_ids = compact_archive_row_ids(raw_ids)
        if row_ids is not None:
            compacted[normalized_key] = row_ids
    return compacted


def _row_ids_tuple(value: object) -> tuple[int, ...]:
    if isinstance(value, int):
        return (int(value),)
    if isinstance(value, array):
        return tuple(int(row_id) for row_id in value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        row_ids: list[int] = []
        for raw_id in value:
            try:
                row_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        return tuple(row_ids)
    return ()


def _row_id_count(value: object) -> int:
    if isinstance(value, int):
        return 1
    if isinstance(value, array):
        return len(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    return 0


class ArchiveRowIndex(Mapping[str, Sequence[ArchiveEntry]]):
    def __init__(
        self,
        entries: Sequence[ArchiveEntry],
        rows_by_key: Mapping[str, ArchiveRowIds],
        *,
        name: str = "",
    ) -> None:
        self._entries = entries
        self._rows_by_key = dict(rows_by_key)
        self._name = str(name or "")
        self._singleton_count: int | None = None
        self._multi_count: int | None = None
        self._row_ref_count: int | None = None
        self._ensure_counts()

    def __len__(self) -> int:
        return len(self._rows_by_key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._rows_by_key)

    def __contains__(self, key: object) -> bool:
        return key in self._rows_by_key

    def __getitem__(self, key: str) -> tuple[ArchiveEntry, ...]:
        if key not in self._rows_by_key:
            raise KeyError(key)
        return self.materialize_key(key)

    def get(self, key: object, default: object = None) -> object:
        if key not in self._rows_by_key:
            return default
        return self.materialize_key(key)

    def row_ids_for_key(self, key: object) -> tuple[int, ...]:
        if key not in self._rows_by_key:
            return ()
        return _row_ids_tuple(self._rows_by_key[key])

    def row_items(self) -> Iterator[tuple[str, tuple[int, ...]]]:
        for key, row_ids in self._rows_by_key.items():
            yield key, _row_ids_tuple(row_ids)

    def entry_for_singleton_key(self, key: object) -> ArchiveEntry | None:
        row_ids = self.row_ids_for_key(key)
        if len(row_ids) != 1:
            return None
        row_id = row_ids[0]
        if 0 <= row_id < len(self._entries):
            return self._entries[row_id]
        return None

    def materialize_key(self, key: object) -> tuple[ArchiveEntry, ...]:
        row_ids = self.row_ids_for_key(key)
        if not row_ids:
            return ()
        entry_count = len(self._entries)
        return tuple(self._entries[row_id] for row_id in row_ids if 0 <= row_id < entry_count)

    def materialize_all(self) -> dict[str, list[ArchiveEntry]]:
        return {key: list(self.materialize_key(key)) for key in self._rows_by_key}

    @property
    def name(self) -> str:
        return self._name

    @property
    def singleton_count(self) -> int:
        self._ensure_counts()
        return int(self._singleton_count or 0)

    @property
    def multi_count(self) -> int:
        self._ensure_counts()
        return int(self._multi_count or 0)

    @property
    def row_ref_count(self) -> int:
        self._ensure_counts()
        return int(self._row_ref_count or 0)

    @property
    def raw_rows_by_key(self) -> Mapping[str, ArchiveRowIds]:
        return self._rows_by_key

    def _ensure_counts(self) -> None:
        if self._singleton_count is not None:
            return
        singleton_count = 0
        multi_count = 0
        row_ref_count = 0
        for row_ids in self._rows_by_key.values():
            count = _row_id_count(row_ids)
            row_ref_count += count
            if count <= 1:
                singleton_count += 1
            else:
                multi_count += 1
        self._singleton_count = singleton_count
        self._multi_count = multi_count
        self._row_ref_count = row_ref_count


def build_archive_path_row_index(entries: Sequence[ArchiveEntry]) -> ArchiveRowIndex:
    rows_by_key: dict[str, MutableArchiveRowIds] = {}
    for row_id, archive_entry in enumerate(entries):
        key = archive_path_key(getattr(archive_entry, "path", ""))
        append_archive_row_id(rows_by_key, key, row_id)
    return ArchiveRowIndex(entries, compact_archive_rows_mapping(rows_by_key), name="path")


def build_archive_basename_row_index(entries: Sequence[ArchiveEntry]) -> ArchiveRowIndex:
    rows_by_key: dict[str, MutableArchiveRowIds] = {}
    for row_id, archive_entry in enumerate(entries):
        key = archive_basename_key(getattr(archive_entry, "path", ""))
        append_archive_row_id(rows_by_key, key, row_id)
    sorted_rows: dict[str, int | tuple[int, ...]] = {}
    for key, raw_ids in rows_by_key.items():
        if isinstance(raw_ids, int):
            sorted_rows[key] = int(raw_ids)
            continue
        sorted_ids = sorted(
            (int(row_id) for row_id in raw_ids),
            key=lambda row_id: (
                -str(entries[row_id].path or "").replace("\\", "/").strip().count("/"),
                -len(str(entries[row_id].path or "").replace("\\", "/").strip()),
                archive_path_key(getattr(entries[row_id], "path", "")),
            ),
        )
        if len(sorted_ids) == 1:
            sorted_rows[key] = sorted_ids[0]
        elif sorted_ids:
            sorted_rows[key] = tuple(sorted_ids)
    return ArchiveRowIndex(entries, sorted_rows, name="basename")


def build_archive_extension_row_index(entries: Sequence[ArchiveEntry]) -> ArchiveRowIndex:
    rows_by_key: dict[str, MutableArchiveRowIds] = {}
    for row_id, archive_entry in enumerate(entries):
        extension = normalize_archive_extension_filter(getattr(archive_entry, "extension", ""))
        append_archive_row_id(rows_by_key, extension, row_id)
    return ArchiveRowIndex(entries, compact_archive_rows_mapping(rows_by_key), name="extension")


def build_archive_role_row_index(entries: Sequence[ArchiveEntry]) -> ArchiveRowIndex:
    rows_by_key: dict[str, MutableArchiveRowIds] = {}
    texture_roles = {"image", "normal", "material", "impostor", "ui"}
    from cdmw.core.archive_format import archive_entry_role

    for row_id, archive_entry in enumerate(entries):
        role = archive_entry_role(archive_entry)
        if role:
            append_archive_row_id(rows_by_key, role, row_id)
            if role in texture_roles:
                append_archive_row_id(rows_by_key, "texture", row_id)
    return ArchiveRowIndex(entries, compact_archive_rows_mapping(rows_by_key), name="role")
