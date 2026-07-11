from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.domain.research.contracts import (
    MaterialTextureReferenceRow,
    SidecarDiscoveryRow,
)
from cdmw.ui.research.models import item_payload, item_user_role
from cdmw.ui.research.progress_helpers import set_progress_error, set_progress_ready, set_research_progress
from cdmw.ui.research.reference_payload_state import (
    normalize_relative_path,
    reference_resolve_already_running_status_text,
    reference_resolve_complete_state,
    reference_resolve_missing_target_status_text,
    reference_resolve_start_state,
    reference_review_incomplete_status_text,
    reference_review_missing_status_text,
    reference_row_review_enabled,
    reference_target_load_state,
    resolved_extract_request_state,
    review_reference_text_search_payload,
)
from cdmw.ui.research.tree_population import (
    populate_research_reference_tree,
    populate_research_sidecar_tree,
    populate_research_ui_constraint_tree,
)
from cdmw.ui.research.workers import ReferenceResolveWorker

def resolve_references(self) -> None:
    if self.resolve_thread is not None:
        return
    target_path = self.reference_target_edit.text().strip()
    if not target_path:
        self.status_message_requested.emit(reference_resolve_missing_target_status_text(), True)
        return
    worker = ReferenceResolveWorker(
        archive_entries=list(self.get_archive_entries()),
        target_path=target_path,
    )
    thread = QThread(self)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress_changed.connect(self._handle_reference_progress)
    worker.completed.connect(self._handle_reference_complete)
    worker.error.connect(self._handle_reference_error)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(self._cleanup_reference_refs)
    self.resolve_worker = worker
    self.resolve_thread = thread
    self.reference_resolve_button.setEnabled(False)
    self.reference_progress.setRange(0, 0)
    self.reference_progress.setFormat("Working...")
    start_state = reference_resolve_start_state(target_path)
    self.reference_status_label.setText(start_state.status_text)
    self.status_message_requested.emit(start_state.user_status_text, False)
    thread.start()

def focus_references_for_path(self, target_path: str, auto_resolve: bool = True) -> None:
    normalized_path = normalize_relative_path(target_path)
    if not normalized_path:
        self.status_message_requested.emit("Select a DDS archive path first.", True)
        return
    self.tab_widget.setCurrentWidget(self.archive_tab)
    if hasattr(self, "archive_insights_tabs"):
        self.archive_insights_tabs.setCurrentIndex(2)
    self._populate_reference_target(normalized_path)
    if auto_resolve:
        if self.resolve_thread is None:
            self.resolve_references()
        else:
            self.reference_status_label.setText(reference_resolve_already_running_status_text(normalized_path))

def _handle_reference_progress(self, current: int, total: int, detail: str) -> None:
    self.reference_status_label.setText(detail)
    set_research_progress(self.reference_progress, current, total)
    self.status_message_requested.emit(detail, False)

def _handle_reference_complete(self, payload: object) -> None:
    self.reference_payload = payload if isinstance(payload, dict) else {}
    self._populate_reference_rows(self.reference_payload.get("reference_rows", []))
    self._populate_sidecar_rows(self.reference_payload.get("sidecar_rows", []))
    complete_state = reference_resolve_complete_state(self.reference_payload)
    self.reference_status_label.setText(complete_state.status_text)
    set_progress_ready(self.reference_progress)
    self.status_message_requested.emit(complete_state.user_status_text, False)

def _handle_reference_error(self, message: str) -> None:
    self.reference_status_label.setText(message)
    set_progress_error(self.reference_progress)
    self.status_message_requested.emit(message, True)

def _cleanup_reference_refs(self) -> None:
    self.resolve_worker = None
    self.resolve_thread = None
    self.reference_resolve_button.setEnabled(True)

def _populate_reference_rows(self, rows: object) -> None:
    self.reference_review_text_button.setEnabled(False)
    populate_research_reference_tree(self.reference_tree, rows)

def _populate_ui_constraint_rows(self, rows: object) -> None:
    populate_research_ui_constraint_tree(self.ui_constraint_tree, rows)

def _populate_sidecar_rows(self, rows: object) -> None:
    populate_research_sidecar_tree(self.sidecar_tree, rows)

def _handle_reference_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    self.reference_review_text_button.setEnabled(False)
    if current is None:
        return
    row = item_payload(current, MaterialTextureReferenceRow)
    if row is None:
        return
    self.reference_review_text_button.setEnabled(reference_row_review_enabled(row))
    if self._focus_archive_picker_path(row.related_path):
        return
    self._focus_archive_picker_path(row.source_path)

def review_selected_reference_in_text_search(self) -> None:
    item = self.reference_tree.currentItem()
    if item is None:
        self.status_message_requested.emit(reference_review_missing_status_text(), True)
        return
    row = item_user_role(item)
    if not isinstance(row, MaterialTextureReferenceRow):
        self.status_message_requested.emit(reference_review_missing_status_text(), True)
        return
    payload = review_reference_text_search_payload(row)
    if payload is None:
        self.status_message_requested.emit(reference_review_incomplete_status_text(), True)
        return
    source_path, highlight_query = payload
    self.review_reference_in_text_search_requested.emit(source_path, highlight_query)

def _handle_sidecar_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    if current is None:
        return
    row = item_payload(current, SidecarDiscoveryRow)
    if row is None:
        return
    self._focus_archive_picker_path(row.related_path)

def _populate_reference_target(self, target_path: str) -> None:
    target_state = reference_target_load_state(target_path)
    if target_state.should_focus_archive_browser:
        self.focus_archive_browser_requested.emit()
    if target_state.is_error:
        self.status_message_requested.emit(target_state.status_text, True)
        return
    self.reference_target_edit.setText(target_state.normalized_target)
    self.status_message_requested.emit(target_state.status_text, False)

def extract_resolved_related_set(self) -> None:
    extract_state = resolved_extract_request_state(self.reference_payload)
    if extract_state.is_error:
        self.status_message_requested.emit(extract_state.status_text, True)
        return
    self.extract_related_set_requested.emit(extract_state.extract_paths, extract_state.status_text)
