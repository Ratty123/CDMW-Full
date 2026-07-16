from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.services.texture_workflow_service import (
    remove_registered_texture_classifications,
    set_registered_texture_classifications,
)
from cdmw.domain.research.contracts import (
    UnknownResolverGroup,
    UnknownResolverMember,
)
from cdmw.services.research_service import research_service
from cdmw.ui.research.archive_picker_state import normalize_archive_path
from cdmw.ui.research.classification_review_state import (
    can_accept_unknown_current_role,
    classification_review_focus_candidates,
    is_unknown_member_classifiable,
    preferred_unknown_choice_for_member,
    primary_unknown_member,
    semantic_subtype_for_unknown_member,
    unknown_label_choice_index,
    unknown_label_tuple,
    unknown_member_local_text,
    unknown_no_current_family_unknown_status_text,
    unknown_no_current_role_status_text,
    unknown_group_classification_text,
    unknown_group_display_name,
    unknown_group_empty_status_text,
    unknown_group_filter_progress_status_text,
    unknown_group_matches_filters,
    unknown_group_package_text,
    unknown_group_ready_status_text,
    unknown_no_selected_families_unknown_status_text,
    unknown_group_target_paths,
    unknown_removed_current_file_status_text,
    unknown_removed_family_status_text,
    unknown_removed_selected_families_status_text,
    unknown_resolver_control_state,
    unknown_saved_current_file_status_text,
    unknown_saved_current_role_status_text,
    unknown_saved_family_status_text,
    unknown_saved_selected_families_status_text,
    unknown_select_dds_status_text,
    unknown_select_families_status_text,
    unknown_select_family_status_text,
)
from cdmw.ui.research.models import (
    build_unknown_group_item,
    build_unknown_member_item,
    current_unknown_group_from_item,
    item_payload,
    selected_unknown_groups_from_items,
)

def _current_unknown_member(self) -> Optional[UnknownResolverMember]:
    value = item_payload(self.unknown_member_tree.currentItem(), UnknownResolverMember)
    if value is not None:
        return value
    return primary_unknown_member(current_unknown_group_from_item(self.unknown_group_tree.currentItem()))

def _update_unknown_member_group_visibility(self, group: Optional[UnknownResolverGroup]) -> None:
    self.unknown_members_group.setVisible(bool(group is not None and group.total_members > 1))

def _current_unknown_classifiable_member(self) -> Optional[UnknownResolverMember]:
    member = self._current_unknown_member()
    if not is_unknown_member_classifiable(member):
        return None
    return member

def _handle_unknown_group_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    self._ensure_archive_picker_ready()
    group = current_unknown_group_from_item(current)
    if group is None:
        self.unknown_member_tree.clear()
        self._update_unknown_member_group_visibility(None)
        self.unknown_detail_edit.clear()
        self._clear_unknown_preview("Select a DDS review item to preview it here.")
        self._update_unknown_resolver_controls()
        return
    self._populating_unknown_resolver_controls = True
    try:
        self.unknown_member_tree.blockSignals(True)
        self.unknown_member_tree.clear()
        self._update_unknown_member_group_visibility(group)
        focused_member_item: Optional[QTreeWidgetItem] = None
        focused_member: Optional[UnknownResolverMember] = None
        for member in group.members:
            item = build_unknown_member_item(member, local_text=unknown_member_local_text(member))
            self.unknown_member_tree.addTopLevelItem(item)
            if (
                focused_member_item is None
                and self.pending_classification_review_focus_keys
                and classification_review_focus_candidates(member.path) & self.pending_classification_review_focus_keys
            ):
                focused_member_item = item
                focused_member = member
        suggested_choice = preferred_unknown_choice_for_member(
            focused_member or primary_unknown_member(group),
            group,
        )
        self._select_unknown_label_choice(suggested_choice)
    finally:
        self.unknown_member_tree.blockSignals(False)
        self._populating_unknown_resolver_controls = False
    if self.unknown_member_tree.topLevelItemCount() > 0:
        first_member = focused_member_item or self.unknown_member_tree.topLevelItem(0)
        if first_member is not None:
            self.unknown_member_tree.setCurrentItem(first_member)
    else:
        self.unknown_detail_edit.setPlainText("No reviewable members found in this unknown family.")
    self._update_unknown_resolver_controls()

def _handle_unknown_group_item_selection_changed(self) -> None:
    self._update_unknown_resolver_controls()

def _handle_unknown_member_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    self._ensure_archive_picker_ready()
    member = item_payload(current, UnknownResolverMember)
    group = current_unknown_group_from_item(self.unknown_group_tree.currentItem())
    if member is None or group is None:
        self.unknown_detail_edit.clear()
        self._clear_unknown_preview("Select a DDS review item to preview it here.")
        self._update_unknown_resolver_controls()
        return
    selected_entry = self._archive_picker_entry_for_path(member.path)
    selected_entries_by_path = (
        {normalize_archive_path(member.path): selected_entry}
        if selected_entry is not None
        else {}
    )
    detail_text = research_service.classification.build_detail(
        group,
        member.path,
        entries_by_path=selected_entries_by_path,
    )
    self.unknown_detail_edit.setPlainText(detail_text)
    self._select_unknown_label_choice(preferred_unknown_choice_for_member(member, group))
    self._render_unknown_preview_for_member(member)
    self._focus_archive_picker_path(member.path)
    self._update_unknown_resolver_controls()

def _preview_selected_unknown_member(self) -> None:
    member = self._current_unknown_member()
    if member is None:
        return
    self._render_unknown_preview_for_member(member)
    self._focus_archive_picker_path(member.path)

def _select_all_unknown_groups(self) -> None:
    if self.unknown_group_tree.topLevelItemCount() <= 0:
        return
    current = self.unknown_group_tree.currentItem()
    if current is None:
        current = self.unknown_group_tree.topLevelItem(0)
    self.unknown_group_tree.blockSignals(True)
    try:
        self.unknown_group_tree.selectAll()
        if current is not None:
            self.unknown_group_tree.setCurrentItem(current)
    finally:
        self.unknown_group_tree.blockSignals(False)
    if current is not None:
        self._handle_unknown_group_selection_changed(current, None)
    self._update_unknown_resolver_controls()

def _clear_unknown_group_selection(self) -> None:
    self.unknown_group_tree.blockSignals(True)
    try:
        self.unknown_group_tree.clearSelection()
    finally:
        self.unknown_group_tree.blockSignals(False)
    self._update_unknown_resolver_controls()

def _selected_unknown_label(self) -> tuple[str, str, str]:
    return unknown_label_tuple(self.unknown_label_combo.currentData())

def _select_unknown_label_choice(self, choice_key: str) -> None:
    combo_index = unknown_label_choice_index(
        [self.unknown_label_combo.itemData(index) for index in range(self.unknown_label_combo.count())],
        choice_key,
    )
    if combo_index >= 0:
        self.unknown_label_combo.setCurrentIndex(combo_index)

def _accept_unknown_current_role(self) -> None:
    member = self._current_unknown_classifiable_member()
    if member is None:
        self.status_message_requested.emit(unknown_select_dds_status_text(), True)
        return
    texture_type = str(member.current_kind or "").strip().lower()
    if not can_accept_unknown_current_role(member):
        self.status_message_requested.emit(unknown_no_current_role_status_text(), True)
        return
    semantic_subtype = semantic_subtype_for_unknown_member(member)
    updated = set_registered_texture_classifications(
        [member.path],
        texture_type,
        semantic_subtype,
        source="unknown_resolver",
        note=f"Accepted current Research role for file {member.path}",
    )
    if updated:
        self.archive_snapshot_cache.clear()
        self.status_message_requested.emit(
            unknown_saved_current_role_status_text(texture_type, semantic_subtype),
            False,
        )
        self.focus_classification_review_for_paths(
            [member.path],
            include_classified=True,
            refresh_if_needed=True,
        )

def _apply_unknown_current_file_label(self) -> None:
    member = self._current_unknown_classifiable_member()
    if member is None:
        self.status_message_requested.emit(unknown_select_dds_status_text(), True)
        return
    _choice_key, texture_type, semantic_subtype = self._selected_unknown_label()
    updated = set_registered_texture_classifications(
        [member.path],
        texture_type,
        semantic_subtype,
        source="unknown_resolver",
        note=f"Approved from Research -> Classification Review for file {member.path}",
    )
    if updated:
        self.archive_snapshot_cache.clear()
        self.status_message_requested.emit(
            unknown_saved_current_file_status_text(texture_type, semantic_subtype),
            False,
        )
        self.focus_classification_review_for_paths(
            [member.path],
            include_classified=self.unknown_show_classified_checkbox.isChecked(),
            refresh_if_needed=True,
        )

def _apply_unknown_selected_file_label(self) -> None:
    group = current_unknown_group_from_item(self.unknown_group_tree.currentItem())
    if group is None:
        self.status_message_requested.emit(unknown_select_family_status_text(), True)
        return
    target_paths = unknown_group_target_paths([group], unknown_only=True)
    if not target_paths:
        self.status_message_requested.emit(unknown_no_current_family_unknown_status_text(), True)
        return
    _choice_key, texture_type, semantic_subtype = self._selected_unknown_label()
    updated = set_registered_texture_classifications(
        target_paths,
        texture_type,
        semantic_subtype,
        source="unknown_resolver",
        note=f"Approved from Research -> Classification Review for family {group.group_key}",
    )
    if updated:
        self.archive_snapshot_cache.clear()
        self.status_message_requested.emit(
            unknown_saved_family_status_text(texture_type, semantic_subtype, updated),
            False,
        )
        self.focus_classification_review_for_paths(
            unknown_group_target_paths([group], unknown_only=False),
            include_classified=self.unknown_show_classified_checkbox.isChecked(),
            refresh_if_needed=True,
        )

def _apply_unknown_group_label(self) -> None:
    groups = selected_unknown_groups_from_items(self.unknown_group_tree.selectedItems())
    if not groups:
        self.status_message_requested.emit(unknown_select_families_status_text(), True)
        return
    target_paths = unknown_group_target_paths(groups, unknown_only=True)
    if not target_paths:
        self.status_message_requested.emit(unknown_no_selected_families_unknown_status_text(), True)
        return
    _choice_key, texture_type, semantic_subtype = self._selected_unknown_label()
    updated = set_registered_texture_classifications(
        target_paths,
        texture_type,
        semantic_subtype,
        source="unknown_resolver",
        note="Approved from Research -> Classification Review for selected families",
    )
    if updated:
        self.archive_snapshot_cache.clear()
        self.status_message_requested.emit(
            unknown_saved_selected_families_status_text(texture_type, semantic_subtype, updated, len(groups)),
            False,
        )
        self.focus_classification_review_for_paths(
            unknown_group_target_paths(groups, unknown_only=False),
            include_classified=self.unknown_show_classified_checkbox.isChecked(),
            refresh_if_needed=True,
        )

def _clear_unknown_current_file_label(self) -> None:
    member = self._current_unknown_classifiable_member()
    if member is None:
        self.status_message_requested.emit(unknown_select_dds_status_text(), True)
        return
    removed = remove_registered_texture_classifications([member.path])
    if removed:
        self.archive_snapshot_cache.clear()
        self.status_message_requested.emit(unknown_removed_current_file_status_text(), False)
        self.focus_classification_review_for_paths(
            [member.path],
            include_classified=True,
            refresh_if_needed=True,
        )

def _clear_unknown_selected_file_label(self) -> None:
    group = current_unknown_group_from_item(self.unknown_group_tree.currentItem())
    if group is None:
        self.status_message_requested.emit(unknown_select_family_status_text(), True)
        return
    removed = remove_registered_texture_classifications(
        unknown_group_target_paths([group], unknown_only=False)
    )
    if removed:
        self.archive_snapshot_cache.clear()
        self.status_message_requested.emit(
            unknown_removed_family_status_text(removed),
            False,
        )
        self.focus_classification_review_for_paths(
            unknown_group_target_paths([group], unknown_only=False),
            include_classified=True,
            refresh_if_needed=True,
        )

def _clear_unknown_group_label(self) -> None:
    groups = selected_unknown_groups_from_items(self.unknown_group_tree.selectedItems())
    if not groups:
        self.status_message_requested.emit(unknown_select_families_status_text(), True)
        return
    target_paths = unknown_group_target_paths(groups, unknown_only=False)
    removed = remove_registered_texture_classifications(target_paths)
    if removed:
        self.archive_snapshot_cache.clear()
        self.status_message_requested.emit(
            unknown_removed_selected_families_status_text(removed, len(groups)),
            False,
        )
        self.focus_classification_review_for_paths(
            unknown_group_target_paths(groups, unknown_only=False),
            include_classified=True,
            refresh_if_needed=True,
        )

def _update_unknown_resolver_controls(self) -> None:
    controls = unknown_resolver_control_state(
        has_group=current_unknown_group_from_item(self.unknown_group_tree.currentItem()) is not None,
        has_selected_groups=bool(selected_unknown_groups_from_items(self.unknown_group_tree.selectedItems())),
        current_member=self._current_unknown_classifiable_member(),
        has_rows=self.unknown_group_tree.topLevelItemCount() > 0,
    )
    self.unknown_label_combo.setEnabled(controls.label_combo_enabled)
    self.unknown_preview_button.setEnabled(controls.preview_button_enabled)
    self.unknown_accept_current_role_button.setEnabled(controls.accept_current_role_enabled)
    self.unknown_apply_current_file_button.setEnabled(controls.apply_current_file_enabled)
    self.unknown_apply_selected_button.setEnabled(controls.apply_selected_enabled)
    self.unknown_apply_group_button.setEnabled(controls.apply_group_enabled)
    self.unknown_clear_current_file_button.setEnabled(controls.clear_current_file_enabled)
    self.unknown_clear_selected_button.setEnabled(controls.clear_selected_enabled)
    self.unknown_clear_group_button.setEnabled(controls.clear_group_enabled)
    self.unknown_select_all_button.setEnabled(controls.select_all_enabled)
    self.unknown_clear_family_selection_button.setEnabled(controls.clear_family_selection_enabled)


def _current_unknown_resolver_groups(self) -> object:
    if self.unknown_show_classified_checkbox.isChecked():
        return self.research_payload.get("classification_review_groups", [])
    return self.research_payload.get("unknown_resolver_groups", [])

def focus_classification_review_for_paths(
    self,
    paths: Sequence[str],
    *,
    include_classified: bool = False,
    refresh_if_needed: bool = False,
) -> None:
    focus_keys: set[str] = set()
    for path_value in paths:
        focus_keys.update(classification_review_focus_candidates(path_value))
    self.pending_classification_review_focus_keys = focus_keys
    self._classification_review_focus_uses_full_archive = bool(focus_keys)
    self.unknown_name_filter_edit.blockSignals(True)
    self.unknown_package_filter_edit.blockSignals(True)
    try:
        self.unknown_name_filter_edit.clear()
        self.unknown_package_filter_edit.clear()
    finally:
        self.unknown_name_filter_edit.blockSignals(False)
        self.unknown_package_filter_edit.blockSignals(False)
    self.unknown_show_classified_checkbox.setChecked(include_classified)
    if focus_keys:
        self.unknown_resolver_status_label.setText(unknown_group_focus_status_text())
    self.tab_widget.setCurrentWidget(self.archive_tab)
    self.archive_insights_tabs.setCurrentWidget(self.classification_review_tab)
    if refresh_if_needed or not self.research_payload:
        self.refresh_research()
    else:
        self._refresh_unknown_resolver_view()

def _handle_unknown_show_classified_toggled(self, _checked: bool) -> None:
    self.unknown_resolver_status_label.setText("Refreshing classification review for the current Research snapshot...")
    QTimer.singleShot(0, self._refresh_unknown_resolver_view)

def _handle_unknown_name_filter_changed(self, _text: str) -> None:
    self._clear_pending_classification_review_focus()
    self._refresh_unknown_resolver_view()

def _handle_unknown_package_filter_changed(self, _text: str) -> None:
    self._clear_pending_classification_review_focus()
    self._refresh_unknown_resolver_view()

def _refresh_unknown_resolver_view(self) -> None:
    self._populate_unknown_resolver(self._current_unknown_resolver_groups())

def _populate_unknown_resolver(self, groups: object) -> None:
    previous_group = current_unknown_group_from_item(self.unknown_group_tree.currentItem())
    previous_group_key = previous_group.group_key if previous_group is not None else ""
    self._unknown_population_timer.stop()
    self.unknown_group_tree.blockSignals(True)
    self.unknown_group_tree.setUpdatesEnabled(False)
    try:
        self.unknown_group_tree.clear()
    finally:
        self.unknown_group_tree.setUpdatesEnabled(True)
        self.unknown_group_tree.blockSignals(False)
    self._pending_unknown_source_groups = [
        group
        for group in groups
        if isinstance(group, UnknownResolverGroup)
    ]
    self._pending_unknown_groups = []
    self._pending_unknown_previous_group_key = previous_group_key
    self._pending_unknown_showing_classified = self.unknown_show_classified_checkbox.isChecked()
    self._pending_unknown_population_total = 0
    self._pending_unknown_scanned_total = len(self._pending_unknown_source_groups)
    if not self._pending_unknown_source_groups:
        self._finalize_unknown_group_population()
        return
    self.unknown_resolver_status_label.setText(
        unknown_group_filter_progress_status_text(
            scanned=0,
            total=self._pending_unknown_scanned_total,
            matched=0,
        )
    )
    self._update_unknown_resolver_controls()
    self._unknown_population_timer.start()

def _build_unknown_group_item(self, group: UnknownResolverGroup) -> QTreeWidgetItem:
    return build_unknown_group_item(
        group,
        display_name=unknown_group_display_name(group, primary_member=primary_unknown_member(group)),
        classification_text=unknown_group_classification_text(group),
        package_text=unknown_group_package_text(group),
    )

def _flush_unknown_group_population_batch(self) -> None:
    if self._pending_unknown_source_groups:
        batch = self._pending_unknown_source_groups[: self.UNKNOWN_GROUP_BATCH_SIZE]
        del self._pending_unknown_source_groups[: self.UNKNOWN_GROUP_BATCH_SIZE]
        matched_groups = [
            group
            for group in batch
            if unknown_group_matches_filters(
                group,
                pending_focus_keys=self.pending_classification_review_focus_keys,
                name_filter=self.unknown_name_filter_edit.text().strip(),
                package_filter=self.unknown_package_filter_edit.text().strip(),
                primary_member=primary_unknown_member(group),
            )
        ]
        self._pending_unknown_groups.extend(matched_groups)
        items = [self._build_unknown_group_item(group) for group in matched_groups]
        if items:
            self.unknown_group_tree.setUpdatesEnabled(False)
            self.unknown_group_tree.addTopLevelItems(items)
            self.unknown_group_tree.setUpdatesEnabled(True)
        self._pending_unknown_population_total += len(matched_groups)
        scanned = self._pending_unknown_scanned_total - len(self._pending_unknown_source_groups)
        self.unknown_resolver_status_label.setText(
            unknown_group_filter_progress_status_text(
                scanned=scanned,
                total=self._pending_unknown_scanned_total,
                matched=self._pending_unknown_population_total,
            )
        )
        self._unknown_population_timer.start()
        return
    self._finalize_unknown_group_population()

def _finalize_unknown_group_population(self) -> None:
    if self.unknown_group_tree.topLevelItemCount() <= 0:
        self.unknown_member_tree.clear()
        self.unknown_members_group.setVisible(False)
        self.unknown_detail_edit.clear()
        self._clear_unknown_preview("No matching DDS preview is available for the current review filter.")
        self.unknown_resolver_status_label.setText(
            unknown_group_empty_status_text(
                showing_classified=self._pending_unknown_showing_classified,
                has_focus_keys=bool(self.pending_classification_review_focus_keys),
            )
        )
        self._update_unknown_resolver_controls()
        return
    selected_item: Optional[QTreeWidgetItem] = None
    if self._pending_unknown_previous_group_key:
        for index in range(self.unknown_group_tree.topLevelItemCount()):
            item = self.unknown_group_tree.topLevelItem(index)
            value = current_unknown_group_from_item(item)
            if value is not None and value.group_key == self._pending_unknown_previous_group_key:
                selected_item = item
                break
    first_item = self.unknown_group_tree.topLevelItem(0)
    if first_item is not None:
        self.unknown_group_tree.setCurrentItem(selected_item or first_item)
        registry_text = str(self.classification_registry_path) if self.classification_registry_path is not None else "local registry"
        self.unknown_resolver_status_label.setText(
            unknown_group_ready_status_text(
                item_count=self._pending_unknown_population_total,
                registry_text=registry_text,
                showing_classified=self._pending_unknown_showing_classified,
                has_focus_keys=bool(self.pending_classification_review_focus_keys),
            )
        )
    self._update_unknown_resolver_controls()
