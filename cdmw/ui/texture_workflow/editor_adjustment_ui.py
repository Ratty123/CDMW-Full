from __future__ import annotations

"""Adjustment-layer UI coordination for the standalone Texture Editor tab."""

import dataclasses
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from cdmw.models import TextureEditorAdjustmentLayer, TextureEditorDocument
from cdmw.ui.texture_workflow.editor_action_state import texture_editor_adjustment_action_state
from cdmw.ui.texture_workflow.editor_adjustments import (
    TextureEditorAdjustmentDocumentState,
    texture_editor_adjustment_control_state,
    texture_editor_adjustment_history_label,
    texture_editor_adjustment_list_label,
    texture_editor_adjustment_operation_state,
    texture_editor_adjustment_parameters_from_controls,
    texture_editor_adjustment_properties_dirty,
    texture_editor_adjustment_properties_update_state,
    texture_editor_adjustment_refresh_selection_id,
    texture_editor_selected_adjustment,
)


class TextureEditorAdjustmentUiMixin:
    def add_adjustment_layer(self) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        adjustment_type = str(self.adjustment_add_combo.currentData() or "levels")
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="add",
            adjustment_type=adjustment_type,
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def _current_adjustment_id(self) -> Optional[str]:
        item = self.adjustments_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return str(value) if value else None

    def _apply_adjustment_document_state(
        self,
        adjustment_state: TextureEditorAdjustmentDocumentState,
        before_document: TextureEditorDocument,
    ) -> bool:
        if not adjustment_state.changed:
            return False
        self.document = adjustment_state.document
        self._invalidate_composite_cache()
        self._record_history_change(
            adjustment_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind=adjustment_state.kind,
            tracked_layer_ids=adjustment_state.tracked_layer_ids,
        )
        self._refresh_editor_views(
            canvas=True,
            history=True,
            adjustments=True,
            status=True,
            tool_visibility=False,
        )
        if adjustment_state.preserve_selection_id:
            self._refresh_adjustments(preserve_selection_id=adjustment_state.preserve_selection_id)
        if adjustment_state.status_text:
            self._set_status(adjustment_state.status_text, False)
        return True

    def remove_selected_adjustment(self) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        adjustment_id = self._current_adjustment_id()
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="remove",
            adjustment_id=str(adjustment_id or ""),
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def duplicate_selected_adjustment(self) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="duplicate",
            adjustment_id=str(self._current_adjustment_id() or ""),
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def move_selected_adjustment(self, direction: int) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        adjustment_id = self._current_adjustment_id()
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="move",
            adjustment_id=str(adjustment_id or ""),
            direction=direction,
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def solo_selected_adjustment(self) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        adjustment_id = self._current_adjustment_id()
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="solo",
            adjustment_id=str(adjustment_id or ""),
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def use_active_layer_as_adjustment_mask(self) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="assign_mask",
            adjustment_id=str(self._current_adjustment_id() or ""),
            active_layer_id=str(self._current_layer_id() or ""),
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def clear_selected_adjustment_mask(self) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="clear_mask",
            adjustment_id=str(self._current_adjustment_id() or ""),
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def _selected_adjustment(self) -> Optional[TextureEditorAdjustmentLayer]:
        if self.document is None:
            return None
        adjustment_id = self._current_adjustment_id()
        return texture_editor_selected_adjustment(self.document.adjustment_layers, adjustment_id)

    def _handle_adjustment_selection_changed(self) -> None:
        if self._refreshing_adjustments:
            return
        if self._adjustment_preview_timer.isActive():
            self._adjustment_preview_timer.stop()
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        adjustment = self._selected_adjustment()
        has_adjustment = adjustment is not None
        self.adjustment_enabled_checkbox.blockSignals(True)
        self.adjustment_opacity_slider.blockSignals(True)
        self.adjustment_mode_combo.blockSignals(True)
        self.adjustment_param_a_slider.blockSignals(True)
        self.adjustment_param_b_slider.blockSignals(True)
        self.adjustment_param_c_slider.blockSignals(True)
        control_state = texture_editor_adjustment_control_state(adjustment)
        self.adjustment_mode_label.setVisible(control_state.mode_visible)
        self.adjustment_mode_combo.setVisible(control_state.mode_visible)
        self.adjustment_enabled_checkbox.setChecked(control_state.enabled_checked)
        self.adjustment_opacity_slider.setValue(control_state.opacity)
        mode_index = self.adjustment_mode_combo.findData(control_state.mode_value)
        if mode_index >= 0:
            self.adjustment_mode_combo.setCurrentIndex(mode_index)
        if control_state.params:
            for label_widget, slider_widget, param_state in (
                (self.adjustment_param_a_label, self.adjustment_param_a_slider, control_state.params[0]),
                (self.adjustment_param_b_label, self.adjustment_param_b_slider, control_state.params[1]),
                (self.adjustment_param_c_label, self.adjustment_param_c_slider, control_state.params[2]),
            ):
                label_widget.setText(param_state.label)
                slider_widget.setRange(param_state.minimum, param_state.maximum)
                slider_widget.setValue(param_state.value)
        else:
            self.adjustment_param_a_slider.setValue(0)
            self.adjustment_param_b_slider.setValue(0)
            self.adjustment_param_c_slider.setValue(0)
        self.adjustment_enabled_checkbox.blockSignals(False)
        self.adjustment_opacity_slider.blockSignals(False)
        self.adjustment_mode_combo.blockSignals(False)
        self.adjustment_param_a_slider.blockSignals(False)
        self.adjustment_param_b_slider.blockSignals(False)
        self.adjustment_param_c_slider.blockSignals(False)
        self.adjustment_enabled_checkbox.setEnabled(has_adjustment)
        self.adjustment_opacity_slider.setEnabled(has_adjustment)
        self.adjustment_mode_label.setEnabled(has_adjustment)
        self.adjustment_mode_combo.setEnabled(control_state.mode_enabled)
        self.adjustment_param_a_slider.setEnabled(has_adjustment)
        self.adjustment_param_b_slider.setEnabled(has_adjustment)
        self.adjustment_param_c_slider.setEnabled(has_adjustment)

    def _schedule_adjustment_preview(self) -> None:
        if self.document is None:
            return
        self._adjustment_preview_timer.start()

    def preview_selected_adjustment_properties(self) -> None:
        if self.document is None:
            return
        adjustment = self._selected_adjustment()
        if adjustment is None:
            return
        if not self._adjustment_property_dirty:
            self._pending_adjustment_before_document = dataclasses.replace(self.document)
        before_document = self._pending_adjustment_before_document or dataclasses.replace(self.document)
        parameters = texture_editor_adjustment_parameters_from_controls(
            adjustment.adjustment_type,
            param_a=self.adjustment_param_a_slider.value(),
            param_b=self.adjustment_param_b_slider.value(),
            param_c=self.adjustment_param_c_slider.value(),
            mode_value=str(self.adjustment_mode_combo.currentData() or "neutrals"),
        )
        update_state = texture_editor_adjustment_properties_update_state(
            self.document,
            adjustment_id=adjustment.layer_id,
            enabled=self.adjustment_enabled_checkbox.isChecked(),
            opacity=self.adjustment_opacity_slider.value(),
            parameters=parameters,
        )
        if update_state is None:
            return
        self.document = update_state.document
        self._invalidate_composite_cache()
        self._adjustment_property_dirty = texture_editor_adjustment_properties_dirty(before_document, self.document)
        self._refresh_canvas()
        self._refresh_canvas_status_strip()

    def commit_selected_adjustment_enabled(self) -> None:
        if self._adjustment_preview_timer.isActive():
            self._adjustment_preview_timer.stop()
        self.preview_selected_adjustment_properties()
        self.commit_selected_adjustment_properties()

    def reset_selected_adjustment(self) -> None:
        if self.document is None:
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        before_document = dataclasses.replace(self.document)
        adjustment_state = texture_editor_adjustment_operation_state(
            self.document,
            action="reset",
            adjustment_id=str(self._current_adjustment_id() or ""),
        )
        if adjustment_state is not None:
            self._apply_adjustment_document_state(adjustment_state, before_document)

    def commit_selected_adjustment_properties(self) -> None:
        if self._adjustment_preview_timer.isActive():
            self._adjustment_preview_timer.stop()
            self.preview_selected_adjustment_properties()
        if self.document is None or not self._adjustment_property_dirty:
            return
        before_document = self._pending_adjustment_before_document or dataclasses.replace(self.document)
        self._record_history_change(
            texture_editor_adjustment_history_label("update"),
            before_document=before_document,
            before_layer_pixels={},
            kind="adjustment_update",
            tracked_layer_ids=[],
        )
        self._pending_adjustment_before_document = None
        self._adjustment_property_dirty = False
        current_adjustment = self._current_adjustment_id()
        self._refresh_editor_views(
            canvas=True,
            history=True,
            adjustments=True,
            status=True,
            tool_visibility=False,
        )
        if current_adjustment:
            self._refresh_adjustments(preserve_selection_id=current_adjustment)

    def _refresh_adjustments(
        self,
        *,
        preserve_selection_id: Optional[str] = None,
        refresh_controls: bool = True,
    ) -> None:
        target_adjustment_id = texture_editor_adjustment_refresh_selection_id(
            self.document.adjustment_layers if self.document is not None else (),
            preserve_selection_id or self._current_adjustment_id(),
        )
        selected_item: Optional[QListWidgetItem] = None
        self._refreshing_adjustments = True
        self.adjustments_list.blockSignals(True)
        self.adjustments_list.clear()
        if self.document is not None:
            for adjustment in self.document.adjustment_layers:
                item = QListWidgetItem(texture_editor_adjustment_list_label(adjustment))
                item.setData(Qt.UserRole, adjustment.layer_id)
                self.adjustments_list.addItem(item)
                if adjustment.layer_id == target_adjustment_id:
                    selected_item = item
            if selected_item is not None:
                self.adjustments_list.setCurrentItem(selected_item)
        self.adjustments_list.blockSignals(False)
        self._refreshing_adjustments = False
        if refresh_controls:
            self._handle_adjustment_selection_changed()

    def _refresh_adjustment_action_state(self, *, has_doc: bool, busy: bool) -> None:
        self.adjustments_section.setVisible(has_doc)
        self.adjustment_mode_label.setVisible(has_doc)
        has_adjustment_item = self.adjustments_list.currentItem() is not None
        adjustment_actions = texture_editor_adjustment_action_state(
            has_document=has_doc,
            busy=busy,
            has_adjustment_item=has_adjustment_item,
            current_row=self.adjustments_list.currentRow(),
            adjustment_count=self.adjustments_list.count(),
            current_layer_id=self._current_layer_id(),
            selected_adjustment=self._selected_adjustment(),
        )
        self.adjustment_add_combo.setEnabled(adjustment_actions.add_enabled)
        self.adjustment_add_button.setEnabled(adjustment_actions.add_enabled)
        self.adjustment_duplicate_button.setEnabled(adjustment_actions.duplicate_enabled)
        self.adjustment_remove_button.setEnabled(adjustment_actions.remove_enabled)
        self.adjustment_reset_button.setEnabled(adjustment_actions.reset_enabled)
        self.adjustment_up_button.setEnabled(adjustment_actions.up_enabled)
        self.adjustment_down_button.setEnabled(adjustment_actions.down_enabled)
        self.adjustment_solo_button.setEnabled(adjustment_actions.solo_enabled)
        self.adjustment_use_active_mask_button.setEnabled(adjustment_actions.use_active_mask_enabled)
        self.adjustment_clear_mask_button.setEnabled(adjustment_actions.clear_mask_enabled)
        self.adjustments_list.setEnabled(adjustment_actions.list_enabled)
