"""Startup shell helpers for static replacement prompt."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps import (
    install_static_replacement_prompt_dependencies,
)
from cdmw.ui.archive_browser.static_replacement_dialog_ui_sections import _alignment_dialog_font_sizes

install_static_replacement_prompt_dependencies(globals())


class _MeshEditorCloseWorker(QObject):
    result = Signal(bool, str)
    finished = Signal()

    def __init__(self, operation, *, force_without_saving: bool) -> None:
        super().__init__()
        self._operation = operation
        self._force_without_saving = bool(force_without_saving)

    @Slot()
    def run(self) -> None:
        try:
            self._operation(self._force_without_saving)
        except Exception as exc:
            self.result.emit(False, f"{type(exc).__name__}: {exc}")
        else:
            self.result.emit(True, "")
        finally:
            self.finished.emit()


class _MeshEditorSaveAwareDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mesh_editor_close_operation = None
        self._mesh_editor_close_success = None
        self._mesh_editor_close_thread = None
        self._mesh_editor_close_worker = None
        self._mesh_editor_close_pending_result = int(QDialog.Rejected)
        self._mesh_editor_close_authorized = False
        self._mesh_editor_close_result = (False, "")

    def configureMeshEditorClose(self, operation, on_success) -> None:
        self._mesh_editor_close_operation = operation
        self._mesh_editor_close_success = on_success

    def done(self, result: int) -> None:
        if self._mesh_editor_close_authorized or not callable(self._mesh_editor_close_operation):
            return super().done(result)
        if self._mesh_editor_close_thread is not None:
            return
        self._mesh_editor_close_pending_result = int(result)
        self._start_mesh_editor_close(force_without_saving=False)

    def closeEvent(self, event) -> None:
        if self._mesh_editor_close_authorized or not callable(self._mesh_editor_close_operation):
            return super().closeEvent(event)
        event.ignore()
        self.done(QDialog.Rejected)

    def _start_mesh_editor_close(self, *, force_without_saving: bool) -> None:
        operation = self._mesh_editor_close_operation
        if not callable(operation) or self._mesh_editor_close_thread is not None:
            return
        self.setEnabled(False)
        self._mesh_editor_close_result = (False, "")
        thread = QThread(self)
        worker = _MeshEditorCloseWorker(
            operation,
            force_without_saving=force_without_saving,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._record_mesh_editor_close_result)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_mesh_editor_close)
        thread.finished.connect(thread.deleteLater)
        self._mesh_editor_close_thread = thread
        self._mesh_editor_close_worker = worker
        thread.start()

    @Slot(bool, str)
    def _record_mesh_editor_close_result(self, succeeded: bool, message: str) -> None:
        self._mesh_editor_close_result = (bool(succeeded), str(message or ""))
        thread = self._mesh_editor_close_thread
        if thread is not None:
            thread.quit()

    @Slot()
    def _finish_mesh_editor_close(self) -> None:
        succeeded, message = self._mesh_editor_close_result
        self._mesh_editor_close_thread = None
        self._mesh_editor_close_worker = None
        self.setEnabled(True)
        if succeeded:
            callback = self._mesh_editor_close_success
            if callable(callback):
                callback()
            self._mesh_editor_close_authorized = True
            QDialog.done(self, self._mesh_editor_close_pending_result)
            return
        self._show_mesh_editor_save_failure(message)

    def _show_mesh_editor_save_failure(self, message: str) -> None:
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Warning)
        prompt.setWindowTitle("Mesh Editor Save Failed")
        prompt.setText("The Mesh Editor still has unsaved geometry or layer changes.")
        prompt.setInformativeText(str(message or "Saving the Mesh Editor draft failed."))
        retry_button = prompt.addButton("Retry", QMessageBox.AcceptRole)
        close_button = prompt.addButton("Close Without Saving", QMessageBox.DestructiveRole)
        prompt.addButton("Cancel", QMessageBox.RejectRole)
        prompt.exec()
        if prompt.clickedButton() is retry_button:
            self._start_mesh_editor_close(force_without_saving=False)
            return
        if prompt.clickedButton() is not close_button:
            return
        confirmed = QMessageBox.question(
            self,
            "Discard Unsaved Mesh Editor Changes?",
            "Close this Mesh Editor session without saving its latest geometry and layer changes?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed == QMessageBox.Yes:
            self._start_mesh_editor_close(force_without_saving=True)


class _EmbeddedAlignmentBuilderDialog(_MeshEditorSaveAwareDialog):
    def keyPressEvent(self, event) -> None:
        if event.key() != Qt.Key_Escape:
            return super().keyPressEvent(event)
        event.accept()


def create_static_replacement_prompt_shell(context: dict[str, object]) -> SimpleNamespace:
    self = context["self"]
    entry = context["entry"]
    obj_path = context["obj_path"]
    dialog_title = context["dialog_title"]
    alignment_dialog_key = context["alignment_dialog_key"]
    embedded_host = context.get("embedded_host")
    runtime_export_target_entry = context.get("runtime_export_target_entry")
    defer_original_texture_preview = context["defer_original_texture_preview"]
    prompt_preflight = context["prompt_preflight"]
    _record_runtime_event = context.get("_record_runtime_event")
    if not callable(_record_runtime_event):
        _record_runtime_event = getattr(self, "_record_runtime_event", lambda *_args, **_kwargs: {})

    alignment_dialog_key_hash = hashlib.sha1(
        str(alignment_dialog_key).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    alignment_d3d11_view_state_reset_generation = int(
        getattr(self, "mesh_editor_d3d11_view_state_reset_generation", 0) or 0
    )
    embedded_alignment_builder = embedded_host is not None
    preview_build_entry = (
        runtime_export_target_entry
        if isinstance(runtime_export_target_entry, ArchiveEntry)
        else entry
    )
    modify_original_clone_mode = bool(prompt_preflight.modify_original_clone_mode)
    original_texture_preview_default = bool(modify_original_clone_mode)
    original_texture_preview_state = _original_texture_preview_initial_state_helper(
        original_texture_preview_default
    )
    original_reference_texture_preview_state = (
        _original_reference_texture_preview_initial_state_helper()
    )

    alignment_startup_text = _alignment_startup_step_text_helper()
    startup_progress = QProgressDialog(alignment_startup_text["initial_label"], "", 0, 0, self)
    startup_progress.setWindowTitle(alignment_startup_text["window_title"])
    startup_progress.setCancelButton(None)
    startup_progress.setMinimumDuration(0)
    startup_progress.setAutoClose(False)
    startup_progress.setWindowModality(Qt.NonModal)
    startup_progress.show()
    startup_progress_closed = _alignment_startup_progress_initial_state_helper()
    alignment_startup_step_state = _alignment_startup_step_initial_state_helper()

    _paint_alignment_startup_progress_helper(startup_progress)

    def _alignment_startup_step(message: str) -> None:
        if _alignment_startup_progress_closed_helper(startup_progress_closed):
            return
        elapsed_ms = _alignment_startup_step_elapsed_ms_helper(
            alignment_startup_step_state,
            time.perf_counter(),
        )
        _record_runtime_event(
            "mesh_alignment_startup_step",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            message=str(message or ""),
            builder_startup_step_elapsed_ms=elapsed_ms,
            modify_original_clone=modify_original_clone_mode,
            defer_original_texture_preview=defer_original_texture_preview,
        )
        startup_progress.setLabelText(message)
        startup_progress.setValue(0)
        _paint_alignment_startup_progress_helper(startup_progress)

    def _finish_alignment_startup_progress() -> None:
        if not _alignment_startup_progress_mark_closed_helper(startup_progress_closed):
            return
        startup_progress.close()

    _alignment_startup_step(alignment_startup_text["creating_window"])
    dialog_type = _EmbeddedAlignmentBuilderDialog if embedded_alignment_builder else _MeshEditorSaveAwareDialog
    dialog = dialog_type(embedded_host if embedded_alignment_builder else self)
    dialog.setObjectName("MeshReplacementAlignmentDialog")
    dialog.setWindowTitle(dialog_title)
    if embedded_alignment_builder:
        dialog.setWindowFlags(Qt.Widget)
    else:
        dialog.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        dialog.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
    dialog.setModal(False)
    dialog.setWindowModality(Qt.NonModal)
    if embedded_alignment_builder:
        dialog.setMinimumSize(0, 0)
    else:
        dialog.setMinimumSize(980, 700)
    dialog.setSizeGripEnabled(not embedded_alignment_builder)
    self._register_modeless_alignment_dialog(alignment_dialog_key, dialog)
    setattr(dialog, "_cdmw_builder_startup_progress", startup_progress)
    setattr(dialog, "_cdmw_builder_construction_context", context)
    setattr(dialog, "_cdmw_builder_construction_complete", False)
    alignment_dialog_closing = _alignment_dialog_closing_initial_state_helper()

    def _alignment_dialog_widgets_live() -> bool:
        return (
            not bool(alignment_dialog_closing.get("closing"))
            and _qt_object_is_valid(dialog)
        )

    def _complete_external_swap_enabled() -> bool:
        return False

    def _complete_external_swap_mappings() -> List[StaticSubmeshMapping]:
        return list(context.get("suggested_mappings") or [])

    def _sync_complete_external_swap_mode(_checked: bool) -> None:
        return None

    def _refresh_output_impact_review() -> None:
        return None

    def _clear_all_part_selections() -> None:
        return None

    def _d3d11_source_part_selected(_source_index: int) -> None:
        return None

    def _mesh_edit_begin_stroke(_payload: object) -> None:
        return None

    def _mesh_edit_apply_preview_payload(_payload: object) -> None:
        return None

    def _mesh_edit_finish_stroke(_payload: object) -> None:
        return None

    def _mesh_edit_cancel_stroke(_payload: object) -> None:
        return None

    def _mesh_edit_selection_changed(_payload: object) -> None:
        return None

    def _mesh_editor_dotnet_tool_changed(_payload: object) -> bool:
        return False

    alignment_texture_lookup_cache: Dict[str, object] = {
        "path": prompt_preflight.texture_entries_by_normalized_path,
        "basename": prompt_preflight.texture_entries_by_basename,
        "source": prompt_preflight.texture_lookup_source,
    }

    def _alignment_texture_lookup_indexes() -> Tuple[
        Dict[str, Sequence[ArchiveEntry]],
        Dict[str, Sequence[ArchiveEntry]],
    ]:
        return (
            prompt_preflight.texture_entries_by_normalized_path,
            prompt_preflight.texture_entries_by_basename,
        )

    _record_runtime_event(
        "mesh_alignment_texture_lookup_ready",
        path=getattr(entry, "path", ""),
        dialog_title=dialog_title,
        source=prompt_preflight.texture_lookup_source,
        dds_entries=prompt_preflight.texture_lookup_dds_count,
        related_entries=prompt_preflight.texture_lookup_sidecar_count,
        graph_entries=prompt_preflight.texture_lookup_reference_count,
        path_keys=len(prompt_preflight.texture_entries_by_normalized_path),
        basename_keys=len(prompt_preflight.texture_entries_by_basename),
        modify_original_clone=modify_original_clone_mode,
        global_path_index_ready=bool(self.archive_entries_by_normalized_path),
        global_basename_index_ready=bool(self.archive_entries_by_basename),
    )

    alignment_dialog_base_stylesheet = dialog.styleSheet()

    def _alignment_dialog_font_stylesheet() -> str:
        font_sizes = _alignment_dialog_font_sizes(context)
        ui_font_size = int(font_sizes["ui"])
        data_font_size = int(font_sizes["data"])
        hint_font_size = int(font_sizes["hint"])
        button_min_height = max(14, ui_font_size + 6)
        field_min_height = max(15, data_font_size + 7)
        help_button_size = max(16, ui_font_size + 8)
        return f"""
        QDialog#MeshReplacementAlignmentDialog {{
            font-size: {ui_font_size}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QLabel {{
            font-size: {ui_font_size}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QLabel#HintLabel {{
            color: #9aa4b2;
            font-size: {hint_font_size}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QGroupBox {{
            font-size: {ui_font_size}px;
            font-weight: 600;
            margin-top: 5px;
            padding-top: 5px;
        }}
        QDialog#MeshReplacementAlignmentDialog QGroupBox::title {{
            subcontrol-origin: margin;
            left: 5px;
            padding: 0 2px;
        }}
        QDialog#MeshReplacementAlignmentDialog QTabBar::tab {{
            font-size: {ui_font_size}px;
            padding: 2px 7px;
        }}
        QDialog#MeshReplacementAlignmentDialog QCheckBox {{
            font-size: {ui_font_size}px;
            spacing: 3px;
        }}
        QDialog#MeshReplacementAlignmentDialog QPushButton {{
            font-size: {ui_font_size}px;
            padding: 1px 5px;
            min-height: {button_min_height}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QComboBox,
        QDialog#MeshReplacementAlignmentDialog QLineEdit,
        QDialog#MeshReplacementAlignmentDialog QSpinBox,
        QDialog#MeshReplacementAlignmentDialog QDoubleSpinBox {{
            font-size: {data_font_size}px;
            min-height: {field_min_height}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QTreeWidget {{
            font-size: {data_font_size}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QTreeWidget::item {{
            padding: 0 2px;
        }}
        QDialog#MeshReplacementAlignmentDialog QHeaderView::section {{
            font-size: {data_font_size}px;
            padding: 0 3px;
        }}
        QDialog#MeshReplacementAlignmentDialog QTextBrowser,
        QDialog#MeshReplacementAlignmentDialog QTextEdit,
        QDialog#MeshReplacementAlignmentDialog QPlainTextEdit {{
            font-size: {data_font_size}px;
            line-height: 1.08;
        }}
        QDialog#MeshReplacementAlignmentDialog QProgressBar {{
            font-size: {ui_font_size}px;
            min-height: {button_min_height}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QPushButton#InlineHelpButton {{
            color: #79c0ff;
            font-weight: 700;
            min-width: {help_button_size}px;
            max-width: {help_button_size}px;
            min-height: {help_button_size}px;
            max-height: {help_button_size}px;
            padding: 0;
            border-radius: {help_button_size // 2}px;
        }}
        QDialog#MeshReplacementAlignmentDialog QFrame#MeshEditVerticalToolPalette {{
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 4px;
            padding: 2px;
        }}
        QDialog#MeshReplacementAlignmentDialog QFrame#MeshEditVerticalToolPalette QToolButton {{
            font-size: {ui_font_size}px;
            text-align: left;
            padding: 2px 6px;
            border: 1px solid #30363d;
            border-radius: 3px;
            background: #161b22;
        }}
        QDialog#MeshReplacementAlignmentDialog QFrame#MeshEditVerticalToolPalette QToolButton:checked {{
            color: #0d1117;
            background: #f78166;
            border-color: #ffab70;
            font-weight: 700;
        }}
        QDialog#MeshReplacementAlignmentDialog QFrame#ClassicMeshEditPreviewToolbar {{
            background: #111820;
            border: 1px solid #30363d;
            border-radius: 4px;
        }}
        QDialog#MeshReplacementAlignmentDialog QFrame#ClassicMeshEditPreviewActionBar QToolButton {{
            font-size: {hint_font_size}px;
            padding: 1px 3px;
            min-width: 40px;
        }}
        QDialog#MeshReplacementAlignmentDialog QFrame#ClassicMeshEditPreviewActionBar QToolButton:checked {{
            color: #0d1117;
            background: #58a6ff;
            border: 1px solid #79c0ff;
            font-weight: 700;
        }}
        QDialog#MeshReplacementAlignmentDialog QWidget#ClassicMeshEditPreviewOptions QLabel,
        QDialog#MeshReplacementAlignmentDialog QWidget#ClassicMeshEditPreviewOptions QCheckBox {{
            font-size: {hint_font_size}px;
        }}
        """

    def _sync_alignment_dialog_font(_font: object = None) -> None:
        dialog.setStyleSheet(alignment_dialog_base_stylesheet + _alignment_dialog_font_stylesheet())

    _sync_alignment_dialog_font()
    setattr(dialog, "sync_ui_font", _sync_alignment_dialog_font)

    return SimpleNamespace(
        alignment_dialog_key_hash=alignment_dialog_key_hash,
        alignment_d3d11_view_state_reset_generation=alignment_d3d11_view_state_reset_generation,
        embedded_alignment_builder=embedded_alignment_builder,
        preview_build_entry=preview_build_entry,
        modify_original_clone_mode=modify_original_clone_mode,
        original_texture_preview_default=original_texture_preview_default,
        original_texture_preview_state=original_texture_preview_state,
        original_reference_texture_preview_state=original_reference_texture_preview_state,
        alignment_startup_text=alignment_startup_text,
        startup_progress=startup_progress,
        startup_progress_closed=startup_progress_closed,
        alignment_startup_step_state=alignment_startup_step_state,
        _alignment_startup_step=_alignment_startup_step,
        _finish_alignment_startup_progress=_finish_alignment_startup_progress,
        dialog=dialog,
        alignment_dialog_closing=alignment_dialog_closing,
        _alignment_dialog_widgets_live=_alignment_dialog_widgets_live,
        _complete_external_swap_enabled=_complete_external_swap_enabled,
        _complete_external_swap_mappings=_complete_external_swap_mappings,
        _sync_complete_external_swap_mode=_sync_complete_external_swap_mode,
        _refresh_output_impact_review=_refresh_output_impact_review,
        _clear_all_part_selections=_clear_all_part_selections,
        _d3d11_source_part_selected=_d3d11_source_part_selected,
        _mesh_edit_begin_stroke=_mesh_edit_begin_stroke,
        _mesh_edit_apply_preview_payload=_mesh_edit_apply_preview_payload,
        _mesh_edit_finish_stroke=_mesh_edit_finish_stroke,
        _mesh_edit_cancel_stroke=_mesh_edit_cancel_stroke,
        _mesh_edit_selection_changed=_mesh_edit_selection_changed,
        _mesh_editor_dotnet_tool_changed=_mesh_editor_dotnet_tool_changed,
        alignment_texture_lookup_cache=alignment_texture_lookup_cache,
        _alignment_texture_lookup_indexes=_alignment_texture_lookup_indexes,
    )


__all__ = ["create_static_replacement_prompt_shell"]
