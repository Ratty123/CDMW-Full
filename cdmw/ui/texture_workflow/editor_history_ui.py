from __future__ import annotations

"""History list, undo, and restore coordination for the Texture Editor tab."""

import time
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from cdmw.models import TextureEditorDocument
from cdmw.ui.texture_workflow.editor_action_state import texture_editor_history_action_state
from cdmw.ui.texture_workflow.editor_history_state import (
    build_texture_editor_checkpoint_record,
    build_texture_editor_delta_history_record,
    texture_editor_history_cleared_state,
    texture_editor_history_list_item_text,
    texture_editor_history_record_application_state,
    texture_editor_history_restore_state,
    texture_editor_history_selected_row_state,
    texture_editor_history_should_checkpoint,
    texture_editor_history_with_appended_record,
)


class TextureEditorHistoryUiMixin:
    def _build_checkpoint_record(self, label: str) -> Dict[str, object]:
        return build_texture_editor_checkpoint_record(
            self.document,
            self.layer_pixels,
            label,
            timestamp=time.time(),
            floating_pixels=self._floating_pixels,
        )

    def _record_history_change(
        self,
        label: str,
        *,
        before_document: TextureEditorDocument,
        before_layer_pixels: Dict[str, np.ndarray],
        kind: str,
        dirty_bounds: Optional[Tuple[int, int, int, int]] = None,
        tracked_layer_ids: Optional[Sequence[str]] = None,
        force_checkpoint: bool = False,
        before_floating_pixels: Optional[np.ndarray] = None,
    ) -> None:
        if self.document is None:
            return
        if texture_editor_history_should_checkpoint(
            history_count=len(self.history_snapshots),
            force_checkpoint=force_checkpoint,
        ):
            record = self._build_checkpoint_record(label)
        else:
            record = build_texture_editor_delta_history_record(
                label=label,
                before_document=before_document,
                after_document=self.document,
                before_layer_pixels=before_layer_pixels,
                after_layer_pixels=self.layer_pixels,
                kind=kind,
                timestamp=time.time(),
                dirty_bounds=dirty_bounds,
                tracked_layer_ids=tracked_layer_ids,
                before_floating_pixels=before_floating_pixels,
                after_floating_pixels=self._floating_pixels,
            )
        self.history_snapshots, self.history_index = texture_editor_history_with_appended_record(
            self.history_snapshots,
            self.history_index,
            record,
        )
        self._refresh_history_list()

    def _push_history(self, label: str) -> None:
        if self.document is None:
            return
        self.history_snapshots, self.history_index = texture_editor_history_with_appended_record(
            self.history_snapshots,
            self.history_index,
            self._build_checkpoint_record(label),
        )
        self._refresh_history_list()

    def _apply_history_record(self, record: Dict[str, object], *, direction: str) -> None:
        state = texture_editor_history_record_application_state(
            record,
            direction=direction,
            current_layer_pixels=dict(self.layer_pixels),
        )
        self.document = state.document
        self.layer_pixels = state.layer_pixels
        self._floating_pixels = state.floating_pixels
        self._floating_mask = state.floating_mask
        self._invalidate_composite_cache()

    def _restore_history_index(self, index: int) -> None:
        state = texture_editor_history_restore_state(self.history_snapshots, index)
        if not state.can_restore:
            return
        for replay_index in state.replay_plan.apply_indices:
            self._apply_history_record(self.history_snapshots[replay_index], direction="after")
        self.history_index = index
        self._layer_property_dirty = False
        self._adjustment_property_dirty = False
        self._pending_adjustment_before_document = None
        self._invalidate_composite_cache()
        self._refresh_ui()
        self._set_status(state.status_text, False)

    def undo(self) -> None:
        if self.history_index <= 0:
            return
        self._restore_history_index(self.history_index - 1)

    def redo(self) -> None:
        if self.history_index >= len(self.history_snapshots) - 1:
            return
        self._restore_history_index(self.history_index + 1)

    def _refresh_history_list(self) -> None:
        self.history_list.blockSignals(True)
        self.history_list.clear()
        for index, snapshot in enumerate(self.history_snapshots):
            entry = snapshot["entry"]
            item = QListWidgetItem(entry.label)
            item.setData(Qt.UserRole, index)
            item.setText(texture_editor_history_list_item_text(entry.label, current=index == self.history_index))
            self.history_list.addItem(item)
        if 0 <= self.history_index < self.history_list.count():
            self.history_list.setCurrentRow(self.history_index)
        self.history_list.blockSignals(False)
        self._update_history_action_state()

    def _handle_history_row_changed(self, row: int) -> None:
        self._update_history_action_state()
        state = texture_editor_history_selected_row_state(
            self.history_snapshots,
            row,
            history_index=self.history_index,
        )
        if state.selected_index is None:
            return
        self._set_status(state.status_text, False)

    def _update_history_action_state(self) -> None:
        state = texture_editor_history_action_state(
            self.document,
            busy=self._busy(),
            selected_row=self.history_list.currentRow(),
            history_index=self.history_index,
            history_count=len(self.history_snapshots),
        )
        self.history_restore_button.setEnabled(state.restore_enabled)

    def restore_selected_history(self) -> None:
        row = self.history_list.currentRow()
        if row < 0 or row == self.history_index:
            return
        self._restore_history_index(row)

    def clear_history(self) -> None:
        if self.document is None:
            return
        current_label = "Current State"
        state = texture_editor_history_cleared_state(self._build_checkpoint_record(current_label))
        self.history_snapshots = state.history_snapshots
        self.history_index = state.history_index
        self._adjustment_property_dirty = False
        self._pending_adjustment_before_document = None
        self._refresh_history_list()
        self._set_status(state.status_text, False)


__all__ = ["TextureEditorHistoryUiMixin"]
