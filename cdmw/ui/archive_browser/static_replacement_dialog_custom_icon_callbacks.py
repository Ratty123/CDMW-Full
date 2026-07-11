"""Custom icon callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_generated_icon_output import (
    AlignmentGeneratedIconOutputController,
)


def create_alignment_custom_icon_callbacks(context: dict[str, object]) -> SimpleNamespace:
    ArchiveEntry = context.get('ArchiveEntry')
    CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE = context.get('CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE')
    ItemIconOverrideSpec = context.get('ItemIconOverrideSpec')
    NativePreviewPanel = context.get('NativePreviewPanel')
    Optional = context.get('Optional')
    QApplication = context.get('QApplication')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    QTimer = context.get('QTimer')
    _alignment_current_camera_state = context.get('_alignment_current_camera_state')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _custom_item_icon_apply_control_enabled_state_helper = context.get('_custom_item_icon_apply_control_enabled_state_helper')
    _custom_item_icon_control_enabled_state_helper = context.get('_custom_item_icon_control_enabled_state_helper')
    _custom_item_icon_file_dialog_filter_helper = context.get('_custom_item_icon_file_dialog_filter_helper')
    _custom_item_icon_override_spec_helper = context.get('_custom_item_icon_override_spec_helper')
    _custom_item_icon_status_text_helper = context.get('_custom_item_icon_status_text_helper')
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

    def _schedule_icon_capture(delay_ms: int, callback) -> None:
        timer = QTimer(dialog)
        timer.setSingleShot(True)

        def _run() -> None:
            try:
                callback()
            finally:
                timer.deleteLater()

        timer.timeout.connect(_run)
        timer.start(max(0, int(delay_ms)))

    def _capture_alignment_replacement_icon_pixmap(on_captured) -> None:
        if _alignment_d3d11_preview_active():
            previous_mode = str(preview_mode_combo.currentData() or "side_by_side")
            previous_view_state = alignment_d3d11_preview_host.view_state_snapshot()
            capture_view_state = _alignment_current_camera_state()
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

            def _capture_d3d11_frame() -> None:
                pixmap = None
                try:
                    screen = alignment_d3d11_preview_host.screen() or dialog.screen() or QApplication.primaryScreen()
                    if screen is not None:
                        captured = screen.grabWindow(int(alignment_d3d11_preview_host.winId()))
                        pixmap = captured if not captured.isNull() else None
                finally:
                    try:
                        alignment_d3d11_preview_host.set_icon_capture_mode(False)
                        alignment_d3d11_preview_host.set_display_mode(previous_mode)
                        alignment_d3d11_preview_host.restore_view_state(previous_view_state)
                        _sync_highlight_sets()
                        _sync_mesh_edit_preview_settings()
                        try:
                            _replay_alignment_d3d11_fast_transform()
                        except NameError:
                            pass
                    finally:
                        on_captured(pixmap)

            _schedule_icon_capture(80, _capture_d3d11_frame)
            return

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

        def _capture_qt_frame() -> None:
            pixmap = None
            try:
                captured = preview_widget.grab()
                pixmap = captured if not captured.isNull() else None
            finally:
                try:
                    replacement_only_preview.restore_view_state(previous_replacement_view_state)
                    for widget, guides_visible, editing_enabled in zip(
                        (static_dialog_preview, overlay_dialog_preview, replacement_only_preview),
                        previous_guides,
                        previous_editing,
                    ):
                        widget.set_alignment_guides_visible(bool(guides_visible))
                        widget.set_alignment_editing_enabled(bool(editing_enabled))
                finally:
                    on_captured(pixmap)

        _schedule_icon_capture(0, _capture_qt_frame)

    generated_icon_output = AlignmentGeneratedIconOutputController(
        context,
        capture=_capture_alignment_replacement_icon_pixmap,
        refresh_status=_refresh_alignment_custom_icon_status,
    )

    return SimpleNamespace(
        _alignment_custom_icon_override_spec=_alignment_custom_icon_override_spec,
        _refresh_alignment_custom_icon_status=_refresh_alignment_custom_icon_status,
        _choose_alignment_custom_icon_file=_choose_alignment_custom_icon_file,
        _choose_alignment_custom_icon_folder=_choose_alignment_custom_icon_folder,
        _choose_alignment_custom_icon_library_source=_choose_alignment_custom_icon_library_source,
        _capture_alignment_replacement_icon_pixmap=_capture_alignment_replacement_icon_pixmap,
        _generate_alignment_icon_from_preview=generated_icon_output.generate,
    )
