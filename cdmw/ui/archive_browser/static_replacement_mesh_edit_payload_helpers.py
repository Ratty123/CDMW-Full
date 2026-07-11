"""Payload Helpers callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_payload_helpers_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_preview_delta_to_source_delta(_state, _callbacks,
        source_index: int,
        transformed_delta: _state.Sequence[object],
    ) -> tuple[float, float, float]:
    raise _callbacks._mesh_edit_inverse_transform_disabled()

def _mesh_edit_preview_point_to_source_point(_state, _callbacks,
        source_index: int,
        transformed_point: _state.Sequence[object],
    ) -> tuple[float, float, float]:
    raise _callbacks._mesh_edit_inverse_transform_disabled()

def _mesh_edit_preview_distance_to_source_distance(_state, _callbacks,
        source_index: int,
        transformed_distance: float,
    ) -> float:
    raise _callbacks._mesh_edit_inverse_transform_disabled()

def _mesh_edit_edges_from_payload(_state, _callbacks, payload: object) -> dict[int, set[tuple[int, int]]]:
    if not callable(_state._mesh_edit_payload_edge_groups_helper):
        return {}
    return _state._mesh_edit_payload_edge_groups_helper(
        payload,
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        allowed_source_indices=_state._mesh_edit_allowed_source_indices(),
        source_indices_for_editor_id=_state._d3d11_source_indices_for_editor_id,
    )

def _mesh_edit_native_screen_selection_payload(_state, _callbacks,
        payload: _state.Mapping[object, object],
        fallback: object = None,
    ) -> dict[str, object]:
    raw_screen_brush = payload.get("screen_brush")
    raw_screen_region = payload.get("screen_region")
    if not isinstance(raw_screen_brush, _state.Mapping) and not isinstance(raw_screen_region, _state.Mapping):
        return dict(fallback) if isinstance(fallback, _state.Mapping) else {}
    screen_payload = {
        "target_mode": str(payload.get("target_mode") or "vertex"),
        "selection_depth_mode": str(payload.get("selection_depth_mode") or "visible"),
        "falloff": str(payload.get("falloff") or "smooth"),
    }
    if isinstance(raw_screen_brush, _state.Mapping):
        screen_payload["screen_brush"] = _state._native_screen_payload(raw_screen_brush)
    if isinstance(raw_screen_region, _state.Mapping):
        screen_payload["screen_region"] = _state._native_screen_payload(raw_screen_region)
    return screen_payload

def _mesh_edit_native_descriptor_selection_payload(_state, _callbacks, native_descriptor_groups: object) -> dict[str, object]:
    vertices_by_submesh: dict[int, dict[str, object]] = {}
    for group in native_descriptor_groups or ():
        if not isinstance(group, _state.Mapping):
            continue
        try:
            source_submesh_index = int(group.get("source_submesh_index", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if source_submesh_index < 0:
            continue
        item: dict[str, object] = {}
        raw_vertices = group.get("source_vertex_indices_binary")
        if isinstance(raw_vertices, _state.Mapping):
            item["selected_vertices_binary"] = dict(raw_vertices)
        else:
            try:
                start = int(group.get("source_vertex_start", -1))
                count = int(group.get("source_vertex_count", 0))
            except (TypeError, ValueError, OverflowError):
                start = -1
                count = 0
            if start >= 0 and count > 0:
                item["start"] = start
                item["count"] = count
        raw_weights = group.get("source_vertex_weights_binary")
        if isinstance(raw_weights, _state.Mapping):
            item["source_vertex_weights_binary"] = dict(raw_weights)
        if item:
            vertices_by_submesh[source_submesh_index] = item
    return {"vertices_by_submesh": vertices_by_submesh} if vertices_by_submesh else {}

def _mesh_edit_set_selection_state(_state, _callbacks, selection: _state.MeshEditSelection) -> None:
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_edges_by_submesh.clear()
    _state.mesh_edit_selected_faces_by_submesh.clear()
    _state.mesh_edit_selected_source_indices.clear()
    _state.mesh_edit_selected_vertices_by_submesh.update(selection.vertex_map())
    _state.mesh_edit_selected_edges_by_submesh.update(selection.edge_map())
    _state.mesh_edit_selected_faces_by_submesh.update(selection.face_map())
    _state.mesh_edit_selected_source_indices.update(selection.source_indices)

def _mesh_edit_apply_native_screen_selection(_state, _callbacks,
        payload: _state.Mapping[object, object],
        screen_payload: _state.Mapping[str, object],
    ) -> bool:
    session = _callbacks._mesh_editor_ensure_static_replacement_session(_state._mesh_edit_state.replacement_mesh_for_mapping)
    if not isinstance(session, _state.StaticReplacementMeshEditSession):
        return False
    try:
        operation = str(payload.get("operation", payload.get("selection_operation", "replace")) or "replace")
        result = session.select(operation=operation, _native_screen_selection_payload=screen_payload)
        if not result.ok:
            return False
        _callbacks._mesh_edit_set_selection_state(session.view().selection)
        _callbacks._mesh_edit_sync_d3d11_selection()
        return True
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_screen_selection_failed", message=str(exc))
        return False

def _mesh_edit_clear_topology_selection(_state, _callbacks, ) -> None:
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_edges_by_submesh.clear()
    _state.mesh_edit_selected_faces_by_submesh.clear()
    _state.mesh_edit_selected_source_indices.clear()
    if _state._alignment_d3d11_preview_active():
        _state.alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
    for preview_widget in (_state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
        if hasattr(preview_widget, "clear_mesh_edit_vertex_selection"):
            preview_widget.clear_mesh_edit_vertex_selection()

def _mesh_edit_commit_working_mesh(_state, _callbacks,
        status_message: str = "",
        *,
        topology_source_indices: _state.Iterable[int] | None = None,
        normal_source_indices: _state.Iterable[int] | None = None,
        native_result: object | None = None,
    ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    native_update_applied = (
        _callbacks._mesh_editor_apply_result_native_update(native_result)
        if native_result is not None
        else False
    )
    _callbacks._mesh_edit_update_mesh_totals()
    if not native_update_applied:
        _callbacks._morph_slider_capture_post_edit_deltas()
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    if native_update_applied:
        pass
    elif topology_source_indices is not None:
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(topology_source_indices)
    elif _state._alignment_d3d11_preview_active():
        _callbacks._mesh_edit_update_live_preview(
            _state._mesh_edit_all_live_vertices_for_sources(normal_source_indices or _state._mesh_edit_preview_source_indices()),
            include_normals=True,
            immediate=True,
        )
    elif _state._mesh_edit_tab_active():
        _callbacks._mesh_edit_mark_native_preview_stale(
            "Active Mesh Editor commit requires native D3D11 refresh; Python preview rebuild fallback is disabled."
        )
    else:
        _state._queue_static_preview_rebuild()
    if status_message:
        _state.self.set_status_message(status_message)


_CALLBACKS = (
    _mesh_edit_preview_delta_to_source_delta,
    _mesh_edit_preview_point_to_source_point,
    _mesh_edit_preview_distance_to_source_distance,
    _mesh_edit_edges_from_payload,
    _mesh_edit_native_screen_selection_payload,
    _mesh_edit_native_descriptor_selection_payload,
    _mesh_edit_set_selection_state,
    _mesh_edit_apply_native_screen_selection,
    _mesh_edit_clear_topology_selection,
    _mesh_edit_commit_working_mesh,
)
