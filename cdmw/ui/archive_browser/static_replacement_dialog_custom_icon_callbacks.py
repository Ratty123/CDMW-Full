"""Custom icon callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def create_alignment_custom_icon_callbacks(context: dict[str, object]) -> SimpleNamespace:
    ArchiveEntry = context.get('ArchiveEntry')
    CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE = context.get('CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE')
    ItemIconOverrideSpec = context.get('ItemIconOverrideSpec')
    NativePreviewPanel = context.get('NativePreviewPanel')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QApplication = context.get('QApplication')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    QPixmap = context.get('QPixmap')
    QThread = context.get('QThread')
    _alignment_current_camera_state = context.get('_alignment_current_camera_state')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _custom_item_icon_alignment_generated_path_helper = context.get('_custom_item_icon_alignment_generated_path_helper')
    _custom_item_icon_apply_control_enabled_state_helper = context.get('_custom_item_icon_apply_control_enabled_state_helper')
    _custom_item_icon_control_enabled_state_helper = context.get('_custom_item_icon_control_enabled_state_helper')
    _custom_item_icon_file_dialog_filter_helper = context.get('_custom_item_icon_file_dialog_filter_helper')
    _custom_item_icon_generated_apply_state_helper = context.get('_custom_item_icon_generated_apply_state_helper')
    _custom_item_icon_generated_status_helper = context.get('_custom_item_icon_generated_status_helper')
    _custom_item_icon_generation_status_message_helper = context.get('_custom_item_icon_generation_status_message_helper')
    _custom_item_icon_maybe_register_generated_icon_helper = context.get('_custom_item_icon_maybe_register_generated_icon_helper')
    _custom_item_icon_override_spec_helper = context.get('_custom_item_icon_override_spec_helper')
    _custom_item_icon_preview_image_from_pixmap_helper = context.get('_custom_item_icon_preview_image_from_pixmap_helper')
    _custom_item_icon_status_text_helper = context.get('_custom_item_icon_status_text_helper')
    _custom_item_icon_write_failure_message_helper = context.get('_custom_item_icon_write_failure_message_helper')
    _qt_alignment_camera_tuple_helper = context.get('_qt_alignment_camera_tuple_helper')
    _replay_alignment_d3d11_fast_transform = context.get('_replay_alignment_d3d11_fast_transform')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _sync_mesh_edit_preview_settings = context.get('_sync_mesh_edit_preview_settings')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    custom_icon_checkbox = context.get('custom_icon_checkbox')
    custom_icon_control_text = context.get('custom_icon_control_text')
    custom_icon_file_button = context.get('custom_icon_file_button')
    custom_icon_folder_button = context.get('custom_icon_folder_button')
    custom_icon_library_button = context.get('custom_icon_library_button')
    custom_icon_source_edit = context.get('custom_icon_source_edit')
    custom_icon_status = context.get('custom_icon_status')
    custom_icon_target_combo = context.get('custom_icon_target_combo')
    custom_icon_target_entries = context.get('custom_icon_target_entries')
    custom_icon_target_graph = context.get('custom_icon_target_graph')
    dialog = context.get('dialog')
    entry = context.get('entry')
    obj_path = context.get('obj_path')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    preview_mode_combo = context.get('preview_mode_combo')
    replacement_only_preview = context.get('replacement_only_preview')
    save_generated_icon_to_library_checkbox = context.get('save_generated_icon_to_library_checkbox')
    self = context.get('self')
    static_dialog_preview = context.get('static_dialog_preview')

    def _alignment_custom_icon_override_spec(*, show_messages: bool) -> Optional[ItemIconOverrideSpec]:
        if not custom_icon_checkbox.isChecked():
            return None
        target_icon_entry = custom_icon_target_combo.currentData()
        if not isinstance(target_icon_entry, ArchiveEntry):
            if show_messages:
                QMessageBox.warning(
                    dialog,
                    custom_icon_control_text["warning_title"],
                    CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE,
                )
            return None
        icon_spec, message = _custom_item_icon_override_spec_helper(
            source_text=custom_icon_source_edit.text(),
            target_entry=target_icon_entry,
            related_stems=self._archive_item_icon_related_stems(entry, custom_icon_target_graph),
            display_name=entry.basename,
        )
        if icon_spec is None:
            if show_messages:
                QMessageBox.warning(dialog, custom_icon_control_text["warning_title"], message)
            return None
        return icon_spec

    def _refresh_alignment_custom_icon_status() -> None:
        _custom_item_icon_apply_control_enabled_state_helper(
            _custom_item_icon_control_enabled_state_helper(
                checked=custom_icon_checkbox.isChecked(),
                has_target_entries=bool(custom_icon_target_entries),
            ),
            source_edit_widget=custom_icon_source_edit,
            file_button_widget=custom_icon_file_button,
            folder_button_widget=custom_icon_folder_button,
            library_button_widget=custom_icon_library_button,
            target_combo_widget=custom_icon_target_combo,
        )
        custom_icon_status.setText(
            _custom_item_icon_status_text_helper(
                checked=custom_icon_checkbox.isChecked(),
                target_entry=custom_icon_target_combo.currentData(),
                source_text=custom_icon_source_edit.text(),
                related_stems=self._archive_item_icon_related_stems(entry, custom_icon_target_graph),
                display_name=entry.basename,
            )
        )

    def _choose_alignment_custom_icon_file() -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            custom_icon_control_text["choose_file_title"],
            str(obj_path.parent if obj_path.parent.is_dir() else self.settings_file_path.parent),
            _custom_item_icon_file_dialog_filter_helper(),
        )
        if selected:
            custom_icon_source_edit.setText(selected)

    def _choose_alignment_custom_icon_folder() -> None:
        selected = QFileDialog.getExistingDirectory(
            dialog,
            custom_icon_control_text["choose_folder_title"],
            str(obj_path.parent if obj_path.parent.is_dir() else self.settings_file_path.parent),
        )
        if selected:
            custom_icon_source_edit.setText(selected)

    def _choose_alignment_custom_icon_library_source() -> None:
        selected = self._choose_item_icon_library_source(dialog)
        if selected is not None:
            custom_icon_source_edit.setText(str(selected))

    def _capture_alignment_replacement_icon_pixmap() -> Optional[QPixmap]:
        if _alignment_d3d11_preview_active():
            previous_mode = str(preview_mode_combo.currentData() or "side_by_side")
            previous_view_state = alignment_d3d11_preview_host.view_state_snapshot()
            capture_view_state = _alignment_current_camera_state()
            try:
                alignment_d3d11_preview_host.restore_view_state(capture_view_state)
                alignment_d3d11_preview_host.set_icon_capture_mode(True)
                alignment_d3d11_preview_host.set_display_mode("replacement_only")
                alignment_d3d11_preview_host.set_highlighted_alignment_submeshes(
                    replacement_submesh_indices=(),
                    original_submesh_indices=(),
                )
                alignment_d3d11_preview_host.set_hidden_source_submeshes(())
                alignment_d3d11_preview_host.set_alignment_state(
                    enabled=False,
                    source_submesh_indices=(),
                    translation_sensitivity=0.85,
                    rotation_degrees_per_pixel=0.18,
                )
                QApplication.processEvents()
                QThread.msleep(80)
                QApplication.processEvents()
                screen = alignment_d3d11_preview_host.screen() or dialog.screen() or QApplication.primaryScreen()
                if screen is None:
                    return None
                pixmap = screen.grabWindow(int(alignment_d3d11_preview_host.winId()))
                return pixmap if not pixmap.isNull() else None
            finally:
                alignment_d3d11_preview_host.set_icon_capture_mode(False)
                alignment_d3d11_preview_host.set_display_mode(previous_mode)
                alignment_d3d11_preview_host.restore_view_state(previous_view_state)
                _sync_highlight_sets()
                _sync_mesh_edit_preview_settings()
                try:
                    _replay_alignment_d3d11_fast_transform()
                except NameError:
                    pass
        preview_widget = replacement_only_preview
        capture_view_state = _alignment_current_camera_state()
        previous_replacement_view_state = replacement_only_preview.view_state_snapshot()
        previous_guides = (
            getattr(static_dialog_preview, "_show_grid_overlay", False),
            getattr(overlay_dialog_preview, "_show_grid_overlay", False),
            getattr(replacement_only_preview, "_show_grid_overlay", False),
        )
        previous_editing = (
            getattr(static_dialog_preview, "_alignment_editing_enabled", False),
            getattr(overlay_dialog_preview, "_alignment_editing_enabled", False),
            getattr(replacement_only_preview, "_alignment_editing_enabled", False),
        )
        try:
            preview_widget.restore_view_state(
                _qt_alignment_camera_tuple_helper(
                    capture_view_state,
                    fit_distance=NativePreviewPanel._FIT_DISTANCE,
                )
            )
            for widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
                widget.set_alignment_guides_visible(False)
                widget.set_alignment_editing_enabled(False)
                widget.repaint()
            QApplication.processEvents()
            pixmap = preview_widget.grab()
            return pixmap if not pixmap.isNull() else None
        finally:
            replacement_only_preview.restore_view_state(previous_replacement_view_state)
            for widget, guides_visible, editing_enabled in zip(
                (static_dialog_preview, overlay_dialog_preview, replacement_only_preview),
                previous_guides,
                previous_editing,
            ):
                widget.set_alignment_guides_visible(bool(guides_visible))
                widget.set_alignment_editing_enabled(bool(editing_enabled))

    def _generate_alignment_icon_from_preview() -> None:
        pixmap = _capture_alignment_replacement_icon_pixmap()
        if pixmap is None or pixmap.isNull():
            QMessageBox.warning(
                dialog,
                custom_icon_control_text["generate_preview_warning_title"],
                custom_icon_control_text["generate_preview_not_ready"],
            )
            return
        output_path = _custom_item_icon_alignment_generated_path_helper(
            save_to_library=save_generated_icon_to_library_checkbox.isChecked(),
            item_icons_tab=getattr(self, "item_icons_tab", None),
            model_library_tab=getattr(self, "model_library_tab", None),
            target_model_path=str(getattr(entry, "path", "") or entry.basename),
            target_fallback_path=str(getattr(entry, "path", "") or obj_path.stem),
            source_model_path=str(obj_path),
            fallback_dir=Path.cwd(),
        )
        model_library = getattr(self, "model_library_tab", None)
        formatter = getattr(model_library, "_model_preview_icon_image", None)
        icon_image = _custom_item_icon_preview_image_from_pixmap_helper(pixmap, formatter=formatter, size=512)
        if not icon_image.save(str(output_path), "PNG"):
            QMessageBox.warning(
                dialog,
                custom_icon_control_text["generate_preview_warning_title"],
                _custom_item_icon_write_failure_message_helper(output_path),
            )
            return
        registration_result = _custom_item_icon_maybe_register_generated_icon_helper(
            save_to_library=save_generated_icon_to_library_checkbox.isChecked(),
            item_icons_tab=getattr(self, "item_icons_tab", None),
            output_path=output_path,
            target_model_path=str(getattr(entry, "path", "") or entry.basename),
            source_model_path=str(obj_path),
            target_icon_entry=custom_icon_target_combo.currentData(),
        )
        output_path = registration_result.output_path
        saved_to_library = registration_result.saved_to_library
        if registration_result.error_status:
            self.set_status_message(registration_result.error_status, error=True)
        custom_icon_source_edit.setText(str(output_path))
        generated_apply_state = _custom_item_icon_generated_apply_state_helper(
            has_target_entries=bool(custom_icon_target_entries),
            checkbox_enabled=custom_icon_checkbox.isEnabled(),
            current_target_entry=custom_icon_target_combo.currentData(),
        )
        if generated_apply_state["has_target"]:
            custom_icon_checkbox.setChecked(True)
            if generated_apply_state["select_first_target"]:
                custom_icon_target_combo.setCurrentIndex(0)
        _refresh_alignment_custom_icon_status()
        custom_icon_status.setText(
            _custom_item_icon_generated_status_helper(
                output_name=output_path.name,
                saved_to_library=saved_to_library,
                has_target=bool(generated_apply_state["has_target"]),
            )
        )
        self.set_status_message(_custom_item_icon_generation_status_message_helper(output_path))

    return SimpleNamespace(
        _alignment_custom_icon_override_spec=_alignment_custom_icon_override_spec,
        _refresh_alignment_custom_icon_status=_refresh_alignment_custom_icon_status,
        _choose_alignment_custom_icon_file=_choose_alignment_custom_icon_file,
        _choose_alignment_custom_icon_folder=_choose_alignment_custom_icon_folder,
        _choose_alignment_custom_icon_library_source=_choose_alignment_custom_icon_library_source,
        _capture_alignment_replacement_icon_pixmap=_capture_alignment_replacement_icon_pixmap,
        _generate_alignment_icon_from_preview=_generate_alignment_icon_from_preview,
    )
