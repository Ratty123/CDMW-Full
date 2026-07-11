"""Payload Apply callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_payload_apply_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_apply_preview_payload(_state, _callbacks, payload: object) -> None:
    callback_started = _state.time.perf_counter()
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or not isinstance(payload, _state.Mapping):
        return
    stroke_id = _state._mesh_edit_stroke_id(payload)
    if stroke_id <= 0 or int(_state.mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
        return
    can_edit, _reason = _callbacks._mesh_edit_can_edit_scope()
    if not can_edit or not _state.mesh_edit_enabled_checkbox.isChecked() or not _state._mesh_edit_tab_active():
        return
    tool = _state._mesh_edit_payload_choice_helper(
        payload,
        "tool",
        _state.mesh_edit_active_stroke.get("tool") or _state._mesh_edit_current_tool(),
        {"move", "grab", "smooth", "inflate", "pinch", "remove", "vertex"},
    )
    if tool == "remove":
        _mesh_edit_apply_remove_payload(_state, _callbacks, payload)
        return
    _mesh_edit_apply_geometry_payload(
        _state, _callbacks, payload, callback_started, stroke_id, tool
    )


def _mesh_edit_apply_remove_payload(_state, _callbacks, payload: object) -> None:
    delete_mode = _state._mesh_edit_payload_choice_helper(
        payload,
        "delete_mode",
        _state.mesh_edit_active_stroke.get("delete_mode") or _state.mesh_edit_delete_mode_combo.currentData() or "release",
        {"release", "live", "selection"},
    )
    raw_screen_brush = payload.get("screen_brush")
    if delete_mode in {"live", "release"} and isinstance(raw_screen_brush, _state.Mapping):
        screen_payload = {
            "target_mode": "face",
            "selection_depth_mode": str(payload.get("selection_depth_mode") or "visible"),
            "falloff": str(payload.get("falloff") or "smooth"),
            "screen_brush": _state._native_screen_payload(raw_screen_brush),
        }
        if delete_mode == "release":
            session = _callbacks._mesh_editor_ensure_static_replacement_session(_state._mesh_edit_state.replacement_mesh_for_mapping)
            if not isinstance(session, _state.StaticReplacementMeshEditSession):
                return
            select_result = session.select(
                operation="add" if _state.mesh_edit_active_stroke.get("native_release_remove_selected") else "replace",
                _native_screen_selection_payload=screen_payload,
            )
            if not select_result.ok:
                return
            _state.mesh_edit_active_stroke["native_release_remove_selected"] = True
            _callbacks._refresh_mesh_edit_controls()
            return
        result = _callbacks._mesh_editor_apply_static_replacement_edit(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            "delete",
            remove_orphans=False,
            recompute_normals=False,
            record_history=False,
            _native_screen_selection_payload=screen_payload,
        )
        if int(result.removed_face_count or 0) <= 0:
            return
        _callbacks._mesh_editor_store_result_mesh(result)
        _callbacks._mesh_editor_remember_static_replacement_session_mesh()
        live_submeshes = _state.mesh_edit_active_stroke.setdefault("live_delete_submeshes", set())
        if isinstance(live_submeshes, set):
            live_submeshes.update(int(index) for index in result.affected_submesh_indices)
        _state.mesh_edit_active_stroke["live_removed_face_count"] = int(
            _state.mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0
        ) + int(result.removed_face_count or 0)
        _state.mesh_edit_active_stroke["changed"] = True
        if not _callbacks._mesh_editor_apply_result_native_update(result):
            _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
        return
    native_delete_groups = (
        _state._mesh_edit_payload_native_vertex_groups_helper(
            payload,
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            allowed_source_indices=_state._mesh_edit_allowed_source_indices(),
            source_indices_for_editor_id=_state._alignment_d3d11_source_indices_for_editor_id,
        )
        if callable(_state._mesh_edit_payload_native_vertex_groups_helper)
        else []
    )
    native_delete_vertices_by_submesh: dict[int, object] = {}
    for native_group in native_delete_groups or ():
        try:
            source_submesh_index = int(native_group.get("source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        if source_submesh_index >= 0 and isinstance(native_group.get("source_vertex_indices_binary"), _state.Mapping):
            native_delete_vertices_by_submesh[source_submesh_index] = native_group["source_vertex_indices_binary"]
    faces_by_submesh = _state._mesh_edit_faces_from_payload(payload)
    vertices_by_submesh = (
        {}
        if delete_mode == "live" and native_delete_vertices_by_submesh and not faces_by_submesh
        else _state._mesh_edit_vertices_from_payload(payload)
    )
    if not vertices_by_submesh and not faces_by_submesh and not native_delete_vertices_by_submesh:
        return
    if delete_mode == "selection":
        if not vertices_by_submesh:
            vertices_by_submesh = _state._mesh_edit_vertices_from_payload(payload)
        _state.mesh_edit_selected_source_indices.clear()
        _state._mesh_edit_merge_vertex_groups(_state.mesh_edit_selected_vertices_by_submesh, vertices_by_submesh)
        _state._mesh_edit_merge_face_groups(_state.mesh_edit_selected_faces_by_submesh, faces_by_submesh)
        _callbacks._refresh_mesh_edit_controls()
        return
    if delete_mode == "live":
        delete_selection = (
            {"faces_by_submesh": faces_by_submesh}
            if faces_by_submesh
            else (
                {"native_selected_vertices_binary_by_submesh": native_delete_vertices_by_submesh}
                if native_delete_vertices_by_submesh
                else {"vertices_by_submesh": vertices_by_submesh}
            )
        )
        result = _callbacks._mesh_editor_apply_static_replacement_edit(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            "delete",
            remove_orphans=False,
            recompute_normals=False,
            record_history=False,
            **delete_selection,
        )
        if callable(_state._mesh_edit_cleanup_native_vertex_group_descriptors_helper):
            _state._mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_delete_groups)
        if int(result.removed_face_count or 0) <= 0:
            return
        _callbacks._mesh_editor_store_result_mesh(result)
        _callbacks._mesh_editor_remember_static_replacement_session_mesh()
        live_submeshes = _state.mesh_edit_active_stroke.setdefault("live_delete_submeshes", set())
        if isinstance(live_submeshes, set):
            live_submeshes.update(int(index) for index in result.affected_submesh_indices)
        _state.mesh_edit_active_stroke["live_removed_face_count"] = int(
            _state.mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0
        ) + int(result.removed_face_count or 0)
        _state.mesh_edit_active_stroke["changed"] = True
        if not _callbacks._mesh_editor_apply_result_native_update(result):
            _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
        return
    remove_faces = _state.mesh_edit_active_stroke.setdefault("remove_faces_by_submesh", {})
    if isinstance(remove_faces, dict):
        _state._mesh_edit_merge_face_groups(remove_faces, faces_by_submesh)
    remove_vertices = _state.mesh_edit_active_stroke.setdefault("remove_vertices_by_submesh", {})
    if isinstance(remove_vertices, dict):
        _state._mesh_edit_merge_vertex_groups(remove_vertices, vertices_by_submesh)
    _callbacks._refresh_mesh_edit_controls()
    return


def _mesh_edit_apply_geometry_payload(
    _state, _callbacks, payload: object, callback_started: float, stroke_id: int, tool: str
) -> None:
    raw_screen_drag = payload.get("screen_drag")
    raw_screen_brush = payload.get("screen_brush")
    raw_screen_radius = payload.get("screen_radius")
    has_screen_drag = isinstance(raw_screen_drag, _state.Mapping)
    has_screen_brush = isinstance(raw_screen_brush, _state.Mapping)
    has_screen_radius = isinstance(raw_screen_radius, _state.Mapping)
    if tool in {"move", "grab", "vertex"} and not has_screen_drag and not _state._mesh_edit_payload_has_drag_motion(payload):
        return
    native_descriptor_groups = (
        _state._mesh_edit_payload_native_vertex_groups_helper(
            payload,
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            allowed_source_indices=_state._mesh_edit_allowed_source_indices(),
            source_indices_for_editor_id=_state._alignment_d3d11_source_indices_for_editor_id,
        )
        if callable(_state._mesh_edit_payload_native_vertex_groups_helper)
        else []
    )
    if has_screen_drag or has_screen_brush or has_screen_radius:
        screen_selection_payload = _callbacks._mesh_edit_native_screen_selection_payload(
            payload,
            _state.mesh_edit_active_stroke.get("native_screen_selection_payload"),
        )
        descriptor_selection_payload = _callbacks._mesh_edit_native_descriptor_selection_payload(native_descriptor_groups)
        if has_screen_brush:
            _state.mesh_edit_active_stroke["native_screen_selection_payload"] = screen_selection_payload
        try:
            params: dict[str, object] = {
                "mirror_x": bool(_state.mesh_edit_mirror_checkbox.isChecked()),
                "recompute_normals": False,
                "record_history": False,
                "_require_native_history_delta": True,
            }
            selected_vertices = _state._mesh_edit_sorted_index_groups_helper(_state.mesh_edit_selected_vertices_by_submesh)
            transform_screen_stroke = tool in {"move", "grab", "vertex"} and has_screen_drag
            transform_screen_stroke_started = bool(_state.mesh_edit_active_stroke.get("native_transform_stroke_started"))
            if transform_screen_stroke:
                params["stroke_phase"] = "update" if transform_screen_stroke_started else "begin"
                params["stroke_id"] = str(stroke_id)
            if has_screen_drag:
                params["screen_drag"] = _state._native_screen_payload(raw_screen_drag)  # type: ignore[arg-type]
            if tool in {"move", "vertex"}:
                if not has_screen_drag:
                    return
                if transform_screen_stroke_started:
                    pass
                elif screen_selection_payload:
                    params["_native_screen_selection_payload"] = screen_selection_payload
                elif descriptor_selection_payload:
                    params["_native_selection_payload"] = descriptor_selection_payload
                elif selected_vertices:
                    params["vertices_by_submesh"] = selected_vertices
                else:
                    return
                edit_apply_started = _state.time.perf_counter()
                result = _callbacks._mesh_editor_apply_static_replacement_edit(
                    _state._mesh_edit_state.replacement_mesh_for_mapping,
                    "transform",
                    **params,
                )
                edit_apply_ms = max(0.0, (_state.time.perf_counter() - edit_apply_started) * 1000.0)
            else:
                params.update(
                    {
                        "mode": "sculpt",
                        "tool": tool,
                        "strength": _state._mesh_edit_payload_float_helper(payload, "strength", minimum=0.0, maximum=1.0),
                        "falloff": str(payload.get("falloff") or "smooth"),
                        "iterations": _state._mesh_edit_payload_int_helper(
                            payload,
                            "smooth_iterations",
                            int(_state.mesh_edit_iterations_spin.value()),
                        ),
                        "invert": bool(payload.get("invert")),
                    }
                )
                if transform_screen_stroke_started and tool == "grab":
                    pass
                elif has_screen_brush:
                    params["screen_brush"] = _state._native_screen_payload(raw_screen_brush)  # type: ignore[arg-type]
                elif descriptor_selection_payload:
                    params["_native_selection_payload"] = descriptor_selection_payload
                elif selected_vertices:
                    params["vertices_by_submesh"] = selected_vertices
                else:
                    return
                if "target_mode" in payload:
                    params["target_mode"] = str(payload.get("target_mode") or "vertex")
                if "selection_depth_mode" in payload:
                    params["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
                if has_screen_radius:
                    params["screen_radius"] = _state._native_screen_payload(raw_screen_radius)  # type: ignore[arg-type]
                edit_apply_started = _state.time.perf_counter()
                result = _callbacks._mesh_editor_apply_static_replacement_edit(
                    _state._mesh_edit_state.replacement_mesh_for_mapping,
                    "brush",
                    **params,
                )
                edit_apply_ms = max(0.0, (_state.time.perf_counter() - edit_apply_started) * 1000.0)
            edit_result = getattr(result, "edit_result", None)
            if edit_result is not None and not bool(getattr(edit_result, "ok", False)):
                return
            _callbacks._mesh_editor_store_result_mesh(result)
            _callbacks._mesh_editor_remember_static_replacement_session_mesh()
            if transform_screen_stroke:
                _state.mesh_edit_active_stroke["native_transform_stroke_started"] = True
            _callbacks._mesh_edit_capture_native_stroke_delta(
                _callbacks._mesh_editor_result_mesh_for_state(result),
                result.changed_vertices_by_submesh,
            )
            native_update_started = _state.time.perf_counter()
            live_native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)
            d3d11_update_ms = max(0.0, (_state.time.perf_counter() - native_update_started) * 1000.0)
            if live_native_update_applied:
                _state.mesh_edit_active_stroke["native_update_applied"] = True
            changed_by_submesh = _callbacks._mesh_edit_changed_vertex_groups_for_live_update(result.changed_vertices_by_submesh or {})
            _callbacks._record_mesh_edit_live_stroke_timing(
                payload,
                result,
                tool=tool,
                phase=params.get("stroke_phase", ""),
                callback_started=callback_started,
                edit_apply_ms=edit_apply_ms,
                d3d11_update_ms=d3d11_update_ms,
                native_update_applied=live_native_update_applied,
                changed_by_submesh=changed_by_submesh,
            )
            if not changed_by_submesh:
                return
            if not live_native_update_applied:
                pending_live_vertices_by_submesh: _state.Dict[int, object] = {}
                _state._mesh_edit_queue_live_vertex_updates_helper(pending_live_vertices_by_submesh, changed_by_submesh)
                _callbacks._mesh_edit_update_live_preview(pending_live_vertices_by_submesh)
            stroke_changed_vertices = _state.mesh_edit_active_stroke.setdefault("changed_vertices_by_submesh", {})
            if isinstance(stroke_changed_vertices, dict):
                _state._mesh_edit_queue_live_vertex_updates_helper(stroke_changed_vertices, changed_by_submesh)
            _state.mesh_edit_active_stroke["changed"] = True
            return
        finally:
            if native_descriptor_groups and callable(_state._mesh_edit_cleanup_native_vertex_group_descriptors_helper):
                _state._mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_descriptor_groups)
    if tool in {"move", "grab", "vertex", "smooth", "inflate", "pinch"}:
        raise RuntimeError("native mesh edit stroke payload did not include native screen update data; Python inverse transform fallback is disabled")


_CALLBACKS = (
    _mesh_edit_apply_preview_payload,
)
