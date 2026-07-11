from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from cdmw.domain.research.contracts import (
    MaterialTextureReferenceRow,
    TextureSetGroup,
)
from cdmw.ui.research.archive_picker_state import cached_archive_snapshot_cache_key
from cdmw.ui.research.analysis_state import (
    compare_path_missing_status_text,
    mip_focus_refresh_pending_state,
)
from cdmw.ui.research.models import (
    build_budget_class_item,
    build_budget_file_item,
    build_budget_group_item,
    build_budget_profile_item,
    build_classification_item,
    build_heatmap_scope_item,
    build_mip_item,
    build_normal_item,
    build_texture_group_item,
    build_ui_constraint_item,
    selected_texture_group_from_items,
)
from cdmw.ui.research.progress_helpers import (
    set_progress_error,
    set_progress_idle,
    set_progress_ready,
    set_research_progress,
)
from cdmw.ui.research.reference_payload_state import (
    current_ui_constraint_related_paths,
    normalize_relative_path,
    ui_constraint_refresh_preserved_status_text,
    ui_constraint_refresh_stale_status_text,
    ui_constraint_scan_complete_state,
    ui_constraint_scan_start_state,
)
from cdmw.ui.research.refresh_population_state import (
    research_refresh_initial_status_text,
    research_refresh_phase_status_text,
    research_refresh_population_rows,
    research_refresh_population_total,
    research_refresh_ready_status_text,
    research_refresh_start_state,
)
from cdmw.ui.research.texture_group_state import (
    texture_group_empty_status_text,
    texture_group_extract_state,
    texture_group_no_available_status_text,
    texture_group_population_selected_status_text,
    texture_group_selected_status_text,
)
from cdmw.ui.research.workers import ResearchRefreshWorker, UIConstraintRefreshWorker

def refresh_research(self) -> None:
    if self.refresh_thread is not None:
        return
    self.mark_archive_picker_dirty()
    archive_entries = self.get_archive_entries()
    filtered_entries = self.get_filtered_archive_entries()
    use_full_archive_for_focus = (
        self._classification_review_focus_uses_full_archive
        and bool(self.pending_classification_review_focus_keys)
    )
    source_entries = archive_entries if use_full_archive_for_focus else (filtered_entries or archive_entries)
    working_entries = source_entries
    full_archive_key = cached_archive_snapshot_cache_key(archive_entries, self._archive_snapshot_key_cache)
    original_root = Path(self.get_original_root()).expanduser() if self.get_original_root().strip() else None
    output_root = Path(self.get_output_root()).expanduser() if self.get_output_root().strip() else None
    texconv_path = Path(self.get_texconv_path()).expanduser() if self.get_texconv_path().strip() else None
    working_archive_key = cached_archive_snapshot_cache_key(working_entries, self._archive_snapshot_key_cache)
    archive_snapshot_cache_key = f"{working_archive_key}|sidecars:{full_archive_key}"
    cached_archive_snapshot = self.archive_snapshot_cache.get(archive_snapshot_cache_key)
    ui_constraint_related_paths = ()
    if self._ui_constraint_scan_archive_key and self._ui_constraint_scan_archive_key == full_archive_key:
        ui_constraint_related_paths = tuple(current_ui_constraint_related_paths(self.research_payload))

    worker = ResearchRefreshWorker(
        archive_entries=archive_entries,
        filtered_archive_entries=filtered_entries,
        sidecar_source_entries=archive_entries,
        original_root=original_root,
        output_root=output_root,
        texconv_path=texconv_path,
        app_config=self.get_app_config(),
        archive_snapshot_payload=cached_archive_snapshot,
        ui_constraint_related_paths=ui_constraint_related_paths,
    )
    thread = QThread(self)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress_changed.connect(self._handle_refresh_progress)
    worker.completed.connect(self._handle_refresh_complete)
    worker.error.connect(self._handle_refresh_error)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(self._cleanup_refresh_refs)
    self.refresh_worker = worker
    self.refresh_thread = thread
    self.pending_archive_snapshot_cache_key = archive_snapshot_cache_key
    self._pending_refresh_full_archive_key = full_archive_key
    self._pending_research_view_entry_count = len(working_entries)
    self._pending_research_full_archive_entry_count = len(archive_entries)
    self._pending_research_uses_full_archive_view = use_full_archive_for_focus
    self.refresh_button.setEnabled(False)
    self.refresh_progress.setRange(0, 0)
    self.refresh_progress.setFormat("Working...")
    start_state = research_refresh_start_state(
        uses_full_archive_view=use_full_archive_for_focus,
        archive_entry_count=len(archive_entries),
        view_entry_count=len(working_entries),
        has_cached_archive_snapshot=bool(cached_archive_snapshot),
    )
    self.refresh_status_label.setText(start_state.status_text)
    self.status_message_requested.emit(start_state.user_status_text, False)
    thread.start()

def refresh_ui_constraints(self) -> None:
    if self.ui_constraint_thread is not None:
        return
    archive_entries = self.get_archive_entries()
    archive_key = cached_archive_snapshot_cache_key(archive_entries, self._archive_snapshot_key_cache)
    worker = UIConstraintRefreshWorker(archive_entries=archive_entries)
    thread = QThread(self)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress_changed.connect(self._handle_ui_constraint_progress)
    worker.completed.connect(self._handle_ui_constraint_complete)
    worker.error.connect(self._handle_ui_constraint_error)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(self._cleanup_ui_constraint_refs)
    self.ui_constraint_worker = worker
    self.ui_constraint_thread = thread
    self._pending_ui_constraint_archive_key = archive_key
    self.ui_constraint_refresh_button.setEnabled(False)
    self.ui_constraint_progress.setRange(0, 0)
    self.ui_constraint_progress.setFormat("Working...")
    start_state = ui_constraint_scan_start_state()
    self.ui_constraint_status_label.setText(start_state.status_text)
    self.status_message_requested.emit(start_state.user_status_text, False)
    thread.start()

def focus_texture_analysis_for_compare_path(
    self,
    relative_path: str,
    *,
    refresh_snapshot: bool = True,
) -> None:
    normalized_path = normalize_relative_path(relative_path)
    if not normalized_path:
        self.status_message_requested.emit(compare_path_missing_status_text(), True)
        return
    self.pending_mip_focus_relative_path = normalized_path
    self.tab_widget.setCurrentWidget(self.texture_tab)
    self.right_panel_stack.setCurrentWidget(self.analysis_detail_group)
    if refresh_snapshot:
        if self.refresh_thread is None:
            self.refresh_research()
        else:
            pending_state = mip_focus_refresh_pending_state(normalized_path)
            self.refresh_status_label.setText(pending_state.status_text)
            self.status_message_requested.emit(pending_state.user_status_text, False)
        return
    self._focus_pending_mip_row()

def _handle_refresh_progress(self, current: int, total: int, detail: str) -> None:
    self.refresh_status_label.setText(detail)
    set_research_progress(self.refresh_progress, current, total)
    self.status_message_requested.emit(detail, False)

def _handle_refresh_complete(self, payload: object) -> None:
    previous_ui_rows = self.research_payload.get("ui_constraint_rows", []) if isinstance(self.research_payload, dict) else []
    preserve_ui_rows = (
        self._ui_constraint_scan_archive_key
        and self._pending_refresh_full_archive_key
        and self._ui_constraint_scan_archive_key == self._pending_refresh_full_archive_key
        and isinstance(previous_ui_rows, list)
    )
    self.research_payload = payload if isinstance(payload, dict) else {}
    if preserve_ui_rows:
        self.research_payload["ui_constraint_rows"] = previous_ui_rows
        self.ui_constraint_status_label.setText(ui_constraint_refresh_preserved_status_text())
        set_progress_ready(self.ui_constraint_progress)
    else:
        self.research_payload["ui_constraint_rows"] = []
        if self._ui_constraint_scan_archive_key != self._pending_refresh_full_archive_key:
            self._ui_constraint_scan_archive_key = ""
        self.ui_constraint_status_label.setText(ui_constraint_refresh_stale_status_text())
        set_progress_idle(self.ui_constraint_progress)
    if self.pending_archive_snapshot_cache_key and self.research_payload:
        self.archive_snapshot_cache[self.pending_archive_snapshot_cache_key] = {
            "classification_rows": self.research_payload.get("classification_rows", []),
            "texture_groups": self.research_payload.get("texture_groups", []),
            "heatmap_rows": self.research_payload.get("heatmap_rows", []),
            "unknown_resolver_groups": self.research_payload.get("unknown_resolver_groups", []),
            "classification_review_groups": self.research_payload.get("classification_review_groups", []),
        }
    self._begin_refresh_population()

def _handle_refresh_error(self, message: str) -> None:
    self.pending_mip_focus_relative_path = ""
    self.refresh_status_label.setText(message)
    set_progress_error(self.refresh_progress)
    self.status_message_requested.emit(message, True)

def _cleanup_refresh_refs(self) -> None:
    self.refresh_worker = None
    self.refresh_thread = None
    self.pending_archive_snapshot_cache_key = ""
    self._pending_refresh_full_archive_key = ""
    self.refresh_button.setEnabled(True)

def _handle_ui_constraint_progress(self, current: int, total: int, detail: str) -> None:
    self.ui_constraint_status_label.setText(detail)
    set_research_progress(self.ui_constraint_progress, current, total)
    self.status_message_requested.emit(detail, False)

def _handle_ui_constraint_complete(self, rows: object) -> None:
    ui_rows = [row for row in rows if isinstance(row, MaterialTextureReferenceRow)] if isinstance(rows, list) else []
    self.research_payload["ui_constraint_rows"] = ui_rows
    self._ui_constraint_scan_archive_key = self._pending_ui_constraint_archive_key
    self._populate_ui_constraint_rows(ui_rows)
    complete_state = ui_constraint_scan_complete_state(len(ui_rows))
    self.ui_constraint_status_label.setText(complete_state.status_text)
    set_progress_ready(self.ui_constraint_progress)
    self._refresh_texture_analysis_summary()
    self.status_message_requested.emit(complete_state.user_status_text, False)

def _handle_ui_constraint_error(self, message: str) -> None:
    self.ui_constraint_status_label.setText(message)
    set_progress_error(self.ui_constraint_progress)
    self.status_message_requested.emit(message, True)

def _cleanup_ui_constraint_refs(self) -> None:
    self.ui_constraint_worker = None
    self.ui_constraint_thread = None
    self._pending_ui_constraint_archive_key = ""
    self.ui_constraint_refresh_button.setEnabled(True)

def _stop_refresh_population(self) -> None:
    self._refresh_population_timer.stop()
    self._refresh_population_phases = []
    self._refresh_population_phase_index = 0
    self._refresh_population_total = 0
    self._refresh_population_processed = 0

def _begin_refresh_population(self) -> None:
    self._stop_refresh_population()
    self._refresh_unknown_resolver_view()
    population_rows = research_refresh_population_rows(self.research_payload)

    self.texture_group_tree.clear()
    self.classifier_tree.clear()
    self.heatmap_tree.clear()
    self.mip_tree.clear()
    self.normal_tree.clear()
    self.ui_constraint_tree.clear()
    self.budget_file_tree.clear()
    self.budget_class_tree.clear()
    self.budget_group_tree.clear()
    self.budget_profile_tree.clear()

    self._refresh_population_phases = [
        {
            "name": "texture groups",
            "items": population_rows.texture_groups,
            "cursor": 0,
            "tree": self.texture_group_tree,
            "build": build_texture_group_item,
            "finalize": self._finalize_texture_group_population,
            "batch_size": self.REFRESH_GROUP_BATCH_SIZE,
        },
        {
            "name": "classifications",
            "items": population_rows.classification_rows,
            "cursor": 0,
            "tree": self.classifier_tree,
            "build": build_classification_item,
            "finalize": self._finalize_classification_population,
            "batch_size": self.REFRESH_POPULATION_BATCH_SIZE,
        },
        {
            "name": "usage heatmap",
            "items": population_rows.heatmap_groups,
            "cursor": 0,
            "tree": self.heatmap_tree,
            "build": build_heatmap_scope_item,
            "finalize": self._finalize_heatmap_population,
            "batch_size": self.REFRESH_GROUP_BATCH_SIZE,
        },
        {
            "name": "mip analysis",
            "items": population_rows.mip_rows,
            "cursor": 0,
            "tree": self.mip_tree,
            "build": build_mip_item,
            "finalize": self._finalize_mip_population,
            "batch_size": self.REFRESH_POPULATION_BATCH_SIZE,
        },
        {
            "name": "normal validation",
            "items": population_rows.normal_rows,
            "cursor": 0,
            "tree": self.normal_tree,
            "build": build_normal_item,
            "finalize": self._finalize_normal_population,
            "batch_size": self.REFRESH_POPULATION_BATCH_SIZE,
        },
        {
            "name": "ui constraints",
            "items": population_rows.ui_constraint_rows,
            "cursor": 0,
            "tree": self.ui_constraint_tree,
            "build": build_ui_constraint_item,
            "finalize": self._finalize_ui_constraint_population,
            "batch_size": self.REFRESH_POPULATION_BATCH_SIZE,
        },
        {
            "name": "budget files",
            "items": population_rows.budget_rows,
            "cursor": 0,
            "tree": self.budget_file_tree,
            "build": build_budget_file_item,
            "finalize": self._finalize_budget_population,
            "batch_size": self.REFRESH_POPULATION_BATCH_SIZE,
        },
        {
            "name": "budget classes",
            "items": population_rows.budget_class_rows,
            "cursor": 0,
            "tree": self.budget_class_tree,
            "build": build_budget_class_item,
            "finalize": None,
            "batch_size": self.REFRESH_POPULATION_BATCH_SIZE,
        },
        {
            "name": "budget groups",
            "items": population_rows.budget_group_rows,
            "cursor": 0,
            "tree": self.budget_group_tree,
            "build": build_budget_group_item,
            "finalize": None,
            "batch_size": self.REFRESH_POPULATION_BATCH_SIZE,
        },
        {
            "name": "budget profile",
            "items": population_rows.budget_profile_rows,
            "cursor": 0,
            "tree": self.budget_profile_tree,
            "build": build_budget_profile_item,
            "finalize": None,
            "batch_size": 1,
        },
    ]
    self._refresh_population_total = research_refresh_population_total(population_rows)
    self._refresh_population_processed = 0
    if self._refresh_population_total <= 0:
        self._finish_refresh_population()
        return
    self.refresh_status_label.setText(
        research_refresh_initial_status_text(
            uses_full_archive_view=self._pending_research_uses_full_archive_view,
            total=self._refresh_population_total,
        )
    )
    self.refresh_progress.setRange(0, self._refresh_population_total)
    self.refresh_progress.setValue(0)
    self.refresh_progress.setFormat(f"0 / {self._refresh_population_total}")
    self._refresh_population_timer.start()

def _flush_refresh_population_batch(self) -> None:
    while self._refresh_population_phase_index < len(self._refresh_population_phases):
        phase = self._refresh_population_phases[self._refresh_population_phase_index]
        items = phase["items"]
        cursor = int(phase.get("cursor", 0))
        if cursor >= len(items):
            finalize = phase.get("finalize")
            if callable(finalize):
                finalize()
            self._refresh_population_phase_index += 1
            continue
        batch_size = max(1, int(phase.get("batch_size", self.REFRESH_POPULATION_BATCH_SIZE)))
        end = min(cursor + batch_size, len(items))
        build = phase.get("build")
        tree = phase.get("tree")
        if not callable(build) or not isinstance(tree, QTreeWidget):
            self._refresh_population_phase_index += 1
            continue
        built = [build(item) for item in items[cursor:end]]
        tree.setUpdatesEnabled(False)
        tree.addTopLevelItems(built)
        tree.setUpdatesEnabled(True)
        phase["cursor"] = end
        self._refresh_population_processed += end - cursor
        self.refresh_status_label.setText(
            research_refresh_phase_status_text(
                phase_name=phase.get("name", "research"),
                processed=self._refresh_population_processed,
                total=self._refresh_population_total,
            )
        )
        self.refresh_progress.setRange(0, self._refresh_population_total)
        self.refresh_progress.setValue(self._refresh_population_processed)
        self.refresh_progress.setFormat(f"{self._refresh_population_processed} / {self._refresh_population_total}")
        if end < len(items):
            self._refresh_population_timer.start()
            return
    self._finish_refresh_population()

def _finalize_texture_group_population(self) -> None:
    first_group_item = self.texture_group_tree.topLevelItem(0)
    if first_group_item is not None:
        self.texture_group_tree.setCurrentItem(first_group_item)
        self.texture_group_status_label.setText(
            texture_group_population_selected_status_text(first_group_item.text(0))
        )
        self.texture_group_extract_button.setEnabled(True)
    else:
        self.texture_group_status_label.setText(texture_group_no_available_status_text())
        self.texture_group_extract_button.setEnabled(False)

def _finalize_classification_population(self) -> None:
    return

def _finalize_heatmap_population(self) -> None:
    return

def _finalize_mip_population(self) -> None:
    if self.mip_tree.topLevelItemCount() > 0:
        first = self.mip_tree.topLevelItem(0)
        if first is not None:
            self.mip_tree.setCurrentItem(first)

def _finalize_normal_population(self) -> None:
    if self.normal_tree.topLevelItemCount() > 0 and self.mip_tree.topLevelItemCount() == 0:
        first = self.normal_tree.topLevelItem(0)
        if first is not None:
            self.normal_tree.setCurrentItem(first)
    if self.normal_tree.topLevelItemCount() == 0 and self.mip_tree.topLevelItemCount() == 0:
        self.analysis_detail_label.setText(
            "Select a row in Texture Analysis to see where the result came from and what it means."
        )
        self.analysis_detail_edit.clear()

def _finalize_ui_constraint_population(self) -> None:
    if self.ui_constraint_tree.topLevelItemCount() > 0:
        first = self.ui_constraint_tree.topLevelItem(0)
        if first is not None:
            self.ui_constraint_tree.setCurrentItem(first)

def _finalize_budget_population(self) -> None:
    if self.budget_file_tree.topLevelItemCount() > 0:
        first = self.budget_file_tree.topLevelItem(0)
        if first is not None:
            self.budget_file_tree.setCurrentItem(first)

def _finish_refresh_population(self) -> None:
    self._stop_refresh_population()
    self._refresh_texture_analysis_summary()
    self.refresh_status_label.setText(
        research_refresh_ready_status_text(
            uses_full_archive_view=self._pending_research_uses_full_archive_view,
            archive_entry_count=self._pending_research_full_archive_entry_count,
            view_entry_count=self._pending_research_view_entry_count,
        )
    )
    set_progress_ready(self.refresh_progress)
    self.status_message_requested.emit(self.refresh_status_label.text(), False)
    self._focus_pending_mip_row()

def _populate_texture_groups(self, groups: object) -> None:
    first_group_item = populate_research_texture_group_tree(self.texture_group_tree, groups)
    if first_group_item is not None:
        self.texture_group_status_label.setText(
            texture_group_population_selected_status_text(first_group_item.text(0))
        )
        self.texture_group_extract_button.setEnabled(True)
    else:
        self.texture_group_status_label.setText(texture_group_no_available_status_text())
        self.texture_group_extract_button.setEnabled(False)

def _selected_texture_group(self) -> Optional[TextureSetGroup]:
    candidate_items = list(self.texture_group_tree.selectedItems())
    current = self.texture_group_tree.currentItem()
    if current is not None and current not in candidate_items:
        candidate_items.insert(0, current)
    return selected_texture_group_from_items(
        candidate_items,
        self.research_payload.get("texture_groups", []),
    )

def _handle_texture_group_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    group = self._selected_texture_group()
    if group is None:
        self.texture_group_status_label.setText(texture_group_empty_status_text(has_current_item=current is not None))
        self.texture_group_extract_button.setEnabled(False)
        return
    self.texture_group_status_label.setText(
        texture_group_selected_status_text(
            display_name=group.display_name,
            member_count=group.member_count,
            package_count=len(group.package_labels),
        )
    )
    self.texture_group_extract_button.setEnabled(True)

def extract_selected_group(self) -> None:
    extract_state = texture_group_extract_state(
        self.research_payload.get("texture_groups", []),
        self._selected_texture_group(),
    )
    if extract_state.is_error:
        self.status_message_requested.emit(extract_state.status_text, True)
        return
    self.extract_related_set_requested.emit(extract_state.paths, extract_state.status_text)
