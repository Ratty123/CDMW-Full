"""Archive picker state and display rules for the Research tab."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping, MutableMapping, Optional, Sequence

from cdmw.models import ArchiveEntry

__all__ = [
    "ArchivePickerPathLookupMaps",
    "ArchivePickerReusableTreeIndex",
    "archive_picker_available_status_text",
    "archive_picker_entries_from_sources",
    "archive_picker_entry_for_path",
    "archive_picker_entry_index_for_path",
    "archive_picker_file_label",
    "archive_picker_flat_limit_status_text",
    "archive_picker_focus_flat_overflow_status_text",
    "archive_picker_focus_missing_status_text",
    "archive_picker_folder_parts",
    "archive_picker_folder_status_text",
    "archive_picker_path_lookup_maps",
    "archive_picker_render_status_text",
    "archive_picker_reusable_browser_tree_index",
    "archive_picker_selected_entry_status_text",
    "build_archive_snapshot_cache_key",
    "cached_archive_snapshot_cache_key",
    "normalize_archive_path",
]


@dataclass(frozen=True, slots=True)
class ArchivePickerPathLookupMaps:
    eager_path_maps: bool
    entry_index_by_path: dict[str, int]
    entry_by_path: dict[str, ArchiveEntry]


@dataclass(frozen=True, slots=True)
class ArchivePickerReusableTreeIndex:
    child_folders: dict[object, object]
    direct_files: dict[object, object]
    folder_entry_indexes: dict[object, object]
    folder_preview_stats: dict[object, object]


def normalize_archive_path(path_value: str) -> str:
    return str(path_value or "").strip().replace("\\", "/").strip("/")


def archive_picker_file_label(path_value: str, *, show_full_path: bool) -> str:
    normalized_path = str(path_value or "").replace("\\", "/")
    return normalized_path if show_full_path else PurePosixPath(normalized_path).name


def archive_picker_folder_parts(path_value: str) -> tuple[str, ...]:
    normalized = normalize_archive_path(path_value)
    return tuple(part for part in PurePosixPath(normalized).parts[:-1] if part)


def archive_picker_entries_from_sources(
    filtered_entries: Sequence[object],
    fallback_entries: Sequence[object],
) -> list[ArchiveEntry]:
    entries = filtered_entries or fallback_entries
    if isinstance(entries, list):
        return entries
    return [entry for entry in entries if isinstance(entry, ArchiveEntry)]


def archive_picker_path_lookup_maps(
    entries: Sequence[ArchiveEntry],
    *,
    eager_limit: int = 100_000,
) -> ArchivePickerPathLookupMaps:
    if len(entries) > eager_limit:
        return ArchivePickerPathLookupMaps(
            eager_path_maps=False,
            entry_index_by_path={},
            entry_by_path={},
        )
    return ArchivePickerPathLookupMaps(
        eager_path_maps=True,
        entry_index_by_path={
            normalize_archive_path(entry.path).casefold(): index
            for index, entry in enumerate(entries)
        },
        entry_by_path={
            normalize_archive_path(entry.path): entry
            for entry in entries
        },
    )


def archive_picker_reusable_browser_tree_index(
    browser_tree_state: object,
    entries: Sequence[ArchiveEntry],
) -> Optional[ArchivePickerReusableTreeIndex]:
    if not isinstance(browser_tree_state, dict):
        return None
    if browser_tree_state.get("entries") is not entries:
        return None
    if not browser_tree_state.get("tree_index_ready", False):
        return None
    child_folders = browser_tree_state.get("tree_child_folders")
    direct_files = browser_tree_state.get("tree_direct_files")
    folder_indexes = browser_tree_state.get("tree_folder_entry_indexes")
    folder_stats = browser_tree_state.get("tree_folder_preview_stats")
    if not (
        isinstance(child_folders, dict)
        and isinstance(direct_files, dict)
        and isinstance(folder_indexes, dict)
        and isinstance(folder_stats, dict)
    ):
        return None
    return ArchivePickerReusableTreeIndex(
        child_folders=child_folders,
        direct_files=direct_files,
        folder_entry_indexes=folder_indexes,
        folder_preview_stats=folder_stats,
    )


def archive_picker_entry_index_for_path(
    path_value: str,
    *,
    entries: Sequence[ArchiveEntry],
    entry_index_by_path: Mapping[str, int],
    lazy_entry_index_by_path: MutableMapping[str, int],
) -> Optional[int]:
    normalized = normalize_archive_path(path_value)
    if not normalized:
        return None
    normalized_key = normalized.casefold()
    entry_index = entry_index_by_path.get(normalized_key)
    if entry_index is not None:
        return entry_index
    entry_index = lazy_entry_index_by_path.get(normalized_key)
    if entry_index is not None:
        return entry_index
    for index, entry in enumerate(entries):
        if normalize_archive_path(entry.path).casefold() == normalized_key:
            lazy_entry_index_by_path[normalized_key] = index
            return index
    return None


def archive_picker_entry_for_path(
    path_value: str,
    *,
    entries: Sequence[ArchiveEntry],
    entry_by_path: Mapping[str, ArchiveEntry],
    entry_index_by_path: Mapping[str, int],
    lazy_entry_index_by_path: MutableMapping[str, int],
) -> Optional[ArchiveEntry]:
    normalized = normalize_archive_path(path_value)
    if not normalized:
        return None
    entry = entry_by_path.get(normalized)
    if entry is not None:
        return entry
    entry_index = archive_picker_entry_index_for_path(
        normalized,
        entries=entries,
        entry_index_by_path=entry_index_by_path,
        lazy_entry_index_by_path=lazy_entry_index_by_path,
    )
    if entry_index is None or not (0 <= entry_index < len(entries)):
        return None
    return entries[entry_index]


def build_archive_snapshot_cache_key(entries: Sequence[ArchiveEntry]) -> str:
    if not entries:
        return "0:empty"
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(normalize_archive_path(entry.path).casefold().encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(entry.package_label).casefold().encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(entry.extension).casefold().encode("utf-8", errors="replace"))
        digest.update(b"\n")
    return f"{len(entries)}:{digest.hexdigest()}"


def cached_archive_snapshot_cache_key(
    entries: Sequence[ArchiveEntry],
    cache: MutableMapping[tuple[int, int, str, str], str],
    *,
    max_cache_entries: int = 16,
) -> str:
    if not entries:
        return "0:empty"
    first_path = normalize_archive_path(entries[0].path)
    last_path = normalize_archive_path(entries[-1].path)
    cache_token = (id(entries), len(entries), first_path, last_path)
    cached_key = cache.get(cache_token)
    if cached_key:
        return cached_key
    cache_key = build_archive_snapshot_cache_key(entries)
    if len(cache) > max_cache_entries:
        cache.clear()
    cache[cache_token] = cache_key
    return cache_key


def archive_picker_flat_limit_status_text(*, entry_count: int, flat_render_limit: int) -> str:
    return (
        f"Flat view shows the first {flat_render_limit:,} of {entry_count:,} visible file(s). "
        "Narrow Archive Browser filters for the rest."
    )


def archive_picker_available_status_text(
    *,
    entry_count: int,
    eager_path_maps: bool,
    view_mode: str,
    flat_render_limit: int,
    skipped_large_index: bool,
) -> str:
    if entry_count <= 0:
        return "No archive files are available yet. Scan archives or broaden the current Archive Browser filter."
    status_text = f"{entry_count:,} archive file(s) available from the current Archive Browser view."
    if not eager_path_maps:
        status_text = f"{entry_count:,} archive file(s) available. Path lookups are lazy to keep RAM usage down."
    if view_mode == "flat" and entry_count > flat_render_limit:
        status_text = archive_picker_flat_limit_status_text(
            entry_count=entry_count,
            flat_render_limit=flat_render_limit,
        )
    elif skipped_large_index:
        status_text = (
            "Archive Files is waiting for the Archive Browser tree index. "
            "Open or refresh the Archive Browser view, or narrow the current filter."
        )
    return status_text


def archive_picker_render_status_text(*, rendered_count: int, total: int) -> str:
    return f"Rendering archive files... {rendered_count:,} / {total:,}"


def archive_picker_focus_missing_status_text(path_value: str) -> str:
    return f"Reference points to {path_value}, but that file is not visible in the current Archive Files list."


def archive_picker_focus_flat_overflow_status_text(path_value: str, *, rendered_count: int) -> str:
    return (
        f"{path_value} is visible in the current Archive Browser filter, but not in the first "
        f"{rendered_count:,} flat rows. Narrow the filter or switch to Folders."
    )


def archive_picker_selected_entry_status_text(entry: ArchiveEntry) -> str:
    return f"Selected: {entry.path} ({entry.package_label})"


def archive_picker_folder_status_text(folder_text: str, *, count: int) -> str:
    return f"Folder: {folder_text} ({count:,} file(s))"
