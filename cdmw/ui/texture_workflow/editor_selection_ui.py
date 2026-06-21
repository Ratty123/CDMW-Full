from __future__ import annotations

"""Selection control coordination for the standalone Texture Editor tab."""

import dataclasses

from PySide6.QtCore import Qt

from cdmw.ui.texture_workflow.editor_clipboard_state import (
    texture_editor_copy_selection_to_layer_missing_status_text,
    texture_editor_selection_clipboard_payload,
    texture_editor_selection_copy_status_text,
    texture_editor_selection_to_layer_state,
)
from cdmw.ui.texture_workflow.editor_selection_state import (
    texture_editor_active_layer_selection_payload_state,
    texture_editor_canvas_selection_payload_state,
    texture_editor_canvas_selection_source_pixels,
    texture_editor_canvas_selection_update_state,
    texture_editor_selection_controls_state,
    texture_editor_selection_feather_preview_document,
    texture_editor_selection_operation_state,
    texture_editor_selection_refine_labels,
)


class TextureEditorSelectionUiMixin:
    def _refresh_selection_controls(self) -> None:
        controls = texture_editor_selection_controls_state(
            self.document,
            current_tool=self.current_tool_settings.tool,
            current_layer_id=self._current_layer_id(),
            layer_pixel_ids=set(self.layer_pixels),
            busy=self._busy(),
        )
        self.selection_help_label.setText(controls.help_text)
        self.selection_invert_checkbox.blockSignals(True)
        self.selection_feather_slider.blockSignals(True)
        self.selection_mode_combo.blockSignals(True)
        self.selection_quick_mask_checkbox.blockSignals(True)
        self.selection_invert_checkbox.setChecked(controls.inverted)
        self.selection_feather_slider.setValue(controls.feather_radius)
        self.selection_quick_mask_checkbox.setChecked(controls.quick_mask_enabled)
        self.selection_mode_combo.setCurrentIndex(max(0, self.selection_mode_combo.findData(self.current_tool_settings.selection_combine_mode)))
        self.selection_invert_checkbox.blockSignals(False)
        self.selection_feather_slider.blockSignals(False)
        self.selection_mode_combo.blockSignals(False)
        self.selection_quick_mask_checkbox.blockSignals(False)
        self._refresh_selection_button_labels()
        self.selection_copy_layer_button.setEnabled(controls.copy_layer_enabled)
        self.selection_select_all_button.setEnabled(controls.select_all_enabled)
        self.selection_clear_button.setEnabled(controls.clear_enabled)
        self.selection_grow_button.setEnabled(controls.refine_enabled)
        self.selection_shrink_button.setEnabled(controls.refine_enabled)
        self.selection_to_mask_button.setEnabled(controls.to_mask_enabled)
        self.selection_from_mask_button.setEnabled(controls.from_mask_enabled)
        self.selection_invert_checkbox.setEnabled(controls.invert_enabled)
        self.selection_feather_slider.setEnabled(controls.feather_enabled)
        self.selection_mode_combo.setEnabled(controls.combine_mode_enabled)
        self.selection_refine_spin.setEnabled(controls.refine_enabled)
        self.selection_quick_mask_checkbox.setEnabled(controls.quick_mask_checkbox_enabled)

    def _apply_selection_update(self, update_state: object, before_document: object) -> None:
        if update_state is None:
            return
        self.document = update_state.document
        self._record_history_change(
            update_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind="selection_update",
            tracked_layer_ids=[],
        )
        self._refresh_ui()

    def clear_selection(self) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        update_state = texture_editor_selection_operation_state(self.document, action="clear")
        self._apply_selection_update(update_state, before_document)

    def select_all_image(self) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        update_state = texture_editor_selection_operation_state(self.document, action="select_all")
        self._apply_selection_update(update_state, before_document)

    def _refresh_selection_button_labels(self) -> None:
        grow_label, shrink_label = texture_editor_selection_refine_labels(self.selection_refine_spin.value())
        self.selection_grow_button.setText(grow_label)
        self.selection_shrink_button.setText(shrink_label)

    def adjust_selection_size(self, delta: int) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        update_state = texture_editor_selection_operation_state(self.document, action="resize", delta=delta)
        self._apply_selection_update(update_state, before_document)

    def toggle_quick_mask(self, checked: bool) -> None:
        if self.document is None:
            self.selection_quick_mask_checkbox.blockSignals(True)
            self.selection_quick_mask_checkbox.setChecked(False)
            self.selection_quick_mask_checkbox.blockSignals(False)
            return
        before_document = dataclasses.replace(self.document)
        update_state = texture_editor_selection_operation_state(self.document, action="quick_mask", checked=checked)
        self._apply_selection_update(update_state, before_document)

    def toggle_quick_mask_shortcut(self) -> None:
        if self.document is None:
            return
        self.selection_quick_mask_checkbox.setChecked(not self.selection_quick_mask_checkbox.isChecked())

    def preview_selection_settings(self) -> None:
        if self.document is None:
            return
        self.document = texture_editor_selection_feather_preview_document(
            self.document,
            self.selection_feather_slider.value(),
        )
        self._refresh_canvas()

    def commit_selection_settings(self) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        update_state = texture_editor_selection_operation_state(
            self.document,
            action="feather",
            feather_radius=self.selection_feather_slider.value(),
        )
        self._apply_selection_update(update_state, before_document)

    def toggle_selection_invert(self, checked: bool) -> None:
        if self.document is None:
            return
        before_document = dataclasses.replace(self.document)
        update_state = texture_editor_selection_operation_state(self.document, action="invert", checked=checked)
        self._apply_selection_update(update_state, before_document)

    def _handle_canvas_selection(self, payload: object) -> None:
        if self.document is None or not isinstance(payload, dict):
            return
        before_document = dataclasses.replace(self.document)
        payload_state = texture_editor_canvas_selection_payload_state(payload)
        snap_pixels = None
        if (
            payload_state is not None
            and payload_state.mode == "lasso"
            and self.current_tool_settings.lasso_snap_to_edges
        ):
            snap_pixels = texture_editor_canvas_selection_source_pixels(
                self.document,
                self.layer_pixels,
                self._current_composite_rgba(),
            )
        update_state = texture_editor_canvas_selection_update_state(
            self.document,
            payload_state,
            settings=self.current_tool_settings,
            snap_pixels=snap_pixels,
        )
        if update_state is not None:
            self.document = update_state.document
            self._record_history_change(
                update_state.history_label,
                before_document=before_document,
                before_layer_pixels={},
                kind="selection_update",
                tracked_layer_ids=[],
            )
        self._refresh_ui()

    def copy_selection_to_clipboard(self) -> bool:
        selection_state = texture_editor_active_layer_selection_payload_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
        )
        if selection_state is None:
            return False
        self.selection_clipboard = texture_editor_selection_clipboard_payload(selection_state)
        self.layer_clipboard = None
        self._set_status(texture_editor_selection_copy_status_text(selection_state.label), False)
        return True

    def copy_content(self) -> None:
        if self.document is not None and self.document.selection.mode != "none":
            if self.copy_selection_to_clipboard():
                return
        self.copy_active_layer()

    def copy_selection_to_new_layer(self) -> None:
        if self.document is None:
            return
        selection_state = texture_editor_active_layer_selection_payload_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
        )
        if selection_state is None:
            self._set_status(texture_editor_copy_selection_to_layer_missing_status_text(), True)
            return
        layer_state = texture_editor_selection_to_layer_state(self.document, self.layer_pixels, selection_state)
        self.document = layer_state.document
        self.layer_pixels = layer_state.layer_pixels
        self._push_history(layer_state.history_label)
        self._refresh_ui()
        for row in range(self.layers_list.count()):
            item = self.layers_list.item(row)
            if item.data(Qt.UserRole) == layer_state.layer_id:
                self.layers_list.setCurrentItem(item)
                break
        self._set_active_tool("move")
        self.selection_clipboard = layer_state.selection_clipboard
        self._set_status(layer_state.status_text, False)


__all__ = ["TextureEditorSelectionUiMixin"]
