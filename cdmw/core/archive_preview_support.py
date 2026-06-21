from __future__ import annotations

import hashlib
import math
import struct
import threading
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.archive_extraction import _dds_bytes_per_block, _dds_surface_size, sanitize_cache_filename
from cdmw.core.archive_filtering import (
    archive_browser_sort_is_active,
    filter_archive_entries,
    sort_archive_entries_for_browser,
)
from cdmw.core.archive_format import calculate_pa_checksum
from cdmw.core.common import raise_if_cancelled
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.texture_pipeline.inspection import inspect_crimson_dds, parse_dds
from cdmw.core.upscale_profiles import classify_texture_type, infer_texture_semantics
from cdmw.models import ArchiveEntry, PathcCollisionEntry, PathcEntry, PathcLookupResult


def _StructuredBinaryPreviewBundle(*args, **kwargs):
    from cdmw.core import archive as archive_core

    return archive_core._StructuredBinaryPreviewBundle(*args, **kwargs)


_PATHC_COLLECTION_CACHE: Dict[str, Tuple[str, "PathcCollection"]] = {}

def build_archive_structure_children_map(entries: Sequence[ArchiveEntry]) -> Dict[str, List[Tuple[str, int]]]:
    child_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
    folder_counts: Dict[Tuple[str, ...], int] = defaultdict(int)
    package_dir_cache: Dict[Path, str] = {}
    folder_parts_cache: Dict[str, Tuple[str, ...]] = {"": ()}

    for entry in entries:
        package_dir = package_dir_cache.get(entry.pamt_path)
        if package_dir is None:
            package_dir = entry.pamt_path.parent.name.strip().lower() or "package"
            package_dir_cache[entry.pamt_path] = package_dir
        normalized_path = entry.path.replace("\\", "/").lower()
        folder_text, _, _basename = normalized_path.rpartition("/")
        raw_parts = folder_parts_cache.get(folder_text)
        if raw_parts is None:
            raw_parts = tuple(
                part
                for part in folder_text.split("/")
                if part not in {"", ".", ".."}
            )
            folder_parts_cache[folder_text] = raw_parts
        folder_counts[(package_dir, *raw_parts)] += 1

    for parts, count in folder_counts.items():
        parent = ""
        child_value = ""
        for part in parts:
            child_value = f"{child_value}/{part}" if child_value else part
            parent_counts = child_counts[parent]
            parent_counts[child_value] = parent_counts.get(child_value, 0) + count
            parent = child_value

    def leaf_sort_key(value: str) -> Tuple[int, int, str]:
        leaf = value.rsplit("/", 1)[-1]
        if leaf.isdigit():
            return (0, int(leaf), leaf)
        return (1, 0, leaf)

    return {
        parent: sorted(children.items(), key=lambda item: leaf_sort_key(item[0]))
        for parent, children in child_counts.items()
    }


def build_archive_tree_index(
    entries: Sequence[ArchiveEntry],
    *,
    preserve_direct_file_order: bool = False,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[
    Dict[Tuple[str, ...], List[Tuple[str, Tuple[str, ...]]]],
    Dict[Tuple[str, ...], List[int]],
    Dict[Tuple[str, ...], List[int]],
    Dict[Tuple[str, ...], Tuple[int, int, int]],
]:
    child_folder_sets: Dict[Tuple[str, ...], Dict[Tuple[str, ...], str]] = defaultdict(dict)
    direct_files: Dict[Tuple[str, ...], List[Tuple[str, int]]] = defaultdict(list)
    folder_entry_indexes: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    folder_preview_stats: Dict[Tuple[str, ...], List[int]] = defaultdict(lambda: [0, 0, 0])
    folder_key_cache: Dict[str, Tuple[str, ...]] = {"": ()}
    folder_hierarchy_cache: Dict[Tuple[str, ...], Tuple[Tuple[Tuple[str, ...], Tuple[str, ...], str], ...]] = {(): ()}
    total_entries = len(entries)
    progress_total = max(total_entries, 1)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000

    if on_progress:
        on_progress(0 if total_entries > 0 else 1, progress_total, f"Indexing archive browser tree... 0 / {total_entries:,} entries")

    for index, entry in enumerate(entries):
        current = index + 1
        if stop_event is not None and (current == 1 or current % 2048 == 0):
            raise_if_cancelled(stop_event)
        normalized_path = entry.path.replace("\\", "/")
        folder_text, _, basename = normalized_path.rpartition("/")
        if not basename:
            basename = normalized_path
        folder_key = folder_key_cache.get(folder_text)
        if folder_key is None:
            folder_key = tuple(
                part
                for part in folder_text.split("/")
                if part not in {"", ".", ".."}
            )
            folder_key_cache[folder_text] = folder_key
        if not folder_key and basename in {"", ".", ".."}:
            continue

        direct_files[folder_key].append((basename.lower(), index))
        folder_entry_indexes[()].append(index)
        root_stats = folder_preview_stats[()]
        root_stats[0] += 1
        root_stats[1] += int(entry.orig_size)
        root_stats[2] += int(entry.comp_size)
        hierarchy = folder_hierarchy_cache.get(folder_key)
        if hierarchy is None:
            parent_key: Tuple[str, ...] = ()
            built_hierarchy: List[Tuple[Tuple[str, ...], Tuple[str, ...], str]] = []
            child_key_parts: List[str] = []
            for part in folder_key:
                child_key_parts.append(part)
                child_key = tuple(child_key_parts)
                built_hierarchy.append((parent_key, child_key, part))
                parent_key = child_key
            hierarchy = tuple(built_hierarchy)
            folder_hierarchy_cache[folder_key] = hierarchy
        for parent_key, child_key, part in hierarchy:
            child_folder_sets[parent_key][child_key] = part
            folder_entry_indexes[child_key].append(index)
            folder_stats = folder_preview_stats[child_key]
            folder_stats[0] += 1
            folder_stats[1] += int(entry.orig_size)
            folder_stats[2] += int(entry.comp_size)

        if on_progress and (current == 1 or current % update_every == 0 or current == total_entries):
            on_progress(current, progress_total, f"Indexing archive browser tree... {current:,} / {total_entries:,} entries")

    def folder_sort_key(item: Tuple[Tuple[str, ...], str]) -> Tuple[int, int, str]:
        _child_key, leaf = item
        if leaf.isdigit():
            return (0, int(leaf), leaf)
        return (1, 0, leaf)

    child_folders = {
        parent: sorted(
            ((leaf, child_key) for child_key, leaf in children.items()),
            key=lambda item: folder_sort_key((item[1], item[0])),
        )
        for parent, children in child_folder_sets.items()
    }
    if preserve_direct_file_order:
        direct_files_by_folder = dict(direct_files)
    else:
        direct_files_by_folder = {
            folder_key: sorted(
                indexes,
                key=lambda item: item[0],
            )
            for folder_key, indexes in direct_files.items()
        }
    direct_file_indexes = {
        folder_key: [index for _basename, index in sorted_items]
        for folder_key, sorted_items in direct_files_by_folder.items()
    }
    normalized_folder_preview_stats = {
        folder_key: (int(stats[0]), int(stats[1]), int(stats[2]))
        for folder_key, stats in folder_preview_stats.items()
    }
    return child_folders, direct_file_indexes, dict(folder_entry_indexes), normalized_folder_preview_stats


def prepare_archive_browser_state(
    entries: Sequence[ArchiveEntry],
    *,
    filter_text: str,
    exclude_filter_text: str,
    extension_filter: str,
    package_filter_text: str,
    structure_filter: str,
    role_filter: str,
    exclude_common_technical_suffixes: bool,
    min_size_kb: int,
    previewable_only: bool,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_name_search_index: Optional[ArchiveNameSearchIndex] = None,
    build_structure_children: bool = True,
    build_tree_index: bool = True,
    sort_column: object = -1,
    sort_order: object = "asc",
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict:
    sort_is_active = archive_browser_sort_is_active(sort_column)
    total_steps = (
        1
        + (1 if build_structure_children else 0)
        + (1 if sort_is_active else 0)
        + (1 if build_tree_index else 0)
    )
    current_step = 0
    structure_children: Dict[str, List[Tuple[str, int]]] = {}
    if build_structure_children:
        raise_if_cancelled(stop_event)
        current_step += 1
        if on_progress:
            on_progress(current_step, total_steps, "Building folder filters from archive entries...")
        structure_children = build_archive_structure_children_map(entries)

    raise_if_cancelled(stop_event)
    current_step += 1
    if on_progress:
        on_progress(current_step, total_steps, "Applying archive filters...")
    filtered_entries = filter_archive_entries(
        entries,
        filter_text=filter_text,
        exclude_filter_text=exclude_filter_text,
        extension_filter=extension_filter,
        package_filter_text=package_filter_text,
        structure_filter=structure_filter,
        role_filter=role_filter,
        exclude_common_technical_suffixes=exclude_common_technical_suffixes,
        min_size_kb=min_size_kb,
        previewable_only=previewable_only,
        item_search_aliases=item_search_aliases,
        archive_entries_by_basename=archive_entries_by_basename,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_name_search_index=archive_name_search_index,
        on_progress=on_progress,
        stop_event=stop_event,
    )
    if sort_is_active:
        raise_if_cancelled(stop_event)
        current_step += 1
        if on_progress:
            on_progress(current_step, total_steps, "Sorting archive browser rows...")
        filtered_entries = sort_archive_entries_for_browser(
            filtered_entries,
            sort_column,
            sort_order,
            item_display_names=item_display_names,
            item_exact_display_names=item_exact_display_names,
            item_related_display_names=item_related_display_names,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        )

    tree_child_folders: Dict[Tuple[str, ...], List[Tuple[str, Tuple[str, ...]]]] = {}
    tree_direct_files: Dict[Tuple[str, ...], List[int]] = {}
    folder_entry_indexes: Dict[Tuple[str, ...], List[int]] = {}
    folder_preview_stats: Dict[Tuple[str, ...], Tuple[int, int, int]] = {}
    if build_tree_index:
        raise_if_cancelled(stop_event)
        current_step += 1
        if on_progress:
            on_progress(current_step, total_steps, "Indexing archive browser tree...")
        tree_child_folders, tree_direct_files, folder_entry_indexes, folder_preview_stats = build_archive_tree_index(
            filtered_entries,
            preserve_direct_file_order=sort_is_active,
            on_progress=on_progress,
            stop_event=stop_event,
        )
    dds_count = sum(1 for entry in filtered_entries if entry.extension == ".dds")

    return {
        "structure_children": structure_children,
        "filtered_entries": filtered_entries,
        "tree_child_folders": tree_child_folders,
        "tree_direct_files": tree_direct_files,
        "tree_folder_entry_indexes": folder_entry_indexes,
        "tree_folder_preview_stats": folder_preview_stats,
        "tree_index_ready": build_tree_index,
        "dds_count": dds_count,
    }


class PathcCollection:
    def __init__(self, path: Path, raw_data: Optional[bytes] = None) -> None:
        raw = path.read_bytes() if raw_data is None else bytes(raw_data)
        if len(raw) < 32:
            raise ValueError(f"{path} is too small to be a valid .pathc file.")
        self.path = path
        self.raw_size = len(raw)
        (
            _reserved0,
            header_size,
            header_count,
            entry_count,
            collision_entry_count,
            filenames_length,
        ) = struct.unpack_from("<QIIIII", raw, 0)
        self.reserved0 = _reserved0
        offset = struct.calcsize("<QIIIII")
        self.header_size = header_size
        self.header_count = header_count
        self.entry_count = entry_count
        self.collision_entry_count = collision_entry_count
        self.filenames_length = filenames_length
        self.headers: List[bytes] = []
        for _ in range(header_count):
            header = raw[offset : offset + header_size]
            if len(header) != header_size:
                raise ValueError(f"{path.name} texture header block is truncated.")
            self.headers.append(header)
            offset += header_size
        checksums: List[int] = []
        for _ in range(entry_count):
            if offset + 4 > len(raw):
                raise ValueError(f"{path.name} checksum table is truncated.")
            checksums.append(struct.unpack_from("<I", raw, offset)[0])
            offset += 4
        self.checksums = tuple(checksums)
        entries: List[PathcEntry] = []
        for entry_index in range(entry_count):
            if offset + 20 > len(raw):
                raise ValueError(f"{path.name} entry table is truncated.")
            texture_header_index, collision_start_index, collision_end_index, compressed_block_infos = struct.unpack_from(
                "<HBB16s",
                raw,
                offset,
            )
            checksum = checksums[entry_index] if entry_index < len(checksums) else 0
            entries.append(
                PathcEntry(
                    texture_header_index=texture_header_index,
                    collision_start_index=collision_start_index,
                    collision_end_index=collision_end_index,
                    compressed_block_infos=compressed_block_infos,
                    checksum=checksum,
                )
            )
            offset += 20
        self.entries = {checksum: entry for checksum, entry in zip(checksums, entries)}
        self.entry_rows = tuple(entries)
        collision_entries: List[PathcCollisionEntry] = []
        for _ in range(collision_entry_count):
            if offset + 24 > len(raw):
                raise ValueError(f"{path.name} collision table is truncated.")
            filename_offset, texture_header_index, unknown0, compressed_block_infos = struct.unpack_from(
                "<IHH16s",
                raw,
                offset,
            )
            collision_entries.append(
                PathcCollisionEntry(
                    filename_offset=filename_offset,
                    texture_header_index=texture_header_index,
                    unknown0=unknown0,
                    compressed_block_infos=compressed_block_infos,
                )
            )
            offset += 24
        filenames = raw[offset : offset + filenames_length]
        if len(filenames) != filenames_length:
            raise ValueError(f"{path.name} filename table is truncated.")
        self.filename_blob = filenames
        self.hash_collision_entries: Dict[str, PathcCollisionEntry] = {}
        for entry in collision_entries:
            end = filenames.find(b"\x00", entry.filename_offset)
            if end < 0:
                end = len(filenames)
            name = filenames[entry.filename_offset:end].decode("utf-8", errors="replace")
            entry.path = name
            self.hash_collision_entries[name] = entry
        self.collision_entries = tuple(collision_entries)
        self.direct_mapping_count = 0
        self.collision_mapping_count = 0
        self.invalid_mapping_count = 0
        self.unknown_mapping_count = 0
        for entry in self.entry_rows:
            if entry.texture_header_index != 0xFFFF:
                if 0 <= int(entry.texture_header_index) < len(self.headers):
                    self.direct_mapping_count += 1
                else:
                    self.invalid_mapping_count += 1
                continue
            if int(entry.collision_start_index) < int(entry.collision_end_index):
                self.collision_mapping_count += 1
            else:
                self.unknown_mapping_count += 1

    def get_file_header(self, path: str) -> bytes:
        lookup = self.lookup_file(path)
        if lookup.mapping_mode not in {"direct", "collision"} or lookup.texture_header_index < 0:
            raise KeyError(lookup.normalized_path)
        header = self.headers[lookup.texture_header_index]
        compressed_block_infos = lookup.compressed_block_infos
        if self.header_size == 0x94:
            return header[:0x20] + compressed_block_infos + header[0x30:]
        return header

    def lookup_file(self, path: str) -> PathcLookupResult:
        normalized = str(path or "").replace("\\", "/").lstrip("/")
        checksum = calculate_pa_checksum(f"/{normalized}")
        entry = self.entries.get(checksum)
        if entry is None:
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="missing",
                message="No PATHC hash entry matched this path.",
            )
        if entry.texture_header_index != 0xFFFF:
            header_index = int(entry.texture_header_index)
            if 0 <= header_index < len(self.headers):
                return PathcLookupResult(
                    normalized_path=normalized,
                    checksum=checksum,
                    mapping_mode="direct",
                    texture_header_index=header_index,
                    header_size=self.header_size,
                    compressed_block_infos=entry.compressed_block_infos,
                )
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="invalid",
                texture_header_index=header_index,
                header_size=self.header_size,
                compressed_block_infos=entry.compressed_block_infos,
                message="Direct PATHC header index is outside the header table.",
            )

        collision_entry = self.hash_collision_entries.get(normalized)
        if collision_entry is None:
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="missing",
                texture_header_index=-1,
                header_size=self.header_size,
                compressed_block_infos=entry.compressed_block_infos,
                message="PATHC hash entry uses collision mapping, but no collision path matched this file.",
            )
        header_index = int(collision_entry.texture_header_index)
        if not (0 <= header_index < len(self.headers)):
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="invalid",
                texture_header_index=header_index,
                header_size=self.header_size,
                compressed_block_infos=collision_entry.compressed_block_infos,
                collision_path=collision_entry.path,
                message="Collision PATHC header index is outside the header table.",
            )
        return PathcLookupResult(
            normalized_path=normalized,
            checksum=checksum,
            mapping_mode="collision",
            texture_header_index=header_index,
            header_size=self.header_size,
            compressed_block_infos=collision_entry.compressed_block_infos,
            collision_path=collision_entry.path,
        )

    def iter_collision_samples(self, limit: int = 16) -> Tuple[PathcCollisionEntry, ...]:
        return tuple(self.collision_entries[: max(0, int(limit))])


def load_pathc_collection(path: Path) -> PathcCollection:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
    cache_key = str(resolved).lower()
    cached = _PATHC_COLLECTION_CACHE.get(cache_key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    collection = PathcCollection(resolved)
    _PATHC_COLLECTION_CACHE[cache_key] = (stamp, collection)
    return collection


def resolve_archive_meta_root(entry: ArchiveEntry) -> Path:
    return entry.pamt_path.parent.parent / "meta"


def resolve_archive_pathc_path(entry: ArchiveEntry) -> Path:
    return resolve_archive_meta_root(entry) / "0.pathc"


def get_archive_partial_dds_header(entry: ArchiveEntry) -> bytes:
    pathc_path = resolve_archive_pathc_path(entry)
    if not pathc_path.is_file():
        raise ValueError(f"Partial DDS metadata was not found: {pathc_path}")
    collection = load_pathc_collection(pathc_path)
    candidates = [
        entry.path.replace("\\", "/").lstrip("/"),
        PurePosixPath(entry.path.replace("\\", "/")).as_posix().lstrip("/"),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return collection.get_file_header(candidate)
        except KeyError:
            continue
    raise ValueError(f"Partial DDS header not found in {pathc_path} for {entry.path}")


def _format_pathc_block_infos(block_infos: bytes) -> str:
    if len(block_infos) < 16:
        return block_infos.hex(" ").upper() if block_infos else "none"
    values = struct.unpack_from("<4I", block_infos, 0)
    return ", ".join(f"mip{i}={value:,}" for i, value in enumerate(values))


def _format_pathc_lookup_detail(lookup: PathcLookupResult) -> str:
    lines = [
        "PATHC Lookup:",
        f"- Path: {lookup.normalized_path or '-'}",
        f"- Hash/checksum: 0x{lookup.checksum:08X}",
        f"- Mapping: {lookup.mapping_mode}",
    ]
    if lookup.texture_header_index >= 0:
        lines.append(f"- Texture header index: {lookup.texture_header_index:,}")
    if lookup.header_size:
        lines.append(f"- Header record size: {lookup.header_size:,} bytes")
    if lookup.compressed_block_infos:
        lines.append(f"- First-four-mip / block metadata: {_format_pathc_block_infos(lookup.compressed_block_infos)}")
    if lookup.collision_path:
        lines.append(f"- Collision path: {lookup.collision_path}")
    if lookup.message:
        lines.append(f"- Note: {lookup.message}")
    return "\n".join(lines)


def build_archive_pathc_preview(data: bytes, virtual_path: str) -> _StructuredBinaryPreviewBundle:
    collection = PathcCollection(Path(PurePosixPath(virtual_path.replace("\\", "/")).name or "0.pathc"), raw_data=data)
    lines = [
        f"PATHC texture path index preview for {virtual_path}",
        "",
        "Summary:",
        f"- Header record size: {collection.header_size:,} bytes",
        f"- DDS template/header records: {collection.header_count:,}",
        f"- Path hash entries: {collection.entry_count:,}",
        f"- Collision path entries: {collection.collision_entry_count:,}",
        f"- Filename table size: {collection.filenames_length:,} bytes",
        f"- Direct mappings: {collection.direct_mapping_count:,}",
        f"- Collision mappings: {collection.collision_mapping_count:,}",
        f"- Unknown mappings: {collection.unknown_mapping_count:,}",
        f"- Invalid mappings: {collection.invalid_mapping_count:,}",
    ]
    collision_samples = collection.iter_collision_samples(limit=16)
    if collision_samples:
        lines.extend(["", "Collision path samples:"])
        for index, collision_entry in enumerate(collision_samples, start=1):
            block_info_text = _format_pathc_block_infos(collision_entry.compressed_block_infos)
            lines.append(
                f"- [{index:02d}] header={collision_entry.texture_header_index} "
                f"offset={collision_entry.filename_offset} path={collision_entry.path or '<empty>'} "
                f"blocks=({block_info_text})"
            )
        if len(collection.collision_entries) > len(collision_samples):
            lines.append(f"... {len(collection.collision_entries) - len(collision_samples):,} more collision path(s)")
    else:
        lines.extend(["", "Collision path samples:", "- None"])

    detail_lines = (
        f"PATHC contains {collection.header_count:,} DDS template/header record(s).",
        f"PATHC contains {collection.entry_count:,} path hash entry/entries.",
        f"Mapping types: direct={collection.direct_mapping_count:,}, collision={collection.collision_mapping_count:,}, "
        f"unknown={collection.unknown_mapping_count:,}, invalid={collection.invalid_mapping_count:,}.",
        "This inspector is read-only and does not change DDS reconstruction or mod packaging.",
    )
    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=detail_lines,
        metadata_label="PATHC Texture Index",
    )


def build_archive_pathc_lookup_detail_for_entry(entry: ArchiveEntry) -> str:
    try:
        pathc_path = resolve_archive_pathc_path(entry)
        if not pathc_path.is_file():
            return ""
        collection = load_pathc_collection(pathc_path)
        return _format_pathc_lookup_detail(collection.lookup_file(entry.path))
    except Exception as exc:
        return f"PATHC Lookup:\n- Unavailable: {exc}"
