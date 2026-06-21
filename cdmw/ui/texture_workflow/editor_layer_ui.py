from __future__ import annotations

"""Layer operation coordination for the standalone Texture Editor tab."""

import dataclasses
from typing import Dict, List

import numpy as np
from PySide6.QtCore import Qt

from cdmw.ui.texture_workflow.editor_layer_state import (
    TextureEditorLayerMaskOperationState,
    added_texture_editor_layer_mask_state,
    deleted_texture_editor_layer_mask_state,
    inverted_texture_editor_layer_mask_state,
    toggled_texture_editor_layer_mask_state,
    texture_editor_active_layer_document,
    texture_editor_current_layer_mask_to_selection_state,
    texture_editor_drag_reordered_document_state,
    texture_editor_edit_mask_target_state,
    texture_editor_layer_action_operation_state,
    texture_editor_layer_by_id,
    texture_editor_layer_control_state,
    texture_editor_layer_history_label,
    texture_editor_layer_lock_operation_state,
    texture_editor_layer_properties_operation_state,
    texture_editor_layer_rename_operation_state,
    texture_editor_layers_reordered_status_text,
    texture_editor_selection_to_current_layer_mask_state,
)
from cdmw.ui.texture_workflow.editor_status_state import texture_editor_tool_status_text


class TextureEditorLayerUiMixin:
    def add_mask_to_selected_layer(self) -> None:
        if self.document is None:
            return
        mask_state = added_texture_editor_layer_mask_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            layer_pixels=self.layer_pixels,
        )
        self._apply_layer_mask_operation(mask_state)

    def invert_selected_layer_mask(self) -> None:
        if self.document is None:
            return
        mask_state = inverted_texture_editor_layer_mask_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            layer_pixels=self.layer_pixels,
        )
        self._apply_layer_mask_operation(mask_state)

    def delete_selected_layer_mask(self) -> None:
        if self.document is None:
            return
        mask_state = deleted_texture_editor_layer_mask_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            layer_pixels=self.layer_pixels,
        )
        self._apply_layer_mask_operation(mask_state)

    def toggle_selected_layer_mask_enabled(self, checked: bool) -> None:
        if self.document is None:
            return
        mask_state = toggled_texture_editor_layer_mask_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            layer_pixels=self.layer_pixels,
            checked=checked,
        )
        self._apply_layer_mask_operation(mask_state)

    def _apply_layer_mask_operation(self, mask_state: TextureEditorLayerMaskOperationState) -> None:
        if self.document is None or not mask_state.changed:
            return
        before_document = dataclasses.replace(self.document)
        self.document = mask_state.document
        self.layer_pixels = mask_state.layer_pixels
        if mask_state.reset_editing_mask_target:
            self._editing_mask_target = False
        if mask_state.invalidate_layer_id:
            self._invalidate_layer_thumbnail(mask_state.invalidate_layer_id)
        self._invalidate_composite_cache()
        self._record_history_change(
            mask_state.history_label,
            before_document=before_document,
            before_layer_pixels=mask_state.before_layer_pixels,
            kind="mask_update",
            tracked_layer_ids=list(mask_state.tracked_layer_ids),
            force_checkpoint=mask_state.force_checkpoint,
        )
        self._refresh_ui()

    def toggle_edit_mask_target(self, checked: bool) -> None:
        layer_id = self._current_layer_id()
        layer = None if self.document is None else texture_editor_layer_by_id(self.document.layers, layer_id)
        state = texture_editor_edit_mask_target_state(
            checked=checked,
            layer=layer,
            layer_pixel_ids=self.layer_pixels.keys(),
        )
        self._editing_mask_target = state.editing_mask_target
        if state.reset_checkbox:
            self.layer_edit_mask_checkbox.blockSignals(True)
            self.layer_edit_mask_checkbox.setChecked(False)
            self.layer_edit_mask_checkbox.blockSignals(False)
        if state.status_text:
            self._set_status(state.status_text, state.error)
        else:
            self._set_status(texture_editor_tool_status_text(self.current_tool_settings.tool), False)
        if not state.allowed:
            return
        self._refresh_ui()

    def _handle_layer_selection_changed(self) -> None:
        if self.document is None:
            return
        layer_id = self._current_layer_id()
        if not layer_id:
            return
        self.document = texture_editor_active_layer_document(self.document, layer_id)
        layer = texture_editor_layer_by_id(self.document.layers, layer_id)
        if layer is None:
            return
        layer_controls = texture_editor_layer_control_state(
            layer,
            layer_pixel_ids=self.layer_pixels.keys(),
            editing_mask_target=self._editing_mask_target,
        )
        self.layer_name_edit.setText(layer_controls.name)
        self.layer_visible_checkbox.blockSignals(True)
        self.layer_visible_checkbox.setChecked(layer_controls.visible_checked)
        self.layer_visible_checkbox.blockSignals(False)
        self.layer_locked_checkbox.blockSignals(True)
        self.layer_locked_checkbox.setChecked(layer_controls.locked_checked)
        self.layer_locked_checkbox.blockSignals(False)
        self.layer_alpha_locked_checkbox.blockSignals(True)
        self.layer_alpha_locked_checkbox.setChecked(layer_controls.alpha_locked_checked)
        self.layer_alpha_locked_checkbox.blockSignals(False)
        self.layer_mask_enabled_checkbox.blockSignals(True)
        self.layer_mask_enabled_checkbox.setChecked(layer_controls.mask_enabled_checked)
        self.layer_mask_enabled_checkbox.blockSignals(False)
        self.layer_edit_mask_checkbox.blockSignals(True)
        self.layer_edit_mask_checkbox.setChecked(layer_controls.edit_mask_checked)
        self.layer_edit_mask_checkbox.blockSignals(False)
        self.layer_blend_mode_combo.blockSignals(True)
        blend_index = self.layer_blend_mode_combo.findData(layer_controls.blend_mode)
        self.layer_blend_mode_combo.setCurrentIndex(max(0, blend_index))
        self.layer_blend_mode_combo.blockSignals(False)
        self.layer_opacity_slider.blockSignals(True)
        self.layer_opacity_slider.setValue(layer_controls.opacity)
        self.layer_opacity_slider.blockSignals(False)
        self.layer_mask_enabled_checkbox.setEnabled(layer_controls.mask_controls_enabled)
        self.layer_edit_mask_checkbox.setEnabled(layer_controls.mask_controls_enabled)
        self.layer_invert_mask_button.setEnabled(layer_controls.mask_controls_enabled)
        self.layer_delete_mask_button.setEnabled(layer_controls.mask_controls_enabled)

    def _handle_layers_reordered_by_drag(self, *_args) -> None:
        if self.document is None or self._refreshing_layers_list or self._busy():
            return
        display_ids: List[str] = []
        for row in range(self.layers_list.count()):
            item = self.layers_list.item(row)
            if item is None:
                continue
            value = item.data(Qt.UserRole)
            if value:
                display_ids.append(str(value))
        reorder_state = texture_editor_drag_reordered_document_state(
            self.document,
            display_layer_ids=display_ids,
        )
        if not reorder_state.changed:
            return
        before_document = dataclasses.replace(self.document)
        self.document = reorder_state.document
        self._invalidate_composite_cache()
        self._record_history_change(
            texture_editor_layer_history_label("reorder"),
            before_document=before_document,
            before_layer_pixels={},
            kind="layer_reorder",
            tracked_layer_ids=[],
        )
        self._refresh_ui()
        self._set_status(texture_editor_layers_reordered_status_text(), False)

    def rename_selected_layer(self) -> None:
        update_state = texture_editor_layer_rename_operation_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            raw_name=self.layer_name_edit.text(),
        )
        if not update_state.changed or update_state.document is None:
            return
        before_document = dataclasses.replace(self.document)
        before_layer_pixels: Dict[str, np.ndarray] = {}
        self.document = update_state.document
        self._layer_property_dirty = False
        self._record_history_change(
            update_state.history_label,
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind=update_state.kind,
            tracked_layer_ids=[],
        )
        self._refresh_layers()

    def preview_selected_layer_properties(self) -> None:
        update_state = texture_editor_layer_properties_operation_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            visible=self.layer_visible_checkbox.isChecked(),
            opacity=self.layer_opacity_slider.value(),
            blend_mode=str(self.layer_blend_mode_combo.currentData() or "normal"),
        )
        if not update_state.changed or update_state.document is None:
            return
        before_document = dataclasses.replace(self.document)
        before_layer_pixels: Dict[str, np.ndarray] = {}
        self.document = update_state.document
        self._layer_property_dirty = True
        self._invalidate_layer_thumbnail(update_state.layer_id)
        self._invalidate_composite_cache()
        self._pending_layer_property_before_document = before_document
        self._pending_layer_property_before_pixels = before_layer_pixels
        if update_state.structural_refresh_needed:
            self._refresh_editor_views(canvas=True, layers=True, status=True, tool_visibility=False)
            return
        self._refresh_editor_views(canvas=True, status=True, tool_visibility=False)

    def commit_selected_layer_opacity(self) -> None:
        if not self._layer_property_dirty:
            return
        self._layer_property_dirty = False
        before_document = getattr(self, "_pending_layer_property_before_document", dataclasses.replace(self.document))
        before_layer_pixels = getattr(self, "_pending_layer_property_before_pixels", {})
        self._record_history_change(
            texture_editor_layer_history_label("change_opacity"),
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind="layer_update",
            tracked_layer_ids=[],
        )
        self._pending_layer_property_before_document = None
        self._pending_layer_property_before_pixels = {}
        self._refresh_editor_views(canvas=True, history=True, status=True, tool_visibility=False)

    def toggle_selected_layer_visibility(self) -> None:
        if self.document is None:
            return
        self.preview_selected_layer_properties()
        if not self._layer_property_dirty:
            return
        self._layer_property_dirty = False
        before_document = getattr(self, "_pending_layer_property_before_document", dataclasses.replace(self.document))
        before_layer_pixels = getattr(self, "_pending_layer_property_before_pixels", {})
        self._record_history_change(
            texture_editor_layer_history_label("toggle_visibility"),
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind="layer_update",
            tracked_layer_ids=[],
        )
        self._pending_layer_property_before_document = None
        self._pending_layer_property_before_pixels = {}
        self._refresh_editor_views(canvas=True, layers=True, history=True, status=True, tool_visibility=False)

    def commit_selected_layer_flags(self) -> None:
        update_state = texture_editor_layer_lock_operation_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            locked=self.layer_locked_checkbox.isChecked(),
            alpha_locked=self.layer_alpha_locked_checkbox.isChecked(),
        )
        if not update_state.changed or update_state.document is None:
            return
        before_document = dataclasses.replace(self.document)
        self.document = update_state.document
        self._record_history_change(
            update_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind=update_state.kind,
            tracked_layer_ids=[],
        )
        self._refresh_editor_views(canvas=True, layers=True, history=True, status=True, tool_visibility=False)

    def _apply_layer_action(self, action: str) -> object:
        before_document = dataclasses.replace(self.document)
        before_layer_pixels = dict(self.layer_pixels)
        layer_state = texture_editor_layer_action_operation_state(
            self.document,
            self.layer_pixels,
            action=action,
            current_layer_id=self._current_layer_id(),
        )
        if layer_state is None:
            return None
        self.document = layer_state.document
        self.layer_pixels = layer_state.layer_pixels
        self._invalidate_composite_cache()
        self._record_history_change(
            layer_state.history_label,
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind=layer_state.kind,
            force_checkpoint=layer_state.force_checkpoint,
        )
        self._refresh_ui()
        return layer_state

    def add_layer(self) -> None:
        if self.document is None:
            return
        layer_state = self._apply_layer_action("add")
        if layer_state is None:
            return
        for row in range(self.layers_list.count()):
            item = self.layers_list.item(row)
            if item.data(Qt.UserRole) == layer_state.layer_id:
                self.layers_list.setCurrentItem(item)
                break

    def duplicate_layer(self) -> None:
        if self.document is not None:
            self._apply_layer_action("duplicate")

    def remove_layer(self) -> None:
        if self.document is not None:
            self._apply_layer_action("remove")

    def merge_layer_down(self) -> None:
        if self.document is not None:
            self._apply_layer_action("merge_down")

    def reorder_layer(self, direction: int) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        layer_state = texture_editor_layer_action_operation_state(
            self.document,
            self.layer_pixels,
            action="reorder",
            current_layer_id=self._current_layer_id(),
            direction=direction,
        )
        if layer_state is None:
            return
        self.document = layer_state.document
        self._invalidate_composite_cache()
        self._record_history_change(
            layer_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind=layer_state.kind,
            tracked_layer_ids=layer_state.tracked_layer_ids,
        )
        self._refresh_ui()

    def apply_selection_to_selected_layer_mask(self) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        before_layer_pixels = dict(self.layer_pixels)
        mask_state = texture_editor_selection_to_current_layer_mask_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
        )
        self.document = mask_state.document
        self.layer_pixels = mask_state.layer_pixels
        if not mask_state.changed:
            self._set_status(mask_state.status_text, mask_state.error)
            return
        layer_id = self._current_layer_id() or before_document.active_layer_id
        self._invalidate_layer_thumbnail(layer_id)
        self._invalidate_composite_cache()
        self._record_history_change(
            mask_state.history_label,
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind="mask_update",
            tracked_layer_ids=[layer_id, mask_state.mask_layer_id],
            force_checkpoint=True,
        )
        self._editing_mask_target = True
        self._refresh_ui()
        self._set_status(mask_state.status_text, mask_state.error)

    def load_selected_layer_mask_as_selection(self) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        selection_state = texture_editor_current_layer_mask_to_selection_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            combine_mode=self.current_tool_settings.selection_combine_mode,
        )
        if not selection_state.changed:
            self._set_status(selection_state.status_text, selection_state.error)
            return
        self.document = selection_state.document
        self._record_history_change(
            selection_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind="selection_update",
            tracked_layer_ids=[],
        )
        self._refresh_ui()
        self._set_status(selection_state.status_text, selection_state.error)


__all__ = ["TextureEditorLayerUiMixin"]
