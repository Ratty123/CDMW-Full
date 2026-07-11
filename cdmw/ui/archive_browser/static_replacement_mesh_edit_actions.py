"""Actions callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    send_resident_material_parameters,
    source_part_material_parameter_groups_for_mesh,
)


def create_actions_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_editor_tool_action_key(_state, _callbacks, tool: str) -> str:
    return {
        "grab": "brush_grab",
        "smooth": "brush_smooth",
        "inflate": "brush_inflate",
        "pinch": "brush_pinch",
    }.get(str(tool or "").strip().lower(), "")

def _mesh_editor_active_tool_action_key(_state, _callbacks, ) -> str:
    current_tool = _state._mesh_edit_current_tool()
    active_key = str(_state.mesh_editor_action_bar_active_tool_key.get("value") or "")
    if current_tool == "grab" and active_key in {"transform_move", "brush_grab"}:
        return active_key
    expected_key = _callbacks._mesh_editor_tool_action_key(current_tool)
    if expected_key:
        _state.mesh_editor_action_bar_active_tool_key["value"] = expected_key
        return expected_key
    return ""

def _set_mesh_edit_enabled(_state, _callbacks, checked: bool) -> None:
    if bool(_state.mesh_edit_enabled_checkbox.isChecked()) == bool(checked):
        _callbacks._refresh_mesh_edit_controls()
        return
    _state.mesh_edit_enabled_checkbox.setChecked(bool(checked))

def _select_mesh_edit_tool(_state, _callbacks, tool: str, *, active_action_key: str = "") -> bool:
    index = _state.mesh_edit_tool_combo.findData(str(tool or ""))
    if int(index) < 0:
        return False
    _state.mesh_editor_action_bar_active_tool_key["value"] = str(active_action_key or _callbacks._mesh_editor_tool_action_key(tool) or "")
    if _state.mesh_edit_tool_combo.currentIndex() == int(index):
        _callbacks._refresh_mesh_edit_controls()
        _callbacks._sync_mesh_edit_preview_settings()
        return True
    _state.mesh_edit_tool_combo.setCurrentIndex(int(index))
    _callbacks._refresh_mesh_edit_controls()
    _callbacks._sync_mesh_edit_preview_settings()
    return True

def _mesh_editor_action_selection(_state, _callbacks, ) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return {}, {}
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
    return selected_vertices, selected_faces

def _mesh_editor_action_source_indices(_state, _callbacks, ) -> tuple[int, ...]:
    return _callbacks._mesh_edit_selected_source_indices()

def _mesh_editor_edge_selection(_state, _callbacks,
        selected_vertices: _state.Mapping[int, _state.Iterable[int]],
        selected_faces: _state.Mapping[int, _state.Iterable[int]],
    ) -> dict[int, set[tuple[int, int]]]:
    _ = selected_vertices, selected_faces
    mesh = _state._mesh_edit_state.replacement_mesh_for_mapping
    if mesh is None:
        return {}

    def _edge(a: object, b: object) -> tuple[int, int]:
        left = int(a)
        right = int(b)
        return (left, right) if left <= right else (right, left)

    edges_by_submesh: dict[int, set[tuple[int, int]]] = {}
    allowed_indices = set(_state._mesh_edit_allowed_source_indices())
    for submesh_index, edge_items in (_state.mesh_edit_selected_edges_by_submesh or {}).items():
        if not 0 <= int(submesh_index) < len(mesh.submeshes):
            continue
        if int(submesh_index) not in allowed_indices:
            continue
        vertex_count = len(getattr(mesh.submeshes[int(submesh_index)], "vertices", ()) or ())
        for edge_item in edge_items or ():
            try:
                left, right = _edge(edge_item[0], edge_item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if left != right and 0 <= left < vertex_count and 0 <= right < vertex_count:
                edges_by_submesh.setdefault(int(submesh_index), set()).add((left, right))
    return {index: edges for index, edges in edges_by_submesh.items() if edges}

def _mesh_editor_selected_edge_count(_state, _callbacks, ) -> int:
    count = 0
    for edge_items in (_state.mesh_edit_selected_edges_by_submesh or {}).values():
        try:
            count += len(edge_items or ())
        except TypeError:
            continue
    return count

def _mesh_editor_action_result_changed(_state, _callbacks, result: object) -> bool:
    return bool(
        getattr(result, "affected_submesh_indices", ())
        or getattr(result, "changed_vertices_by_submesh", None)
        or int(getattr(result, "removed_face_count", 0) or 0) > 0
        or int(getattr(result, "added_face_count", 0) or 0) > 0
        or int(getattr(result, "moved_face_count", 0) or 0) > 0
        or int(getattr(result, "added_vertex_count", 0) or 0) > 0
        or int(getattr(result, "removed_vertex_count", 0) or 0) > 0
    )

def _mesh_editor_action_result_within_allowed_scope(_state, _callbacks, result: object) -> bool:
    allowed_indices = set(int(index) for index in _state._mesh_edit_allowed_source_indices(require_enabled=False))
    if not allowed_indices:
        return True
    touched_indices: set[int] = set()
    for raw_index in getattr(result, "affected_submesh_indices", ()) or ():
        try:
            touched_indices.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    for attr_name in (
        "changed_vertices_by_submesh",
        "changed_normals_by_submesh",
        "changed_faces_by_submesh",
    ):
        changed = getattr(result, attr_name, None)
        keys = getattr(changed, "keys", None)
        if not callable(keys):
            continue
        for raw_index in keys() or ():
            try:
                touched_indices.add(int(raw_index))
            except (TypeError, ValueError):
                continue
    for attr_name in ("source_submesh_index", "target_submesh_index"):
        try:
            raw_index = int(getattr(result, attr_name, -1) or -1)
        except (TypeError, ValueError):
            raw_index = -1
        if raw_index >= 0:
            touched_indices.add(raw_index)
    try:
        new_submesh_index = int(getattr(result, "new_submesh_index", -1) or -1)
    except (TypeError, ValueError):
        new_submesh_index = -1
    new_submesh_indices = {
        int(new_index)
        for new_index, _source_index in tuple(getattr(result, "new_submesh_source_indices", ()) or ())
    }
    if new_submesh_index >= 0:
        new_submesh_indices.add(new_submesh_index)
    unsafe_indices = {
        index
        for index in touched_indices
        if index >= 0 and index not in allowed_indices and index not in new_submesh_indices
    }
    return not unsafe_indices

def _mesh_editor_sync_new_source_part(_state, _callbacks, result: object) -> None:
    pairs = tuple(getattr(result, "new_submesh_source_indices", ()) or ())
    if not pairs:
        new_index = int(getattr(result, "new_submesh_index", -1) or -1)
        source_index = int(getattr(result, "source_submesh_index", -1) or -1)
        pairs = ((new_index, source_index),) if new_index >= 0 else ()
    if not pairs:
        return
    adjustments = _state.context.get("source_part_adjustments") or {}
    role_overrides = _state.context.get("source_role_overrides") or {}
    display_overrides = _state.context.get("source_display_overrides") or {}
    for new_source_index, source_index in pairs:
        if hasattr(_state.appended_source_indices, "add"):
            _state.appended_source_indices.add(new_source_index)
        if source_index in adjustments:
            adjustment = _state.copy.deepcopy(adjustments[source_index])
            adjustment.source_submesh_index = new_source_index
            adjustment.enabled = True
            adjustments[new_source_index] = adjustment
        if source_index in role_overrides:
            role_overrides[new_source_index] = role_overrides[source_index]
            adjustment = adjustments.get(new_source_index, _state.StaticSourcePartAdjustment(new_source_index))
            adjustment.material_role = str(role_overrides[new_source_index] or '')
            adjustments[new_source_index] = adjustment
        if source_index in display_overrides:
            display_overrides[new_source_index] = f"{display_overrides[source_index]} Copy"
        for name in ("independent_output_source_indices", "preview_only_source_indices"):
            values = _state.context.get(name)
            if hasattr(values, "add") and source_index in values:
                values.add(new_source_index)
    parse_mapping = _state.context.get("_parse_mapping_edit")
    set_mapping = _state.context.get("_set_mapping_indices")
    if callable(parse_mapping) and callable(set_mapping):
        for target_index, edit in tuple(_state.context.get("mapping_edits") or ()):
            indices = list(parse_mapping(edit))
            additions = [new_index for new_index, source_index in pairs if source_index in indices]
            if additions:
                set_mapping(target_index, indices + additions, push_undo=False, defer_preview=True)
    new_indices = tuple(new_index for new_index, _source_index in pairs)
    mesh = getattr(getattr(_state, '_mesh_edit_state', None), 'replacement_mesh_for_mapping', None)
    if mesh is not None:
        groups = source_part_material_parameter_groups_for_mesh(
            mesh, adjustments, _state.StaticSourcePartAdjustment, source_indices=new_indices
        )
        send_resident_material_parameters(getattr(_state, 'dialog', None), groups)
    _state.selected_source_part["index"] = new_indices[0]
    for name in ("selected_source_highlight_indices", "transform_source_indices"):
        values = _state.context.get(name)
        if hasattr(values, "clear") and hasattr(values, "update"):
            values.clear()
            values.update(new_indices)
    invalidate = _state.context.get("_invalidate_source_display_cache")
    if callable(invalidate):
        invalidate()
    if callable(_state._rebuild_source_part_widgets):
        _state._rebuild_source_part_widgets(new_indices, current_index=new_indices[0])

def _mesh_editor_send_embedded_dotnet_update(_state, _callbacks, update: object) -> bool:
    sender = getattr(_state.dialog, "_mesh_editor_embedded_send_native_update", None)
    return bool(callable(sender) and sender(update))

def _mesh_editor_commit_action_bar_service_result(_state, _callbacks,
        result: object,
        *,
        action_key: str,
        action_text: str,
        topology_action: bool,
    ) -> bool:
    if not _callbacks._mesh_editor_action_result_changed(result):
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._refresh_mesh_edit_controls()
        _state.self.set_status_message(f"Mesh Editor action made no changes: {action_text}.")
        return True
    if not _callbacks._mesh_editor_action_result_within_allowed_scope(result):
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._refresh_mesh_edit_controls()
        _state.self.set_status_message(
            f"Mesh Editor action blocked outside selected scope: {action_text}.",
            error=True,
        )
        return True
    _callbacks._mesh_editor_store_result_mesh(result)
    edit_result = getattr(result, "edit_result", None)
    actual_topology_action = bool(topology_action or getattr(edit_result, "topology_changed", False))
    if actual_topology_action:
        _callbacks._morph_slider_mark_topology_changed(
            _state._mesh_edit_topology_changed_status_helper(action_key) or _state._morph_slider_topology_changed_reason_text_helper()
        )
        _callbacks._mesh_edit_clear_topology_selection()
    native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)
    native_update_applied = _callbacks._mesh_editor_send_embedded_dotnet_update(
        getattr(result, "native_update", None)
    ) or native_update_applied
    _callbacks._mesh_edit_update_mesh_totals()
    if not native_update_applied:
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    if actual_topology_action and _callbacks._mesh_editor_sync_static_replacement_session_to_working_mesh(
        f"mesh_edit.{action_key}"
    ):
        if str(action_key or "").strip().lower() == "delete" and int(
            getattr(getattr(result, "edit_result", None), "submesh_count_delta", 0) or 0
        ) < 0:
            delete_state = _state.context.get("_delete_selected_source_parts")
            if callable(delete_state):
                delete_state(
                    getattr(result, "selected_source_indices", ()),
                    resident_state_only=True,
                    previous_source_count=int(getattr(result, "previous_submesh_count", 0) or 0),
                )
        else:
            _callbacks._mesh_editor_sync_new_source_part(result)
        _callbacks._mesh_edit_update_mesh_totals()
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    if not native_update_applied:
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(getattr(result, "affected_submesh_indices", ()))
    _state.self.set_status_message(f"Mesh Editor action applied: {action_text}.")
    return True

def _mesh_editor_embedded_controller(_state, _callbacks, ):
    session = _callbacks._mesh_editor_ensure_static_replacement_session()
    return session.controller if isinstance(session, _state.StaticReplacementMeshEditSession) else None

def _mesh_editor_embedded_apply_native_update(_state, _callbacks, native_update: object) -> bool:
    return _callbacks._mesh_editor_apply_native_update(native_update)

def _mesh_editor_embedded_set_skeleton_bone(_state, _callbacks, bone_index: object) -> bool:
    setter = getattr(_state.alignment_d3d11_preview_host, "set_skeleton_selected_bone", None)
    if not callable(setter):
        return False
    try:
        return bool(setter(int(bone_index)))
    except (TypeError, ValueError, RuntimeError):
        return False

def _mesh_editor_embedded_run_part_action(_state, _callbacks, action_key: str, source_indices: object) -> bool:
    normalized = str(action_key or "").strip().lower()
    if normalized in {"undo", "redo"}:
        history_action = getattr(_callbacks, f"_mesh_edit_{normalized}", None)
        if not callable(history_action):
            return False
        history_action()
        return True
    try:
        selected_sources = tuple(sorted({int(index) for index in tuple(source_indices or ()) if int(index) >= 0}))
    except (TypeError, ValueError):
        selected_sources = ()
    if not selected_sources:
        _state.self.set_status_message("Select one or more mesh parts first.", error=True)
        return False
    if normalized not in {"delete", "duplicate", "recalculate_normals", "weighted_normals", "flip_normals"}:
        return False
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return False
    action_text = {
        "delete": "Delete Part",
        "duplicate": "Clone Part",
        "recalculate_normals": "Recalculate Normals",
        "weighted_normals": "Weighted Normals",
        "flip_normals": "Flip Normals",
    }.get(normalized, normalized)
    _callbacks._mesh_edit_record_snapshot()
    params = {"delete_parts": True} if normalized == "delete" else {}
    result = _callbacks._mesh_editor_apply_static_replacement_edit(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        normalized,
        source_indices=selected_sources,
        recompute_normals=True,
        **params,
    )
    return _callbacks._mesh_editor_commit_action_bar_service_result(
        result,
        action_key=normalized,
        action_text=action_text,
        topology_action=normalized in {"delete", "duplicate"},
    )


_CALLBACKS = (
    _mesh_editor_tool_action_key,
    _mesh_editor_active_tool_action_key,
    _set_mesh_edit_enabled,
    _select_mesh_edit_tool,
    _mesh_editor_action_selection,
    _mesh_editor_action_source_indices,
    _mesh_editor_edge_selection,
    _mesh_editor_selected_edge_count,
    _mesh_editor_action_result_changed,
    _mesh_editor_action_result_within_allowed_scope,
    _mesh_editor_sync_new_source_part,
    _mesh_editor_send_embedded_dotnet_update,
    _mesh_editor_commit_action_bar_service_result,
    _mesh_editor_embedded_controller,
    _mesh_editor_embedded_apply_native_update,
    _mesh_editor_embedded_set_skeleton_bone,
    _mesh_editor_embedded_run_part_action,
)
