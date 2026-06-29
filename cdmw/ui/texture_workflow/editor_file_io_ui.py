from __future__ import annotations
"""File, project, export, and handoff UI coordination for the Texture Editor."""

import dataclasses
from pathlib import Path
from typing import Callable, Optional
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox
from cdmw.constants import APP_TITLE
from cdmw.domain.textures.editor_presets import (
    texture_editor_dds_format_label,
    texture_editor_dds_preset,
)
from cdmw.models import TextureEditorSourceBinding
from cdmw.services.texture_editor_service import (
    TextureEditorNativeDdsOptions,
    TextureEditorNativeDdsResult,
    native_texture_editor_backend_status_text,
)
from cdmw.ui.texture_workflow.editor_action_state import texture_editor_atlas_action_state
from cdmw.ui.texture_workflow.editor_export_state import (
    texture_editor_compressed_preview_dds_path,
    texture_editor_compressed_preview_status_text,
    texture_editor_compressed_preview_task_label,
    texture_editor_dds_default_path,
    texture_editor_document_with_last_flattened_output,
    texture_editor_existing_project_status_text,
    texture_editor_flattened_png_default_path,
    texture_editor_flattened_png_status_text,
    texture_editor_flattened_png_task_label,
    texture_editor_grid_slices_status_text,
    texture_editor_grid_slices_task_label,
    texture_editor_handoff_delivery_state,
    texture_editor_handoff_export_suffix,
    texture_editor_handoff_source_binding,
    texture_editor_native_dds_status_text,
    texture_editor_native_dds_task_label,
    texture_editor_open_project_history_label,
    texture_editor_open_project_status_text,
    texture_editor_open_project_task_label,
    texture_editor_project_default_path,
    texture_editor_save_project_status_text,
    texture_editor_save_project_task_label,
    texture_editor_selection_region_default_path,
    texture_editor_selection_region_missing_status_text,
    texture_editor_selection_region_status_text,
    texture_editor_selection_region_task_label,
    texture_editor_workspace_export_task_label,
)
from cdmw.ui.texture_workflow.editor_export_tasks import (
    copy_texture_editor_layer_pixels,
    create_texture_editor_source_document_task,
    export_texture_editor_flattened_png_task,
    export_texture_editor_grid_slices_task,
    export_texture_editor_native_dds_task,
    export_texture_editor_region_png_task,
    export_texture_editor_workspace_png_task,
    load_texture_editor_project_task,
    preview_texture_editor_native_dds_task,
    save_texture_editor_project_task,
)
from cdmw.ui.texture_workflow.editor_floating_state import texture_editor_snapshot_floating_pixels
from cdmw.ui.texture_workflow.editor_selection_state import current_texture_editor_selection_bounds
from cdmw.ui.texture_workflow.editor_session import (
    texture_editor_active_session_label_update_state,
    texture_editor_existing_project_session_index,
    texture_editor_existing_source_session_index,
)
from cdmw.ui.texture_workflow.editor_source_binding import (
    texture_editor_browse_archive_request_path,
    texture_editor_compare_request_state,
    texture_editor_existing_source_status_text,
    texture_editor_open_source_history_label,
    texture_editor_open_source_status_text,
    texture_editor_open_source_task_label,
)

class TextureEditorFileIoUiMixin:
    def _selected_native_dds_preset_key(self) -> str:
        return str(self.native_dds_preset_combo.currentData() or "base_color")

    def _refresh_native_dds_format_options(self) -> None:
        current = str(self.native_dds_format_combo.currentData() or "")
        preset = texture_editor_dds_preset(self._selected_native_dds_preset_key())
        self.native_dds_format_combo.blockSignals(True)
        self.native_dds_format_combo.clear()
        for dds_format in preset.allowed_formats:
            self.native_dds_format_combo.addItem(texture_editor_dds_format_label(dds_format), dds_format)
        index = self.native_dds_format_combo.findData(current)
        if index < 0:
            index = self.native_dds_format_combo.findData(preset.default_format)
        self.native_dds_format_combo.setCurrentIndex(max(0, index))
        self.native_dds_format_combo.blockSignals(False)
        self.native_dds_status_label.setText(native_texture_editor_backend_status_text())
    def _handle_native_dds_preset_changed(self, *_args: object) -> None:
        self._refresh_native_dds_format_options()
    def _native_dds_options(self, output_path: Path, *, overwrite: bool = True) -> TextureEditorNativeDdsOptions:
        return TextureEditorNativeDdsOptions(
            output_path=output_path,
            preset_key=self._selected_native_dds_preset_key(),
            dds_format=str(self.native_dds_format_combo.currentData() or ""),
            mip_mode=str(self.native_dds_mip_combo.currentData() or ""),
            overwrite=overwrite,
            preview_max_dimension=max(1024, int(max(getattr(self.document, "width", 1), getattr(self.document, "height", 1)))),
            temp_root=Path(self.workspace_root) / "native_temp",
        )
    def _refresh_atlas_action_state(self, *, has_doc: bool, busy: bool) -> None:
        atlas_actions = texture_editor_atlas_action_state(
            self.document,
            busy=busy,
            has_selection_bounds=current_texture_editor_selection_bounds(self.document) is not None,
        )
        self.atlas_section.setVisible(has_doc)
        self.atlas_padding_spin.setEnabled(atlas_actions.controls_enabled)
        self.atlas_trim_checkbox.setEnabled(atlas_actions.controls_enabled)
        self.atlas_skip_empty_checkbox.setEnabled(atlas_actions.controls_enabled)
        self.atlas_export_selection_button.setEnabled(atlas_actions.export_selection_enabled)
        self.atlas_export_grid_button.setEnabled(atlas_actions.export_grid_enabled)
        self.history_list.setEnabled(atlas_actions.history_list_enabled)
    def export_selection_region(self) -> None:
        if self.document is None:
            return
        bounds = current_texture_editor_selection_bounds(self.document)
        if bounds is None:
            self._set_status(texture_editor_selection_region_missing_status_text(), True)
            return
        output_path_text, _selected = QFileDialog.getSaveFileName(
            self,
            "Export selection region",
            str(texture_editor_selection_region_default_path(self.document, self._last_save_dir)),
            "PNG files (*.png)",
        )
        if not output_path_text:
            return
        output_path = Path(output_path_text).expanduser().resolve()
        self._last_save_dir = str(output_path.parent)
        document = dataclasses.replace(self.document)
        layer_pixels = copy_texture_editor_layer_pixels(self.layer_pixels)
        padding = int(self.atlas_padding_spin.value())
        trim_transparent = bool(self.atlas_trim_checkbox.isChecked())
        def _task() -> object:
            return export_texture_editor_region_png_task(
                document,
                layer_pixels,
                output_path,
                bounds,
                padding=padding,
                trim_transparent=trim_transparent,
            )
        def _on_success(result: object) -> None:
            self._set_status(texture_editor_selection_region_status_text(Path(str(result))), False)
        self._run_async_task(
            label=texture_editor_selection_region_task_label(),
            task=_task,
            on_success=_on_success,
        )

    def export_grid_slices(self) -> None:
        if self.document is None:
            return
        output_dir_text = QFileDialog.getExistingDirectory(
            self,
            "Export grid slices",
            self._last_save_dir,
        )
        if not output_dir_text:
            return
        output_dir = Path(output_dir_text).expanduser().resolve()
        self._last_save_dir = str(output_dir)
        document = dataclasses.replace(self.document)
        layer_pixels = copy_texture_editor_layer_pixels(self.layer_pixels)
        cell_size = int(self.grid_size_spin.value())
        padding = int(self.atlas_padding_spin.value())
        trim_transparent = bool(self.atlas_trim_checkbox.isChecked())
        skip_empty = bool(self.atlas_skip_empty_checkbox.isChecked())

        def _task() -> object:
            return export_texture_editor_grid_slices_task(
                document,
                layer_pixels,
                output_dir,
                cell_size=cell_size,
                padding=padding,
                trim_transparent=trim_transparent,
                skip_empty=skip_empty,
            )

        def _on_success(result: object) -> None:
            exported = result if isinstance(result, list) else []
            self._set_status(texture_editor_grid_slices_status_text(output_dir, len(exported)), False)

        self._run_async_task(
            label=texture_editor_grid_slices_task_label(),
            task=_task,
            on_success=_on_success,
        )

    def request_browse_archive(self) -> None:
        self.browse_archive_requested.emit(texture_editor_browse_archive_request_path(self.document))

    def request_open_compare(self) -> None:
        state = texture_editor_compare_request_state(self.document)
        if not state.can_request or state.binding is None:
            self._set_status(state.status_text, state.error)
            return
        self.open_in_compare_requested.emit(state.relative_path, state.binding)

    def open_file_dialog(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open image or DDS for Texture Editor",
            self._last_open_dir,
            "Supported files (*.png *.dds *.jpg *.jpeg *.bmp *.tga *.webp);;All files (*.*)",
        )
        if not file_path:
            return
        self._last_open_dir = str(Path(file_path).expanduser().resolve().parent)
        self.open_source_path(Path(file_path), binding=TextureEditorSourceBinding(launch_origin="file"))

    def open_project_dialog(self) -> None:
        project_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Texture Editor project",
            self._last_open_dir,
            "Texture Editor projects (*.ctfedit.json);;JSON files (*.json);;All files (*.*)",
        )
        if not project_path:
            return
        self._last_open_dir = str(Path(project_path).expanduser().resolve().parent)
        self.load_project(Path(project_path))

    def open_source_path(self, source_path: Path, *, binding: Optional[TextureEditorSourceBinding] = None) -> None:
        resolved_source = source_path.expanduser().resolve()
        try:
            texture_binding = self._build_binding_for_source(
                resolved_source,
                launch_origin=binding.launch_origin if binding is not None else "file",
                binding=binding,
            )
        except Exception as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        existing_index = texture_editor_existing_source_session_index(self._sessions, resolved_source)
        if existing_index >= 0:
            session = self._sessions[existing_index]
            document = session.document
            if document is not None:
                session.document = dataclasses.replace(
                    document,
                    source_binding=texture_binding,
                    technical_warning=texture_binding.technical_warning,
                )
            self._load_session_index(existing_index)
            self._refresh_metadata()
            self._refresh_canvas_status_strip()
            self._set_status(texture_editor_existing_source_status_text(resolved_source), False)
            return
        texconv_text = str(self.get_texconv_path()).strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None

        def _task() -> object:
            return create_texture_editor_source_document_task(
                resolved_source,
                texconv_path=texconv_path,
                workspace_root=self.workspace_root,
                binding=texture_binding,
            )

        def _handle_open(result: object) -> None:
            document, layer_pixels = result  # type: ignore[misc]
            self._create_session(document, layer_pixels, label=document.title)
            self._push_history(texture_editor_open_source_history_label())
            self._refresh_ui()
            self._set_status(texture_editor_open_source_status_text(resolved_source), False)

        self._run_async_task(label=texture_editor_open_source_task_label(resolved_source), task=_task, on_success=_handle_open)

    def load_project(self, project_path: Path) -> None:
        resolved_project = project_path.expanduser().resolve()
        existing_index = texture_editor_existing_project_session_index(self._sessions, resolved_project)
        if existing_index >= 0:
            self._load_session_index(existing_index)
            self._set_status(texture_editor_existing_project_status_text(resolved_project), False)
            return

        def _task() -> object:
            return load_texture_editor_project_task(resolved_project)

        def _handle_open_project(result: object) -> None:
            document, layer_pixels, floating_pixels = result  # type: ignore[misc]
            self._create_session(document, layer_pixels, label=document.title)
            self._floating_pixels = None if floating_pixels is None else floating_pixels.copy()
            self._floating_mask = None if self._floating_pixels is None else self._floating_pixels[..., 3].copy()
            self._push_history(texture_editor_open_project_history_label())
            self._refresh_ui()
            self._set_status(texture_editor_open_project_status_text(resolved_project), False)

        self._run_async_task(label=texture_editor_open_project_task_label(resolved_project), task=_task, on_success=_handle_open_project)

    def save_project_dialog(self) -> None:
        if self.document is None:
            return
        initial = texture_editor_project_default_path(self.document, self._last_save_dir)
        project_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Texture Editor project",
            str(initial),
            "Texture Editor projects (*.ctfedit.json)",
        )
        if not project_path:
            return
        self._last_save_dir = str(Path(project_path).expanduser().resolve().parent)
        document = dataclasses.replace(self.document)
        layer_pixels = copy_texture_editor_layer_pixels(self.layer_pixels)
        floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)

        def _task() -> object:
            return save_texture_editor_project_task(
                document,
                layer_pixels,
                Path(project_path),
                floating_pixels=floating_pixels,
            )

        def _handle_save(result: object) -> None:
            self.document = result  # type: ignore[assignment]
            label_state = texture_editor_active_session_label_update_state(
                self._sessions,
                self._active_session_index,
                self.document.title,
            )
            if label_state.can_update:
                self._sessions[label_state.index].label = label_state.label
                self._sync_document_tab_label(label_state.index)
            self._set_status(texture_editor_save_project_status_text(Path(project_path)), False)
            self._refresh_ui()

        self._run_async_task(label=texture_editor_save_project_task_label(Path(project_path)), task=_task, on_success=_handle_save)

    def _export_workspace_png(self, suffix: str, *, on_ready: Optional[Callable[[Path], None]] = None) -> None:
        if self.document is None:
            return
        document = dataclasses.replace(self.document)
        layer_pixels = copy_texture_editor_layer_pixels(self.layer_pixels)

        def _task() -> object:
            return export_texture_editor_workspace_png_task(document, layer_pixels, self.workspace_root, suffix)

        def _handle_export(result: object) -> None:
            output_path = Path(str(result))
            if self.document is not None:
                self.document = texture_editor_document_with_last_flattened_output(self.document, output_path)
                self._refresh_metadata()
            if on_ready is not None:
                on_ready(output_path)

        self._run_async_task(label=texture_editor_workspace_export_task_label(suffix), task=_task, on_success=_handle_export)

    def save_flattened_png_dialog(self) -> None:
        if self.document is None:
            return
        initial = texture_editor_flattened_png_default_path(self.document, self._last_save_dir)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save flattened PNG",
            str(initial),
            "PNG files (*.png)",
        )
        if not file_path:
            return
        self._last_save_dir = str(Path(file_path).expanduser().resolve().parent)
        document = dataclasses.replace(self.document)
        layer_pixels = copy_texture_editor_layer_pixels(self.layer_pixels)

        def _task() -> object:
            return export_texture_editor_flattened_png_task(document, layer_pixels, Path(file_path))

        def _handle_save_png(result: object) -> None:
            output_path = Path(str(result))
            if self.document is not None:
                self.document = texture_editor_document_with_last_flattened_output(self.document, output_path)
                self._refresh_metadata()
            self._set_status(texture_editor_flattened_png_status_text(output_path), False)
            self._refresh_ui()

        self._run_async_task(label=texture_editor_flattened_png_task_label(Path(file_path)), task=_task, on_success=_handle_save_png)

    def export_dds_dialog(self) -> None:
        if self.document is None:
            return
        initial = texture_editor_dds_default_path(self.document, self._last_save_dir)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export DDS",
            str(initial),
            "DDS files (*.dds)",
        )
        if not file_path:
            return
        output_path = Path(file_path).expanduser().resolve()
        self._last_save_dir = str(output_path.parent)
        document = dataclasses.replace(self.document)
        layer_pixels = copy_texture_editor_layer_pixels(self.layer_pixels)
        options = self._native_dds_options(output_path)

        def _task() -> object:
            return export_texture_editor_native_dds_task(document, layer_pixels, options)

        def _handle_export(result: object) -> None:
            native_result = result if isinstance(result, TextureEditorNativeDdsResult) else None
            if native_result is None:
                return
            self.native_dds_status_label.setText(native_texture_editor_backend_status_text())
            self._set_status(texture_editor_native_dds_status_text(native_result.dds_path, native_result.report), False)
            if self.document is not None:
                self.native_dds_ready.emit(str(native_result.dds_path), texture_editor_handoff_source_binding(self.document))
            self._refresh_ui()

        self._run_async_task(
            label=texture_editor_native_dds_task_label(output_path),
            task=_task,
            on_success=_handle_export,
        )

    def preview_compressed_dds(self) -> None:
        if self.document is None:
            return
        preset_key = self._selected_native_dds_preset_key()
        output_path = texture_editor_compressed_preview_dds_path(self.document, self.workspace_root, preset_key)
        document = dataclasses.replace(self.document)
        layer_pixels = copy_texture_editor_layer_pixels(self.layer_pixels)
        options = self._native_dds_options(output_path)

        def _task() -> object:
            return preview_texture_editor_native_dds_task(document, layer_pixels, options)

        def _handle_preview(result: object) -> None:
            native_result = result if isinstance(result, TextureEditorNativeDdsResult) else None
            if native_result is None:
                return
            if 0 <= int(self._active_session_index) < len(self._sessions) and native_result.preview_rgba is not None:
                self._sessions[int(self._active_session_index)].compressed_preview_flattened = native_result.preview_rgba.copy()
                split_index = self.view_mode_combo.findData("split")
                if split_index >= 0:
                    self.view_mode_combo.setCurrentIndex(split_index)
            self.native_dds_status_label.setText(native_texture_editor_backend_status_text())
            self._set_status(
                texture_editor_compressed_preview_status_text(native_result.preview_path or native_result.dds_path, native_result.report),
                False,
            )
            if self.document is not None:
                self.native_dds_ready.emit(str(native_result.dds_path), texture_editor_handoff_source_binding(self.document))
            self._refresh_ui()

        self._run_async_task(
            label=texture_editor_compressed_preview_task_label(),
            task=_task,
            on_success=_handle_preview,
        )

    def _complete_handoff_target(
        self,
        target: str,
        output_path: Path,
        source_binding: TextureEditorSourceBinding,
    ) -> None:
        delivery_state = texture_editor_handoff_delivery_state(target, output_path, source_binding)
        if delivery_state.emit_replace_assistant:
            self.send_to_replace_assistant_requested.emit(str(delivery_state.output_path), delivery_state.source_binding)
        elif delivery_state.emit_texture_workflow:
            QTimer.singleShot(
                0,
                lambda path_text=str(delivery_state.output_path), binding=delivery_state.source_binding: self.send_to_texture_workflow_requested.emit(
                    path_text,
                    binding,
                ),
            )
        elif delivery_state.emit_item_icons:
            self.send_to_item_icons_requested.emit(str(delivery_state.output_path), delivery_state.source_binding)
        self._set_status(delivery_state.status_text, False)
        self._refresh_ui()

    def _send_to_handoff_target(self, target: str) -> None:
        if self.document is None:
            return
        source_binding = texture_editor_handoff_source_binding(self.document)

        def _handle_ready(output_path: Path) -> None:
            self._complete_handoff_target(target, output_path, source_binding)

        self._export_workspace_png(texture_editor_handoff_export_suffix(target), on_ready=_handle_ready)

    def send_to_replace_assistant(self) -> None:
        self._send_to_handoff_target("replace_assistant")

    def send_to_texture_workflow(self) -> None:
        self._send_to_handoff_target("texture_workflow")

    def send_to_item_icons(self) -> None:
        self._send_to_handoff_target("item_icons")
