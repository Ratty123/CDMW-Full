"""Archive browser interaction coordinator boundary."""

from __future__ import annotations

import os
import time
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.constants import (
    ARCHIVE_AUDIO_EXTENSIONS,
    ARCHIVE_IMAGE_EXTENSIONS,
    ARCHIVE_TEXT_EXTENSIONS,
    ARCHIVE_VIDEO_EXTENSIONS,
)
from cdmw.core.archive import (
    _is_material_sidecar_extension,
    active_archive_entry_for_virtual_path,
    archive_browser_sort_is_active,
    archive_entry_identity_key,
    archive_entry_is_mod_package,
    archive_entry_load_priority,
    build_archive_tree_index,
    format_byte_size,
    normalize_archive_browser_sort_column,
    normalize_archive_extension_filter,
    sort_archive_entries_for_browser,
)
from cdmw.domain.archives.filters import build_archive_category_entry_index
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.model import ArchiveBrowserRowPayload


class ArchiveBrowserController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context


class ArchiveBrowserRowPayloadMixin:
    """Archive browser virtual-row payload and cache helpers."""

    @staticmethod
    def _normalize_archive_entry_path(path: str) -> str:
        return path.replace("\\", "/").strip().lower()

    def _build_archive_entry_path_index(self, entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
        index: Dict[str, List[ArchiveEntry]] = {}
        for archive_entry in entries:
            normalized_path = self._normalize_archive_entry_path(archive_entry.path)
            index.setdefault(normalized_path, []).append(archive_entry)
        return index

    def _build_archive_entry_basename_index(self, entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
        index: Dict[str, List[ArchiveEntry]] = {}
        for archive_entry in entries:
            basename = Path(archive_entry.path).name.strip().lower()
            if not basename:
                continue
            index.setdefault(basename, []).append(archive_entry)
        return index

    def _build_archive_entry_extension_index(self, entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
        index: Dict[str, List[ArchiveEntry]] = {}
        for archive_entry in entries:
            extension = normalize_archive_extension_filter(archive_entry.extension)
            if not extension:
                continue
            index.setdefault(extension, []).append(archive_entry)
        return index

    def _find_archive_preview_companion_entry(self, entry: Optional[ArchiveEntry]) -> Optional[ArchiveEntry]:
        if entry is None or entry.extension not in {".pam", ".pamlod"}:
            return None
        normalized_path = self._normalize_archive_entry_path(entry.path)
        companion_paths: List[str] = []
        if entry.extension == ".pam" and normalized_path.endswith(".pam"):
            companion_paths.append(f"{normalized_path[:-4]}.pamlod")
            stem = normalized_path[:-4]
            if stem.endswith("_breakable"):
                companion_paths.append(f"{stem[:-10]}.pamlod")
        elif entry.extension == ".pamlod" and normalized_path.endswith(".pamlod"):
            companion_paths.append(f"{normalized_path[:-7]}.pam")

        for companion_path in companion_paths:
            candidates = self.archive_entries_by_normalized_path.get(companion_path, [])
            if not candidates:
                continue
            for candidate in candidates:
                if candidate.pamt_path == entry.pamt_path:
                    return candidate
            return candidates[0]
        return None

    def current_archive_path_for_research(self) -> str:
        entry = self._current_archive_entry()
        return entry.path if entry is not None else ""

    def _archive_entry_display_size(self, entry: ArchiveEntry) -> Tuple[str, str]:
        original_text = format_byte_size(entry.orig_size)
        stored_text = format_byte_size(entry.comp_size)
        if int(entry.orig_size) == int(entry.comp_size):
            size_text = original_text
        else:
            size_text = f"{original_text} / {stored_text} stored"
        tooltip = f"Original: {int(entry.orig_size):,} bytes\nStored: {int(entry.comp_size):,} bytes"
        return size_text, tooltip

    def _archive_entry_role_label(self, entry: Optional[ArchiveEntry]) -> str:
        if not isinstance(entry, ArchiveEntry):
            return "Unknown"
        ext = str(entry.extension or "").lower()
        path = str(entry.path or "").replace("\\", "/").lower()
        basename = PurePosixPath(path).name
        if ext in ARCHIVE_IMAGE_EXTENSIONS:
            return "Texture"
        if _is_material_sidecar_extension(ext, basename) or ext in {".pac_xml", ".pam_xml", ".pamlod_xml"}:
            return "Material"
        if ext in {".hkx", ".hkt"}:
            if "meshphysics" in path or "havokphysics" in path or "ragdoll" in path or "physics" in path:
                return "Physics"
            return "HKX"
        if ext == ".paa_metabin":
            return "Animation Metadata"
        if ext in {".paa", ".motionblending", ".pae", ".paem", ".papr", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
            return "Animation"
        if ext == ".pab":
            return "Skeleton / Rig"
        if ext in {".prefab", ".prefabdata_xml", ".prefabdata.xml", ".pappt"}:
            return "Prefab"
        if ext == ".pamhc":
            return "Model Property Metadata"
        if ext == ".seqmt":
            return "Sequence Texture Metadata"
        if ext in ARCHIVE_AUDIO_EXTENSIONS:
            return "Audio"
        if ext in ARCHIVE_VIDEO_EXTENSIONS:
            return "Video"
        if ext in ARCHIVE_TEXT_EXTENSIONS or ext in {".meshinfo", ".motionblending", ".paa_metabin", ".prefab", ".pappt", ".pamhc", ".seqmt"}:
            if "/ui" in path or path.startswith("ui/"):
                return "UI"
            return "Metadata"
        if ext in {".pac", ".pam", ".pamlod", ".obj", ".fbx", ".dae", ".gltf", ".glb", ".mesh", ".mdl", ".model", ".pat", ".patx"}:
            return "Mesh"
        if "/ui" in path or path.startswith("ui/"):
            return "UI"
        return "Unknown"

    def _archive_role_display_text(self, entry: Optional[ArchiveEntry]) -> str:
        if not isinstance(entry, ArchiveEntry):
            return "Unknown"
        role = self._archive_entry_role_label(entry)
        extension = str(entry.extension or "").lower()
        return f"{role} {extension}".strip()

    def _archive_entry_override_state(self, entry: Optional[ArchiveEntry]) -> Tuple[str, str]:
        if not isinstance(entry, ArchiveEntry):
            return "", ""
        normalized_path = str(entry.path or "").replace("\\", "/").strip().lower()
        same_path_entries = list(self.archive_entries_by_normalized_path.get(normalized_path, ()))
        if not same_path_entries:
            same_path_entries = [entry]
        is_mod_package = archive_entry_is_mod_package(entry)
        if len(same_path_entries) <= 1:
            if is_mod_package:
                return (
                    "Mod-added",
                    "This file comes from a mod/DMM-style package and no vanilla duplicate with the same virtual path was found.",
                )
            return "", ""
        active_entry = active_archive_entry_for_virtual_path(same_path_entries) or entry
        active_key = archive_entry_identity_key(active_entry)
        current_key = archive_entry_identity_key(entry)
        active_label = str(getattr(active_entry, "package_label", "") or "").strip() or str(active_entry.pamt_path)
        duplicate_labels = [
            str(getattr(candidate, "package_label", "") or "").strip() or str(candidate.pamt_path)
            for candidate in sorted(same_path_entries, key=archive_entry_load_priority, reverse=True)
        ]
        duplicate_text = "\n".join(f"- {label}" for label in duplicate_labels[:12])
        if current_key == active_key:
            state = "Active mod" if archive_entry_is_mod_package(entry) else "Active original"
            return (
                state,
                "This duplicate is the active winner for this virtual path based on package/load priority.\n"
                f"Active package: {active_label}\n"
                f"Duplicate candidates:\n{duplicate_text}",
            )
        state = "Shadowed mod" if is_mod_package else "Shadowed original"
        return (
            state,
            "This duplicate is shadowed by a higher-priority archive entry with the same virtual path.\n"
            f"Active package: {active_label}\n"
            f"Duplicate candidates:\n{duplicate_text}",
        )

    def _archive_entry_override_state_label(self, entry: Optional[ArchiveEntry]) -> str:
        if not isinstance(entry, ArchiveEntry):
            return ""
        normalized_path = str(entry.path or "").replace("\\", "/").strip().lower()
        same_path_entries = list(self.archive_entries_by_normalized_path.get(normalized_path, ()))
        if not same_path_entries:
            same_path_entries = [entry]
        is_mod_package = archive_entry_is_mod_package(entry)
        if len(same_path_entries) <= 1:
            return "Mod-added" if is_mod_package else ""
        active_entry = active_archive_entry_for_virtual_path(same_path_entries) or entry
        active_key = archive_entry_identity_key(active_entry)
        current_key = archive_entry_identity_key(entry)
        if current_key == active_key:
            return "Active mod" if is_mod_package else "Active original"
        return "Shadowed mod" if is_mod_package else "Shadowed original"

    def _archive_browser_row_cache_key(self, entry: ArchiveEntry, show_full_path: bool) -> Tuple[str, str, int, bool]:
        return (
            str(getattr(entry, "path", "") or ""),
            str(getattr(entry, "pamt_path", "") or ""),
            int(getattr(entry, "offset", 0) or 0),
            bool(show_full_path),
        )

    def _remember_archive_browser_row_payload(
        self,
        key: Tuple[str, str, int, bool],
        payload: ArchiveBrowserRowPayload,
    ) -> ArchiveBrowserRowPayload:
        self.archive_browser_row_display_cache[key] = payload
        self.archive_browser_row_display_cache.move_to_end(key)
        while len(self.archive_browser_row_display_cache) > self.archive_browser_row_display_cache_limit:
            self.archive_browser_row_display_cache.popitem(last=False)
        return payload

    def _archive_browser_row_tooltips(
        self,
        entry: ArchiveEntry,
        *,
        exact_item_name: str,
        name_match: str,
        name_match_tooltip: str,
        role_label: str,
        size_tooltip: str,
    ) -> Tuple[str, ...]:
        _override_state, override_tooltip = self._archive_entry_override_state(entry)
        return (
            entry.path,
            f"{exact_item_name}\nExact: iteminfo localization ID plus direct model/prefab hash." if exact_item_name else "",
            name_match_tooltip or name_match or "",
            f"Role: {role_label}\nExtension: {entry.extension or '-'}",
            size_tooltip,
            "",
            f"Package: {entry.package_label}\nPAMT: {entry.pamt_path}",
            override_tooltip or "No duplicate override state was detected for this virtual path.",
            entry.path,
        )

    def _archive_browser_row_payload(self, entry_index: int, show_full_path: bool = False) -> ArchiveBrowserRowPayload:
        entry = self.archive_filtered_entries[entry_index]
        cache_key = self._archive_browser_row_cache_key(entry, show_full_path)
        cached_payload = self.archive_browser_row_display_cache.get(cache_key)
        if cached_payload is not None:
            self.archive_browser_row_display_cache.move_to_end(cache_key)
            return cached_payload
        normalized_parts = tuple(part for part in PurePosixPath(entry.path.replace("\\", "/")).parts if part)
        size_text, size_tooltip = self._archive_entry_display_size(entry)
        display_name = normalized_parts[-1] if normalized_parts else entry.basename
        exact_item_name, name_match, name_match_tooltip = self._archive_entry_item_name_match(entry)
        role_label = self._archive_entry_role_label(entry)
        override_state = self._archive_entry_override_state_label(entry)
        columns = (
            display_name,
            exact_item_name or "-",
            name_match or "-",
            self._archive_role_display_text(entry),
            size_text,
            entry.compression_label,
            entry.package_label,
            override_state or "-",
            entry.path if show_full_path else "/".join(normalized_parts[:-1]),
        )
        payload = ArchiveBrowserRowPayload(
            columns=columns,
            tooltip_provider=lambda current_entry=entry,
            current_exact_item_name=exact_item_name,
            current_name_match=name_match,
            current_name_match_tooltip=name_match_tooltip,
            current_role_label=role_label,
            current_size_tooltip=size_tooltip: self._archive_browser_row_tooltips(
                current_entry,
                exact_item_name=current_exact_item_name,
                name_match=current_name_match,
                name_match_tooltip=current_name_match_tooltip,
                role_label=current_role_label,
                size_tooltip=current_size_tooltip,
            ),
        )
        return self._remember_archive_browser_row_payload(cache_key, payload)

    def _archive_virtual_tree_mode(self) -> str:
        if self._archive_category_view_enabled():
            return "categories"
        if self._archive_tree_view_enabled():
            return "folders"
        return "flat"

    def _archive_virtual_fetch_batch_size(self) -> int:
        settings = self._current_archive_performance_settings()
        manual_batch = int(getattr(settings, "archive_fetch_batch_size", 0) or 0)
        if manual_batch > 0:
            return max(100, min(5000, manual_batch))
        profile = str(getattr(settings, "resource_profile", "balanced_60fps") or "balanced_60fps")
        if self._archive_ui_interactive_active():
            return 150 if profile == "quiet_laptop" else 240
        if profile == "maximum_throughput":
            return 1600
        if profile == "quiet_laptop":
            return 250
        return 500

    def _prewarm_archive_browser_row_display_cache(self, limit: int = 160) -> None:
        if self._archive_virtual_tree_mode() != "flat":
            return
        count = min(max(0, int(limit)), len(self.archive_filtered_entries))
        started_at = time.perf_counter()
        for entry_index in range(count):
            self._archive_browser_row_payload(entry_index, show_full_path=True)
            if entry_index >= 24 and (time.perf_counter() - started_at) >= 0.012:
                break

    def _note_archive_ui_activity(self) -> None:
        self.archive_ui_activity_until = time.perf_counter() + 0.35
        self.archive_ui_activity_timer.start(420)

    def _clear_archive_ui_activity(self) -> None:
        self.archive_ui_activity_until = 0.0

    def _archive_ui_interactive_active(self) -> bool:
        return time.perf_counter() < float(getattr(self, "archive_ui_activity_until", 0.0) or 0.0)

    def _archive_background_worker_limit(self) -> int:
        settings = self._current_archive_performance_settings()
        manual_limit = int(getattr(settings, "background_worker_limit", 0) or 0)
        if manual_limit > 0:
            return max(1, min(16, manual_limit))
        profile = str(getattr(settings, "resource_profile", "balanced_60fps") or "balanced_60fps")
        if profile == "maximum_throughput":
            return min(16, max(4, (os.cpu_count() or 4) - 1))
        if profile == "quiet_laptop":
            return 2
        return min(8, max(2, (os.cpu_count() or 4) // 2))


class ArchiveBrowserTreeControllerMixin:
    """Archive browser virtual tree rendering and selection helpers."""

    def _archive_tree_sort_active(self) -> bool:
        return archive_browser_sort_is_active(self.archive_tree_sort_column)

    def _update_archive_tree_sort_indicator(self) -> None:
        if not hasattr(self, "archive_tree"):
            return
        header = self.archive_tree.header()
        if header is None:
            return
        column = normalize_archive_browser_sort_column(self.archive_tree_sort_column)
        if column < 0:
            header.setSortIndicatorShown(False)
            return
        order = Qt.DescendingOrder if self.archive_tree_sort_order == "desc" else Qt.AscendingOrder
        header.setSortIndicator(column, order)
        header.setSortIndicatorShown(True)

    def _sort_current_archive_filtered_entries(self) -> None:
        if not self._archive_tree_sort_active():
            return
        self.archive_filtered_entries = sort_archive_entries_for_browser(
            self.archive_filtered_entries,
            self.archive_tree_sort_column,
            self.archive_tree_sort_order,
            item_display_names=self.archive_item_display_names,
            item_exact_display_names=self.archive_item_exact_display_names,
            item_related_display_names=self.archive_item_related_display_names,
            archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
        )

    def _rebuild_archive_browser_indexes_for_current_sort(self) -> None:
        self.archive_tree_category_entry_indexes = build_archive_category_entry_index(self.archive_filtered_entries)
        if self._archive_folder_tree_enabled():
            (
                self.archive_tree_child_folders,
                self.archive_tree_direct_files,
                self.archive_tree_folder_entry_indexes,
                self.archive_tree_folder_preview_stats,
            ) = build_archive_tree_index(
                self.archive_filtered_entries,
                preserve_direct_file_order=self._archive_tree_sort_active(),
            )
            self.archive_tree_index_ready = True
        else:
            self.archive_tree_child_folders = {}
            self.archive_tree_direct_files = {}
            self.archive_tree_folder_entry_indexes = {}
            self.archive_tree_folder_preview_stats = {}
            self.archive_tree_index_ready = False

    def _handle_archive_tree_header_clicked(self, column: int) -> None:
        column = normalize_archive_browser_sort_column(column)
        if column < 0:
            return
        current_entry = self._current_archive_entry()
        preferred_path = current_entry.path if current_entry is not None else ""
        if self.archive_tree_sort_column == column:
            self.archive_tree_sort_order = "desc" if self.archive_tree_sort_order != "desc" else "asc"
        else:
            self.archive_tree_sort_column = column
            self.archive_tree_sort_order = "asc"
        self._update_archive_tree_sort_indicator()
        self.schedule_settings_save()
        if self._archive_sort_waits_for_enhanced_index():
            self._ensure_archive_enhanced_index_worker_started()
            self.archive_initial_sort_apply_pending = True
            self.append_archive_log(
                "Archive name-column sort will apply after item-name search is ready.",
                verbose=True,
            )
            self._schedule_archive_initial_sort_after_first_paint(700)
            return
        if self.worker_thread is not None:
            if self.archive_filter_worker is not None:
                self.archive_filter_apply_pending = True
                self.archive_filter_worker.stop()
                self._set_archive_load_progress(
                    "Stopping previous archive filter before applying column sort...",
                    phase="Stopping",
                )
            else:
                self.archive_browser_refresh_pending = True
                self.set_status_message("Archive column sort will apply after the current task finishes.")
            return
        if not self.archive_entries and not self.archive_filtered_entries:
            return
        if self.archive_active_asset_catalog_scope:
            self._sort_current_archive_filtered_entries()
            self._rebuild_archive_browser_indexes_for_current_sort()
            self._populate_archive_tree(preferred_path, rebuild_index=False)
            return
        if self.archive_entries:
            self._start_archive_filter_worker(preferred_path)
        else:
            self._sort_current_archive_filtered_entries()
            self._rebuild_archive_browser_indexes_for_current_sort()
            self._populate_archive_tree(preferred_path, rebuild_index=False)

    def _handle_archive_browser_view_mode_changed(self, _index: int) -> None:
        self._mark_archive_browser_render_stale()
        self.archive_tree.setRootIsDecorated(self._archive_tree_view_enabled())
        if self.worker_thread is not None:
            self.archive_browser_refresh_pending = True
            return
        current_entry = self._current_archive_entry()
        current_entry_path = current_entry.path if current_entry is not None else ""
        rebuild_tree_index = bool(self._archive_folder_tree_enabled() and not self.archive_tree_index_ready and self.archive_filtered_entries)
        rebuild_category_index = bool(self._archive_category_view_enabled() and not self._archive_category_index_ready() and self.archive_filtered_entries)
        if (rebuild_tree_index or rebuild_category_index) and self.archive_entries:
            self._start_archive_filter_worker(current_entry_path)
            return
        self._populate_archive_tree(current_entry_path, rebuild_index=rebuild_tree_index)

    def _rebuild_archive_tree_index(self) -> None:
        (
            self.archive_tree_child_folders,
            self.archive_tree_direct_files,
            self.archive_tree_folder_entry_indexes,
            self.archive_tree_folder_preview_stats,
        ) = build_archive_tree_index(
            self.archive_filtered_entries,
            preserve_direct_file_order=self._archive_tree_sort_active(),
        )
        self.archive_tree_index_ready = True

    def _archive_tree_item_kind(self, item: Optional[QTreeWidgetItem]) -> str:
        if item is None:
            return ""
        raw = item.data(0, Qt.UserRole)
        return raw if isinstance(raw, str) else ""

    def _archive_tree_item_value(self, item: Optional[QTreeWidgetItem]) -> object:
        if item is None:
            return None
        return item.data(0, Qt.UserRole + 1)

    def _archive_tree_folder_key(self, item: Optional[QTreeWidgetItem]) -> Tuple[str, ...]:
        raw = self._archive_tree_item_value(item)
        return raw if isinstance(raw, tuple) else ()

    def _select_archive_tree_entry(self, entry_index: int) -> Optional[QTreeWidgetItem]:
        if not (0 <= entry_index < len(self.archive_filtered_entries)):
            return None
        find_virtual_item = getattr(self.archive_tree, "find_item_for_entry", None)
        if callable(find_virtual_item):
            return find_virtual_item(entry_index)
        return None

    def _populate_archive_virtual_tree(
        self,
        preferred_path: str = "",
        *,
        on_complete: Optional[Callable[[], None]] = None,
        defer_default_selection: bool = False,
    ) -> None:
        self.archive_browser_row_display_cache.clear()
        self.archive_tree.blockSignals(True)
        try:
            self.archive_tree.setRootIsDecorated(self._archive_tree_view_enabled())
            reset_started_at = time.perf_counter()
            self.archive_tree.set_archive_state(
                self.archive_filtered_entries,
                mode=self._archive_virtual_tree_mode(),
                tree_child_folders=self.archive_tree_child_folders,
                tree_direct_files=self.archive_tree_direct_files,
                tree_folder_entry_indexes=self.archive_tree_folder_entry_indexes,
                category_entry_indexes=self.archive_tree_category_entry_indexes,
                fetch_batch_size=self._archive_virtual_fetch_batch_size(),
            )
            self._log_archive_browser_render_stage("model_reset", reset_started_at)
        finally:
            self.archive_tree.blockSignals(False)
            self.archive_tree.setEnabled(True)
        prewarm_started_at = time.perf_counter()
        self._prewarm_archive_browser_row_display_cache()
        self._log_archive_browser_render_stage("row_prewarm", prewarm_started_at)
        finalize_started_at = time.perf_counter()
        self._finalize_archive_tree_render(
            preferred_path,
            defer_default_selection=defer_default_selection,
        )
        self._log_archive_browser_render_stage("finalize", finalize_started_at)
        self._set_archive_warmup_overlay(False)
        self._mark_archive_browser_render_ready(reason="model_reset", on_complete=on_complete)

    def _finalize_archive_tree_render(
        self,
        preferred_path: str = "",
        *,
        target_item: Optional[QTreeWidgetItem] = None,
        defer_default_selection: bool = False,
    ) -> None:
        total_entries = len(self.archive_entries)
        filtered_entries = len(self.archive_filtered_entries)
        rendered_entries = self.archive_tree.topLevelItemCount()
        render_note = ""
        if not self._archive_tree_view_enabled() and rendered_entries < filtered_entries:
            render_note = f" First {max(0, rendered_entries):,} rows rendered; scroll to fetch more, refine filters, or use Folders view."
        material_catalog_count = len(self._archive_material_catalog_rows())
        catalog_note = (
            f" Scope: {self.archive_active_asset_catalog_scope}."
            if self.archive_active_asset_catalog_scope
            else f" Item Finder: {len(self.archive_item_asset_catalog):,} rows; Material Finder: {material_catalog_count:,} rows."
            if self.archive_item_asset_catalog
            else ""
        )
        self.archive_stats_label.setText(
            f"{filtered_entries:,} shown / {total_entries:,} total entries. DDS in current view: {self.archive_filtered_dds_count:,}.{catalog_note}{render_note}"
        )

        current_item = self.archive_tree.currentItem()
        if target_item is None and current_item is not None and not defer_default_selection:
            target_item = current_item
        if target_item is None:
            preferred_index = -1
            if preferred_path:
                preferred_index = next(
                    (index for index, entry in enumerate(self.archive_filtered_entries) if entry.path == preferred_path),
                    -1,
                )
            target_item = self._select_archive_tree_entry(preferred_index) if preferred_index >= 0 else None
        if target_item is None and not defer_default_selection and self.archive_tree.topLevelItemCount() > 0:
            target_item = self.archive_tree.topLevelItem(0)
        if target_item is not None:
            self.archive_tree.setCurrentItem(target_item)
            target_item.setSelected(True)
        else:
            if defer_default_selection and self.archive_tree.topLevelItemCount() > 0:
                self._clear_archive_preview("Rendering archive browser view... Select a file when the list is ready.")
            else:
                self._clear_archive_preview("No archive entries match the current filter.")
        self._update_archive_selection_state()

    def _populate_archive_tree(
        self,
        preferred_path: str = "",
        *,
        rebuild_index: bool = True,
        on_complete: Optional[Callable[[], None]] = None,
        defer_default_selection: bool = False,
    ) -> None:
        if rebuild_index:
            self.archive_tree_index_ready = False
            if self.archive_entries and self.worker_thread is None:
                self._start_archive_filter_worker(preferred_path)
                return
        if (
            self._archive_category_view_enabled()
            and not self._archive_category_index_ready()
            and self.archive_filtered_entries
            and self.worker_thread is None
        ):
            self._start_archive_filter_worker(preferred_path)
            return
        self._populate_archive_virtual_tree(
            preferred_path,
            on_complete=on_complete,
            defer_default_selection=defer_default_selection,
        )

    def _collect_archive_entries_from_item(
        self,
        item: Optional[QTreeWidgetItem],
        collected_indexes: set[int],
    ) -> None:
        if item is None:
            return
        kind = self._archive_tree_item_kind(item)
        value = self._archive_tree_item_value(item)
        if kind == "file" and isinstance(value, int) and 0 <= value < len(self.archive_filtered_entries):
            collected_indexes.add(value)
            return
        if kind == "folder":
            folder_key = value if isinstance(value, tuple) else ()
            collected_indexes.update(self.archive_tree_folder_entry_indexes.get(folder_key, []))
            return
        if kind == "category":
            category = str(value or "")
            collected_indexes.update(self._archive_category_entry_indexes().get(category, []))
            return
        for child_index in range(item.childCount()):
            self._collect_archive_entries_from_item(item.child(child_index), collected_indexes)

    def _selected_archive_entries(self) -> List[ArchiveEntry]:
        collected_indexes: set[int] = set()
        for item in self.archive_tree.selectedItems():
            self._collect_archive_entries_from_item(item, collected_indexes)
        return [self.archive_filtered_entries[index] for index in sorted(collected_indexes)]

    def _selected_archive_entry_summary(self) -> Tuple[int, bool]:
        selected_items = self.archive_tree.selectedItems()
        if not selected_items:
            return 0, False
        if len(selected_items) == 1:
            item = selected_items[0]
            kind = self._archive_tree_item_kind(item)
            value = self._archive_tree_item_value(item)
            if kind == "file" and isinstance(value, int) and 0 <= value < len(self.archive_filtered_entries):
                return 1, self.archive_filtered_entries[value].extension == ".dds"
            if kind == "folder":
                folder_key = value if isinstance(value, tuple) else ()
                indexes = self.archive_tree_folder_entry_indexes.get(folder_key, [])
                return len(indexes), any(self.archive_filtered_entries[index].extension == ".dds" for index in indexes)
            if kind == "category":
                category = str(value or "")
                indexes = self._archive_category_entry_indexes().get(category, [])
                has_dds = category == "Texture" and self.archive_filtered_dds_count > 0
                if not has_dds and len(indexes) <= self.archive_tree_flat_render_limit:
                    has_dds = any(self.archive_filtered_entries[index].extension == ".dds" for index in indexes)
                return len(indexes), has_dds
        collected_indexes: set[int] = set()
        for item in selected_items:
            self._collect_archive_entries_from_item(item, collected_indexes)
        return (
            len(collected_indexes),
            any(self.archive_filtered_entries[index].extension == ".dds" for index in collected_indexes),
        )

    def _archive_entries_for_workflow_extract(self) -> Tuple[List[ArchiveEntry], bool]:
        selected_entries = self._selected_archive_entries()
        if selected_entries:
            selected_dds = [entry for entry in selected_entries if entry.extension == ".dds"]
            return selected_dds, True
        filtered_dds = [entry for entry in self.archive_filtered_entries if entry.extension == ".dds"]
        return filtered_dds, False

    def _current_archive_entry(self) -> Optional[ArchiveEntry]:
        item = self.archive_tree.currentItem()
        if item is None:
            return None
        kind = self._archive_tree_item_kind(item)
        value = self._archive_tree_item_value(item)
        if kind == "file" and isinstance(value, int) and 0 <= value < len(self.archive_filtered_entries):
            return self.archive_filtered_entries[value]
        return None

    def _current_archive_action_entry(self, action_label: str) -> Optional[ArchiveEntry]:
        entry = self._current_archive_entry()
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message(f"Select an archive file before using {action_label}.", error=True)
            return None
        return entry


__all__ = [
    "ArchiveBrowserController",
    "ArchiveBrowserRowPayloadMixin",
    "ArchiveBrowserTreeControllerMixin",
]
