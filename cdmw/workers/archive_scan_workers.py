"""Archive scan worker for cache-aware archive browser loads."""

from __future__ import annotations

import gc
import json
import os
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.archive import (
    ArchiveNameSearchIndex,
    archive_browser_sort_is_active,
    build_archive_name_search_index,
    invalidate_archive_browser_cache,
    load_archive_derived_index_cache,
    load_or_update_archive_basic_index_shards,
    load_or_update_archive_name_search_shards,
    normalize_archive_browser_sort_column,
    normalize_archive_browser_sort_order,
    normalize_archive_extension_filter,
    resolve_crimson_desert_executable,
    save_archive_basic_index_cache,
    save_archive_derived_index_cache,
    sha256_file,
)
from cdmw.core.archive_accelerator import (
    build_archive_basic_indexes_accelerated,
    prepare_archive_browser_state_accelerated,
    scan_archive_entries_cached_accelerated,
)
from cdmw.core.item_index import build_archive_item_search_index
from cdmw.domain.archives.filters import build_archive_category_entry_index
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity, RunCancelled


def _timing_value(timings: Optional[Dict[str, float]], key: str) -> float:
    if not timings:
        return 0.0
    raw_value = timings.get(key, 0.0)
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        return 0.0


def _format_timing_summary(
    prefix: str,
    source: str,
    timings: Optional[Dict[str, float]],
    ordered_fields: Sequence[Tuple[str, str]],
) -> str:
    parts = [prefix, f"source={str(source or '').strip() or 'unknown'}"]
    for key, label in ordered_fields:
        parts.append(f"{label}={_timing_value(timings, key):.2f}s")
    return " | ".join(parts)


_LIGHTWEIGHT_MESH_EXTENSIONS = frozenset({".pac", ".pam", ".pamlod"})


def build_archive_lightweight_lookup_indexes(
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[
    Dict[str, List[ArchiveEntry]],
    Counter[str],
    Dict[str, List[ArchiveEntry]],
    Dict[ArchiveEntryIdentity, ArchiveEntry],
]:
    """Build lookup data needed before deferred full path indexes are ready."""

    extension_index: Dict[str, List[ArchiveEntry]] = {}
    mesh_path_index: Dict[str, List[ArchiveEntry]] = {}
    mesh_entries: List[ArchiveEntry] = []
    for index, entry in enumerate(entries):
        if index % 4096 == 0 and stop_event is not None and stop_event.is_set():
            raise RunCancelled("Archive lookup indexing cancelled.")
        extension = normalize_archive_extension_filter(entry.extension)
        if not extension:
            continue
        extension_index.setdefault(extension, []).append(entry)
        if extension in _LIGHTWEIGHT_MESH_EXTENSIONS:
            normalized_path = str(entry.path or "").replace("\\", "/").strip().strip("/").casefold()
            if normalized_path:
                mesh_path_index.setdefault(normalized_path, []).append(entry)
            if extension in {".pam", ".pamlod"}:
                mesh_entries.append(entry)

    companion_index: Dict[ArchiveEntryIdentity, ArchiveEntry] = {}
    for index, entry in enumerate(mesh_entries):
        if index % 1024 == 0 and stop_event is not None and stop_event.is_set():
            raise RunCancelled("Archive companion indexing cancelled.")
        normalized_path = str(entry.path or "").replace("\\", "/").strip().strip("/").casefold()
        companion_paths: List[str] = []
        if entry.extension == ".pam" and normalized_path.endswith(".pam"):
            companion_paths.append(f"{normalized_path[:-4]}.pamlod")
            stem = normalized_path[:-4]
            if stem.endswith("_breakable"):
                companion_paths.append(f"{stem[:-10]}.pamlod")
        elif entry.extension == ".pamlod" and normalized_path.endswith(".pamlod"):
            companion_paths.append(f"{normalized_path[:-7]}.pam")
        for companion_path in companion_paths:
            candidates = mesh_path_index.get(companion_path, ())
            if not candidates:
                continue
            companion = next(
                (candidate for candidate in candidates if candidate.pamt_path == entry.pamt_path),
                candidates[0],
            )
            companion_index[entry.identity] = companion
            break

    return (
        extension_index,
        Counter({extension: len(items) for extension, items in extension_index.items()}),
        mesh_path_index,
        companion_index,
    )


class ArchiveScanWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        package_root: Path,
        cache_root: Path,
        *,
        force_refresh: bool = False,
        build_structure_children: bool = True,
        build_tree_index: bool = True,
        filter_text: str = "",
        exclude_filter_text: str = "",
        extension_filter: str = "*",
        package_filter_text: str = "",
        structure_filter: str = "",
        role_filter: str = "all",
        exclude_common_technical_suffixes: bool = False,
        min_size_kb: int = 0,
        previewable_only: bool = False,
        build_category_index: bool = True,
        item_search_aliases: Optional[Mapping[str, str]] = None,
        sort_column: int = -1,
        sort_order: str = "asc",
        result_filter_signature: Tuple[object, ...] = (),
        load_basic_index_cache: bool = False,
        load_name_search_index_cache: bool = False,
        defer_enhanced_index_build: bool = False,
        native_archive_acceleration: bool = True,
        resource_profile: str = "balanced_60fps",
        game_executable_fingerprints: Optional[Mapping[str, Mapping[str, object]]] = None,
        crash_reports_dir: Optional[Path] = None,
    ):
        super().__init__()
        self.package_root = package_root
        self.cache_root = cache_root
        self.force_refresh = force_refresh
        self.build_structure_children = bool(build_structure_children)
        self.build_tree_index = build_tree_index
        self.filter_text = filter_text
        self.exclude_filter_text = exclude_filter_text
        self.extension_filter = extension_filter
        self.package_filter_text = package_filter_text
        self.structure_filter = structure_filter
        self.role_filter = role_filter
        self.exclude_common_technical_suffixes = exclude_common_technical_suffixes
        self.min_size_kb = min_size_kb
        self.previewable_only = previewable_only
        self.build_category_index = build_category_index
        self.item_search_aliases = dict(item_search_aliases or {})
        self.sort_column = normalize_archive_browser_sort_column(sort_column)
        self.sort_order = normalize_archive_browser_sort_order(sort_order)
        self.result_filter_signature = tuple(result_filter_signature or ())
        self.load_basic_index_cache = bool(load_basic_index_cache)
        self.load_name_search_index_cache = bool(load_name_search_index_cache)
        self.defer_enhanced_index_build = bool(defer_enhanced_index_build)
        self.native_archive_acceleration = bool(native_archive_acceleration)
        self.resource_profile = str(resource_profile or "balanced_60fps")
        self.crash_reports_dir = crash_reports_dir
        self.game_executable_fingerprints = {
            str(key): dict(value)
            for key, value in (game_executable_fingerprints or {}).items()
            if isinstance(value, Mapping)
        }
        self.updated_game_executable_fingerprints: Optional[Dict[str, Dict[str, object]]] = None
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def _can_use_fast_flat_initial_browser_state(self, entries: Sequence[ArchiveEntry]) -> bool:
        if not entries or self.build_tree_index or self.build_category_index:
            return False
        if self.build_structure_children:
            return False
        if archive_browser_sort_is_active(self.sort_column):
            return False
        normalized_extension = normalize_archive_extension_filter(self.extension_filter)
        if normalized_extension and normalized_extension not in {"*", "all", ".*"}:
            return False
        normalized_role = str(self.role_filter or "all").strip().lower()
        return not any(
            (
                str(self.filter_text or "").strip(),
                str(self.exclude_filter_text or "").strip(),
                str(self.package_filter_text or "").strip(),
                str(self.structure_filter or "").strip(),
                normalized_role not in {"", "all"},
                bool(self.exclude_common_technical_suffixes),
                int(self.min_size_kb or 0) > 0,
                bool(self.previewable_only),
            )
        )

    def _build_enhanced_archive_indexes_inline(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        shard_entry_signatures: Optional[Mapping[str, str]] = None,
        shard_entry_counts: Optional[Mapping[str, int]] = None,
    ) -> Dict[str, object]:
        self.log_message.emit("Preparing archive search cache (1/3): item links...")
        self.progress_changed.emit(0, 0, "Preparing archive search cache (1/3): item links...")
        item_index = build_archive_item_search_index(
            entries,
            on_log=self.log_message.emit,
            on_progress=self.progress_changed.emit,
            stop_event=self.stop_event,
        )
        item_search_aliases = dict(item_index.model_base_aliases)
        item_display_names = dict(getattr(item_index, "model_base_display_names", {}) or {})
        item_exact_display_names = dict(getattr(item_index, "model_base_exact_display_names", {}) or {})
        item_related_display_names = dict(getattr(item_index, "model_base_related_display_names", {}) or {})
        item_asset_catalog = [
            row.to_cache_dict()
            for row in getattr(item_index, "asset_catalog", [])
            if hasattr(row, "to_cache_dict")
        ]
        self.log_message.emit("Preparing archive search cache (2/3): path/name index...")
        self.progress_changed.emit(0, 0, "Preparing archive search cache (2/3): path/name index...")
        name_search_index = load_or_update_archive_name_search_shards(
            self.package_root,
            self.cache_root,
            entries,
            item_search_aliases,
            load_name_search_index=True,
            shard_entry_signatures=shard_entry_signatures,
            shard_entry_counts=shard_entry_counts,
            on_progress=self.progress_changed.emit,
            on_log=self.log_message.emit,
            stop_event=self.stop_event,
        )
        if not isinstance(name_search_index, ArchiveNameSearchIndex):
            self.log_message.emit("Preparing archive search cache (2/3): path/name index...")
            self.progress_changed.emit(0, 0, "Preparing archive search cache (2/3): path/name index...")
            name_search_index = build_archive_name_search_index(
                entries,
                item_search_aliases=item_search_aliases,
                on_progress=self.progress_changed.emit,
                stop_event=self.stop_event,
            )
        return {
            "item_search_aliases": item_search_aliases,
            "item_display_names": item_display_names,
            "item_exact_display_names": item_exact_display_names,
            "item_related_display_names": item_related_display_names,
            "item_asset_catalog": item_asset_catalog,
            "name_search_index": name_search_index,
        }

    def _write_scan_breadcrumb(self, payload: Mapping[str, object]) -> None:
        if self.crash_reports_dir is None:
            return
        try:
            self.crash_reports_dir.mkdir(parents=True, exist_ok=True)
            breadcrumb_path = self.crash_reports_dir / "archive_scan_breadcrumb.json"
            enriched = dict(payload)
            enriched.setdefault("worker", "ArchiveScanWorker")
            enriched.setdefault("pid", os.getpid())
            temp_path = breadcrumb_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
            temp_path.replace(breadcrumb_path)
        except Exception:
            pass

    def _check_game_update_and_invalidate_archive_cache(self) -> None:
        executable_path = resolve_crimson_desert_executable(self.package_root)
        if executable_path is None:
            return

        try:
            stat_result = executable_path.stat()
        except OSError as exc:
            self.log_message.emit(f"Game update check skipped: could not read {executable_path}: {exc}")
            return

        executable_key = str(executable_path).strip().lower()
        current_size = int(stat_result.st_size)
        current_mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
        records: Dict[str, Dict[str, object]] = {
            str(key): dict(value)
            for key, value in self.game_executable_fingerprints.items()
            if isinstance(value, Mapping)
        }
        previous_record = records.get(executable_key, {})
        previous_hash = str(previous_record.get("sha256", "") or "").strip()
        previous_size = int(previous_record.get("size", -1) or -1)
        previous_mtime_ns = int(previous_record.get("mtime_ns", -1) or -1)

        if previous_hash and previous_size == current_size and previous_mtime_ns == current_mtime_ns:
            return

        try:
            current_hash = sha256_file(executable_path)
        except OSError as exc:
            self.log_message.emit(f"Game update check skipped: could not hash {executable_path}: {exc}")
            return

        records[executable_key] = {
            "path": str(executable_path),
            "sha256": current_hash,
            "size": current_size,
            "mtime_ns": current_mtime_ns,
            "checked_at": time.time(),
        }
        self.updated_game_executable_fingerprints = records

        if not previous_hash:
            self.log_message.emit(f"Recorded CrimsonDesert.exe hash baseline: {executable_path}")
            return
        if previous_hash == current_hash:
            return

        deleted_paths = invalidate_archive_browser_cache(
            self.package_root,
            self.cache_root,
            on_log=self.log_message.emit,
        )
        if deleted_paths:
            self.log_message.emit(
                "Game update detected via CrimsonDesert.exe hash. "
                f"Archive Browser cache invalidated ({len(deleted_paths):,} file(s))."
            )
        else:
            self.log_message.emit(
                "Game update detected via CrimsonDesert.exe hash. No existing Archive Browser cache file needed deletion."
            )

    @Slot()
    def run(self) -> None:
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            timings: Dict[str, float] = {}
            started_at = time.perf_counter()
            if self.force_refresh:
                self.log_message.emit(f"Refreshing archive packages under {self.package_root}")
            else:
                self.log_message.emit(f"Loading archive packages under {self.package_root}")
            game_update_started_at = time.perf_counter()
            self._check_game_update_and_invalidate_archive_cache()
            timings["game_update_check_s"] = max(0.0, float(time.perf_counter() - game_update_started_at))
            entries, source, cache_path, scan_timings, scan_metadata = scan_archive_entries_cached_accelerated(
                self.package_root,
                self.cache_root,
                force_refresh=self.force_refresh,
                on_log=self.log_message.emit,
                on_progress=self.progress_changed.emit,
                on_breadcrumb=self._write_scan_breadcrumb,
                stop_event=self.stop_event,
            )
            timings.update(scan_timings)
            scan_metadata = scan_metadata if isinstance(scan_metadata, Mapping) else {}
            entry_metadata_signature = str(scan_metadata.get("entry_metadata_signature", "") or "").strip()
            entry_metadata_sources = tuple(
                tuple(row)
                for row in (scan_metadata.get("entry_metadata_sources", ()) or ())
                if isinstance(row, (list, tuple)) and len(row) == 3
            )
            raw_shard_signatures = scan_metadata.get("scan_shard_entry_signatures")
            scan_shard_entry_signatures = {
                str(key): str(value)
                for key, value in (raw_shard_signatures.items() if isinstance(raw_shard_signatures, Mapping) else ())
                if str(key)
            }
            raw_shard_counts = scan_metadata.get("scan_shard_entry_counts")
            scan_shard_entry_counts: Dict[str, int] = {}
            if isinstance(raw_shard_counts, Mapping):
                for key, value in raw_shard_counts.items():
                    try:
                        scan_shard_entry_counts[str(key)] = int(value)
                    except (TypeError, ValueError):
                        continue
            item_search_aliases: Dict[str, str] = {}
            item_display_names: Dict[str, str] = {}
            item_exact_display_names: Dict[str, str] = {}
            item_related_display_names: Dict[str, str] = {}
            item_asset_catalog: List[Dict[str, object]] = []
            path_index: Mapping[str, Sequence[ArchiveEntry]] = {}
            basename_index: Mapping[str, Sequence[ArchiveEntry]] = {}
            role_index: Mapping[str, Sequence[ArchiveEntry]] = {}
            extension_index_started_at = time.perf_counter()
            (
                extension_index,
                extension_counts,
                mesh_path_index,
                mesh_companion_index,
            ) = build_archive_lightweight_lookup_indexes(
                entries,
                stop_event=self.stop_event,
            )
            timings["entry_extension_index_s"] = max(
                0.0,
                float(time.perf_counter() - extension_index_started_at),
            )
            name_search_index: Optional[ArchiveNameSearchIndex] = None
            derived_cache = None
            derived_cache_needs_write = False
            enhanced_index_deferred_message = ""
            enhanced_index_deferred_progress = ""
            if entries and not self.force_refresh:
                self.log_message.emit("Checking archive search cache...")
                self.progress_changed.emit(0, 0, "Checking archive search cache...")
                derived_cache = load_archive_derived_index_cache(
                    self.package_root,
                    self.cache_root,
                    entries,
                    entry_metadata_signature=entry_metadata_signature or None,
                    current_sources=entry_metadata_sources or None,
                    load_name_search_index=self.load_name_search_index_cache,
                    shard_entry_signatures=scan_shard_entry_signatures,
                    shard_entry_counts=scan_shard_entry_counts,
                    on_log=self.log_message.emit,
                    timings=timings,
                )
            if isinstance(derived_cache, dict):
                item_search_aliases = dict(derived_cache.get("item_search_aliases", {}) or {})
                item_display_names = dict(derived_cache.get("item_display_names", {}) or {})
                item_exact_display_names = dict(derived_cache.get("item_exact_display_names", {}) or {})
                item_related_display_names = dict(derived_cache.get("item_related_display_names", {}) or {})
                item_asset_catalog = [
                    dict(row)
                    for row in (derived_cache.get("item_asset_catalog", []) or [])
                    if isinstance(row, Mapping)
                ]
                cached_name_search_index = derived_cache.get("name_search_index")
                if isinstance(cached_name_search_index, ArchiveNameSearchIndex):
                    name_search_index = cached_name_search_index
                elif bool(derived_cache.get("name_search_index_deferred")):
                    enhanced_index_deferred_message = "Item-name search cache will load on demand after the archive list opens."
                    enhanced_index_deferred_progress = "Item-name search cache deferred until needed..."
                else:
                    derived_cache_needs_write = bool(entries)
                enhanced_index_needs_build = bool(entries and name_search_index is None)
                timings.setdefault("item_search_index_s", 0.0)
            else:
                derived_cache_needs_write = False
                enhanced_index_needs_build = bool(entries)
                enhanced_index_deferred_message = "Item-name search cache is missing or stale; archive list will open and search will build on demand."
                enhanced_index_deferred_progress = "Item-name search deferred until needed..."
                timings["item_search_index_s"] = 0.0
            build_enhanced_indexes_before_ready = bool(
                entries and name_search_index is None
                and not self.defer_enhanced_index_build
                and (
                    self.force_refresh
                    or source != "cache"
                    or self.load_name_search_index_cache
                )
            )
            if build_enhanced_indexes_before_ready:
                self.log_message.emit("Preparing archive search cache as part of archive cache build.")
                enhanced_started_at = time.perf_counter()
                enhanced_payload = self._build_enhanced_archive_indexes_inline(
                    entries,
                    shard_entry_signatures=scan_shard_entry_signatures,
                    shard_entry_counts=scan_shard_entry_counts,
                )
                item_search_aliases = dict(enhanced_payload.get("item_search_aliases", {}) or {})
                item_display_names = dict(enhanced_payload.get("item_display_names", {}) or {})
                item_exact_display_names = dict(enhanced_payload.get("item_exact_display_names", {}) or {})
                item_related_display_names = dict(enhanced_payload.get("item_related_display_names", {}) or {})
                item_asset_catalog = [
                    dict(row)
                    for row in (enhanced_payload.get("item_asset_catalog", []) or [])
                    if isinstance(row, Mapping)
                ]
                built_name_search_index = enhanced_payload.get("name_search_index")
                if isinstance(built_name_search_index, ArchiveNameSearchIndex):
                    name_search_index = built_name_search_index
                    derived_cache_needs_write = True
                    enhanced_index_needs_build = False
                else:
                    enhanced_index_needs_build = bool(entries)
                timings["item_search_index_s"] = max(0.0, float(time.perf_counter() - enhanced_started_at))
            elif enhanced_index_deferred_message:
                self.log_message.emit(enhanced_index_deferred_message)
                self.progress_changed.emit(0, 0, enhanced_index_deferred_progress)
            can_use_initial_list = self._can_use_fast_flat_initial_browser_state(entries)
            basic_cache = None
            if entries and self.load_basic_index_cache:
                if self.force_refresh:
                    self.log_message.emit("Rebuilding archive path lookup shard cache...")
                    self.progress_changed.emit(0, 0, "Rebuilding archive path lookup shard cache...")
                else:
                    self.log_message.emit("Checking archive path lookup cache...")
                    self.progress_changed.emit(0, 0, "Checking archive path lookup cache...")
                try:
                    basic_cache = load_or_update_archive_basic_index_shards(
                        self.package_root,
                        self.cache_root,
                        entries,
                        force_refresh=self.force_refresh,
                        shard_entry_signatures=scan_shard_entry_signatures,
                        shard_entry_counts=scan_shard_entry_counts,
                        on_progress=self.progress_changed.emit,
                        on_log=self.log_message.emit,
                        timings=timings,
                        stop_event=self.stop_event,
                    )
                except Exception as exc:
                    self.log_message.emit(f"Archive path lookup shard cache could not be used: {exc}")
                    basic_cache = None
            basic_indexes_loaded_from_cache = False
            if isinstance(basic_cache, Mapping):
                cached_path_index = basic_cache.get("path_index")
                cached_basename_index = basic_cache.get("basename_index")
                cached_extension_index = basic_cache.get("extension_index")
                cached_role_index = basic_cache.get("role_index")
                if (
                    isinstance(cached_path_index, Mapping)
                    and isinstance(cached_basename_index, Mapping)
                    and isinstance(cached_extension_index, Mapping)
                    and isinstance(cached_role_index, Mapping)
                ):
                    path_index = cached_path_index
                    basename_index = cached_basename_index
                    extension_index = cached_extension_index
                    role_index = cached_role_index
                    basic_indexes_loaded_from_cache = True
            basic_indexes_needed_before_ready = bool(
                entries and self.load_basic_index_cache and not basic_indexes_loaded_from_cache
            )
            native_basic_indexes_used = False
            if basic_indexes_needed_before_ready:
                self.log_message.emit("Building path lookup...")
                self.progress_changed.emit(0, 0, "Building path lookup...")
                path_index_started_at = time.perf_counter()
                path_index, basename_index, extension_index, role_index, native_basic_indexes_used = build_archive_basic_indexes_accelerated(
                    entries,
                    native_enabled=self.native_archive_acceleration,
                    on_progress=self.progress_changed.emit,
                    stop_event=self.stop_event,
                )
                basic_index_elapsed = max(0.0, float(time.perf_counter() - path_index_started_at))
                timings["entry_path_index_s"] = basic_index_elapsed
                if native_basic_indexes_used:
                    self.log_message.emit("Built path lookup with C++ helper.")
                try:
                    save_archive_basic_index_cache(
                        self.package_root,
                        self.cache_root,
                        entries,
                        path_index=path_index,
                        basename_index=basename_index,
                        extension_index=extension_index,
                        role_index=role_index,
                        entry_metadata_signature=entry_metadata_signature or None,
                        entry_metadata_sources=entry_metadata_sources or None,
                        on_log=self.log_message.emit,
                        timings=timings,
                    )
                except Exception as exc:
                    self.log_message.emit(f"Warning: path lookup cache could not be written: {exc}")
            else:
                if basic_indexes_loaded_from_cache:
                    if isinstance(basic_cache, Mapping) and not bool(basic_cache.get("cache_loaded", True)):
                        rebuilt_shards = int(basic_cache.get("rebuilt_shards", 0) or 0)
                        self.log_message.emit(f"Path lookup cache ready after rebuilding {rebuilt_shards:,} shard(s).")
                    else:
                        self.log_message.emit("Path lookup loaded from cache.")
                else:
                    self.log_message.emit("Path lookup cache is deferred until filters, search, preview, or priority indexing need it.")
                    self.progress_changed.emit(0, 0, "Path lookup deferred until needed...")
                timings["entry_path_index_s"] = 0.0
            timings["entry_basename_index_s"] = 0.0
            timings.setdefault("entry_extension_index_s", 0.0)
            if name_search_index is None:
                timings["entry_name_search_index_s"] = 0.0
            else:
                self.log_message.emit("Loaded archive name search index from derived cache.")
                timings["entry_name_search_index_s"] = 0.0
            browser_state_started_at = time.perf_counter()
            if can_use_initial_list:
                self.log_message.emit("Opening archive list from loaded entries...")
                self.progress_changed.emit(
                    len(entries),
                    max(len(entries), 1),
                    "Opening archive list from loaded entries...",
                )
                dds_count = int(extension_counts.get(".dds", 0) or 0)
                browser_state = {
                    "structure_children": {},
                    "filtered_entries": entries,
                    "tree_child_folders": {},
                    "tree_direct_files": {},
                    "tree_folder_entry_indexes": {},
                    "tree_folder_preview_stats": {},
                    "tree_index_ready": False,
                    "dds_count": dds_count,
                    "archive_accelerator": {
                        "backend": "raw_flat",
                        "native_requested": bool(self.native_archive_acceleration),
                        "native_used": False,
                        "resource_profile": str(self.resource_profile or "balanced_60fps"),
                    },
                }
                self.log_message.emit(
                    "Archive Browser state mode: raw_flat (no active filters/sort/tree/category; reusing loaded entries)."
                )
            else:
                self.log_message.emit("Preparing archive list from filters and view mode...")
                self.progress_changed.emit(
                    0,
                    max(len(entries), 1),
                    "Preparing archive list from filters and view mode...",
                )
                browser_state = prepare_archive_browser_state_accelerated(
                    entries,
                    filter_text=self.filter_text,
                    exclude_filter_text=self.exclude_filter_text,
                    extension_filter=self.extension_filter,
                    package_filter_text=self.package_filter_text,
                    structure_filter=self.structure_filter,
                    role_filter=self.role_filter,
                    exclude_common_technical_suffixes=self.exclude_common_technical_suffixes,
                    min_size_kb=self.min_size_kb,
                    previewable_only=self.previewable_only,
                    item_search_aliases=item_search_aliases,
                    archive_entries_by_basename=basename_index,
                    archive_entries_by_normalized_path=path_index,
                    archive_name_search_index=name_search_index,
                    build_structure_children=self.build_structure_children,
                    build_tree_index=self.build_tree_index,
                    sort_column=self.sort_column,
                    sort_order=self.sort_order,
                    item_display_names=item_display_names,
                    item_exact_display_names=item_exact_display_names,
                    item_related_display_names=item_related_display_names,
                    on_progress=self.progress_changed.emit,
                    stop_event=self.stop_event,
                    native_enabled=self.native_archive_acceleration,
                    resource_profile=self.resource_profile,
                )
                accelerator = browser_state.get("archive_accelerator") if isinstance(browser_state, dict) else {}
                if (
                    isinstance(accelerator, Mapping)
                    and not accelerator.get("native_used")
                    and len(entries) >= 500_000
                ):
                    fallback_reason = str(accelerator.get("fallback_reason", "") or "unknown reason")
                    if not fallback_reason.endswith("_python_path"):
                        self.log_message.emit(
                            "WARNING: Archive browser state used Python fallback for a very large entry set; "
                            f"first render may be slower. Native fallback reason: {fallback_reason}"
                        )
            timings["browser_state_s"] = max(0.0, float(time.perf_counter() - browser_state_started_at))
            if self.build_category_index:
                self.log_message.emit("Building archive category index...")
                self.progress_changed.emit(0, 0, "Building archive category index...")
                category_index_started_at = time.perf_counter()
                browser_state["category_entry_indexes"] = build_archive_category_entry_index(
                    browser_state.get("filtered_entries", ()),
                    on_progress=self.progress_changed.emit,
                    stop_event=self.stop_event,
                )
                timings["category_index_s"] = max(0.0, float(time.perf_counter() - category_index_started_at))
            else:
                browser_state["category_entry_indexes"] = {}
                timings["category_index_s"] = 0.0
            if derived_cache_needs_write and entries and name_search_index is not None:
                self.log_message.emit("Preparing archive search cache (3/3): saving...")
                self.progress_changed.emit(0, 0, "Preparing archive search cache (3/3): saving...")
                save_archive_derived_index_cache(
                    self.package_root,
                    self.cache_root,
                    entries,
                    item_search_aliases=item_search_aliases,
                    item_display_names=item_display_names,
                    item_exact_display_names=item_exact_display_names,
                    item_related_display_names=item_related_display_names,
                    item_asset_catalog=item_asset_catalog,
                    archive_name_search_index=name_search_index,
                    entry_metadata_signature=entry_metadata_signature or None,
                    entry_metadata_sources=entry_metadata_sources or None,
                    on_log=self.log_message.emit,
                    timings=timings,
                )
                elapsed = float(timings.get("derived_cache_write_s", 0.0) or 0.0)
                self.log_message.emit(f"Archive search cache saved in {elapsed:.2f}s.")
                derived_cache_needs_write = False
            timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
            timing_summary = _format_timing_summary(
                "Archive scan timings",
                source,
                timings,
                (
                    ("game_update_check_s", "game_update"),
                    ("cache_check_s", "cache_check"),
                    ("cache_load_s", "cache_load"),
                    ("scan_shard_load_s", "scan_shard_load"),
                    ("scan_shard_rescan_s", "scan_shard_rescan"),
                    ("archive_scan_s", "archive_scan"),
                    ("scan_shard_write_s", "scan_shard_write"),
                    ("cache_write_s", "cache_write"),
                    ("derived_cache_check_s", "derived_check"),
                    ("derived_cache_load_s", "derived_load"),
                    ("basic_index_cache_check_s", "path_cache_check"),
                    ("basic_index_cache_load_s", "path_cache_load"),
                    ("basic_index_cache_write_s", "path_cache_write"),
                    ("item_search_index_s", "item_search"),
                    ("browser_state_s", "browser_state"),
                    ("category_index_s", "category_index"),
                    ("entry_path_index_s", "path_index"),
                    ("entry_basename_index_s", "basename_index"),
                    ("entry_extension_index_s", "extension_index"),
                    ("entry_name_search_index_s", "name_search_index"),
                    ("total_s", "total"),
                ),
            )
            self.completed.emit(
                {
                    "entries": entries,
                    "source": source,
                    "cache_path": str(cache_path) if cache_path is not None else "",
                    "browser_state": browser_state,
                    "path_index": path_index,
                    "basename_index": basename_index,
                    "extension_index": extension_index,
                    "mesh_path_index": mesh_path_index,
                    "mesh_companion_index": mesh_companion_index,
                    "role_index": role_index,
                    "name_search_index": name_search_index,
                    "item_search_aliases": item_search_aliases,
                    "item_display_names": item_display_names,
                    "item_exact_display_names": item_exact_display_names,
                    "item_related_display_names": item_related_display_names,
                    "item_asset_catalog": item_asset_catalog,
                    "derived_cache_needs_write": derived_cache_needs_write,
                    "enhanced_index_needs_build": enhanced_index_needs_build,
                    "basic_index_needs_build": bool(
                        entries and not (path_index and basename_index and extension_index and role_index)
                    ),
                    "archive_native_derived_cache_ready": bool(native_basic_indexes_used),
                    "extension_counts": dict(extension_counts),
                    "entry_metadata_signature": entry_metadata_signature,
                    "entry_metadata_sources": entry_metadata_sources,
                    "scan_metadata": dict(scan_metadata),
                    "result_filter_signature": self.result_filter_signature,
                    "game_executable_fingerprints": self.updated_game_executable_fingerprints,
                    "timings": timings,
                    "timing_summary": timing_summary,
                }
            )
        except RunCancelled as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if gc_was_enabled:
                gc.enable()
            self.finished.emit()

__all__ = ["ArchiveScanWorker"]
