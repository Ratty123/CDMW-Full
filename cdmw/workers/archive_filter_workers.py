"""Archive browser filter workers."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.archive import (
    ArchiveNameSearchIndex,
    normalize_archive_browser_sort_column,
    normalize_archive_browser_sort_order,
    normalize_archive_extension_filter,
)
from cdmw.core.archive_accelerator import prepare_archive_browser_state_accelerated
from cdmw.domain.archives.filters import (
    archive_filter_text_needs_item_name_search as _archive_filter_text_needs_item_name_search,
    build_archive_category_entry_index,
)
from cdmw.models import ArchiveEntry, RunCancelled


class ArchiveFilterWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        entries_by_extension: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
        entries_by_role: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        archive_name_search_index: Optional[ArchiveNameSearchIndex] = None,
        request_signature: Tuple[object, ...] = (),
        preferred_path: str = "",
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
        item_display_names: Optional[Mapping[str, str]] = None,
        item_exact_display_names: Optional[Mapping[str, str]] = None,
        item_related_display_names: Optional[Mapping[str, str]] = None,
        sort_column: int = -1,
        sort_order: str = "asc",
        native_archive_acceleration: bool = True,
        resource_profile: str = "balanced_60fps",
        record_runtime_event: Optional[Callable[..., object]] = None,
    ) -> None:
        super().__init__()
        # Keep references instead of copying 1M+ archive entries on the UI thread
        # before the worker even starts running.
        self.entries = entries
        self.entries_by_extension = entries_by_extension or {}
        self.entries_by_role = entries_by_role or {}
        self.entries_by_normalized_path = entries_by_normalized_path or {}
        self.entries_by_basename = entries_by_basename or {}
        self.archive_name_search_index = archive_name_search_index
        self.request_signature = tuple(request_signature or ())
        self.preferred_path = preferred_path
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
        self.item_search_aliases = item_search_aliases if item_search_aliases is not None else {}
        self.item_display_names = item_display_names if item_display_names is not None else {}
        self.item_exact_display_names = item_exact_display_names if item_exact_display_names is not None else {}
        self.item_related_display_names = item_related_display_names if item_related_display_names is not None else {}
        self.sort_column = normalize_archive_browser_sort_column(sort_column)
        self.sort_order = normalize_archive_browser_sort_order(sort_order)
        self.native_archive_acceleration = bool(native_archive_acceleration)
        self.resource_profile = str(resource_profile or "balanced_60fps")
        self.record_runtime_event = record_runtime_event
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def _candidate_entries_for_filter(self) -> Tuple[Sequence[ArchiveEntry], str]:
        candidates: List[Tuple[str, Sequence[ArchiveEntry]]] = []
        normalized_extension = normalize_archive_extension_filter(self.extension_filter)
        if normalized_extension and normalized_extension not in {"*", "all", ".*"} and self.entries_by_extension:
            candidates.append((f"extension:{normalized_extension}", self.entries_by_extension.get(normalized_extension, ())))

        normalized_role = str(self.role_filter or "all").strip().lower()
        if normalized_role and normalized_role != "all" and self.entries_by_role:
            candidates.append((f"role:{normalized_role}", self.entries_by_role.get(normalized_role, ())))

        if not candidates:
            return self.entries, "all"
        if len(candidates) == 1:
            return candidates[0][1], candidates[0][0]

        base_label, base_entries = min(candidates, key=lambda item: len(item[1]))
        filtered_entries: List[ArchiveEntry] = list(base_entries)
        for label, entries in candidates:
            if label == base_label:
                continue
            entry_ids = {id(entry) for entry in entries}
            filtered_entries = [entry for entry in filtered_entries if id(entry) in entry_ids]
        labels = "+".join(label for label, _entries in candidates)
        return filtered_entries, labels

    @Slot()
    def run(self) -> None:
        try:
            source_entries, candidate_source = self._candidate_entries_for_filter()
            item_name_search_enabled = _archive_filter_text_needs_item_name_search(self.filter_text)
            item_search_aliases = self.item_search_aliases if item_name_search_enabled else {}
            bounded_item_name_python_scan = bool(
                item_name_search_enabled
                and self.archive_name_search_index is not None
                and item_search_aliases
                and str(self.filter_text or "").strip()
                and len(source_entries) <= 250_000
            )
            archive_name_search_index = (
                None
                if bounded_item_name_python_scan or not item_name_search_enabled
                else self.archive_name_search_index
            )
            browser_state = prepare_archive_browser_state_accelerated(
                source_entries,
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
                archive_entries_by_basename=self.entries_by_basename,
                archive_entries_by_normalized_path=self.entries_by_normalized_path,
                archive_name_search_index=archive_name_search_index,
                build_structure_children=False,
                build_tree_index=self.build_tree_index,
                sort_column=self.sort_column,
                sort_order=self.sort_order,
                item_display_names=self.item_display_names,
                item_exact_display_names=self.item_exact_display_names,
                item_related_display_names=self.item_related_display_names,
                on_progress=self.progress_changed.emit,
                stop_event=self.stop_event,
                native_enabled=self.native_archive_acceleration,
                resource_profile=self.resource_profile,
            )
            accelerator = browser_state.get("archive_accelerator") if isinstance(browser_state, Mapping) else {}
            fallback_reason = ""
            native_used = False
            if isinstance(accelerator, Mapping):
                fallback_reason = str(accelerator.get("fallback_reason", "") or "").strip()
                native_used = bool(accelerator.get("native_used"))
            detail = (
                "Archive filter candidate set | "
                f"source={candidate_source} | "
                f"candidates={len(source_entries):,} / {len(self.entries):,} | "
                f"native_used={native_used}"
            )
            if bounded_item_name_python_scan:
                detail += " | name_search=bounded_python_scan"
            if fallback_reason:
                detail += f" | fallback={fallback_reason}"
            if self.record_runtime_event is not None:
                try:
                    self.record_runtime_event(
                        "archive_filter_candidate_set",
                        candidate_source=candidate_source,
                        candidate_count=len(source_entries),
                        total_entries=len(self.entries),
                        native_used=native_used,
                        fallback_reason=fallback_reason,
                        bounded_item_name_python_scan=bounded_item_name_python_scan,
                    )
                except Exception:
                    pass
            self.log_message.emit(detail)
            if self.build_category_index:
                browser_state["category_entry_indexes"] = build_archive_category_entry_index(
                    browser_state.get("filtered_entries", ()),
                    on_progress=self.progress_changed.emit,
                    stop_event=self.stop_event,
                )
            else:
                browser_state["category_entry_indexes"] = {}
            self.completed.emit(
                {
                    "browser_state": browser_state,
                    "request_signature": self.request_signature,
                    "preferred_path": self.preferred_path,
                }
            )
        except RunCancelled:
            pass
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = ["ArchiveFilterWorker"]
