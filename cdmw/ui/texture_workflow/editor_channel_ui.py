from __future__ import annotations

"""Channel operation coordination for the standalone Texture Editor tab."""

import dataclasses

from PySide6.QtCore import Qt

from cdmw.ui.texture_workflow.editor_channel_state import (
    texture_editor_channel_controls_state,
    texture_editor_channel_copy_operation_state,
    texture_editor_channel_extract_operation_state,
    texture_editor_channel_lock_update_state,
    texture_editor_channel_luma_pack_operation_state,
    texture_editor_channel_paste_operation_state,
    texture_editor_channel_selection_load_operation_state,
    texture_editor_channel_selection_write_operation_state,
    texture_editor_channel_swap_operation_state,
)


class TextureEditorChannelUiMixin:
    def _set_channel_lock_state(self, red: bool, green: bool, blue: bool, alpha: bool) -> None:
        self.channel_red_checkbox.setChecked(red)
        self.channel_green_checkbox.setChecked(green)
        self.channel_blue_checkbox.setChecked(blue)
        self.channel_alpha_checkbox.setChecked(alpha)

    def _handle_channel_lock_changed(self) -> None:
        if self.document is None:
            return
        lock_state = texture_editor_channel_lock_update_state(
            self.document,
            red=self.channel_red_checkbox.isChecked(),
            green=self.channel_green_checkbox.isChecked(),
            blue=self.channel_blue_checkbox.isChecked(),
            alpha=self.channel_alpha_checkbox.isChecked(),
        )
        self.document = lock_state.document
        self._refresh_canvas_status_strip()
        self._set_status(lock_state.status_text, False)

    def extract_active_channel_to_new_layer(self) -> None:
        operation_state = texture_editor_channel_extract_operation_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            channel_key=self.channel_extract_combo.currentData(),
        )
        channel_state = operation_state.layer_state
        if channel_state is None:
            if operation_state.status_text:
                self._set_status(operation_state.status_text, operation_state.error)
            return
        before_document = dataclasses.replace(self.document)
        self.document = channel_state.document
        self.layer_pixels = channel_state.layer_pixels
        self._record_history_change(
            channel_state.history_label,
            before_document=before_document,
            before_layer_pixels=channel_state.before_layer_pixels,
            kind=channel_state.kind,
            tracked_layer_ids=channel_state.tracked_layer_ids,
            force_checkpoint=channel_state.force_checkpoint,
        )
        self._refresh_ui()
        for row in range(self.layers_list.count()):
            item = self.layers_list.item(row)
            if item is not None and item.data(Qt.UserRole) == channel_state.new_layer_id:
                self.layers_list.setCurrentItem(item)
                break
        self._set_status(channel_state.status_text, False)

    def write_active_layer_luma_to_selected_channel(self) -> None:
        operation_state = texture_editor_channel_luma_pack_operation_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            channel_key=self.channel_pack_combo.currentData(),
        )
        channel_state = operation_state.layer_state
        if channel_state is None:
            if operation_state.status_text:
                self._set_status(operation_state.status_text, operation_state.error)
            return
        before_document = dataclasses.replace(self.document)
        self.document = channel_state.document
        self.layer_pixels = channel_state.layer_pixels
        self._invalidate_layer_thumbnail(channel_state.layer_id)
        self._invalidate_composite_cache()
        self._record_history_change(
            channel_state.history_label,
            before_document=before_document,
            before_layer_pixels=channel_state.before_layer_pixels,
            kind=channel_state.kind,
            tracked_layer_ids=channel_state.tracked_layer_ids,
        )
        self._refresh_ui()
        self._set_status(channel_state.status_text, False)

    def load_selected_channel_as_selection(self) -> None:
        operation_state = texture_editor_channel_selection_load_operation_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            channel_key=self.channel_selection_combo.currentData(),
            combine_mode=str(self.selection_mode_combo.currentData() or "replace"),
        )
        channel_state = operation_state.document_state
        if channel_state is None:
            if operation_state.status_text:
                self._set_status(operation_state.status_text, operation_state.error)
            return
        before_document = dataclasses.replace(self.document)
        self.document = channel_state.document
        self._record_history_change(
            channel_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind=channel_state.kind,
            tracked_layer_ids=channel_state.tracked_layer_ids,
        )
        self._refresh_ui()
        self._set_status(channel_state.status_text, False)

    def write_selection_to_selected_channel(self) -> None:
        operation_state = texture_editor_channel_selection_write_operation_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            channel_key=self.channel_selection_to_combo.currentData(),
        )
        channel_state = operation_state.layer_state
        if channel_state is None:
            if operation_state.status_text:
                self._set_status(operation_state.status_text, operation_state.error)
            return
        before_document = dataclasses.replace(self.document)
        self.document = channel_state.document
        self.layer_pixels = channel_state.layer_pixels
        self._invalidate_layer_thumbnail(channel_state.layer_id)
        self._invalidate_composite_cache()
        self._record_history_change(
            channel_state.history_label,
            before_document=before_document,
            before_layer_pixels=channel_state.before_layer_pixels,
            kind=channel_state.kind,
            tracked_layer_ids=channel_state.tracked_layer_ids,
        )
        self._refresh_ui()
        self._set_status(channel_state.status_text, False)

    def copy_selected_channel(self) -> None:
        operation_state = texture_editor_channel_copy_operation_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            channel_key=self.channel_copy_combo.currentData(),
        )
        channel_state = operation_state.clipboard_state
        if channel_state is None:
            if operation_state.status_text:
                self._set_status(operation_state.status_text, operation_state.error)
            return
        self.channel_clipboard = channel_state.clipboard
        self._refresh_channel_controls()
        self._set_status(channel_state.status_text, False)

    def paste_channel_clipboard(self) -> None:
        operation_state = texture_editor_channel_paste_operation_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            channel_key=self.channel_paste_combo.currentData(),
            channel_clipboard=self.channel_clipboard,
        )
        channel_state = operation_state.layer_state
        if channel_state is None:
            if operation_state.status_text:
                self._set_status(operation_state.status_text, operation_state.error)
            return
        before_document = dataclasses.replace(self.document)
        self.document = channel_state.document
        self.layer_pixels = channel_state.layer_pixels
        self._invalidate_layer_thumbnail(channel_state.layer_id)
        self._invalidate_composite_cache()
        self._record_history_change(
            channel_state.history_label,
            before_document=before_document,
            before_layer_pixels=channel_state.before_layer_pixels,
            kind=channel_state.kind,
            tracked_layer_ids=channel_state.tracked_layer_ids,
        )
        self._refresh_ui()
        self._set_status(channel_state.status_text, False)

    def swap_selected_channels(self) -> None:
        operation_state = texture_editor_channel_swap_operation_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
            channel_a=self.channel_swap_a_combo.currentData(),
            channel_b=self.channel_swap_b_combo.currentData(),
        )
        channel_state = operation_state.layer_state
        if channel_state is None:
            if operation_state.status_text:
                self._set_status(operation_state.status_text, operation_state.error)
            return
        before_document = dataclasses.replace(self.document)
        self.document = channel_state.document
        self.layer_pixels = channel_state.layer_pixels
        self._invalidate_layer_thumbnail(channel_state.layer_id)
        self._invalidate_composite_cache()
        self._record_history_change(
            channel_state.history_label,
            before_document=before_document,
            before_layer_pixels=channel_state.before_layer_pixels,
            kind=channel_state.kind,
            tracked_layer_ids=channel_state.tracked_layer_ids,
        )
        self._refresh_ui()
        self._set_status(channel_state.status_text, False)

    def _refresh_channel_controls(self) -> None:
        controls = texture_editor_channel_controls_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            busy=self._busy(),
            has_clipboard=self.channel_clipboard is not None,
        )
        for checkbox, value in (
            (self.channel_red_checkbox, controls.channel_values[0]),
            (self.channel_green_checkbox, controls.channel_values[1]),
            (self.channel_blue_checkbox, controls.channel_values[2]),
            (self.channel_alpha_checkbox, controls.channel_values[3]),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)
        self.channel_extract_button.setEnabled(controls.extract_enabled)
        self.channel_extract_combo.setEnabled(controls.extract_enabled)
        self.channel_pack_button.setEnabled(controls.pack_enabled)
        self.channel_pack_combo.setEnabled(controls.pack_enabled)
        self.channel_selection_combo.setEnabled(controls.selection_from_enabled)
        self.channel_selection_from_button.setEnabled(controls.selection_from_enabled)
        self.channel_selection_to_combo.setEnabled(controls.selection_to_enabled)
        self.channel_selection_to_button.setEnabled(controls.selection_to_enabled)
        self.channel_copy_combo.setEnabled(controls.copy_enabled)
        self.channel_copy_button.setEnabled(controls.copy_enabled)
        self.channel_paste_combo.setEnabled(controls.paste_enabled)
        self.channel_paste_button.setEnabled(controls.paste_enabled)
        self.channel_swap_a_combo.setEnabled(controls.swap_enabled)
        self.channel_swap_b_combo.setEnabled(controls.swap_enabled)
        self.channel_swap_button.setEnabled(controls.swap_enabled)


__all__ = ["TextureEditorChannelUiMixin"]
