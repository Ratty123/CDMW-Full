from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from cdmw.core.archive_compact_index import (
    ArchiveRowIndex,
    append_archive_row_id,
    archive_basename_key,
    archive_path_key,
    compact_archive_row_ids,
    compact_archive_rows_mapping,
)

from cdmw.core.archive_filtering import archive_entry_identity_key, archive_entry_role
from cdmw.core.archive_format import normalize_archive_extension_filter
from cdmw.core.archive_name_search import (
    ArchiveNameSearchIndex,
    _archive_name_search_alias_signature,
    _load_archive_name_search_shards_trusted,
    _load_native_name_search_index_binary,
    _load_or_update_archive_name_search_shards,
    _write_archive_name_search_shard_caches,
    _write_native_name_search_index_binary,
    archive_item_index_dependency_signature,
)
from cdmw.core.archive_scan_cache import (
    _ARCHIVE_BASIC_INDEX_CACHE_MAGIC,
    _ARCHIVE_BASIC_INDEX_CACHE_MAX_SAFE_BYTES,
    _ARCHIVE_BASIC_INDEX_CACHE_VERSION,
    _ARCHIVE_BASIC_INDEX_SHARD_CACHE_MAGIC,
    _ARCHIVE_BASIC_INDEX_SHARD_CACHE_VERSION,
    _ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
    _ARCHIVE_DERIVED_INDEX_CACHE_MAX_SAFE_BYTES,
    _ARCHIVE_DERIVED_INDEX_CACHE_VERSION,
    _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
    _archive_entry_metadata_from_entries,
    _archive_entry_shard_groups,
    _archive_scan_shard_id,
    _collect_archive_scan_sources_from_entries,
    _describe_archive_cache_metadata_mismatch,
    _deserialize_archive_basic_index_cache_payload_from_path,
    _deserialize_archive_basic_index_shard_cache_payload_from_path,
    _deserialize_archive_derived_index_cache_payload_from_path,
    _normalize_archive_entry_metadata_signature,
    _normalize_archive_source_rows,
    _record_timing,
    _write_raw_pickle_cache_payload_to_path,
    archive_cache_protected_paths,
    prune_archive_cache_root,
    resolve_archive_basic_index_cache_path,
    resolve_archive_basic_index_shard_cache_dir,
    resolve_archive_derived_index_cache_path,
    resolve_archive_name_search_index_cache_path,
    resolve_archive_name_search_shard_cache_dir,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.core.table_catalog import table_catalog_cache_metadata, table_catalog_cache_metadata_matches
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity


def format_byte_size(value: int) -> str:
    from cdmw.core.archive_extraction import format_byte_size as owner

    return owner(value)


_ARCHIVE_DERIVED_INDEX_CACHE_SUPPORTED_VERSIONS = {12}

def _row_ids_as_tuple(value: object) -> Tuple[int, ...]:
    compacted = compact_archive_row_ids(value)
    if compacted is None:
        return ()
    if isinstance(compacted, int):
        return (int(compacted),)
    return tuple(int(row_id) for row_id in compacted)


def _encode_archive_entry_index_rows(
    index: Mapping[str, Sequence[ArchiveEntry]],
    entries: Sequence[ArchiveEntry],
) -> List[Tuple[str, Tuple[int, ...]]]:
    row_items = getattr(index, "row_items", None)
    if callable(row_items):
        entry_count = len(entries)
        rows: List[Tuple[str, Tuple[int, ...]]] = []
        for key, row_ids in row_items():
            normalized_key = str(key or "")
            if not normalized_key:
                continue
            valid_row_ids = tuple(
                int(row_id)
                for row_id in _row_ids_as_tuple(row_ids)
                if 0 <= int(row_id) < entry_count
            )
            if valid_row_ids:
                rows.append((normalized_key, valid_row_ids))
        rows.sort(key=lambda row: row[0])
        return rows

    entry_indexes_by_id = {id(entry): entry_index for entry_index, entry in enumerate(entries)}
    entry_indexes_by_identity: Dict[ArchiveEntryIdentity, int] = {}
    rows: List[Tuple[str, Tuple[int, ...]]] = []
    for entry_index, entry in enumerate(entries):
        entry_indexes_by_identity.setdefault(archive_entry_identity_key(entry), entry_index)
    for key, values in index.items():
        row_indexes: List[int] = []
        for entry in values:
            entry_index = entry_indexes_by_id.get(id(entry))
            if entry_index is None:
                entry_index = entry_indexes_by_identity.get(archive_entry_identity_key(entry), -1)
            if entry_index is not None and entry_index >= 0:
                row_indexes.append(int(entry_index))
        if row_indexes:
            rows.append((str(key), tuple(row_indexes)))
    rows.sort(key=lambda row: row[0])
    return rows


def _decode_archive_entry_index_row_ids(
    rows: object,
    entry_count: int,
    *,
    row_offset: int = 0,
) -> dict[str, int | tuple[int, ...]]:
    if not isinstance(rows, (list, tuple)):
        raise ValueError("Archive path lookup cache rows are invalid.")
    decoded: dict[str, object] = {}
    entry_count = int(entry_count)
    row_offset = int(row_offset)
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        key = str(row[0] or "")
        raw_indexes = row[1]
        if not key or not isinstance(raw_indexes, (list, tuple)):
            continue
        for raw_index in raw_indexes:
            try:
                entry_index = row_offset + int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= entry_index < entry_count:
                append_archive_row_id(decoded, key, entry_index)
    return compact_archive_rows_mapping(decoded)


def _decode_archive_entry_index_rows(
    rows: object,
    entries: Sequence[ArchiveEntry],
) -> Dict[str, List[ArchiveEntry]]:
    decoded_row_ids = _decode_archive_entry_index_row_ids(rows, len(entries))
    decoded: Dict[str, List[ArchiveEntry]] = {}
    entry_count = len(entries)
    for key, row_ids in decoded_row_ids.items():
        values = [entries[row_id] for row_id in _row_ids_as_tuple(row_ids) if 0 <= row_id < entry_count]
        if values:
            decoded[key] = values
    return decoded


def _sort_archive_basename_index_values(index: Dict[str, List[ArchiveEntry]]) -> Dict[str, List[ArchiveEntry]]:
    """Compatibility sorter for legacy ArchiveEntry basename indexes."""
    for basename_entries in index.values():
        basename_entries.sort(
            key=lambda entry: (
                -str(entry.path or "").replace("\\", "/").strip().count("/"),
                -len(str(entry.path or "").replace("\\", "/").strip()),
                archive_path_key(getattr(entry, "path", "")),
            )
        )
    return index


def _sort_archive_basename_row_ids(
    rows_by_key: Mapping[str, object],
    entries: Sequence[ArchiveEntry],
) -> dict[str, int | tuple[int, ...]]:
    sorted_rows: dict[str, int | tuple[int, ...]] = {}
    entry_count = len(entries)
    for key, raw_ids in rows_by_key.items():
        row_ids = [row_id for row_id in _row_ids_as_tuple(raw_ids) if 0 <= row_id < entry_count]
        if not row_ids:
            continue
        row_ids.sort(
            key=lambda row_id: (
                -str(entries[row_id].path or "").replace("\\", "/").strip().count("/"),
                -len(str(entries[row_id].path or "").replace("\\", "/").strip()),
                archive_path_key(getattr(entries[row_id], "path", "")),
            )
        )
        if len(row_ids) == 1:
            sorted_rows[str(key)] = int(row_ids[0])
        else:
            sorted_rows[str(key)] = tuple(int(row_id) for row_id in row_ids)
    return sorted_rows


def _merge_archive_entry_index_rows(
    target: dict[str, object],
    rows: object,
    entry_count: int,
    *,
    row_offset: int = 0,
) -> None:
    decoded = _decode_archive_entry_index_row_ids(rows, entry_count, row_offset=row_offset)
    for key, row_ids in decoded.items():
        for row_id in _row_ids_as_tuple(row_ids):
            append_archive_row_id(target, key, row_id)


def _archive_basic_index_shard_cache_path(cache_dir: Path, relative_pamt_path: str) -> Path:
    return cache_dir / f"{_archive_scan_shard_id(relative_pamt_path)}.bin"


def _archive_index_row_mapping_to_rows(rows: Mapping[str, object]) -> List[Tuple[str, Tuple[int, ...]]]:
    encoded: List[Tuple[str, Tuple[int, ...]]] = []
    for key, values in rows.items():
        normalized_key = str(key or "")
        if not normalized_key:
            continue
        row_indexes = _row_ids_as_tuple(values)
        if row_indexes:
            encoded.append((normalized_key, row_indexes))
    encoded.sort(key=lambda row: row[0])
    return encoded


def _build_archive_basic_index_shard_row_payload(
    entries: Sequence[ArchiveEntry],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    progress_label: str = "Building path lookup shard",
) -> Dict[str, List[Tuple[str, Tuple[int, ...]]]]:
    path_rows: Dict[str, List[int]] = defaultdict(list)
    basename_rows: Dict[str, List[int]] = defaultdict(list)
    extension_rows: Dict[str, List[int]] = defaultdict(list)
    role_rows: Dict[str, List[int]] = defaultdict(list)
    texture_roles = {"image", "normal", "material", "impostor", "ui"}
    total_entries = len(entries)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
    for entry_index, archive_entry in enumerate(entries):
        if entry_index == 0 or entry_index % 4096 == 0:
            raise_if_cancelled(stop_event)
        normalized_path = str(getattr(archive_entry, "path", "") or "").replace("\\", "/").strip()
        normalized_path_lower = archive_path_key(getattr(archive_entry, "path", ""))
        if normalized_path_lower:
            path_rows[normalized_path_lower].append(entry_index)
        basename = archive_basename_key(normalized_path)
        if basename:
            basename_rows[basename].append(entry_index)
        extension = normalize_archive_extension_filter(archive_entry.extension)
        if extension:
            extension_rows[extension].append(entry_index)
        role = archive_entry_role(archive_entry)
        if role:
            role_rows[role].append(entry_index)
            if role in texture_roles:
                role_rows["texture"].append(entry_index)
        processed = entry_index + 1
        if on_progress is not None and (processed == 1 or processed % update_every == 0 or processed == total_entries):
            on_progress(processed, max(total_entries, 1), f"{progress_label}... {processed:,} / {total_entries:,} entries")
    for row_indexes in basename_rows.values():
        row_indexes.sort(
            key=lambda raw_index: (
                -str(entries[int(raw_index)].path or "").replace("\\", "/").strip().count("/"),
                -len(str(entries[int(raw_index)].path or "").replace("\\", "/").strip()),
                str(entries[int(raw_index)].path or "").replace("\\", "/").strip().lower(),
            )
        )
    return {
        "path_rows": _archive_index_row_mapping_to_rows(path_rows),
        "basename_rows": _archive_index_row_mapping_to_rows(basename_rows),
        "extension_rows": _archive_index_row_mapping_to_rows(extension_rows),
        "role_rows": _archive_index_row_mapping_to_rows(role_rows),
    }


def _write_archive_basic_index_shard_cache(
    cache_dir: Path,
    group: _ArchiveEntryShardGroup,
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    group_entries = group.entries
    row_payload = _build_archive_basic_index_shard_row_payload(
        group_entries,
        on_progress=on_progress,
        stop_event=stop_event,
        progress_label=f"Building path lookup shard {group.relative_pamt_path}",
    )
    cache_path = _archive_basic_index_shard_cache_path(cache_dir, group.relative_pamt_path)
    payload = {
        "version": _ARCHIVE_BASIC_INDEX_SHARD_CACHE_VERSION,
        "created_at": time.time(),
        "relative_pamt_path": group.relative_pamt_path,
        "entry_count": len(group_entries),
        "entry_list_signature": group.entry_list_signature,
        "path_rows": row_payload.get("path_rows") or [],
        "basename_rows": row_payload.get("basename_rows") or [],
        "extension_rows": row_payload.get("extension_rows") or [],
        "role_rows": row_payload.get("role_rows") or [],
    }
    _write_raw_pickle_cache_payload_to_path(
        cache_path,
        magic=_ARCHIVE_BASIC_INDEX_SHARD_CACHE_MAGIC,
        payload=payload,
    )
    return cache_path


def _load_archive_basic_index_shard_cache(cache_path: Path, group: _ArchiveEntryShardGroup) -> dict:
    data = _deserialize_archive_basic_index_shard_cache_payload_from_path(cache_path)
    if int(data.get("version", 0)) != _ARCHIVE_BASIC_INDEX_SHARD_CACHE_VERSION:
        raise ValueError("format changed")
    if str(data.get("relative_pamt_path") or "").replace("\\", "/") != group.relative_pamt_path.replace("\\", "/"):
        raise ValueError("shard path changed")
    if int(data.get("entry_count", -1)) != len(group.entries):
        raise ValueError("entry count changed")
    if str(data.get("entry_list_signature") or "") != group.entry_list_signature:
        raise ValueError("entry list changed")
    return data


def load_or_update_archive_basic_index_shards(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    force_refresh: bool = False,
    shard_entry_signatures: Optional[Mapping[str, str]] = None,
    shard_entry_counts: Optional[Mapping[str, int]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, object]]:
    check_started_at = time.perf_counter()
    cache_dir = resolve_archive_basic_index_shard_cache_dir(package_root, cache_root)
    if on_log is not None:
        on_log("Preparing archive path lookup shard metadata...")
    groups = _archive_entry_shard_groups(
        package_root,
        entries,
        precomputed_entry_list_signatures=shard_entry_signatures,
        precomputed_entry_counts=shard_entry_counts,
        on_progress=on_progress,
        stop_event=stop_event,
        progress_label="Preparing path lookup shard metadata",
    )
    if timings is not None:
        timings["basic_index_cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
    path_rows_by_key: dict[str, object] = {}
    basename_rows_by_key: dict[str, object] = {}
    extension_rows_by_key: dict[str, object] = {}
    role_rows_by_key: dict[str, object] = {}
    loaded_count = 0
    rebuilt_count = 0
    load_started_at = time.perf_counter()
    total_groups = len(groups)
    if on_progress is not None:
        on_progress(0, max(total_groups, 1), f"Loading path lookup shards... 0 / {total_groups:,}")
    for index, group in enumerate(groups, start=1):
        raise_if_cancelled(stop_event)
        cache_path = _archive_basic_index_shard_cache_path(cache_dir, group.relative_pamt_path)
        try:
            if force_refresh:
                raise ValueError("refresh")
            if not cache_path.is_file():
                raise ValueError("added")
            data = _load_archive_basic_index_shard_cache(cache_path, group)
            loaded_count += 1
        except Exception as exc:
            reason = str(exc).strip() or "changed"
            if on_log is not None:
                on_log(f"Archive path lookup shard stale: {group.relative_pamt_path} {reason}")
            write_started_at = time.perf_counter()
            data = {}
            try:
                _write_archive_basic_index_shard_cache(
                    cache_dir,
                    group,
                    on_progress=on_progress,
                    stop_event=stop_event,
                )
                data = _load_archive_basic_index_shard_cache(cache_path, group)
                rebuilt_count += 1
            finally:
                if timings is not None:
                    timings["basic_index_cache_write_s"] = (
                        float(timings.get("basic_index_cache_write_s", 0.0) or 0.0)
                        + max(0.0, float(time.perf_counter() - write_started_at))
                    )
        _merge_archive_entry_index_rows(path_rows_by_key, data.get("path_rows"), len(entries), row_offset=group.start_index)
        _merge_archive_entry_index_rows(basename_rows_by_key, data.get("basename_rows"), len(entries), row_offset=group.start_index)
        _merge_archive_entry_index_rows(extension_rows_by_key, data.get("extension_rows"), len(entries), row_offset=group.start_index)
        _merge_archive_entry_index_rows(role_rows_by_key, data.get("role_rows"), len(entries), row_offset=group.start_index)
        if on_progress is not None and (index == 1 or index % 20 == 0 or index == total_groups):
            on_progress(index, max(total_groups, 1), f"Loading path lookup shards... {index:,} / {total_groups:,}")
    path_index = ArchiveRowIndex(entries, compact_archive_rows_mapping(path_rows_by_key), name="path")
    basename_index = ArchiveRowIndex(entries, _sort_archive_basename_row_ids(basename_rows_by_key, entries), name="basename")
    extension_index = ArchiveRowIndex(entries, compact_archive_rows_mapping(extension_rows_by_key), name="extension")
    role_index = ArchiveRowIndex(entries, compact_archive_rows_mapping(role_rows_by_key), name="role")
    _record_timing(timings, "basic_index_cache_load_s", load_started_at)
    if on_log is not None:
        if rebuilt_count:
            on_log(
                "Archive path lookup shard cache updated: "
                f"{rebuilt_count:,} rebuilt, {loaded_count:,} reused."
            )
        else:
            on_log("Loaded archive path lookup shards from cache.")
    if rebuilt_count:
        prune_report = prune_archive_cache_root(
            cache_root,
            protected_paths=archive_cache_protected_paths(package_root, cache_root),
        )
        if on_log is not None and prune_report.get("removed_files"):
            on_log(
                "Archive cache pruned: "
                f"{prune_report.get('removed_files', 0)} files, {format_byte_size(int(prune_report.get('removed_bytes', 0) or 0))}."
            )
    return {
        "path_index": path_index,
        "basename_index": basename_index,
        "extension_index": extension_index,
        "role_index": role_index,
        "cache_path": str(cache_dir),
        "cache_loaded": rebuilt_count == 0,
        "loaded_shards": loaded_count,
        "rebuilt_shards": rebuilt_count,
    }


def save_archive_basic_index_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    extension_index: Mapping[str, Sequence[ArchiveEntry]],
    role_index: Mapping[str, Sequence[ArchiveEntry]],
    entry_metadata_signature: Optional[str] = None,
    entry_metadata_sources: Optional[Sequence[Tuple[str, int, int]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Path:
    started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = resolve_archive_basic_index_cache_path(package_root, cache_root)
    normalized_entry_metadata_signature = _normalize_archive_entry_metadata_signature(entry_metadata_signature)
    sources = (
        _normalize_archive_source_rows(list(entry_metadata_sources))
        if entry_metadata_sources is not None
        else None
    )
    if sources is None or not normalized_entry_metadata_signature:
        normalized_entry_metadata_signature, sources = _archive_entry_metadata_from_entries(package_root, entries)
    payload = {
        "version": _ARCHIVE_BASIC_INDEX_CACHE_VERSION,
        "created_at": time.time(),
        "sources": sources,
        "entry_count": len(entries),
        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
        "entry_metadata_signature": normalized_entry_metadata_signature,
        "path_rows": _encode_archive_entry_index_rows(path_index, entries),
        "basename_rows": _encode_archive_entry_index_rows(basename_index, entries),
        "extension_rows": _encode_archive_entry_index_rows(extension_index, entries),
        "role_rows": _encode_archive_entry_index_rows(role_index, entries),
    }
    _write_raw_pickle_cache_payload_to_path(
        cache_path,
        magic=_ARCHIVE_BASIC_INDEX_CACHE_MAGIC,
        payload=payload,
    )
    if on_log is not None:
        on_log(f"Archive path lookup cache updated: {cache_path}")
    prune_report = prune_archive_cache_root(
        cache_root,
        protected_paths=archive_cache_protected_paths(package_root, cache_root),
    )
    if on_log is not None and prune_report.get("removed_files"):
        on_log(
            "Archive cache pruned: "
            f"{prune_report.get('removed_files', 0)} files, {format_byte_size(int(prune_report.get('removed_bytes', 0) or 0))}."
        )
    _record_timing(timings, "basic_index_cache_write_s", started_at)
    return cache_path


def load_archive_basic_index_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    entry_metadata_signature: Optional[str] = None,
    current_sources: Optional[Sequence[Tuple[str, int, int]]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, object]]:
    check_started_at = time.perf_counter()
    cache_path = resolve_archive_basic_index_cache_path(package_root, cache_root)
    if not cache_path.exists():
        if timings is not None:
            timings.setdefault("basic_index_cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("basic_index_cache_load_s", 0.0)
        return None
    try:
        try:
            cache_size = int(cache_path.stat().st_size)
        except OSError:
            cache_size = 0
        if cache_size > _ARCHIVE_BASIC_INDEX_CACHE_MAX_SAFE_BYTES:
            try:
                cache_path.unlink()
            except OSError:
                pass
            if on_log is not None:
                on_log("Archive path lookup cache format changed; rebuilding in background.")
            if timings is not None:
                timings["basic_index_cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
                timings.setdefault("basic_index_cache_load_s", 0.0)
            return None
        normalized_entry_metadata_signature = _normalize_archive_entry_metadata_signature(entry_metadata_signature)
        normalized_current_sources = (
            _normalize_archive_source_rows(list(current_sources))
            if current_sources is not None
            else None
        )
        if timings is not None:
            timings["basic_index_cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
        load_started_at = time.perf_counter()
        data = _deserialize_archive_basic_index_cache_payload_from_path(cache_path)
        if int(data.get("version", 0)) != _ARCHIVE_BASIC_INDEX_CACHE_VERSION:
            if on_log is not None:
                on_log("Archive path lookup cache format changed; rebuilding in background.")
            try:
                cache_path.unlink()
            except OSError:
                pass
            return None
        cached_entry_count = int(data.get("entry_count", -1))
        if cached_entry_count != len(entries):
            if on_log is not None:
                on_log(
                    "Archive path lookup cache is out of date: "
                    f"entry count changed {cached_entry_count:,}->{len(entries):,}"
                )
            return None
        cached_entry_metadata_signature = _normalize_archive_entry_metadata_signature(
            data.get("entry_metadata_signature")
        )
        if normalized_entry_metadata_signature:
            if not cached_entry_metadata_signature:
                if on_log is not None:
                    on_log("Archive path lookup cache is missing compact entry metadata; rebuilding in background.")
                return None
            if cached_entry_metadata_signature != normalized_entry_metadata_signature:
                if on_log is not None:
                    on_log("Archive path lookup cache is out of date: compact entry metadata changed.")
                return None
        else:
            cached_sources = _normalize_archive_source_rows(data.get("sources"))
            if normalized_current_sources is None:
                _base_dir, normalized_current_sources = _collect_archive_scan_sources_from_entries(package_root, entries)
            if cached_sources != normalized_current_sources:
                if on_log is not None:
                    reasons = _describe_archive_cache_metadata_mismatch(
                        cached_sources,
                        normalized_current_sources,
                        cached_entry_count,
                        len(entries),
                    )
                    on_log("Archive path lookup cache is out of date: " + "; ".join(reasons or ["metadata changed"]))
                return None
        if on_progress is not None:
            on_progress(0, 4, "Loading path lookup cache... 0 / 4 parts")
        path_index = ArchiveRowIndex(
            entries,
            _decode_archive_entry_index_row_ids(data.get("path_rows"), len(entries)),
            name="path",
        )
        if on_progress is not None:
            on_progress(1, 4, "Loading path lookup cache... 1 / 4 parts")
        basename_index = ArchiveRowIndex(
            entries,
            _sort_archive_basename_row_ids(
                _decode_archive_entry_index_row_ids(data.get("basename_rows"), len(entries)),
                entries,
            ),
            name="basename",
        )
        if on_progress is not None:
            on_progress(2, 4, "Loading path lookup cache... 2 / 4 parts")
        extension_index = ArchiveRowIndex(
            entries,
            _decode_archive_entry_index_row_ids(data.get("extension_rows"), len(entries)),
            name="extension",
        )
        if on_progress is not None:
            on_progress(3, 4, "Loading path lookup cache... 3 / 4 parts")
        role_index = ArchiveRowIndex(
            entries,
            _decode_archive_entry_index_row_ids(data.get("role_rows"), len(entries)),
            name="role",
        )
        if on_progress is not None:
            on_progress(4, 4, "Loading path lookup cache... 4 / 4 parts")
        payload = {
            "path_index": path_index,
            "basename_index": basename_index,
            "extension_index": extension_index,
            "role_index": role_index,
            "cache_path": str(cache_path),
        }
        _record_timing(timings, "basic_index_cache_load_s", load_started_at)
        if on_log is not None:
            on_log("Loaded archive path lookup cache.")
        return payload
    except Exception as exc:
        if on_log is not None:
            on_log(f"Archive path lookup cache could not be used; rebuilding in background: {exc}")
        if timings is not None:
            timings.setdefault("basic_index_cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("basic_index_cache_load_s", 0.0)
        return None


def save_archive_derived_index_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    item_asset_catalog: Optional[Sequence[Mapping[str, object]]] = None,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    extension_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_name_search_index: Optional[ArchiveNameSearchIndex] = None,
    entry_metadata_signature: Optional[str] = None,
    entry_metadata_sources: Optional[Sequence[Tuple[str, int, int]]] = None,
    item_index_dependency_signature: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Path:
    started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = resolve_archive_derived_index_cache_path(package_root, cache_root)
    normalized_entry_metadata_signature = _normalize_archive_entry_metadata_signature(entry_metadata_signature)
    sources = (
        _normalize_archive_source_rows(list(entry_metadata_sources))
        if entry_metadata_sources is not None
        else None
    )
    if sources is None or not normalized_entry_metadata_signature:
        normalized_entry_metadata_signature, sources = _archive_entry_metadata_from_entries(package_root, entries)
    normalized_dependency_signature = _normalize_archive_entry_metadata_signature(item_index_dependency_signature)
    if not normalized_dependency_signature and not normalized_entry_metadata_signature:
        normalized_dependency_signature = archive_item_index_dependency_signature(package_root, entries)
    catalog_rows = [dict(row) for row in (item_asset_catalog or []) if isinstance(row, Mapping)]
    payload = {
        "version": _ARCHIVE_DERIVED_INDEX_CACHE_VERSION,
        "created_at": time.time(),
        "sources": sources,
        "entry_count": len(entries),
        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
        "entry_metadata_signature": normalized_entry_metadata_signature,
        "item_index_dependency_signature": normalized_dependency_signature,
        "item_search_aliases": dict(item_search_aliases or {}),
        "item_display_names": dict(item_display_names or {}),
        "item_exact_display_names": dict(item_exact_display_names or {}),
        "item_related_display_names": dict(item_related_display_names or {}),
        "item_asset_catalog": catalog_rows,
        "table_catalog": table_catalog_cache_metadata(row_counts={"item_asset_catalog": len(catalog_rows)}),
    }
    if archive_name_search_index is not None:
        try:
            name_shard_dir = _write_archive_name_search_shard_caches(
                package_root,
                cache_root,
                entries,
                archive_name_search_index,
                item_search_aliases,
            )
            payload["name_search_index"] = {
                "format": "CDNSHARDS1",
                "version": 1,
                "entry_count": len(entries),
                "token_count": len(archive_name_search_index.token_rows),
                "alias_signature": _archive_name_search_alias_signature(item_search_aliases),
                "path": str(name_shard_dir),
            }
        except Exception as exc:
            if on_log is not None:
                on_log(f"Archive search cache shard files could not be written: {exc}")
            name_index_path = resolve_archive_name_search_index_cache_path(package_root, cache_root)
            try:
                _write_native_name_search_index_binary(name_index_path, archive_name_search_index, len(entries))
                payload["name_search_index"] = {
                    "format": "CDNIDX1",
                    "version": 1,
                    "entry_count": len(entries),
                    "token_count": len(archive_name_search_index.token_rows),
                    "path": str(name_index_path),
                }
            except Exception as fallback_exc:
                if on_log is not None:
                    on_log(f"Archive name-search index cache could not be written: {fallback_exc}")
    _write_raw_pickle_cache_payload_to_path(
        cache_path,
        magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
        payload=payload,
    )
    if on_log is not None:
        on_log(f"Archive search cache updated: {cache_path}")
    prune_report = prune_archive_cache_root(
        cache_root,
        protected_paths=archive_cache_protected_paths(package_root, cache_root),
    )
    if on_log is not None and prune_report.get("removed_files"):
        on_log(
            "Archive cache pruned: "
            f"{prune_report.get('removed_files', 0)} files, {format_byte_size(int(prune_report.get('removed_bytes', 0) or 0))}."
        )
    _record_timing(timings, "derived_cache_write_s", started_at)
    return cache_path


def load_archive_derived_index_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    entry_metadata_signature: Optional[str] = None,
    current_sources: Optional[Sequence[Tuple[str, int, int]]] = None,
    load_name_search_index: bool = True,
    shard_entry_signatures: Optional[Mapping[str, str]] = None,
    shard_entry_counts: Optional[Mapping[str, int]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, object]]:
    check_started_at = time.perf_counter()
    cache_path = resolve_archive_derived_index_cache_path(package_root, cache_root)
    if not cache_path.exists():
        if timings is not None:
            timings.setdefault("derived_cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("derived_cache_load_s", 0.0)
        return None
    try:
        try:
            cache_size = int(cache_path.stat().st_size)
        except OSError:
            cache_size = 0
        if cache_size > _ARCHIVE_DERIVED_INDEX_CACHE_MAX_SAFE_BYTES:
            try:
                cache_path.unlink()
            except OSError:
                pass
            if on_log is not None:
                on_log("Archive search cache format changed; rebuilding it now.")
            if timings is not None:
                timings["derived_cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
                timings.setdefault("derived_cache_load_s", 0.0)
            return None
        normalized_entry_metadata_signature = _normalize_archive_entry_metadata_signature(entry_metadata_signature)
        normalized_current_sources = (
            _normalize_archive_source_rows(list(current_sources))
            if current_sources is not None
            else None
        )
        if timings is not None:
            timings["derived_cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
        load_started_at = time.perf_counter()
        data = _deserialize_archive_derived_index_cache_payload_from_path(cache_path)
        if int(data.get("version", 0)) not in _ARCHIVE_DERIVED_INDEX_CACHE_SUPPORTED_VERSIONS:
            if on_log is not None:
                on_log("Archive search cache format changed; rebuilding it now.")
            try:
                cache_path.unlink()
            except OSError:
                pass
            return None
        if not table_catalog_cache_metadata_matches(data.get("table_catalog")):
            if on_log is not None:
                on_log("Archive search cache metadata changed; rebuilding it now.")
            try:
                cache_path.unlink()
            except OSError:
                pass
            return None
        cached_entry_count = int(data.get("entry_count", -1))
        cached_entry_metadata_signature = _normalize_archive_entry_metadata_signature(
            data.get("entry_metadata_signature")
        )
        cached_dependency_signature = _normalize_archive_entry_metadata_signature(
            data.get("item_index_dependency_signature")
        )
        metadata_verified = False
        if normalized_entry_metadata_signature and cached_entry_metadata_signature:
            if cached_entry_metadata_signature != normalized_entry_metadata_signature:
                if on_log is not None:
                    on_log("Archive search cache is out of date: archive metadata changed.")
                return None
            metadata_verified = True
        if cached_dependency_signature and not metadata_verified:
            current_dependency_signature = archive_item_index_dependency_signature(package_root, entries)
            if current_dependency_signature != cached_dependency_signature:
                if on_log is not None:
                    on_log("Archive search cache is out of date: item index dependency metadata changed.")
                return None
        elif not metadata_verified:
            if cached_entry_count != len(entries):
                if on_log is not None:
                    on_log(
                        "Archive search cache is out of date: "
                        f"entry count changed {cached_entry_count:,}->{len(entries):,}"
                    )
                return None
            if normalized_entry_metadata_signature:
                if not cached_entry_metadata_signature:
                    if on_log is not None:
                        on_log("Archive search cache is missing compact metadata; rebuilding it now.")
                    return None
                if cached_entry_metadata_signature != normalized_entry_metadata_signature:
                    if on_log is not None:
                        on_log("Archive search cache is out of date: archive metadata changed.")
                    return None
            else:
                cached_sources = _normalize_archive_source_rows(data.get("sources"))
                if normalized_current_sources is None:
                    _base_dir, normalized_current_sources = _collect_archive_scan_sources_from_entries(package_root, entries)
                if cached_sources != normalized_current_sources:
                    if on_log is not None:
                        reasons = _describe_archive_cache_metadata_mismatch(
                            cached_sources,
                            normalized_current_sources,
                            cached_entry_count,
                            len(entries),
                        )
                        on_log("Archive search cache is out of date: " + "; ".join(reasons or ["metadata changed"]))
                    return None
        payload = {
            "item_search_aliases": {
                str(key): str(value)
                for key, value in (data.get("item_search_aliases", {}) or {}).items()
            },
            "item_display_names": {
                str(key): str(value)
                for key, value in (data.get("item_display_names", {}) or {}).items()
            },
            "item_exact_display_names": {
                str(key): str(value)
                for key, value in (data.get("item_exact_display_names", {}) or {}).items()
            },
            "item_related_display_names": {
                str(key): str(value)
                for key, value in (data.get("item_related_display_names", {}) or {}).items()
            },
            "item_asset_catalog": [
                dict(row)
                for row in (data.get("item_asset_catalog", []) or [])
                if isinstance(row, Mapping)
            ],
            "table_catalog": dict(data.get("table_catalog", {}) or {}),
            "cache_path": str(cache_path),
        }
        name_index_payload = data.get("name_search_index")
        if isinstance(name_index_payload, Mapping):
            name_index_format = str(name_index_payload.get("format") or "")
            if name_index_format == "CDNSHARDS1":
                aliases_for_shards = {
                    str(key): str(value)
                    for key, value in (data.get("item_search_aliases", {}) or {}).items()
                }
                if not load_name_search_index:
                    shard_cache_dir = resolve_archive_name_search_shard_cache_dir(package_root, cache_root)
                    if shard_cache_dir.is_dir():
                        payload["name_search_index_deferred"] = True
                        payload["name_search_index_path"] = str(shard_cache_dir)
                else:
                    try:
                        if metadata_verified:
                            try:
                                name_search_index = _load_archive_name_search_shards_trusted(
                                    package_root,
                                    cache_root,
                                    entries,
                                    on_progress=on_progress,
                                )
                            except Exception as exc:
                                if on_log is not None:
                                    on_log(f"Archive search cache shard files need repair: {exc}")
                                name_search_index = _load_or_update_archive_name_search_shards(
                                    package_root,
                                    cache_root,
                                    entries,
                                    aliases_for_shards,
                                    load_name_search_index=True,
                                    shard_entry_signatures=shard_entry_signatures,
                                    shard_entry_counts=shard_entry_counts,
                                    on_progress=on_progress,
                                    on_log=on_log,
                                )
                        else:
                            name_search_index = _load_or_update_archive_name_search_shards(
                                package_root,
                                cache_root,
                                entries,
                                aliases_for_shards,
                                load_name_search_index=True,
                                shard_entry_signatures=shard_entry_signatures,
                                shard_entry_counts=shard_entry_counts,
                                on_progress=on_progress,
                                on_log=on_log,
                            )
                        if isinstance(name_search_index, ArchiveNameSearchIndex):
                            payload["name_search_index"] = name_search_index
                    except Exception as exc:
                        if on_log is not None:
                            on_log(f"Archive search cache shard files could not be used; rebuilding: {exc}")
            else:
                name_index_path = Path(str(name_index_payload.get("path") or ""))
                if not name_index_path.is_absolute():
                    name_index_path = resolve_archive_name_search_index_cache_path(package_root, cache_root)
                name_index_cache_ready = (
                    name_index_format == "CDNIDX1"
                    and int(name_index_payload.get("entry_count") or -1) == len(entries)
                    and name_index_path.is_file()
                )
                if name_index_cache_ready and not load_name_search_index:
                    payload["name_search_index_deferred"] = True
                    payload["name_search_index_path"] = str(name_index_path)
                elif name_index_cache_ready:
                    try:
                        payload["name_search_index"] = _load_native_name_search_index_binary(
                            name_index_path,
                            entries,
                            on_progress=on_progress,
                        )
                    except Exception as exc:
                        if on_log is not None:
                            on_log(f"Archive name-search index cache could not be used; rebuilding name search index: {exc}")
        _record_timing(timings, "derived_cache_load_s", load_started_at)
        if on_log is not None:
            on_log("Loaded archive derived indexes from cache.")
        return payload
    except Exception as exc:
        if on_log is not None:
            on_log(f"Archive search cache could not be used; rebuilding: {exc}")
        if timings is not None:
            timings.setdefault("derived_cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("derived_cache_load_s", 0.0)
        return None
