from __future__ import annotations

import html
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.archive_format import _is_material_sidecar_extension, try_decode_text_like_archive_data
from cdmw.core.archive_name_search import LazyArchiveEntryRowIndex
from cdmw.core.archive_scan_cache import (
    _ARCHIVE_SIDECAR_CACHE_MAGIC,
    _ARCHIVE_SIDECAR_CACHE_VERSION,
    _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT,
    _build_archive_entry_cache_signatures,
    _collect_archive_scan_sources_from_entries,
    _describe_archive_cache_metadata_mismatch,
    _deserialize_cache_payload_from_path,
    _normalize_archive_source_rows,
    _read_archive_sidecar_cache_metadata,
    _record_timing,
    _write_archive_sidecar_cache_metadata,
    _write_raw_pickle_cache_payload_to_path,
    archive_cache_protected_paths,
    prune_archive_cache_root,
    resolve_archive_sidecar_cache_metadata_path,
    resolve_archive_sidecar_cache_path,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup
from cdmw.models import ArchiveEntry, RunCancelled


def format_byte_size(value: int) -> str:
    from cdmw.core import archive as archive_core

    return archive_core.format_byte_size(value)


def _read_archive_entry_data_from_handle(*args, **kwargs):
    from cdmw.core import archive as archive_core

    return archive_core._read_archive_entry_data_from_handle(*args, **kwargs)


_ARCHIVE_SIDECAR_CACHE_SUPPORTED_VERSIONS = {8, 9, 10}
_ARCHIVE_SCAN_IGNORED_TOP_LEVEL_DIRS: frozenset[str] = frozenset({"cdmods"})
_ARCHIVE_SIDECAR_TEXTURE_ATTR_RE = re.compile(
    r"""\b(?:_path|path|Path|Value|_value|value|File|file|_file|Texture|texture)\s*=\s*(['"])(?P<value>[^'"<>]{1,1024}?\.(?:dds|png|jpg|jpeg|tga|bmp|tif|tiff))\1""",
    re.IGNORECASE,
)
_ARCHIVE_TEXTURE_BYTES_RE = re.compile(br"\.(?:dds|png|jpg|jpeg|tga|bmp|tif|tiff)", re.IGNORECASE)


def _archive_material_sidecar_entry_indices(entries: Sequence[ArchiveEntry]) -> List[int]:
    indices: List[int] = []
    for entry_index, entry in enumerate(entries):
        entry_basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        if _is_material_sidecar_extension(entry.extension, entry_basename):
            indices.append(entry_index)
    return indices



def _build_archive_sidecar_entry_cache_signatures(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
) -> Tuple[Tuple[int, Tuple[object, ...]], ...]:
    sidecar_indices = _archive_material_sidecar_entry_indices(entries)
    sidecar_entries = [entries[index] for index in sidecar_indices]
    sidecar_signatures = _build_archive_entry_cache_signatures(package_root, sidecar_entries)
    return tuple(
        (int(entry_index), tuple(signature))
        for entry_index, signature in zip(sidecar_indices, sidecar_signatures)
    )


def _normalize_archive_sidecar_entry_signature_rows(raw_rows: object) -> Optional[Tuple[Tuple[int, Tuple[object, ...]], ...]]:
    if not isinstance(raw_rows, (list, tuple)):
        return None
    rows: List[Tuple[int, Tuple[object, ...]]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, (list, tuple)) or len(raw_row) != 2:
            return None
        raw_index, raw_signature = raw_row
        if not isinstance(raw_signature, (list, tuple)):
            return None
        try:
            entry_index = int(raw_index)
        except (TypeError, ValueError):
            return None
        if entry_index < 0:
            return None
        rows.append((entry_index, tuple(raw_signature)))
    return tuple(rows)


def _extract_archive_sidecar_texture_lookup_paths(sidecar_text: str) -> Tuple[str, ...]:
    if not sidecar_text:
        return ()

    texture_paths: List[str] = []
    seen_paths: set[str] = set()

    for match in _ARCHIVE_SIDECAR_TEXTURE_ATTR_RE.finditer(sidecar_text):
        texture_path = html.unescape(str(match.group("value") or "")).replace("\\", "/").strip()
        normalized_texture = normalize_texture_reference_for_sidecar_lookup(texture_path)
        if not normalized_texture or normalized_texture in seen_paths:
            continue
        seen_paths.add(normalized_texture)
        texture_paths.append(normalized_texture)
    return tuple(texture_paths)


def _build_archive_texture_sidecar_path_rows_for_group(
    group_entries: Sequence[Tuple[int, ArchiveEntry]],
    *,
    stop_event: Optional[threading.Event] = None,
    on_entry_processed: Optional[Callable[[int], None]] = None,
) -> Dict[str, List[int]]:
    path_rows_lists: Dict[str, List[int]] = defaultdict(list)
    if not group_entries:
        return path_rows_lists

    paz_path = group_entries[0][1].paz_file
    try:
        with paz_path.open("rb") as handle:
            for entry_index, entry in group_entries:
                raise_if_cancelled(stop_event)
                try:
                    raw_data, _decompressed, _note = _read_archive_entry_data_from_handle(
                        handle,
                        entry,
                        stop_event=stop_event,
                    )
                except RunCancelled:
                    raise
                except Exception:
                    if on_entry_processed is not None:
                        on_entry_processed(1)
                    continue
                if not raw_data or _ARCHIVE_TEXTURE_BYTES_RE.search(raw_data) is None:
                    if on_entry_processed is not None:
                        on_entry_processed(1)
                    continue
                text = try_decode_text_like_archive_data(raw_data)
                if not text:
                    if on_entry_processed is not None:
                        on_entry_processed(1)
                    continue
                for normalized_texture in _extract_archive_sidecar_texture_lookup_paths(text):
                    path_rows_lists[normalized_texture].append(entry_index)
                if on_entry_processed is not None:
                    on_entry_processed(1)
    except RunCancelled:
        raise
    except Exception:
        return {}
    return path_rows_lists


def build_archive_texture_sidecar_path_rows(
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Indexing archive texture sidecars...",
    timings: Optional[Dict[str, float]] = None,
) -> Dict[str, Tuple[int, ...]]:
    grouped_sidecar_entries: Dict[str, List[Tuple[int, ArchiveEntry]]] = defaultdict(list)
    total_sidecars = 0
    for entry_index, entry in enumerate(entries):
        entry_basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        if not _is_material_sidecar_extension(entry.extension, entry_basename):
            continue
        paz_key = str(entry.paz_file).strip().lower()
        grouped_sidecar_entries[paz_key].append((entry_index, entry))
        total_sidecars += 1
    if total_sidecars <= 0:
        return {}

    path_rows_lists: Dict[str, List[int]] = defaultdict(list)
    progress_interval = max(total_sidecars // 100, 1) if total_sidecars > 0 else 1
    processed_count = 0
    progress_lock = threading.Lock()
    sorted_groups = [
        (paz_key, sorted(grouped_sidecar_entries[paz_key], key=lambda item: item[1].offset))
        for paz_key in sorted(grouped_sidecar_entries)
    ]
    try:
        configured_workers = int(
            worker_count
            if worker_count is not None
            else os.environ.get("CDMW_ARCHIVE_SIDECAR_WORKERS")
            or os.environ.get("CFT_ARCHIVE_SIDECAR_WORKERS", "0")
        )
    except ValueError:
        configured_workers = 0
    if configured_workers <= 0:
        configured_workers = min(12, max(4, (os.cpu_count() or 2) - 1), max(1, len(sorted_groups)))
    worker_count = min(max(configured_workers, 1), 16, max(1, len(sorted_groups)))
    if timings is not None:
        timings["sidecar_count"] = float(total_sidecars)
        timings["sidecar_group_count"] = float(len(sorted_groups))
        timings["sidecar_worker_count"] = float(worker_count)

    def merge_group_rows(group_rows: Dict[str, List[int]]) -> None:
        for normalized_texture, entry_indexes in group_rows.items():
            if entry_indexes:
                path_rows_lists[normalized_texture].extend(entry_indexes)

    def publish_progress(force: bool = False) -> None:
        if on_progress is None:
            return
        if force or processed_count == total_sidecars or processed_count % progress_interval == 0:
            on_progress(
                processed_count,
                total_sidecars,
                f"{progress_label} {processed_count:,} / {total_sidecars:,}",
            )

    def mark_entries_processed(count: int = 1) -> None:
        nonlocal processed_count
        if count <= 0:
            return
        with progress_lock:
            processed_count = min(total_sidecars, processed_count + int(count))
            publish_progress(force=False)

    if worker_count <= 1 or total_sidecars < 2_000:
        for _paz_key, group_entries in sorted_groups:
            raise_if_cancelled(stop_event)
            group_rows = _build_archive_texture_sidecar_path_rows_for_group(
                group_entries,
                stop_event=stop_event,
                on_entry_processed=mark_entries_processed,
            )
            merge_group_rows(group_rows)
            publish_progress(force=True)
    else:
        group_results: Dict[str, Dict[str, List[int]]] = {}
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ArchiveSidecarIndex") as executor:
            future_by_key = {
                executor.submit(
                    _build_archive_texture_sidecar_path_rows_for_group,
                    group_entries,
                    stop_event=stop_event,
                    on_entry_processed=mark_entries_processed,
                ): (paz_key, len(group_entries))
                for paz_key, group_entries in sorted_groups
            }
            for future in as_completed(future_by_key):
                paz_key, group_count = future_by_key[future]
                raise_if_cancelled(stop_event)
                try:
                    group_results[paz_key] = future.result()
                except RunCancelled:
                    raise
                except Exception:
                    group_results[paz_key] = {}
                    mark_entries_processed(group_count)
                publish_progress(force=True)
        for paz_key, _group_entries in sorted_groups:
            merge_group_rows(group_results.get(paz_key, {}))

    return {key: tuple(value) for key, value in path_rows_lists.items() if value}


def _build_archive_texture_sidecar_path_rows_for_indices(
    entries: Sequence[ArchiveEntry],
    entry_indices: Sequence[int],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Indexing changed archive texture sidecars...",
) -> Dict[str, Tuple[int, ...]]:
    grouped_sidecar_entries: Dict[str, List[Tuple[int, ArchiveEntry]]] = defaultdict(list)
    for raw_index in entry_indices:
        entry_index = int(raw_index)
        if entry_index < 0 or entry_index >= len(entries):
            continue
        entry = entries[entry_index]
        entry_basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        if not _is_material_sidecar_extension(entry.extension, entry_basename):
            continue
        paz_key = str(entry.paz_file).strip().lower()
        grouped_sidecar_entries[paz_key].append((entry_index, entry))
    total_sidecars = sum(len(group_entries) for group_entries in grouped_sidecar_entries.values())
    if total_sidecars <= 0:
        return {}

    path_rows_lists: Dict[str, List[int]] = defaultdict(list)
    processed_count = 0
    progress_lock = threading.Lock()
    if on_progress is not None:
        on_progress(0, total_sidecars, f"{progress_label} 0 / {total_sidecars:,}")
    configured_workers = int(worker_count or 0)
    if configured_workers <= 0:
        configured_workers = min(12, max(4, (os.cpu_count() or 2) - 1), max(1, len(grouped_sidecar_entries)))
    configured_workers = min(max(configured_workers, 1), 16, max(1, len(grouped_sidecar_entries)))
    sorted_groups = [
        (paz_key, sorted(grouped_sidecar_entries[paz_key], key=lambda item: item[1].offset))
        for paz_key in sorted(grouped_sidecar_entries)
    ]

    def mark_entries_processed(count: int = 1) -> None:
        nonlocal processed_count
        if count <= 0:
            return
        with progress_lock:
            processed_count = min(total_sidecars, processed_count + int(count))
            if on_progress is not None:
                on_progress(
                    processed_count,
                    total_sidecars,
                    f"{progress_label} {processed_count:,} / {total_sidecars:,}",
                )

    if configured_workers <= 1 or total_sidecars < 2_000:
        for paz_key, group_entries in sorted_groups:
            del paz_key
            raise_if_cancelled(stop_event)
            group_rows = _build_archive_texture_sidecar_path_rows_for_group(
                group_entries,
                stop_event=stop_event,
                on_entry_processed=mark_entries_processed,
            )
            for normalized_texture, row_indices in group_rows.items():
                if row_indices:
                    path_rows_lists[normalized_texture].extend(row_indices)
            if on_progress is not None:
                on_progress(
                    processed_count,
                    total_sidecars,
                    f"{progress_label} {processed_count:,} / {total_sidecars:,}",
                )
    else:
        with ThreadPoolExecutor(max_workers=configured_workers, thread_name_prefix="ArchiveSidecarIndex") as executor:
            future_by_count = {
                executor.submit(
                    _build_archive_texture_sidecar_path_rows_for_group,
                    group_entries,
                    stop_event=stop_event,
                    on_entry_processed=mark_entries_processed,
                ): len(group_entries)
                for _paz_key, group_entries in sorted_groups
            }
            for future in as_completed(future_by_count):
                group_count = future_by_count[future]
                raise_if_cancelled(stop_event)
                try:
                    group_rows = future.result()
                except RunCancelled:
                    raise
                except Exception:
                    group_rows = {}
                    mark_entries_processed(group_count)
                for normalized_texture, row_indices in group_rows.items():
                    if row_indices:
                        path_rows_lists[normalized_texture].extend(row_indices)
                if on_progress is not None:
                    on_progress(
                        processed_count,
                        total_sidecars,
                        f"{progress_label} {processed_count:,} / {total_sidecars:,}",
                    )
    return {key: tuple(value) for key, value in path_rows_lists.items() if value}


def _incremental_archive_texture_sidecar_path_rows(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
    cached_path_rows: Dict[str, Tuple[int, ...]],
    cached_entry_signatures: object,
    *,
    cached_sidecar_entry_signatures: bool = False,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, Tuple[int, ...]]]:
    if cached_sidecar_entry_signatures:
        old_signature_rows = _normalize_archive_sidecar_entry_signature_rows(cached_entry_signatures)
        if old_signature_rows is None:
            return None
        current_sidecar_indices = _archive_material_sidecar_entry_indices(entries)
        current_sidecar_entries = [entries[index] for index in current_sidecar_indices]
        current_signatures = _build_archive_entry_cache_signatures(package_root, current_sidecar_entries)
        current_signature_rows = tuple(
            (int(entry_index), tuple(signature))
            for entry_index, signature in zip(current_sidecar_indices, current_signatures)
        )
    else:
        if not isinstance(cached_entry_signatures, (list, tuple)):
            return None
        try:
            old_signature_rows = tuple(
                (old_index, tuple(signature))
                for old_index, signature in enumerate(cached_entry_signatures)
            )
        except Exception:
            return None
        current_signatures = _build_archive_entry_cache_signatures(package_root, entries)
        current_signature_rows = tuple(
            (current_index, tuple(signature))
            for current_index, signature in enumerate(current_signatures)
        )

    current_by_signature: Dict[Tuple[object, ...], int] = {}
    duplicate_current_signatures: set[Tuple[object, ...]] = set()
    for current_index, signature in current_signature_rows:
        if signature in current_by_signature:
            duplicate_current_signatures.add(signature)
            continue
        current_by_signature[signature] = current_index
    for signature in duplicate_current_signatures:
        current_by_signature.pop(signature, None)

    old_to_current: Dict[int, int] = {}
    reused_current_indices: set[int] = set()
    for old_index, signature in old_signature_rows:
        current_index = current_by_signature.get(signature)
        if current_index is None:
            continue
        old_to_current[int(old_index)] = current_index
        reused_current_indices.add(current_index)

    changed_sidecar_indices = [
        index
        for index in _archive_material_sidecar_entry_indices(entries)
        if index not in reused_current_indices
    ]
    if old_to_current and not changed_sidecar_indices and len(current_signature_rows) == len(old_signature_rows):
        if on_log is not None:
            on_log("Texture sidecar cache metadata changed, but all sidecar rows remapped without rescanning.")
    elif on_log is not None:
        on_log(
            "Texture sidecar cache is partially out of date; "
            f"reusing {len(reused_current_indices):,} unchanged entries, rescanning {len(changed_sidecar_indices):,} sidecar entries."
        )

    merge_started_at = time.perf_counter()
    remapped_rows_lists: Dict[str, List[int]] = defaultdict(list)
    for normalized_texture, old_indices in cached_path_rows.items():
        for old_index in old_indices:
            current_index = old_to_current.get(int(old_index))
            if current_index is not None:
                remapped_rows_lists[normalized_texture].append(current_index)
    _record_timing(timings, "incremental_remap_s", merge_started_at)

    scan_started_at = time.perf_counter()
    if changed_sidecar_indices:
        changed_rows = _build_archive_texture_sidecar_path_rows_for_indices(
            entries,
            changed_sidecar_indices,
            worker_count=worker_count,
            stop_event=stop_event,
            on_progress=on_progress,
        )
    else:
        changed_rows = {}
    _record_timing(timings, "incremental_scan_s", scan_started_at)
    for normalized_texture, current_indices in changed_rows.items():
        remapped_rows_lists[normalized_texture].extend(int(index) for index in current_indices)

    return {
        key: tuple(dict.fromkeys(value))
        for key, value in remapped_rows_lists.items()
        if value
    }


def _build_archive_sidecar_basename_rows_from_path_rows(
    path_rows: Dict[str, Tuple[int, ...]],
) -> Dict[str, Tuple[int, ...]]:
    basename_rows_lists: Dict[str, List[int]] = defaultdict(list)
    for normalized_texture, raw_indexes in path_rows.items():
        texture_basename = PurePosixPath(str(normalized_texture or "").strip().lower()).name
        if not texture_basename or not raw_indexes:
            continue
        basename_rows_lists[texture_basename].extend(int(index) for index in raw_indexes)
    return {key: tuple(value) for key, value in basename_rows_lists.items() if value}


def build_archive_texture_sidecar_basename_rows(
    path_rows: Dict[str, Tuple[int, ...]],
) -> Dict[str, Tuple[int, ...]]:
    return _build_archive_sidecar_basename_rows_from_path_rows(path_rows)


def resolve_archive_texture_sidecar_entry_rows(
    rows: object,
    entries: Sequence[ArchiveEntry],
) -> Dict[str, List[ArchiveEntry]]:
    return _deserialize_archive_sidecar_entry_rows(rows, entries)


def build_lazy_archive_texture_sidecar_entry_index(
    rows: Optional[Dict[str, Tuple[int, ...]]],
    entries: Sequence[ArchiveEntry],
) -> LazyArchiveEntryRowIndex:
    return LazyArchiveEntryRowIndex(rows, entries)


def build_archive_texture_sidecar_entry_index(
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Indexing archive texture sidecars...",
) -> Tuple[Dict[str, List[ArchiveEntry]], Dict[str, List[ArchiveEntry]]]:
    path_rows = build_archive_texture_sidecar_path_rows(
        entries,
        worker_count=worker_count,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label=progress_label,
    )
    if not path_rows:
        return {}, {}
    basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(path_rows)
    return (
        _deserialize_archive_sidecar_entry_rows(path_rows, entries),
        _deserialize_archive_sidecar_entry_rows(basename_rows, entries),
    )


def _serialize_archive_sidecar_entry_rows(
    index: Dict[str, List[ArchiveEntry]],
    *,
    entry_positions_by_identity: Dict[int, int],
) -> Dict[str, Tuple[int, ...]]:
    rows: Dict[str, Tuple[int, ...]] = {}
    for key, entries_for_key in index.items():
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        entry_indexes: List[int] = []
        seen_indexes: set[int] = set()
        for entry in entries_for_key:
            entry_index = entry_positions_by_identity.get(id(entry))
            if entry_index is None or entry_index in seen_indexes:
                continue
            seen_indexes.add(entry_index)
            entry_indexes.append(entry_index)
        if entry_indexes:
            rows[normalized_key] = tuple(entry_indexes)
    return rows


def _deserialize_archive_sidecar_entry_rows(
    rows: object,
    entries: Sequence[ArchiveEntry],
) -> Dict[str, List[ArchiveEntry]]:
    if not isinstance(rows, dict):
        raise ValueError("Texture sidecar cache rows are invalid.")
    resolved_entries = list(entries)
    entry_count = len(resolved_entries)
    index: Dict[str, List[ArchiveEntry]] = {}
    for key, raw_indexes in rows.items():
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        if not isinstance(raw_indexes, (list, tuple)):
            raise ValueError("Texture sidecar cache entry references are invalid.")
        resolved_for_key: List[ArchiveEntry] = []
        seen_indexes: set[int] = set()
        for raw_index in raw_indexes:
            entry_index = int(raw_index)
            if entry_index < 0 or entry_index >= entry_count:
                raise ValueError("Texture sidecar cache entry index is out of range.")
            if entry_index in seen_indexes:
                continue
            seen_indexes.add(entry_index)
            resolved_for_key.append(resolved_entries[entry_index])
        if resolved_for_key:
            index[normalized_key] = resolved_for_key
    return index


def save_archive_texture_sidecar_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    entries_by_texture_path: Optional[Dict[str, List[ArchiveEntry]]] = None,
    entries_by_texture_basename: Optional[Dict[str, List[ArchiveEntry]]] = None,
    path_rows: Optional[Dict[str, Tuple[int, ...]]] = None,
    basename_rows: Optional[Dict[str, Tuple[int, ...]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Path:
    started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = resolve_archive_sidecar_cache_path(package_root, cache_root)
    metadata_path = resolve_archive_sidecar_cache_metadata_path(package_root, cache_root)
    _base_dir, sources = _collect_archive_scan_sources_from_entries(package_root, entries)
    if on_progress is not None:
        on_progress(0, 0, "Writing texture sidecar cache...")
    raise_if_cancelled(stop_event)
    entry_positions_by_identity: Optional[Dict[int, int]] = None
    if path_rows is None:
        if entries_by_texture_path is None:
            raise ValueError("entries_by_texture_path is required when path_rows is not provided.")
        entry_positions_by_identity = {id(entry): index for index, entry in enumerate(entries)}
        path_rows = _serialize_archive_sidecar_entry_rows(
            entries_by_texture_path,
            entry_positions_by_identity=entry_positions_by_identity,
        )
    if basename_rows is None:
        if entries_by_texture_basename is not None:
            if entry_positions_by_identity is None:
                entry_positions_by_identity = {id(entry): index for index, entry in enumerate(entries)}
            basename_rows = _serialize_archive_sidecar_entry_rows(
                entries_by_texture_basename,
                entry_positions_by_identity=entry_positions_by_identity,
            )
        else:
            basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(path_rows)
    payload = {
        "version": _ARCHIVE_SIDECAR_CACHE_VERSION,
        "created_at": time.time(),
        "sources": sources,
        "entry_count": len(entries),
        "entry_signature_format": _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT,
        "sidecar_entry_signatures": _build_archive_sidecar_entry_cache_signatures(package_root, entries),
        "path_rows": path_rows,
        "basename_rows": basename_rows,
    }
    _write_raw_pickle_cache_payload_to_path(
        cache_path,
        magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
        payload=payload,
    )
    try:
        _write_archive_sidecar_cache_metadata(
            metadata_path,
            version=_ARCHIVE_SIDECAR_CACHE_VERSION,
            sources=sources,
            entry_count=len(entries),
        )
    except Exception as exc:
        if on_log is not None:
            on_log(f"Warning: texture sidecar cache metadata could not be written: {exc}")
    if on_progress is not None:
        on_progress(1, 1, "Texture sidecar cache is ready.")
    if on_log is not None:
        on_log(f"Texture sidecar cache updated: {cache_path}")
    prune_report = prune_archive_cache_root(
        cache_root,
        protected_paths=archive_cache_protected_paths(package_root, cache_root),
    )
    if on_log is not None and prune_report.get("removed_files"):
        on_log(
            "Archive cache pruned: "
            f"{prune_report.get('removed_files', 0)} files, {format_byte_size(int(prune_report.get('removed_bytes', 0) or 0))}."
        )
    _record_timing(timings, "cache_write_s", started_at)
    return cache_path


def load_archive_texture_sidecar_cache_rows(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Tuple[Dict[str, Tuple[int, ...]], Dict[str, Tuple[int, ...]]]]:
    check_started_at = time.perf_counter()
    cache_path = resolve_archive_sidecar_cache_path(package_root, cache_root)
    metadata_path = resolve_archive_sidecar_cache_metadata_path(package_root, cache_root)
    if not cache_path.exists():
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None
    if on_progress is not None:
        on_progress(0, 0, "Checking texture sidecar cache...")
    try:
        _base_dir, current_sources = _collect_archive_scan_sources_from_entries(package_root, entries)
    except Exception as exc:
        if on_log is not None:
            on_log(f"Texture sidecar cache check failed; rebuilding it now: {exc}")
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None

    metadata_payload: Optional[dict] = None
    metadata_mismatch_reasons: List[str] = []
    if metadata_path.exists():
        try:
            metadata_payload = _read_archive_sidecar_cache_metadata(metadata_path)
        except Exception as exc:
            if on_log is not None:
                on_log(f"Texture sidecar cache metadata could not be read; falling back to the full cache payload: {exc}")

    if metadata_payload is not None:
        cached_version = int(metadata_payload.get("version", 0))
        if cached_version not in _ARCHIVE_SIDECAR_CACHE_SUPPORTED_VERSIONS:
            if on_log is not None:
                on_log("Texture sidecar cache metadata format changed; rebuilding it now.")
            return None
        cached_sources = _normalize_archive_source_rows(metadata_payload.get("sources"))
        cached_entry_count = int(metadata_payload.get("entry_count", -1))
        if cached_sources != current_sources or cached_entry_count != len(entries):
            metadata_mismatch_reasons = _describe_archive_cache_metadata_mismatch(
                cached_sources,
                current_sources,
                cached_entry_count,
                len(entries),
            )
            if on_log is not None:
                on_log(
                    "Texture sidecar cache metadata changed: "
                    + "; ".join(metadata_mismatch_reasons or ["metadata changed"])
                    + ". Checking cache payload for reuse."
                )

    if on_progress is not None:
        on_progress(0, 0, "Loading texture sidecar cache...")
    try:
        if timings is not None:
            timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
        load_started_at = time.perf_counter()
        data = _deserialize_cache_payload_from_path(
            cache_path,
            magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
            invalid_message="Texture sidecar cache header is not recognized.",
        )
    except Exception as exc:
        if on_log is not None:
            on_log(f"Texture sidecar cache could not be read; rebuilding it now: {exc}")
        return None

    if int(data.get("version", 0)) not in _ARCHIVE_SIDECAR_CACHE_SUPPORTED_VERSIONS:
        if on_log is not None:
            on_log("Texture sidecar cache format changed; rebuilding it now.")
        return None

    try:
        raise_if_cancelled(stop_event)
        raw_path_rows = {
            str(key or "").strip().lower(): tuple(int(index) for index in value)
            for key, value in (data.get("path_rows", {}) or {}).items()
            if isinstance(value, (list, tuple)) and str(key or "").strip()
        }
        cached_sources = _normalize_archive_source_rows(data.get("sources"))
        cached_entry_count = int(data.get("entry_count", -1))
        payload_matches_current_archives = cached_sources == current_sources and cached_entry_count == len(entries)
        if timings is not None and "cache_load_s" not in timings:
            timings["cache_load_s"] = max(0.0, float(time.perf_counter() - load_started_at))
        if not payload_matches_current_archives:
            payload_mismatch_reasons = _describe_archive_cache_metadata_mismatch(
                cached_sources,
                current_sources,
                cached_entry_count,
                len(entries),
            )
            if on_log is not None:
                on_log(
                    "Texture sidecar cache payload is out of date: "
                    + "; ".join(payload_mismatch_reasons or ["archive metadata changed"])
                )
            cache_version = int(data.get("version", 0))
            signature_format = int(data.get("entry_signature_format", 0) or 0)
            reusable_signatures_available = False
            if signature_format == _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT:
                reusable_signatures_available = bool(
                    cache_version >= 10 and data.get("sidecar_entry_signatures") is not None
                    or cache_version >= 9 and data.get("entry_signatures") is not None
                )
            if reusable_signatures_available:
                incremental_started_at = time.perf_counter()
                updated_path_rows = None
                if cache_version >= 10 and data.get("sidecar_entry_signatures") is not None:
                    updated_path_rows = _incremental_archive_texture_sidecar_path_rows(
                        package_root,
                        entries,
                        raw_path_rows,
                        data.get("sidecar_entry_signatures"),
                        cached_sidecar_entry_signatures=True,
                        worker_count=worker_count,
                        stop_event=stop_event,
                        on_log=on_log,
                        on_progress=on_progress,
                        timings=timings,
                    )
                if updated_path_rows is None and cache_version >= 9 and data.get("entry_signatures") is not None:
                    updated_path_rows = _incremental_archive_texture_sidecar_path_rows(
                        package_root,
                        entries,
                        raw_path_rows,
                        data.get("entry_signatures"),
                        worker_count=worker_count,
                        stop_event=stop_event,
                        on_log=on_log,
                        on_progress=on_progress,
                        timings=timings,
                    )
                _record_timing(timings, "incremental_update_s", incremental_started_at)
                if updated_path_rows is not None:
                    updated_basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(updated_path_rows)
                    try:
                        save_archive_texture_sidecar_cache(
                            package_root,
                            cache_root,
                            entries,
                            path_rows=updated_path_rows,
                            basename_rows=updated_basename_rows,
                            on_log=on_log,
                            on_progress=on_progress,
                            stop_event=stop_event,
                            timings=timings,
                        )
                    except Exception as exc:
                        if on_log is not None:
                            on_log(f"Warning: incrementally updated texture sidecar cache could not be written: {exc}")
                    if on_progress is not None:
                        on_progress(1, 1, "Texture sidecar cache loaded.")
                    return updated_path_rows, updated_basename_rows
                if on_log is not None:
                    on_log("Texture sidecar cache could not be updated incrementally; rebuilding it now.")
            elif on_log is not None:
                on_log("Texture sidecar cache is stale and does not contain v9 entry signatures; rebuilding it now.")
            return None

        raw_basename_rows = data.get("basename_rows")
        if isinstance(raw_basename_rows, dict):
            basename_rows = {
                str(key or "").strip().lower(): tuple(int(index) for index in value)
                for key, value in raw_basename_rows.items()
                if isinstance(value, (list, tuple)) and str(key or "").strip()
            }
        else:
            basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(raw_path_rows)
        _record_timing(timings, "cache_load_s", load_started_at)
    except Exception as exc:
        if on_log is not None:
            on_log(f"Texture sidecar cache could not be applied; rebuilding it now: {exc}")
        return None

    metadata_refreshed_by_cache_write = False
    if int(data.get("version", 0)) < _ARCHIVE_SIDECAR_CACHE_VERSION:
        try:
            save_archive_texture_sidecar_cache(
                package_root,
                cache_root,
                entries,
                path_rows=raw_path_rows,
                basename_rows=basename_rows,
                on_log=on_log,
                on_progress=None,
                stop_event=stop_event,
                timings=timings,
            )
            metadata_refreshed_by_cache_write = True
            if on_log is not None:
                on_log("Texture sidecar cache upgraded to the current metadata format without rescanning.")
        except Exception as exc:
            if on_log is not None:
                on_log(f"Warning: texture sidecar cache could not be upgraded after loading: {exc}")

    if not metadata_refreshed_by_cache_write and (metadata_payload is None or metadata_mismatch_reasons):
        try:
            _write_archive_sidecar_cache_metadata(
                metadata_path,
                version=int(data.get("version", _ARCHIVE_SIDECAR_CACHE_VERSION)),
                sources=current_sources,
                entry_count=len(entries),
            )
            if metadata_mismatch_reasons and on_log is not None:
                on_log("Texture sidecar cache metadata was stale, but payload matched current archives; metadata refreshed without rescanning.")
        except Exception:
            pass

    if on_progress is not None:
        on_progress(1, 1, "Texture sidecar cache loaded.")
    if on_log is not None:
        on_log("Loaded texture sidecar bindings from cache.")
    return raw_path_rows, basename_rows


def load_archive_texture_sidecar_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Tuple[Dict[str, List[ArchiveEntry]], Dict[str, List[ArchiveEntry]]]]:
    cached_rows = load_archive_texture_sidecar_cache_rows(
        package_root,
        cache_root,
        entries,
        worker_count=worker_count,
        on_log=on_log,
        on_progress=on_progress,
        stop_event=stop_event,
        timings=timings,
    )
    if cached_rows is None:
        return None
    path_rows, basename_rows = cached_rows
    return (
        _deserialize_archive_sidecar_entry_rows(path_rows, entries),
        _deserialize_archive_sidecar_entry_rows(basename_rows, entries),
    )


def build_archive_texture_sidecar_entry_index_cached(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[Dict[str, List[ArchiveEntry]], Dict[str, List[ArchiveEntry]], str, Optional[Path]]:
    cache_path = resolve_archive_sidecar_cache_path(package_root, cache_root)
    cached = load_archive_texture_sidecar_cache(
        package_root,
        cache_root,
        entries,
        worker_count=worker_count,
        on_log=on_log,
        on_progress=on_progress,
        stop_event=stop_event,
    )
    if cached is not None:
        entries_by_texture_path, entries_by_texture_basename = cached
        return entries_by_texture_path, entries_by_texture_basename, "cache", cache_path

    if on_log is not None:
        on_log("Indexing texture sidecar bindings for related-file discovery...")
    path_rows = build_archive_texture_sidecar_path_rows(
        entries,
        worker_count=worker_count,
        stop_event=stop_event,
        on_progress=on_progress,
    )
    basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(path_rows)
    entries_by_texture_path = _deserialize_archive_sidecar_entry_rows(path_rows, entries) if path_rows else {}
    entries_by_texture_basename = (
        _deserialize_archive_sidecar_entry_rows(basename_rows, entries) if basename_rows else {}
    )
    try:
        cache_path = save_archive_texture_sidecar_cache(
            package_root,
            cache_root,
            entries,
            path_rows=path_rows,
            basename_rows=basename_rows if int(_ARCHIVE_SIDECAR_CACHE_VERSION) <= 1 else None,
            entries_by_texture_path=entries_by_texture_path,
            entries_by_texture_basename=entries_by_texture_basename,
            on_log=on_log,
            on_progress=on_progress,
            stop_event=stop_event,
        )
    except Exception as exc:
        if on_log is not None:
            on_log(f"Warning: texture sidecar cache could not be written: {exc}")
        cache_path = None
    return entries_by_texture_path, entries_by_texture_basename, "scan", cache_path
