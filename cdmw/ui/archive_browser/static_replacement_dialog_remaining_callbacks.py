"""Remaining static replacement dialog callback factories."""

from __future__ import annotations

import traceback
from types import SimpleNamespace

from cdmw.ui.archive_browser import static_replacement_preview_materials as preview_materials
from cdmw.ui.archive_browser.static_replacement_sparse_history import (
    allow_python_mesh_history_snapshot_fallback,
    clear_mesh_history_snapshot_stack,
    clone_mesh_for_static_replacement_native_first,
    release_sparse_vertex_snapshot,
    retain_sparse_vertex_snapshot,
)

from cdmw.ui.archive_browser.static_replacement_dialog_factory_runtime import (
    run_static_replacement_factory,
)
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_preview_render_settings_part_01 as _remaining_preview_render_settings_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_geometry_history_part_01 as _remaining_geometry_history_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_original_copy_payload_part_01 as _remaining_original_copy_payload_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_source_role_flush_part_01 as _remaining_source_role_flush_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_selected_part_adjustment_part_01 as _remaining_selected_part_adjustment_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_selected_part_glow_picker_part_01 as _remaining_selected_part_glow_picker_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_static_preview_refresh_part_01 as _remaining_static_preview_refresh_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_source_material_plan_refresh_part_01 as _remaining_source_material_plan_refresh_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_remaining_manual_profile_control_part_01 as _remaining_manual_profile_control_part_01


class _StaticReplacementDialogState:
    def __init__(self, context: dict[str, object]) -> None:
        self._get_preview_render_settings = context.get('_get_preview_render_settings')
        self._set_preview_render_settings = context.get('_set_preview_render_settings')
        self._get_replacement_mesh_for_mapping = context.get('_get_replacement_mesh_for_mapping')
        self._set_replacement_mesh_for_mapping = context.get('_set_replacement_mesh_for_mapping')
        self._get_replacement_mesh_base_for_mapping = context.get('_get_replacement_mesh_base_for_mapping')
        self._set_replacement_mesh_base_for_mapping = context.get('_set_replacement_mesh_base_for_mapping')
        self._get_replacement_preview_model = context.get('_get_replacement_preview_model')
        self._set_replacement_preview_model = context.get('_set_replacement_preview_model')
        self._get_texture_sets = context.get('_get_texture_sets')
        self._set_texture_sets = context.get('_set_texture_sets')
        self._get_texture_override_preview_specs = context.get('_get_texture_override_preview_specs')
        self._set_texture_override_preview_specs = context.get('_set_texture_override_preview_specs')
        self._get_original_reference_preview_model = context.get('_get_original_reference_preview_model')
        self._set_original_reference_preview_model = context.get('_set_original_reference_preview_model')

    @property
    def preview_render_settings(self):
        return self._get_preview_render_settings()

    @preview_render_settings.setter
    def preview_render_settings(self, value) -> None:
        self._set_preview_render_settings(value)

    @property
    def replacement_mesh_for_mapping(self):
        return self._get_replacement_mesh_for_mapping()

    @replacement_mesh_for_mapping.setter
    def replacement_mesh_for_mapping(self, value) -> None:
        self._set_replacement_mesh_for_mapping(value)

    @property
    def replacement_mesh_base_for_mapping(self):
        return self._get_replacement_mesh_base_for_mapping()

    @replacement_mesh_base_for_mapping.setter
    def replacement_mesh_base_for_mapping(self, value) -> None:
        self._set_replacement_mesh_base_for_mapping(value)

    @property
    def replacement_preview_model(self):
        return self._get_replacement_preview_model()

    @replacement_preview_model.setter
    def replacement_preview_model(self, value) -> None:
        self._set_replacement_preview_model(value)

    @property
    def texture_sets(self):
        return self._get_texture_sets()

    @texture_sets.setter
    def texture_sets(self, value) -> None:
        self._set_texture_sets(value)

    @property
    def texture_override_preview_specs(self):
        return self._get_texture_override_preview_specs()

    @texture_override_preview_specs.setter
    def texture_override_preview_specs(self, value) -> None:
        self._set_texture_override_preview_specs(value)

    @property
    def original_reference_preview_model(self):
        return self._get_original_reference_preview_model()

    @original_reference_preview_model.setter
    def original_reference_preview_model(self, value) -> None:
        self._set_original_reference_preview_model(value)



def create_alignment_preview_render_settings_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_preview_render_settings_part_01.STEPS,),
    )


def create_alignment_geometry_history_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_geometry_history_part_01.STEPS,),
    )


def create_alignment_mapping_edit_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QLineEdit = context.get('QLineEdit')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _flush_mapping_edit_refresh = context.get('_flush_mapping_edit_refresh')
    _mapping_target_index_for_edit_helper = context.get('_mapping_target_index_for_edit_helper')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _sync_target_mapping_tree_item = context.get('_sync_target_mapping_tree_item')
    edit = context.get('edit')
    dialog = context.get('dialog')
    mapping_edits = context.get('mapping_edits')
    next_text = context.get('next_text')
    previous_text = context.get('previous_text')
    self = context.get('self')
    target_index = context.get('target_index')
    texture_overrides_dirty = context.get('texture_overrides_dirty')

    def _active_mesh_edit_mapping_mutation_blocked() -> bool:
        if not (callable(_alignment_mesh_edit_tab_active) and _alignment_mesh_edit_tab_active()):
            return False
        if bool(getattr(dialog, '_mesh_editor_embedded_dotnet_active', False)) and callable(getattr(dialog, '_mesh_editor_embedded_apply_material_parameters', None)):
            return False
        message = (
            "Active Mesh Editor mapping edits require native material execution; "
            "Python routing mutation fallback is disabled."
        )
        set_status_message = getattr(self, "set_status_message", None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True

    def _commit_mapping_edit(edit: QLineEdit) -> None:
        target_index = _mapping_target_index_for_edit_helper(mapping_edits, edit)
        previous_text = str(edit.property('committed_mapping_text') or '')
        next_text = edit.text().strip()
        if previous_text == next_text:
            return
        if _active_mesh_edit_mapping_mutation_blocked():
            return
        _push_geometry_undo_snapshot('Apply advanced mapping', metadata_only=True)
        texture_overrides_dirty['dirty'] = True
        edit.setProperty('committed_mapping_text', next_text)
        _sync_target_mapping_tree_item(target_index)
        _flush_mapping_edit_refresh()

    return SimpleNamespace(_commit_mapping_edit=_commit_mapping_edit)


def create_alignment_original_source_filter_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QEvent = context.get('QEvent')
    QObject = context.get('QObject')
    QTreeWidget = context.get('QTreeWidget')
    Qt = context.get('Qt')
    _qt_object_is_valid = context.get('_qt_object_is_valid')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _source_tree_context_selection_record_multi_indices_helper = context.get('_source_tree_context_selection_record_multi_indices_helper')
    _source_tree_context_selection_set_right_press_helper = context.get('_source_tree_context_selection_set_right_press_helper')
    button = context.get('button')
    event = context.get('event')
    event_type = context.get('event_type')
    selected_indices = context.get('selected_indices')
    self = context.get('self')
    source_tree_context_selection_state = context.get('source_tree_context_selection_state')
    tree = context.get('tree')
    watched = context.get('watched')

    class _SourceTreeContextSelectionFilter(QObject):

        def __init__(self, tree: QTreeWidget) -> None:
            super().__init__(tree)
            self._tree = tree
            self._viewport = tree.viewport()

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if watched is not self._viewport or not _qt_object_is_valid(self._tree):
                return False
            try:
                event_type = event.type()
            except RuntimeError:
                return False
            if event_type == QEvent.MouseButtonPress:
                try:
                    button = event.button()
                except Exception:
                    button = None
                if button == Qt.RightButton:
                    _source_tree_context_selection_set_right_press_helper(source_tree_context_selection_state, True)
                    selected_indices = tuple(_selected_source_indices_from_tree(include_fallback=False))
                    if len(selected_indices) > 1:
                        _source_tree_context_selection_record_multi_indices_helper(source_tree_context_selection_state, selected_indices)
                elif button == Qt.LeftButton:
                    _source_tree_context_selection_set_right_press_helper(source_tree_context_selection_state, False)
            return False

    return SimpleNamespace(_SourceTreeContextSelectionFilter=_SourceTreeContextSelectionFilter)


def create_alignment_original_reference_preview_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _clone_preview_model = context.get('_clone_preview_model')
    _original_reference_preview_model_state_helper = context.get('_original_reference_preview_model_state_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    highlighted_original_indices = context.get('highlighted_original_indices')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    original_dialog_preview = context.get('original_dialog_preview')
    original_texture_preview_state = context.get('original_texture_preview_state')
    preview_model = context.get('preview_model')
    view_state = context.get('view_state')

    def _refresh_original_reference_preview() -> None:
        if state.original_reference_preview_model is None:
            return
        if _alignment_d3d11_preview_active():
            _sync_highlight_sets()
            return
        preview_model = _original_reference_preview_model_state_helper(state.original_reference_preview_model, highlighted_indices=highlighted_original_indices, preserve_material_preview=_original_texture_preview_material_preview_enabled_helper(modify_original_clone_mode, original_texture_preview_state), clone_model=_clone_preview_model)
        view_state = original_dialog_preview.view_state_snapshot()
        original_dialog_preview.set_model(preview_model)
        original_dialog_preview.restore_view_state(view_state)
        original_dialog_preview.set_use_textures(True)
        original_dialog_preview.set_high_quality_textures(True)

    return SimpleNamespace(_refresh_original_reference_preview=_refresh_original_reference_preview)


def create_alignment_original_copy_payload_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_original_copy_payload_part_01.STEPS,),
    )


def create_alignment_original_part_copy_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QMessageBox = context.get('QMessageBox')
    _append_original_part_payload_as_source = context.get('_append_original_part_payload_as_source')
    _copy_original_part_payload = context.get('_copy_original_part_payload')
    _selected_original_index_from_tree = context.get('_selected_original_index_from_tree')
    assign_to_target = context.get('assign_to_target')
    dialog = context.get('dialog')
    original_index = context.get('original_index')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_part_clipboard_action_text = context.get('original_part_clipboard_action_text')
    payload = context.get('payload')

    def _copy_selected_original_part(*, assign_to_target: bool = False) -> None:
        if original_mesh_for_mapping is None or state.replacement_mesh_for_mapping is None:
            return
        original_index = _selected_original_index_from_tree()
        payload = _copy_original_part_payload(original_index)
        if payload is None:
            QMessageBox.information(dialog, original_part_clipboard_action_text['select_original_title'], original_part_clipboard_action_text['select_original_message'])
            return
        _append_original_part_payload_as_source(payload, assign_to_target=assign_to_target, preview_only=not assign_to_target, undo_label=original_part_clipboard_action_text['copy_undo_label'])

    return SimpleNamespace(_copy_selected_original_part=_copy_selected_original_part)


def create_alignment_source_role_flush_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_source_role_flush_part_01.STEPS,),
    )


def create_alignment_selected_part_adjustment_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_selected_part_adjustment_part_01.STEPS,),
    )


def create_alignment_selected_part_glow_picker_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_selected_part_glow_picker_part_01.STEPS,),
    )


def create_alignment_static_preview_refresh_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_static_preview_refresh_part_01.STEPS,),
    )


def create_alignment_original_texture_worker_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    ModelPreviewData = context.get('ModelPreviewData')
    QObject = context.get('QObject')
    Slot = context.get('Slot')
    _alignment_d3d11_clear_archive_parity_upgrade_helper = context.get('_alignment_d3d11_clear_archive_parity_upgrade_helper')
    _alignment_d3d11_invalidate_package_cache = context.get('_alignment_d3d11_invalidate_package_cache')
    _alignment_d3d11_original_texture_worker_request_current_helper = context.get('_alignment_d3d11_original_texture_worker_request_current_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_reset_request_state_helper = context.get('_alignment_d3d11_reset_request_state_helper')
    _alignment_d3d11_stop_worker = context.get('_alignment_d3d11_stop_worker')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _handle_original_reference_texture_preview_error = context.get('_handle_original_reference_texture_preview_error')
    _mark_alignment_d3d11_rebuild_reason = context.get('_mark_alignment_d3d11_rebuild_reason')
    _original_reference_texture_preview_ready_result_state_helper = context.get('_original_reference_texture_preview_ready_result_state_helper')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _record_runtime_event = context.get('_record_runtime_event')
    if not callable(_record_runtime_event):
        _record_runtime_event = lambda *_args, **_kwargs: None
    _set_alignment_d3d11_progress = context.get('_set_alignment_d3d11_progress')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    dialog_title = context.get('dialog_title')
    dialog = context.get('dialog')
    entry = context.get('entry')
    elapsed_ms = context.get('elapsed_ms')
    message = context.get('message')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    native_material_batches = context.get('native_material_batches')
    original_dialog_preview = context.get('original_dialog_preview')
    original_reference_texture_preview_state = context.get('original_reference_texture_preview_state')
    preview_model = context.get('preview_model')
    preview_model_object = context.get('preview_model_object')
    ready_state = context.get('ready_state')
    request_id = context.get('request_id')

    def _handle_original_reference_texture_preview_ready(request_id: int, preview_model_object: object, native_material_batches: int, elapsed_ms: float) -> None:
        ready_state = _original_reference_texture_preview_ready_result_state_helper(original_reference_texture_preview_state, request_current=_alignment_d3d11_original_texture_worker_request_current_helper(alignment_d3d11_state, request_id), widgets_live=_alignment_dialog_widgets_live(), native_material_batches=native_material_batches, elapsed_ms=elapsed_ms, d3d11_preview_active=_alignment_d3d11_preview_active())
        if not ready_state.handled:
            return
        _record_runtime_event(
            "mesh_alignment_original_texture_preview_ready",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            request_id=int(request_id or 0),
            native_material_batches=int(native_material_batches or 0),
            d3d11_preview_active=bool(_alignment_d3d11_preview_active()),
            modify_original_clone=modify_original_clone_mode,
        )
        state.original_reference_preview_model = preview_model_object if isinstance(preview_model_object, ModelPreviewData) else state.original_reference_preview_model
        if isinstance(preview_model_object, ModelPreviewData):
            preview_materials.apply_resolved_original_materials_to_resident_editor(
                dialog=dialog,
                replacement_mesh_base=state.replacement_mesh_base_for_mapping,
                replacement_mesh=state.replacement_mesh_for_mapping,
                preview_model=preview_model_object,
                modify_original_clone_mode=bool(modify_original_clone_mode),
                publish_resident_updates=not (
                    bool(modify_original_clone_mode) and int(native_material_batches or 0) > 0
                ),
            )
        if ready_state.should_apply_manifest_performance:
            _set_preview_performance_status(ready_state.manifest_performance.summary, details=ready_state.manifest_performance.details)
        _alignment_d3d11_reset_request_state_helper(alignment_d3d11_state, clear_active_request_id=False)
        _alignment_d3d11_stop_worker()
        _alignment_d3d11_invalidate_package_cache('material')
        if ready_state.should_update_d3d11_progress:
            _set_alignment_d3d11_progress(15, ready_state.progress_message, stage='source_textures', detail=ready_state.progress_detail)
        elif ready_state.should_apply_model:
            original_dialog_preview.set_model(state.original_reference_preview_model)
            original_dialog_preview.set_use_textures(True)
            original_dialog_preview.set_high_quality_textures(True)
        _alignment_d3d11_clear_archive_parity_upgrade_helper(alignment_d3d11_state)
        _set_preview_performance_status(ready_state.loaded_performance.summary, details=ready_state.loaded_performance.details)
        _mark_alignment_d3d11_rebuild_reason('material')
        _queue_static_preview_refresh()
    class _OriginalTexturePreviewWorkerReceiver(QObject):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self._thread_finished_callbacks: dict[object, tuple[object, object]] = {}

        @Slot(int, object, int, float)
        def handle_completed(self, request_id: int, preview_model: object, native_material_batches: int, elapsed_ms: float) -> None:
            _handle_original_reference_texture_preview_ready(request_id, preview_model, native_material_batches, elapsed_ms)

        @Slot(int, str)
        def handle_error(self, request_id: int, message: str) -> None:
            _handle_original_reference_texture_preview_error(request_id, message)
        def watch_thread(self, thread: object, worker: object, callback: object, connection_type: object) -> None:
            self._thread_finished_callbacks[thread] = (worker, callback)
            thread.finished.connect(self.handle_thread_finished, connection_type)
        @Slot()
        def handle_thread_finished(self) -> None:
            thread = self.sender()
            worker, callback = self._thread_finished_callbacks.pop(thread, (None, None))
            if callable(callback):
                callback(thread, worker)

    return SimpleNamespace(_handle_original_reference_texture_preview_ready=_handle_original_reference_texture_preview_ready, _OriginalTexturePreviewWorkerReceiver=_OriginalTexturePreviewWorkerReceiver)


def create_alignment_added_part_texture_override_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    _added_part_texture_override_action_state_helper = context.get('_added_part_texture_override_action_state_helper')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_added_part_texture_tree = context.get('_refresh_added_part_texture_tree')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _source_material_name_for_index_helper = context.get('_source_material_name_for_index_helper')
    action_state = context.get('action_state')
    assignment_key = context.get('assignment_key')
    inject_base_color_checkbox = context.get('inject_base_color_checkbox')
    material_name = context.get('material_name')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    slot_kind = context.get('slot_kind')
    source_index = context.get('source_index')
    source_material_texture_override_assignments = context.get('source_material_texture_override_assignments')
    source_path = context.get('source_path')
    self = context.get('self')
    texture_overrides_dirty = context.get('texture_overrides_dirty')

    def _active_mesh_edit_added_part_texture_override_blocked() -> bool:
        if not (callable(_alignment_mesh_edit_tab_active) and _alignment_mesh_edit_tab_active()):
            return False
        message = (
            "Active Mesh Editor added-part texture overrides require native material execution; "
            "Python texture override mutation fallback is disabled."
        )
        set_status_message = getattr(self, "set_status_message", None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True

    def _set_added_part_texture_override(source_index: int, slot_kind: str, source_path: str) -> None:
        material_name = _source_material_name_for_index_helper(source_index, state.replacement_mesh_for_mapping, state.texture_sets)
        action_state = _added_part_texture_override_action_state_helper(source_index=source_index, material_name=material_name, slot_kind=slot_kind, source_path=source_path)
        if not action_state['apply']:
            return
        if _active_mesh_edit_added_part_texture_override_blocked():
            return
        assignment_key = action_state['assignment_key']
        if not action_state['clear']:
            source_material_texture_override_assignments[assignment_key] = str(action_state['source_path'])
            rebuild_sidecar_checkbox.setChecked(True)
            if action_state['enable_inject_base_color']:
                inject_base_color_checkbox.setChecked(True)
        else:
            source_material_texture_override_assignments.pop(assignment_key, None)
        texture_overrides_dirty['dirty'] = bool(action_state['mark_dirty'])
        try:
            _refresh_source_material_plan()
        except NameError:
            _refresh_added_part_texture_tree(source_index)
        _queue_texture_preview_refresh()

    return SimpleNamespace(_set_added_part_texture_override=_set_added_part_texture_override)


def create_alignment_added_part_texture_choice_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Path = context.get('Path')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    SCENE_TEXTURE_SOURCE_EXTENSIONS = context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    _added_part_texture_choose_dialog_state_helper = context.get('_added_part_texture_choose_dialog_state_helper')
    _added_part_texture_invalid_file_message_helper = context.get('_added_part_texture_invalid_file_message_helper')
    _current_added_part_texture_source_index = context.get('_current_added_part_texture_source_index')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _register_added_part_texture_file = context.get('_register_added_part_texture_file')
    _set_added_part_texture_override = context.get('_set_added_part_texture_override')
    choose_state = context.get('choose_state')
    dialog = context.get('dialog')
    obj_path = context.get('obj_path')
    path = context.get('path')
    resolved = context.get('resolved')
    selected_file = context.get('selected_file')
    slot_kind = context.get('slot_kind')
    source_index = context.get('source_index')

    def _choose_added_part_texture(slot_kind: str) -> None:
        source_index = _current_added_part_texture_source_index()
        choose_state = _added_part_texture_choose_dialog_state_helper(source_index, slot_kind)
        if not choose_state['can_choose']:
            QMessageBox.information(dialog, str(choose_state['title']), str(choose_state['message']))
            return
        selected_file, _ = QFileDialog.getOpenFileName(dialog, str(choose_state['title']), str(obj_path.parent), 'Texture files (*.dds *.png *.tga *.bmp *.jpg *.jpeg);;All files (*.*)')
        if not selected_file:
            return
        path = Path(selected_file)
        if path.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
            QMessageBox.warning(dialog, str(choose_state['invalid_title']), str(_added_part_texture_invalid_file_message_helper(path.name)))
            return
        resolved = _register_added_part_texture_file(path)
        _set_added_part_texture_override(source_index, slot_kind, str(resolved))
        _refresh_source_material_plan()

    return SimpleNamespace(_choose_added_part_texture=_choose_added_part_texture)


def create_alignment_preview_pixmap_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    Path = context.get('Path')
    QImageReader = context.get('QImageReader')
    QPixmap = context.get('QPixmap')
    image = context.get('image')
    preview_path = context.get('preview_path')
    reader = context.get('reader')

    def _read_preview_pixmap(preview_path: Path) -> Optional[QPixmap]:
        reader = QImageReader(str(preview_path))
        image = reader.read()
        if image.isNull():
            return None
        return QPixmap.fromImage(image)

    return SimpleNamespace(_read_preview_pixmap=_read_preview_pixmap)


def create_alignment_source_material_plan_refresh_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_source_material_plan_refresh_part_01.STEPS,),
    )


def create_alignment_complete_swap_profile_select_callbacks(context: dict[str, object]) -> SimpleNamespace:
    _material_authority_requested_profile_name_helper = context.get('_material_authority_requested_profile_name_helper')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    complete_swap_profile_store_path = context.get('complete_swap_profile_store_path')
    get_complete_swap_material_profile = context.get('get_complete_swap_material_profile')
    name = context.get('name')
    persist = context.get('persist')
    profile_index = context.get('profile_index')
    profile_name = context.get('profile_name')
    requested = context.get('requested')
    self = context.get('self')
    write_complete_swap_calibrated_material_profile = context.get('write_complete_swap_calibrated_material_profile')

    def _select_complete_swap_material_profile(profile_name: str, *, persist: bool = False) -> None:
        stored_name = str(profile_name or '').strip()
        requested = _material_authority_requested_profile_name_helper(profile_name, resolve_profile_name=lambda name: getattr(get_complete_swap_material_profile(str(name)), 'name', ''))
        profile_index = complete_swap_material_profile_combo.findData(requested)
        if profile_index < 0:
            requested = 'material_authority_detail_mask'
            profile_index = complete_swap_material_profile_combo.findData(requested)
        if profile_index >= 0 and complete_swap_material_profile_combo.currentIndex() != profile_index:
            complete_swap_material_profile_combo.setCurrentIndex(profile_index)
        migrate_automatic = requested == 'material_authority_detail_mask' and stored_name not in {'', requested}
        if persist or migrate_automatic:
            self.settings.setValue('settings/complete_swap_material_profile', requested)
            try:
                write_complete_swap_calibrated_material_profile(complete_swap_profile_store_path, requested)
            except Exception:
                pass

    return SimpleNamespace(_select_complete_swap_material_profile=_select_complete_swap_material_profile)


def create_alignment_manual_profile_preset_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Mapping = context.get('Mapping')
    Sequence = context.get('Sequence')
    _manual_material_profile_presets_payload_helper = context.get('_manual_material_profile_presets_payload_helper')
    json = context.get('json')
    manual_profile_default_values = context.get('manual_profile_default_values')
    manual_profile_presets_key = context.get('manual_profile_presets_key')
    payload = context.get('payload')
    presets = context.get('presets')
    self = context.get('self')

    def _save_manual_profile_presets(presets: Sequence[Mapping[str, object]]) -> None:
        payload = _manual_material_profile_presets_payload_helper(presets, defaults=manual_profile_default_values)
        self.settings.setValue(manual_profile_presets_key, json.dumps(payload, sort_keys=True, separators=(',', ':')))

    return SimpleNamespace(_save_manual_profile_presets=_save_manual_profile_presets)


def create_alignment_manual_profile_control_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_remaining_manual_profile_control_part_01.STEPS,),
    )


def create_alignment_texture_orientation_callbacks(context: dict[str, object]) -> SimpleNamespace:
    _queue_texture_uv_preview_refresh = context.get('_queue_texture_uv_preview_refresh')
    _record_texture_uv_global_transform_state_helper = context.get('_record_texture_uv_global_transform_state_helper')
    _texture_uv_global_transform_control_state_helper = context.get('_texture_uv_global_transform_control_state_helper')
    _try_apply_global_flip_v_fast_preview = context.get('_try_apply_global_flip_v_fast_preview')
    setup_texture_flip_u_checkbox = context.get('setup_texture_flip_u_checkbox')
    setup_texture_flip_v_checkbox = context.get('setup_texture_flip_v_checkbox')
    setup_texture_rotate_combo = context.get('setup_texture_rotate_combo')
    texture_uv_global_transform_state = context.get('texture_uv_global_transform_state')

    def _save_setup_texture_orientation() -> None:
        _record_texture_uv_global_transform_state_helper(texture_uv_global_transform_state, _texture_uv_global_transform_control_state_helper(rotate_degrees=int(setup_texture_rotate_combo.currentData() or 0), flip_u=bool(setup_texture_flip_u_checkbox.isChecked()), flip_v=bool(setup_texture_flip_v_checkbox.isChecked())))
        if _try_apply_global_flip_v_fast_preview():
            return
        _queue_texture_uv_preview_refresh()

    def _reset_setup_texture_orientation() -> None:
        setup_texture_rotate_combo.setCurrentIndex(max(0, setup_texture_rotate_combo.findData(0)))
        setup_texture_flip_u_checkbox.setChecked(False)
        setup_texture_flip_v_checkbox.setChecked(False)
        _save_setup_texture_orientation()

    return SimpleNamespace(_save_setup_texture_orientation=_save_setup_texture_orientation, _reset_setup_texture_orientation=_reset_setup_texture_orientation)


def create_alignment_transform_slider_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QSlider = context.get('QSlider')
    _make_spinbox_slider_helper = context.get('_make_spinbox_slider_helper')
    alignment_transform_sliders = context.get('alignment_transform_sliders')
    scale = context.get('scale')
    slider = context.get('slider')
    slider_maximum = context.get('slider_maximum')
    slider_minimum = context.get('slider_minimum')
    spin = context.get('spin')
    tooltip = context.get('tooltip')
    transform_layout_specs = context.get('transform_layout_specs')

    def _paired_transform_slider(spin: QDoubleSpinBox, *, scale: float, tooltip: str, slider_minimum: Optional[float]=None, slider_maximum: Optional[float]=None) -> QSlider:
        slider = _make_spinbox_slider_helper(spin, scale=scale, tooltip=tooltip, object_name=str(transform_layout_specs['slider_object_name']), minimum_width=int(transform_layout_specs['slider_minimum_width']), slider_minimum=slider_minimum, slider_maximum=slider_maximum)
        alignment_transform_sliders[spin] = slider
        return slider

    return SimpleNamespace(_paired_transform_slider=_paired_transform_slider)


def create_alignment_transform_row_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    Qt = context.get('Qt')
    Sequence = context.get('Sequence')
    _alignment_transform_slider_sync_state_helper = context.get('_alignment_transform_slider_sync_state_helper')
    _spin_with_slider = context.get('_spin_with_slider')
    alignment_transform_control_text = context.get('alignment_transform_control_text')
    alignment_transform_sliders = context.get('alignment_transform_sliders')
    axis = context.get('axis')
    axis_label = context.get('axis_label')
    axis_labels = context.get('axis_labels')
    label_text = context.get('label_text')
    label_widget = context.get('label_widget')
    offset_x_spin = context.get('offset_x_spin')
    offset_y_spin = context.get('offset_y_spin')
    offset_z_spin = context.get('offset_z_spin')
    original_text = context.get('original_text')
    original_widget = context.get('original_widget')
    rotate_x_spin = context.get('rotate_x_spin')
    rotate_y_spin = context.get('rotate_y_spin')
    rotate_z_spin = context.get('rotate_z_spin')
    row_index = context.get('row_index')
    slider = context.get('slider')
    slider_maximum = context.get('slider_maximum')
    slider_minimum = context.get('slider_minimum')
    slider_scale = context.get('slider_scale')
    slider_spec = context.get('slider_spec')
    spin = context.get('spin')
    sync_state = context.get('sync_state')
    transform_layout = context.get('transform_layout')
    transform_slider_specs = context.get('transform_slider_specs')
    value_row = context.get('value_row')
    widget = context.get('widget')
    widgets = context.get('widgets')

    def _sync_alignment_transform_slider_from_spin(spin: QDoubleSpinBox) -> None:
        slider = alignment_transform_sliders.get(spin)
        if slider is None:
            return
        if spin in (offset_x_spin, offset_y_spin, offset_z_spin):
            slider_spec = transform_slider_specs['offset']
        elif spin in (rotate_x_spin, rotate_y_spin, rotate_z_spin):
            slider_spec = transform_slider_specs['rotation']
        else:
            slider_spec = transform_slider_specs['scale']
        sync_state = _alignment_transform_slider_sync_state_helper(value=spin.value(), slider_value=slider.value(), scale=slider_spec['slider_scale'])
        if not bool(sync_state['apply']):
            return
        slider.blockSignals(True)
        slider.setValue(int(sync_state['slider_value']))
        slider.blockSignals(False)

    def _add_transform_row(row_index: int, label_text: str, original_text: str, widgets: Sequence[QDoubleSpinBox], *, slider_scale: float, slider_minimum: Optional[float]=None, slider_maximum: Optional[float]=None) -> None:
        label_widget = QLabel(label_text)
        original_widget = QLabel(original_text)
        original_widget.setObjectName('HintLabel')
        original_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(3)
        axis_labels = (alignment_transform_control_text['axis_x'], alignment_transform_control_text['axis_y'], alignment_transform_control_text['axis_z'])
        for axis_label, widget in zip(axis_labels, widgets):
            axis = QLabel(axis_label)
            axis.setObjectName('HintLabel')
            value_row.addWidget(axis)
            value_row.addWidget(_spin_with_slider(widget, slider_scale=slider_scale, slider_minimum=slider_minimum, slider_maximum=slider_maximum, tooltip=alignment_transform_control_text['axis_slider_tooltip_template'].format(label=label_text, axis=axis_label)), 1)
        transform_layout.addWidget(label_widget, row_index, 0)
        transform_layout.addWidget(original_widget, row_index, 1)
        transform_layout.addLayout(value_row, row_index, 2)

    return SimpleNamespace(_sync_alignment_transform_slider_from_spin=_sync_alignment_transform_slider_from_spin, _add_transform_row=_add_transform_row)


def create_alignment_modeless_dialog_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QDialog = context.get('QDialog')
    QTimer = context.get('QTimer')
    _alignment_builder_closed_empty_state_message_helper = context.get('_alignment_builder_closed_empty_state_message_helper')
    _alignment_cancel_handler_failed_status_helper = context.get('_alignment_cancel_handler_failed_status_helper')
    _alignment_dialog_accepted_helper = context.get('_alignment_dialog_accepted_helper')
    _alignment_dialog_finished_route_helper = context.get('_alignment_dialog_finished_route_helper')
    _alignment_dialog_mark_closing_helper = context.get('_alignment_dialog_mark_closing_helper')
    _finish_alignment_startup_progress = context.get('_finish_alignment_startup_progress')
    _safe_shutdown_alignment_d3d11_preview = context.get('_safe_shutdown_alignment_d3d11_preview')
    _safe_stop_alignment_timer = context.get('_safe_stop_alignment_timer')
    _stop_original_reference_texture_worker = context.get('_stop_original_reference_texture_worker')
    alignment_dialog_closing = context.get('alignment_dialog_closing')
    alignment_dialog_key = context.get('alignment_dialog_key')
    dialog = context.get('dialog')
    dialog_accepted_state = context.get('dialog_accepted_state')
    embedded_alignment_builder = context.get('embedded_alignment_builder')
    finished_route = context.get('finished_route')
    material_edit_refresh_timer = context.get('material_edit_refresh_timer')
    on_cancel = context.get('on_cancel')
    self = context.get('self')
    source_material_plan_refresh_timer = context.get('source_material_plan_refresh_timer')

    def _modeless_alignment_dialog_finished(result: int=0) -> None:
        _alignment_dialog_mark_closing_helper(alignment_dialog_closing)
        _safe_stop_alignment_timer(material_edit_refresh_timer)
        _safe_stop_alignment_timer(source_material_plan_refresh_timer)
        if callable(_stop_original_reference_texture_worker):
            _stop_original_reference_texture_worker()
        _safe_shutdown_alignment_d3d11_preview()
        _finish_alignment_startup_progress()
        self._unregister_modeless_alignment_dialog(alignment_dialog_key, dialog)
        finished_route = _alignment_dialog_finished_route_helper(result=int(result), accepted_code=int(QDialog.Accepted), accepted=_alignment_dialog_accepted_helper(dialog_accepted_state), has_cancel_handler=on_cancel is not None, embedded_builder=bool(embedded_alignment_builder), has_mesh_editor=hasattr(self, 'mesh_editor_tab'))
        if finished_route.should_call_cancel_handler and on_cancel is not None:
            try:
                on_cancel()
            except Exception as exc:
                self.set_status_message(_alignment_cancel_handler_failed_status_helper(exc), error=True)
        dialog.deleteLater()
        if finished_route.should_show_embedded_empty_state:
            QTimer.singleShot(0, lambda: self.mesh_editor_tab.show_empty_state(_alignment_builder_closed_empty_state_message_helper()))

    return SimpleNamespace(_modeless_alignment_dialog_finished=_modeless_alignment_dialog_finished)


def create_alignment_fit_dialog_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QApplication = context.get('QApplication')
    _alignment_dialog_fit_size_helper = context.get('_alignment_dialog_fit_size_helper')
    _alignment_dialog_frame_origin_helper = context.get('_alignment_dialog_frame_origin_helper')
    _apply_alignment_dialog_responsive_layout = context.get('_apply_alignment_dialog_responsive_layout')
    available = context.get('available')
    dialog = context.get('dialog')
    fit_size = context.get('fit_size')
    frame = context.get('frame')
    frame_origin = context.get('frame_origin')
    screen = context.get('screen')
    self = context.get('self')

    def _fit_alignment_dialog_to_screen() -> None:
        screen = dialog.screen() or self.screen() or QApplication.primaryScreen()
        if screen is None:
            dialog.resize(1500, 820)
            _apply_alignment_dialog_responsive_layout(force_sizes=True)
            return
        available = screen.availableGeometry()
        fit_size = _alignment_dialog_fit_size_helper(available_width=int(available.width()), available_height=int(available.height()))
        dialog.resize(fit_size.width, fit_size.height)
        frame = dialog.frameGeometry()
        frame.moveCenter(available.center())
        frame_origin = _alignment_dialog_frame_origin_helper(available_left=int(available.left()), available_top=int(available.top()), available_right=int(available.right()), available_bottom=int(available.bottom()), frame_left=int(frame.left()), frame_top=int(frame.top()), frame_width=int(frame.width()), frame_height=int(frame.height()))
        dialog.move(frame_origin.left, frame_origin.top)
        _apply_alignment_dialog_responsive_layout(force_sizes=True)

    return SimpleNamespace(_fit_alignment_dialog_to_screen=_fit_alignment_dialog_to_screen)
