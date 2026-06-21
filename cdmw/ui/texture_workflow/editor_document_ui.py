from __future__ import annotations

"""Document-level Texture Editor UI operations and prompts."""

import dataclasses
from typing import Optional, Tuple

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QVBoxLayout

from cdmw.ui.texture_workflow.editor_document_state import (
    TextureEditorDocumentPixelsChangeState,
    texture_editor_crop_to_selection_gate,
    texture_editor_cropped_to_selection_state,
    texture_editor_document_pixels_change_gate,
    texture_editor_flipped_document_state,
    texture_editor_resized_canvas_state,
    texture_editor_resized_image_state,
    texture_editor_rotated_document_state,
    texture_editor_trimmed_transparent_state,
)


class TextureEditorDocumentUiMixin:
    def _prompt_document_dimensions(
        self,
        *,
        title: str,
        width: int,
        height: int,
        allow_anchor: bool = False,
        keep_aspect_default: bool = False,
    ) -> Optional[Tuple[int, int, str]]:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        width_spin = QSpinBox(dialog)
        width_spin.setRange(1, 16384)
        width_spin.setValue(max(1, int(width)))
        height_spin = QSpinBox(dialog)
        height_spin.setRange(1, 16384)
        height_spin.setValue(max(1, int(height)))
        form.addRow("Width", width_spin)
        form.addRow("Height", height_spin)
        keep_aspect_checkbox: Optional[QCheckBox] = None
        if not allow_anchor:
            keep_aspect_checkbox = QCheckBox("Keep aspect ratio", dialog)
            keep_aspect_checkbox.setChecked(bool(keep_aspect_default))
            form.addRow("", keep_aspect_checkbox)
            base_ratio = float(max(1, int(width))) / float(max(1, int(height)))
            updating = {"active": False}

            def _sync_from_width(value: int) -> None:
                if keep_aspect_checkbox is None or not keep_aspect_checkbox.isChecked() or updating["active"]:
                    return
                updating["active"] = True
                try:
                    height_spin.setValue(max(1, int(round(float(value) / max(base_ratio, 1e-6)))))
                finally:
                    updating["active"] = False

            def _sync_from_height(value: int) -> None:
                if keep_aspect_checkbox is None or not keep_aspect_checkbox.isChecked() or updating["active"]:
                    return
                updating["active"] = True
                try:
                    width_spin.setValue(max(1, int(round(float(value) * base_ratio))))
                finally:
                    updating["active"] = False

            width_spin.valueChanged.connect(_sync_from_width)
            height_spin.valueChanged.connect(_sync_from_height)
        anchor_combo: Optional[QComboBox] = None
        if allow_anchor:
            anchor_combo = QComboBox(dialog)
            anchor_combo.addItem("Top Left", "top_left")
            anchor_combo.addItem("Center", "center")
            form.addRow("Anchor", anchor_combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return None
        anchor_value = str(anchor_combo.currentData() or "top_left") if anchor_combo is not None else "top_left"
        return (int(width_spin.value()), int(height_spin.value()), anchor_value)

    def resize_document_image(self) -> None:
        if self.document is None:
            return
        result = self._prompt_document_dimensions(
            title="Image Size",
            width=self.document.width,
            height=self.document.height,
            allow_anchor=False,
            keep_aspect_default=True,
        )
        if result is None:
            return
        new_width, new_height, _anchor = result
        self._apply_document_pixels_change_state(
            texture_editor_resized_image_state(
                self.document,
                self.layer_pixels,
                new_width,
                new_height,
            )
        )

    def resize_document_canvas(self) -> None:
        if self.document is None:
            return
        result = self._prompt_document_dimensions(
            title="Canvas Size",
            width=self.document.width,
            height=self.document.height,
            allow_anchor=True,
        )
        if result is None:
            return
        new_width, new_height, anchor = result
        self._apply_document_pixels_change_state(
            texture_editor_resized_canvas_state(
                self.document,
                self.layer_pixels,
                new_width,
                new_height,
                anchor=anchor,
            )
        )

    def _apply_document_pixels_change_state(
        self,
        change_state: Optional[TextureEditorDocumentPixelsChangeState],
    ) -> None:
        gate = texture_editor_document_pixels_change_gate(self.document)
        if not gate.can_apply:
            if gate.status_text:
                self._set_status(gate.status_text, gate.error)
            return
        if change_state is None:
            return
        before_document = dataclasses.replace(self.document)
        self.document = change_state.document
        self.layer_pixels = change_state.layer_pixels
        self._thumbnail_cache = {}
        self._invalidate_composite_cache()
        self._record_history_change(
            change_state.history_label,
            before_document=before_document,
            before_layer_pixels=change_state.before_layer_pixels,
            kind=change_state.kind,
            tracked_layer_ids=change_state.tracked_layer_ids,
            force_checkpoint=change_state.force_checkpoint,
        )
        self._refresh_ui()
        self._set_status(change_state.status_text, False)

    def crop_document_to_selection(self) -> None:
        gate = texture_editor_crop_to_selection_gate(self.document)
        if not gate.can_apply:
            self._set_status(gate.status_text, gate.error)
            return
        self._apply_document_pixels_change_state(
            texture_editor_cropped_to_selection_state(self.document, self.layer_pixels)
        )

    def trim_document_transparent(self) -> None:
        if self.document is None:
            return
        self._apply_document_pixels_change_state(
            texture_editor_trimmed_transparent_state(self.document, self.layer_pixels)
        )

    def flip_document(self, horizontal: bool, vertical: bool) -> None:
        if self.document is None:
            return
        self._apply_document_pixels_change_state(
            texture_editor_flipped_document_state(
                self.document,
                self.layer_pixels,
                horizontal=horizontal,
                vertical=vertical,
            )
        )

    def rotate_document_90(self, clockwise: bool) -> None:
        if self.document is None:
            return
        self._apply_document_pixels_change_state(
            texture_editor_rotated_document_state(self.document, self.layer_pixels, clockwise=clockwise)
        )


__all__ = ["TextureEditorDocumentUiMixin"]
