"""Workers callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_workers_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_can_edit_scope(_state, _callbacks, ) -> tuple[bool, str]:
    allowed_indices = _state._mesh_edit_allowed_source_indices()
    return _state._mesh_edit_can_edit_scope_helper(
        mesh_edit_supported=_state.mesh_edit_supported,
        scope_mode=_state._mesh_edit_scope_mode(),
        selected_scope_source_index=_state._mesh_edit_selected_scope_source_index(),
        allowed_source_count=len(allowed_indices),
        current_tool=_state._mesh_edit_current_tool(),
        morph_slider_has_nonzero_values=_state._morph_slider_has_nonzero_values(),
    )

def _alignment_d3d11_mesh_edit_commands_active(_state, _callbacks, ) -> bool:
    return bool(
        _state._alignment_d3d11_preview_active()
        and callable(getattr(_state.alignment_d3d11_preview_host, "set_mesh_edit_state", None))
        and callable(getattr(_state.alignment_d3d11_preview_host, "update_mesh_edit_vertices", None))
        and callable(getattr(_state.alignment_d3d11_preview_host, "replace_mesh_edit_triangles", None))
    )

def _sync_mesh_edit_preview_settings(_state, _callbacks, ) -> None:
    allowed_indices = _state._mesh_edit_allowed_source_indices()
    active = (
        bool(_state.mesh_edit_enabled_checkbox.isChecked())
        and _state._mesh_edit_tab_active()
        and _callbacks._mesh_edit_can_edit_scope()[0]
    )
    tool = _state._mesh_edit_current_tool()
    target_mode = _callbacks._mesh_edit_target_mode_for_tool()
    delete_mode = str(_state.mesh_edit_delete_mode_combo.currentData() or "release")
    if _callbacks._alignment_d3d11_mesh_edit_commands_active():
        if active:
            _state._clear_alignment_d3d11_fast_transform_state()
            _state.alignment_d3d11_preview_host.set_alignment_state(
                enabled=False,
                source_submesh_indices=(),
                translation_sensitivity=0.85,
                rotation_degrees_per_pixel=0.18,
            )
            _state.alignment_d3d11_preview_host.set_alignment_preview_transform()
        _state.alignment_d3d11_preview_host.set_mesh_edit_state(
            enabled=active,
            scope_mode=_state._mesh_edit_scope_mode(),
            source_submesh_indices=allowed_indices,
            target_mode=target_mode,
            tool=tool,
            delete_mode=delete_mode,
            radius_pixels=float(_state.mesh_edit_radius_spin.value()),
            strength=float(_state.mesh_edit_strength_spin.value()) / 100.0,
            falloff=str(_state.mesh_edit_falloff_combo.currentData() or "smooth"),
            show_vertices=bool(_state.mesh_edit_show_vertices_checkbox.isChecked()),
            selection_mode=_state._mesh_edit_selection_mode(),
            selection_depth_mode=_state._mesh_edit_selection_depth_mode(),
            smooth_iterations=int(_state.mesh_edit_iterations_spin.value()),
        )
    for preview_widget in (_state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
        preview_widget.set_mesh_edit_target_mode(target_mode)
        preview_widget.set_mesh_edit_tool(tool)
        if hasattr(preview_widget, "set_mesh_edit_source_submesh_indices"):
            preview_widget.set_mesh_edit_source_submesh_indices(allowed_indices)
        if hasattr(preview_widget, "set_mesh_edit_delete_mode"):
            preview_widget.set_mesh_edit_delete_mode(delete_mode)
        preview_widget.set_mesh_edit_brush_settings(
            radius_pixels=float(_state.mesh_edit_radius_spin.value()),
            strength=float(_state.mesh_edit_strength_spin.value()) / 100.0,
            falloff=str(_state.mesh_edit_falloff_combo.currentData() or "smooth"),
            show_vertices=bool(_state.mesh_edit_show_vertices_checkbox.isChecked()),
        )
        preview_widget.set_mesh_editing_enabled(active)

def _mesh_edit_topology_worker_active(_state, _callbacks, ) -> bool:
    thread = _state.mesh_edit_topology_worker_state.get("thread")
    is_running = getattr(thread, "isRunning", None)
    return bool(callable(is_running) and is_running())

def _mesh_edit_selection_worker_active(_state, _callbacks, ) -> bool:
    thread = _state.mesh_edit_selection_worker_state.get("thread")
    is_running = getattr(thread, "isRunning", None)
    return bool(callable(is_running) and is_running())

def _mesh_edit_worker_active(_state, _callbacks, ) -> bool:
    return _callbacks._mesh_edit_topology_worker_active() or _callbacks._mesh_edit_selection_worker_active()

def _mesh_edit_should_run_topology_worker(_state, _callbacks,
        selected_vertices: _state.Mapping[int, object] | None,
        selected_faces: _state.Mapping[int, object] | None,
        selected_edges: _state.Mapping[int, object] | None,
        selected_source_indices: _state.Sequence[int] | None = None,
    ) -> bool:
    _ = selected_vertices, selected_faces, selected_edges, selected_source_indices
    if _state.QThread is None or _state.QProgressDialog is None:
        return False
    return True

def _mesh_edit_cancel_topology_worker(_state, _callbacks, ) -> None:
    worker = _state.mesh_edit_topology_worker_state.get("worker")
    stop = getattr(worker, "stop", None)
    if callable(stop):
        stop()
    progress = _state.mesh_edit_topology_worker_state.get("progress")
    set_label = getattr(progress, "setLabelText", None)
    if callable(set_label):
        set_label("Cancelling mesh edit...")
    _state.self.set_status_message("Cancelling mesh edit...")

def _mesh_edit_topology_worker_progress(_state, _callbacks, request_id: int, percent: int, message: str) -> None:
    if int(request_id) != int(_state.mesh_edit_topology_worker_state.get("request_id", 0) or 0):
        return
    progress = _state.mesh_edit_topology_worker_state.get("progress")
    set_value = getattr(progress, "setValue", None)
    set_label = getattr(progress, "setLabelText", None)
    if callable(set_value):
        set_value(max(0, min(100, int(percent))))
    if callable(set_label) and message:
        set_label(str(message))

def _mesh_edit_finish_topology_worker(_state, _callbacks, request_id: int) -> None:
    if int(request_id) != int(_state.mesh_edit_topology_worker_state.get("request_id", 0) or 0):
        return
    progress = _state.mesh_edit_topology_worker_state.get("progress")
    disconnect = getattr(getattr(progress, "canceled", None), "disconnect", None)
    if callable(disconnect):
        try:
            disconnect(_callbacks._mesh_edit_cancel_topology_worker)
        except (TypeError, RuntimeError):
            pass
    close = getattr(progress, "close", None)
    delete_later = getattr(progress, "deleteLater", None)
    if callable(close):
        close()
    if callable(delete_later):
        delete_later()
    _state.mesh_edit_topology_worker_state.update(
        {
            "thread": None,
            "worker": None,
            "progress": None,
            "start_revision": 0,
        }
    )
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_topology_worker_failed(_state, _callbacks, request_id: int, message: str) -> None:
    if int(request_id) != int(_state.mesh_edit_topology_worker_state.get("request_id", 0) or 0):
        return
    _callbacks._mesh_edit_pop_undo_snapshot()
    _state._pop_geometry_undo_snapshot()
    _callbacks._refresh_mesh_edit_controls()
    _state.self.set_status_message(str(message or "Mesh edit failed."), error=True)

def _mesh_edit_topology_worker_cancelled(_state, _callbacks, request_id: int, message: str) -> None:
    if int(request_id) != int(_state.mesh_edit_topology_worker_state.get("request_id", 0) or 0):
        return
    _callbacks._mesh_edit_pop_undo_snapshot()
    _state._pop_geometry_undo_snapshot()
    _callbacks._refresh_mesh_edit_controls()
    _state.self.set_status_message(str(message or "Mesh edit cancelled."))

def _mesh_edit_topology_worker_completed(_state, _callbacks,
        request_id: int,
        result: object,
        commit_callback: object,
        result_adapter: object | None = None,
    ) -> None:
    if int(request_id) != int(_state.mesh_edit_topology_worker_state.get("request_id", 0) or 0):
        return
    start_revision = int(_state.mesh_edit_topology_worker_state.get("start_revision", 0) or 0)
    if int(_state.mesh_edit_revision.get("value", 0) or 0) != start_revision:
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._refresh_mesh_edit_controls()
        _state.self.set_status_message("Mesh edit result was discarded because the mesh changed while it was running.", error=True)
        return
    if callable(result_adapter):
        try:
            result = result_adapter(result)
        except Exception as exc:
            _callbacks._mesh_edit_topology_worker_failed(request_id, f"{type(exc).__name__}: {exc}")
            return
    if callable(commit_callback):
        commit_callback(result)

def _mesh_edit_start_topology_worker(_state, _callbacks,
        action: str,
        *,
        action_text: str,
        selected_vertices: _state.Mapping[int, object] | None,
        selected_faces: _state.Mapping[int, object] | None,
        selected_edges: _state.Mapping[int, object] | None,
        params: _state.Mapping[str, object],
        commit_callback: object,
        selected_source_indices: _state.Sequence[int] | None = None,
    ) -> bool:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return False
    if _callbacks._mesh_edit_worker_active():
        _state.self.set_status_message("Wait for the current mesh edit to finish, or cancel it first.", error=True)
        return True
    if not _callbacks._mesh_edit_should_run_topology_worker(
        selected_vertices,
        selected_faces,
        selected_edges,
        selected_source_indices,
    ):
        return False
    request_id = int(_state.mesh_edit_topology_worker_state.get("request_id", 0) or 0) + 1
    _callbacks._mesh_edit_record_snapshot()
    session = _callbacks._mesh_editor_ensure_static_replacement_session(_state._mesh_edit_state.replacement_mesh_for_mapping)
    if not isinstance(session, _state.StaticReplacementMeshEditSession):
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        return False
    selection = _state.MeshEditSelection.from_maps(
        vertices_by_submesh=selected_vertices,
        edges_by_submesh=selected_edges,
        faces_by_submesh=selected_faces,
        source_indices=selected_source_indices,
    )
    before = session.submesh_counts
    service_action = "separate" if str(action or "").strip().lower() == "split" else str(action or "")
    action_params = dict(params or {})
    command_mode = action_params.pop("mode", None) or (
        "sculpt" if str(service_action).strip().lower() == "brush" else "edit"
    )
    command = _state.MeshEditCommand(
        action=service_action,
        selection=selection,
        params=action_params,
        mode=str(command_mode),
    )

    def _result_adapter(edit_result: object) -> object:
        return session._result(edit_result, before=before, selection=selection)

    worker = _state.MeshEditCommandWorker(
        request_id,
        session.controller.mesh_service,
        session.session_id,
        command,
        action_text=action_text,
    )
    thread = _state.QThread(_state.dialog)
    progress = _state.QProgressDialog(f"Applying {action_text}...", "Cancel", 0, 100, _state.dialog)
    progress.setWindowTitle(_state._mesh_edit_dialog_title_helper())
    progress.setWindowModality(_state.Qt.WindowModal)
    progress.setMinimumDuration(250)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.canceled.connect(_callbacks._mesh_edit_cancel_topology_worker)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress_changed.connect(_callbacks._mesh_edit_topology_worker_progress)
    worker.completed.connect(
        lambda finished_request_id, result, callback=commit_callback, adapter=_result_adapter: _callbacks._mesh_edit_topology_worker_completed(
            finished_request_id,
            result,
            callback,
            adapter,
        )
    )
    worker.cancelled.connect(_callbacks._mesh_edit_topology_worker_cancelled)
    worker.error.connect(_callbacks._mesh_edit_topology_worker_failed)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(lambda finished_request_id=request_id: _callbacks._mesh_edit_finish_topology_worker(finished_request_id))
    _state.mesh_edit_topology_worker_state.update(
        {
            "request_id": request_id,
            "thread": thread,
            "worker": worker,
            "progress": progress,
            "start_revision": int(_state.mesh_edit_revision.get("value", 0) or 0),
        }
    )
    _callbacks._refresh_mesh_edit_controls()
    _state.self.set_status_message(f"Applying {action_text} in the background...")
    thread.start(_state.QThread.LowPriority)
    return True

def _sync_mesh_editor_tab_action_state(_state, _callbacks,
        *,
        editing_active: bool,
        sculpt_tool: bool,
        selected_count: int,
        selected_face_count: int,
        selected_edge_count: int = 0,
    ) -> None:
    active_selection_mode = str(_state.mesh_editor_action_bar_selection_mode.get("value") or "vertex")
    mode = "edit" if editing_active else "object"
    selection_empty = (int(selected_count or 0) + int(selected_face_count or 0) + int(selected_edge_count or 0)) <= 0
    active_tool_key = _callbacks._mesh_editor_active_tool_action_key()
    mesh_editor_tab = getattr(_state.self, "mesh_editor_tab", None)
    update_action_state = getattr(mesh_editor_tab, "update_editor_action_state", None)
    if callable(update_action_state):
        update_action_state(
            mode=mode,
            active_selection_mode=active_selection_mode,
            active_tool_key=active_tool_key,
            selection_empty=selection_empty,
            undo_count=len(_state.mesh_edit_undo_stack),
            redo_count=len(_state.mesh_edit_redo_stack),
        )
    compact_update = getattr(_state.classic_mesh_edit_action_bar, "update_action_state", None)
    if callable(compact_update):
        compact_update(
            has_target=bool(_state.mesh_edit_supported),
            selection_empty=selection_empty,
            mode=mode,
            active_selection_mode=active_selection_mode,
            active_tool_key=active_tool_key,
            undo_count=len(_state.mesh_edit_undo_stack),
            redo_count=len(_state.mesh_edit_redo_stack),
        )
    compact_set_enabled = getattr(_state.classic_mesh_edit_action_bar, "setEnabled", None)
    if callable(compact_set_enabled):
        compact_set_enabled(not _callbacks._mesh_edit_worker_active())

def _show_mesh_edit_tab(_state, _callbacks, ) -> None:
    _callbacks._refresh_mesh_edit_controls()
    if callable(_state._apply_alignment_dialog_responsive_layout):
        _state._apply_alignment_dialog_responsive_layout()


_CALLBACKS = (
    _mesh_edit_can_edit_scope,
    _alignment_d3d11_mesh_edit_commands_active,
    _sync_mesh_edit_preview_settings,
    _mesh_edit_topology_worker_active,
    _mesh_edit_selection_worker_active,
    _mesh_edit_worker_active,
    _mesh_edit_should_run_topology_worker,
    _mesh_edit_cancel_topology_worker,
    _mesh_edit_topology_worker_progress,
    _mesh_edit_finish_topology_worker,
    _mesh_edit_topology_worker_failed,
    _mesh_edit_topology_worker_cancelled,
    _mesh_edit_topology_worker_completed,
    _mesh_edit_start_topology_worker,
    _sync_mesh_editor_tab_action_state,
    _show_mesh_edit_tab,
)
