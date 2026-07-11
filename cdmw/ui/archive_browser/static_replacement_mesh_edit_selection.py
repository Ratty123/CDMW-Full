"""Selection callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_selection_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_clear_vertex_selection(_state, _callbacks, ) -> None:
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_edges_by_submesh.clear()
    _state.mesh_edit_selected_faces_by_submesh.clear()
    _state.mesh_edit_selected_source_indices.clear()
    if _state._alignment_d3d11_preview_active():
        _state.alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
        _callbacks._refresh_mesh_edit_controls()
        return
    for preview_widget in (_state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
        preview_widget.clear_mesh_edit_vertex_selection()
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_current_selection(_state, _callbacks, ) -> _state.MeshEditSelection:
    return _state.MeshEditSelection.from_maps(
        vertices_by_submesh=_state.mesh_edit_selected_vertices_by_submesh,
        edges_by_submesh=_state.mesh_edit_selected_edges_by_submesh,
        faces_by_submesh=_state.mesh_edit_selected_faces_by_submesh,
        source_indices=_state.mesh_edit_selected_source_indices,
    )

def _mesh_edit_sync_d3d11_selection(_state, _callbacks, ) -> bool:
    if not _state._alignment_d3d11_preview_active():
        return False
    group_sender = getattr(_state.alignment_d3d11_preview_host, "set_mesh_edit_selection_groups", None)
    if not callable(group_sender) or _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        _callbacks._record_mesh_edit_event("mesh_edit_selection_group_update_unavailable")
        return False
    selection = _callbacks._mesh_edit_current_selection()
    try:
        groups = _state.mesh_edit_selection_groups(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            selection,
        )
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_selection_group_build_failed", message=str(exc))
        return False
    if not groups and not selection.is_empty():
        _callbacks._record_mesh_edit_event("mesh_edit_selection_group_build_empty")
        return False
    if group_sender(groups):
        return True
    _callbacks._record_mesh_edit_event(
        "mesh_edit_selection_group_update_failed",
        group_count=len(groups),
    )
    return False

def _mesh_edit_set_vertex_selection(_state, _callbacks, selected_vertices_by_submesh: _state.Mapping[int, _state.Iterable[int]]) -> None:
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_edges_by_submesh.clear()
    _state.mesh_edit_selected_faces_by_submesh.clear()
    _state.mesh_edit_selected_source_indices.clear()
    _state.mesh_edit_selected_vertices_by_submesh.update(
        _state._mesh_edit_index_groups_as_sets_helper(selected_vertices_by_submesh or {})
    )
    _callbacks._mesh_edit_sync_d3d11_selection()
    for preview_widget in (_state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
        if hasattr(preview_widget, "set_mesh_edit_vertex_selection"):
            preview_widget.set_mesh_edit_vertex_selection(_state.mesh_edit_selected_vertices_by_submesh)
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_set_source_selection(_state, _callbacks, source_indices: _state.Iterable[int]) -> None:
    allowed_sources = set(_state._mesh_edit_allowed_source_indices())
    selected_sources: set[int] = set()
    for raw_index in source_indices or ():
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if source_index in allowed_sources:
            selected_sources.add(source_index)
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_edges_by_submesh.clear()
    _state.mesh_edit_selected_faces_by_submesh.clear()
    _state.mesh_edit_selected_source_indices.clear()
    _state.mesh_edit_selected_source_indices.update(selected_sources)
    d3d11_synced = _callbacks._mesh_edit_sync_d3d11_selection()
    if not d3d11_synced and not _state._alignment_d3d11_preview_active():
        legacy_selection = _state._mesh_edit_all_vertices_by_source_helper(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            selected_sources,
        )
        for preview_widget in (_state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
            if hasattr(preview_widget, "set_mesh_edit_vertex_selection"):
                preview_widget.set_mesh_edit_vertex_selection(legacy_selection)
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_finish_selection_worker(_state, _callbacks, request_id: int) -> None:
    if int(request_id) != int(_state.mesh_edit_selection_worker_state.get("request_id", 0) or 0):
        return
    _state.mesh_edit_selection_worker_state.update({"thread": None, "worker": None, "start_revision": 0})
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_selection_worker_progress(_state, _callbacks, request_id: int, _percent: int, message: str) -> None:
    if int(request_id) == int(_state.mesh_edit_selection_worker_state.get("request_id", 0) or 0) and message:
        _state.self.set_status_message(str(message))

def _mesh_edit_selection_worker_failed(_state, _callbacks, request_id: int, message: str) -> None:
    if int(request_id) == int(_state.mesh_edit_selection_worker_state.get("request_id", 0) or 0):
        _state.self.set_status_message(str(message or "Selection update failed."), error=True)

def _mesh_edit_selection_worker_cancelled(_state, _callbacks, request_id: int, message: str) -> None:
    if int(request_id) == int(_state.mesh_edit_selection_worker_state.get("request_id", 0) or 0):
        _state.self.set_status_message(str(message or "Selection update cancelled."))

def _mesh_edit_selection_worker_completed(_state, _callbacks, request_id: int, result: object, session: object) -> None:
    if int(request_id) != int(_state.mesh_edit_selection_worker_state.get("request_id", 0) or 0):
        return
    start_revision = int(_state.mesh_edit_selection_worker_state.get("start_revision", 0) or 0)
    if int(_state.mesh_edit_revision.get("value", 0) or 0) != start_revision:
        _state.self.set_status_message("Selection result was discarded because the mesh changed while it was running.", error=True)
        return
    controller = getattr(session, "controller", None)
    session_view = getattr(controller, "session_view", None)
    if not callable(session_view):
        _state.self.set_status_message("Selection update failed.", error=True)
        return
    selection = session_view().selection
    _callbacks._mesh_edit_set_vertex_selection(selection.vertex_map())
    diagnostics = tuple(getattr(result, "diagnostics", ()) or ())
    if diagnostics:
        _state.self.set_status_message(str(diagnostics[0]), error=True)
    else:
        _state.self.set_status_message("Selection updated.")

def _mesh_edit_start_selection_worker(_state, _callbacks, operation: str, action_text: str) -> bool:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or _state.QThread is None:
        return False
    if _callbacks._mesh_edit_worker_active():
        _state.self.set_status_message("Wait for the current mesh edit to finish, or cancel it first.", error=True)
        return True
    session = _callbacks._mesh_editor_ensure_static_replacement_session(_state._mesh_edit_state.replacement_mesh_for_mapping)
    if not isinstance(session, _state.StaticReplacementMeshEditSession):
        return False
    selection = _callbacks._mesh_edit_current_selection()
    if selection.is_empty():
        _callbacks._mesh_edit_set_vertex_selection({})
        return True
    request_id = int(_state.mesh_edit_selection_worker_state.get("request_id", 0) or 0) + 1
    worker = _state.MeshEditCommandWorker(
        request_id,
        session.controller.mesh_service,
        session.session_id,
        _state.MeshEditCommand("select", selection=selection, params={"operation": operation}, mode="edit"),
        action_text=action_text,
    )
    thread = _state.QThread(_state.dialog)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress_changed.connect(_callbacks._mesh_edit_selection_worker_progress)
    worker.completed.connect(lambda finished_request_id, result, worker_session=session: _callbacks._mesh_edit_selection_worker_completed(
        finished_request_id,
        result,
        worker_session,
    ))
    worker.cancelled.connect(_callbacks._mesh_edit_selection_worker_cancelled)
    worker.error.connect(_callbacks._mesh_edit_selection_worker_failed)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(lambda finished_request_id=request_id: _callbacks._mesh_edit_finish_selection_worker(finished_request_id))
    _state.mesh_edit_selection_worker_state.update(
        {
            "request_id": request_id,
            "thread": thread,
            "worker": worker,
            "start_revision": int(_state.mesh_edit_revision.get("value", 0) or 0),
        }
    )
    _callbacks._refresh_mesh_edit_controls()
    _state.self.set_status_message(f"Updating {action_text} in the background...")
    thread.start(_state.QThread.LowPriority)
    return True

def _mesh_edit_native_all_vertex_selection(_state, _callbacks, *, operation: str) -> dict[int, set[int]] | None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return None
    allowed_sources = _state._mesh_edit_allowed_source_indices()
    if not allowed_sources:
        return None
    try:
        from cdmw.services.mesh_workflow_service import prune_native_mesh_selection

        native_selection = prune_native_mesh_selection(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            vertices_by_submesh={},
            edges_by_submesh={},
            faces_by_submesh={},
            selected_all_vertices_by_submesh=allowed_sources,
            source_indices=allowed_sources,
            current_vertices_by_submesh=_state.mesh_edit_selected_vertices_by_submesh,
            selection_operation=operation,
        )
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_native_all_vertex_selection_failed", message=str(exc))
        return None
    if not isinstance(native_selection, _state.Mapping):
        return None
    return _state._mesh_edit_index_groups_as_sets_helper(native_selection.get("vertices_by_submesh") or {})

def _mesh_edit_native_vertex_selection(_state, _callbacks, operation: str, *, iterations: int = 1) -> dict[int, set[int]] | None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return None
    allowed_indices = set(_state._mesh_edit_allowed_source_indices())
    selected_vertices = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_vertices_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_faces = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_faces_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_edges = _callbacks._mesh_editor_edge_selection(selected_vertices, selected_faces)
    selected_sources = _callbacks._mesh_editor_action_source_indices()
    if not selected_vertices and not selected_edges and not selected_faces and not selected_sources:
        return {}
    try:
        from cdmw.services.mesh_workflow_service import apply_native_mesh_selection

        native_selection = apply_native_mesh_selection(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            selected_vertices,
            selected_edges_by_submesh=selected_edges,
            selected_faces_by_submesh=selected_faces,
            source_indices=selected_sources,
            operation=operation,
            iterations=iterations,
        )
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_native_vertex_selection_failed", message=str(exc))
        return None
    if not isinstance(native_selection, _state.Mapping):
        return None
    return _state._mesh_edit_index_groups_as_sets_helper(native_selection)

def _mesh_edit_native_selection_unavailable(_state, _callbacks, action_text: str) -> None:
    _state.mesh_edit_status_label.setText(f"Native {action_text} is unavailable.")
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_select_whole_part(_state, _callbacks, ) -> None:
    allowed_sources = _state._mesh_edit_allowed_source_indices()
    if allowed_sources:
        _callbacks._mesh_edit_set_source_selection(allowed_sources)
        return
    selection = _callbacks._mesh_edit_native_all_vertex_selection(operation="replace")
    if selection is not None:
        _callbacks._mesh_edit_set_vertex_selection(selection)
        return
    _callbacks._mesh_edit_native_selection_unavailable("Select Part")

def _mesh_edit_invert_selection(_state, _callbacks, ) -> None:
    allowed_sources = tuple(_state._mesh_edit_allowed_source_indices())
    if _state.mesh_edit_selected_source_indices and not (
        _state.mesh_edit_selected_vertices_by_submesh
        or _state.mesh_edit_selected_edges_by_submesh
        or _state.mesh_edit_selected_faces_by_submesh
    ):
        selected_sources = set(_state.mesh_edit_selected_source_indices)
        _callbacks._mesh_edit_set_source_selection(source for source in allowed_sources if source not in selected_sources)
        return
    selection = _callbacks._mesh_edit_native_all_vertex_selection(operation="toggle")
    if selection is not None:
        _callbacks._mesh_edit_set_vertex_selection(selection)
        return
    _callbacks._mesh_edit_native_selection_unavailable("Invert Selection")

def _mesh_edit_grow_selection(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    if _callbacks._mesh_edit_start_selection_worker("grow", "Grow Selection"):
        return
    selection = _callbacks._mesh_edit_native_vertex_selection("grow")
    if selection is not None:
        _callbacks._mesh_edit_set_vertex_selection(selection)
        return
    _callbacks._mesh_edit_native_selection_unavailable("Grow Selection")

def _mesh_edit_shrink_selection(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    if _callbacks._mesh_edit_start_selection_worker("shrink", "Shrink Selection"):
        return
    selection = _callbacks._mesh_edit_native_vertex_selection("shrink")
    if selection is not None:
        _callbacks._mesh_edit_set_vertex_selection(selection)
        return
    _callbacks._mesh_edit_native_selection_unavailable("Shrink Selection")

def _mesh_edit_smooth_selection(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    if _callbacks._mesh_edit_start_selection_worker("smooth", "Smooth Selection"):
        return
    selection = _callbacks._mesh_edit_native_vertex_selection("smooth")
    if selection is not None:
        _callbacks._mesh_edit_set_vertex_selection(selection)
        return
    _callbacks._mesh_edit_native_selection_unavailable("Smooth Selection")

def _mesh_edit_selection_changed(_state, _callbacks, payload: object) -> None:
    native_screen_selection = False
    if isinstance(payload, _state.Mapping):
        screen_payload = _callbacks._mesh_edit_native_screen_selection_payload(payload)
        if screen_payload:
            if not _callbacks._mesh_edit_apply_native_screen_selection(payload, screen_payload):
                _state.mesh_edit_status_label.setText("Native D3D11 mesh selection failed.")
                _callbacks._refresh_mesh_edit_controls()
                return
            native_screen_selection = True
    if not native_screen_selection:
        _callbacks._mesh_edit_set_selection_state(_state.MeshEditSelection())
    if isinstance(payload, _state.Mapping) and not native_screen_selection:
        _state._mesh_edit_merge_vertex_groups(_state.mesh_edit_selected_vertices_by_submesh, _state._mesh_edit_vertices_from_payload(payload))
        _state.mesh_edit_selected_edges_by_submesh.update(_callbacks._mesh_edit_edges_from_payload(payload))
        _state._mesh_edit_merge_face_groups(_state.mesh_edit_selected_faces_by_submesh, _state._mesh_edit_faces_from_payload(payload))
    selected_count = _state._mesh_edit_index_group_count_helper(_state.mesh_edit_selected_vertices_by_submesh)
    selected_count += _callbacks._mesh_edit_selected_source_vertex_count()
    selected_face_count = _state._mesh_edit_index_group_count_helper(_state.mesh_edit_selected_faces_by_submesh)
    can_edit, reason = _callbacks._mesh_edit_can_edit_scope()
    if can_edit and _state.mesh_edit_enabled_checkbox.isChecked() and _state._mesh_edit_tab_active():
        revision_text = int(_state.mesh_edit_revision.get("value", 0) or 0)
        _state.mesh_edit_status_label.setText(
            _state._mesh_edit_selection_status_text_helper(
                reason,
                selected_count,
                selected_face_count,
                revision_text,
            )
        )
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_surface_tab_active(_state, _callbacks, index: int | None = None) -> bool:
    try:
        tab_index = _state.control_tabs.currentIndex() if index is None else int(index)
        if _state.control_tabs.widget(tab_index) is _state.mesh_edit_tab:
            return True
        return _state.control_tabs.tabText(tab_index).strip().lower() in {
            "mesh editing",
            "classic mesh editing",
            "merged mesh editing",
        }
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False

def _mesh_edit_control_tab_changed(_state, _callbacks, index: int) -> None:
    _state.mesh_edit_surface_tab_state["active"] = _state._mesh_edit_surface_tab_active(index)
    _callbacks._refresh_mesh_edit_controls()
    _state._apply_alignment_dialog_responsive_layout()

def _start_mesh_edit_fallback(_state, _callbacks, reason: str) -> None:
    if _state.dialog is not None:
        setattr(_state.dialog, "_mesh_editor_embedded_dotnet_active", False)
    _callbacks._record_mesh_edit_event(
        "mesh_edit_dotnet_fallback",
        reason=str(reason or "mesh_edit_dotnet_fallback"),
        dotnet_state=str(getattr(_state.dialog, "_mesh_editor_embedded_dotnet_state", "") or ""),
    )
    _state._mesh_edit_apply_preview_mode_transition(str(reason or "mesh_edit_dotnet_fallback"))
    _callbacks._refresh_mesh_edit_controls()

def _mesh_editor_embedded_dotnet_ready(_state, _callbacks, ) -> None:
    if _state.dialog is not None:
        setattr(_state.dialog, "_mesh_editor_embedded_dotnet_state", "ready")
        setattr(_state.dialog, "_mesh_editor_embedded_dotnet_active", True)
    _callbacks._record_mesh_edit_event("mesh_dotnet_process_ready", reason="embedded_callback")
    _callbacks._refresh_mesh_edit_controls()

def _mesh_editor_embedded_dotnet_failed(_state, _callbacks, reason: str = "", diagnostics: str = "") -> None:
    if _state.dialog is not None:
        setattr(_state.dialog, "_mesh_editor_embedded_dotnet_state", "failed")
        setattr(_state.dialog, "_mesh_editor_embedded_dotnet_active", False)
    summary = str(diagnostics or "").strip()
    if summary:
        _state.self.set_status_message(f"Mesh .NET launch failed, using native/classic fallback: {summary}", error=True)
    else:
        _state.self.set_status_message("Mesh .NET launch failed, using native/classic fallback.", error=True)
    _callbacks._start_mesh_edit_fallback("mesh_edit_dotnet_fallback")

def _mesh_edit_enabled_toggled(_state, _callbacks, _checked: bool = False) -> None:
    edit_enabled = bool(_state.mesh_edit_enabled_checkbox.isChecked())
    dotnet_active = bool(getattr(_state.dialog, "_mesh_editor_embedded_dotnet_active", False))
    stop_dotnet = getattr(_state.dialog, "_mesh_editor_embedded_stop_dotnet", None)
    if not edit_enabled:
        if callable(stop_dotnet) and bool(stop_dotnet()):
            _callbacks._refresh_mesh_edit_controls()
            return
        if not _callbacks._mesh_editor_finalize_edit_mode_exit("mesh_edit_toggle", mesh_changed=True):
            return
        return
    start_dotnet = getattr(_state.dialog, "_mesh_editor_embedded_start_dotnet", None)
    dotnet_enabled = bool(getattr(_state.dialog, "_mesh_editor_use_embedded_dotnet_viewport", False))
    dotnet_available = bool(getattr(_state.dialog, "_mesh_editor_dotnet_available", False))
    if dotnet_enabled and callable(start_dotnet):
        setattr(_state.dialog, "_mesh_editor_embedded_dotnet_state", "launching")
        setattr(_state.dialog, "_mesh_editor_embedded_dotnet_active", False)
        _state.self.set_status_message("Launching embedded Mesh .NET editor...", error=False)
        _callbacks._refresh_mesh_edit_controls()
        _callbacks._record_mesh_edit_event(
            "mesh_edit_dotnet_launch_requested",
            dotnet_state="launching",
            dotnet_active=False,
            dotnet_enabled=dotnet_enabled,
            dotnet_available=dotnet_available,
            parent_hwnd=_callbacks._embedded_dotnet_parent_hwnd(),
            classic_toolbar_visible=False,
            native_d3d11_process_active=_callbacks._alignment_d3d11_process_active(),
        )
        start_dotnet()
        return
    if not dotnet_available:
        _state.self.set_status_message(
            "Mesh .NET editor helper unavailable; using native/classic Mesh Editor controls.",
            error=True,
        )
        _callbacks._start_mesh_edit_fallback("mesh_edit_dotnet_unavailable")
        return
    _callbacks._start_mesh_edit_fallback("mesh_edit_dotnet_disabled")


_CALLBACKS = (
    _mesh_edit_clear_vertex_selection,
    _mesh_edit_current_selection,
    _mesh_edit_sync_d3d11_selection,
    _mesh_edit_set_vertex_selection,
    _mesh_edit_set_source_selection,
    _mesh_edit_finish_selection_worker,
    _mesh_edit_selection_worker_progress,
    _mesh_edit_selection_worker_failed,
    _mesh_edit_selection_worker_cancelled,
    _mesh_edit_selection_worker_completed,
    _mesh_edit_start_selection_worker,
    _mesh_edit_native_all_vertex_selection,
    _mesh_edit_native_vertex_selection,
    _mesh_edit_native_selection_unavailable,
    _mesh_edit_select_whole_part,
    _mesh_edit_invert_selection,
    _mesh_edit_grow_selection,
    _mesh_edit_shrink_selection,
    _mesh_edit_smooth_selection,
    _mesh_edit_selection_changed,
    _mesh_edit_surface_tab_active,
    _mesh_edit_control_tab_changed,
    _start_mesh_edit_fallback,
    _mesh_editor_embedded_dotnet_ready,
    _mesh_editor_embedded_dotnet_failed,
    _mesh_edit_enabled_toggled,
)
