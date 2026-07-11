"""Stroke History callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_stroke_history_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_begin_stroke(_state, _callbacks, payload: object) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or not isinstance(payload, _state.Mapping):
        return
    if _callbacks._mesh_edit_worker_active():
        return
    can_edit, _reason = _callbacks._mesh_edit_can_edit_scope()
    if not can_edit or not _state.mesh_edit_enabled_checkbox.isChecked() or not _state._mesh_edit_tab_active():
        return
    stroke_id = _state._mesh_edit_stroke_id(payload)
    if stroke_id <= 0:
        return
    tool = _state._mesh_edit_payload_choice_helper(
        payload,
        "tool",
        _state._mesh_edit_current_tool(),
        {"move", "grab", "smooth", "inflate", "pinch", "remove", "vertex"},
    )
    delete_mode = _state._mesh_edit_payload_choice_helper(
        payload,
        "delete_mode",
        _state.mesh_edit_delete_mode_combo.currentData() or "release",
        {"release", "live", "selection"},
    )
    native_descriptor_groups = (
        _state._mesh_edit_payload_native_vertex_groups_helper(
            payload,
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            allowed_source_indices=_state._mesh_edit_allowed_source_indices(),
            source_indices_for_editor_id=_state._alignment_d3d11_source_indices_for_editor_id,
        )
        if tool != "remove" and callable(_state._mesh_edit_payload_native_vertex_groups_helper)
        else []
    )
    native_screen_selection_payload = _callbacks._mesh_edit_native_screen_selection_payload(payload)
    native_screen_stroke = tool != "remove" and (
        isinstance(payload.get("screen_drag"), _state.Mapping)
        or bool(native_screen_selection_payload)
        or isinstance(payload.get("screen_radius"), _state.Mapping)
    )
    native_descriptor_stroke = (bool(native_descriptor_groups) or native_screen_stroke) and callable(
        _state._push_geometry_sparse_mesh_edit_snapshot
    )
    if native_descriptor_groups and callable(_state._mesh_edit_cleanup_native_vertex_group_descriptors_helper):
        _state._mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_descriptor_groups)
    snapshot = None
    before_topology = None
    if not native_descriptor_stroke:
        snapshot = _callbacks._mesh_edit_capture_live_stroke_base_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)
        if snapshot is None:
            return
        before_topology = _state.mesh_topology_signature(_state._mesh_edit_state.replacement_mesh_for_mapping)
        _state._push_geometry_undo_snapshot("Mesh edit stroke")
        undo_source = snapshot if isinstance(snapshot, _state.ParsedMesh) else _state._mesh_edit_state.replacement_mesh_for_mapping
        if not _callbacks._mesh_edit_push_undo_snapshot(undo_source, take_ownership=isinstance(snapshot, _state.ParsedMesh)):
            _state.release_mesh_history_snapshot(snapshot)
            _state._pop_geometry_undo_snapshot()
            return
    _callbacks._mesh_edit_clear_active_stroke()
    _state.mesh_edit_active_stroke.update(
        {
            "id": stroke_id,
            "tool": tool,
            "delete_mode": delete_mode,
            "snapshot": snapshot,
            "base": snapshot,
            "before_topology": None if tool == "remove" or native_descriptor_stroke else before_topology,
            "native_descriptor_stroke": native_descriptor_stroke,
            "native_screen_stroke": native_screen_stroke,
            "native_screen_selection_payload": native_screen_selection_payload,
            "geometry_snapshot_pushed": not native_descriptor_stroke,
            "geometry_history_mesh_edit_revision": int(_state.mesh_edit_revision.get("value", 0) or 0),
            "geometry_history_source_geometry_revision": int(_state.source_geometry_revision.get("value", 0) or 0),
            "geometry_history_morph_slider_values": _state.copy.deepcopy(dict(_state.morph_slider_values or {})),
            "geometry_history_morph_slider_post_edit_deltas": _state.copy.deepcopy(list(_state.morph_slider_post_edit_deltas or ())),
            "geometry_history_morph_slider_topology_blocked": _state.copy.deepcopy(dict(_state.morph_slider_topology_blocked or {})),
            "undo_snapshot_pushed": not native_descriptor_stroke,
            "changed": False,
            "remove_faces_by_submesh": {},
            "remove_vertices_by_submesh": {},
            "live_delete_submeshes": set(),
        }
    )
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_restore_snapshot(_state, _callbacks, snapshot: object) -> bool:
    if not _callbacks._mesh_edit_restore_live_stroke_base_snapshot(snapshot):
        return False
    _callbacks._mesh_edit_update_mesh_totals()
    if _state._alignment_d3d11_preview_active():
        _state.mesh_edit_preview_model_dirty["value"] = True
        _callbacks._mesh_edit_commit_geometry_preview_state()
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices(), replace_all=True)
        return True
    _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _state._safe_refresh_static_dialog_preview(live_mesh_edit=True)
    return True

def _mesh_edit_descriptor_vertex_range(_state, _callbacks, raw_group: _state.Mapping[str, object]) -> tuple[int, int] | None:
    try:
        raw_start = raw_group.get("vertex_index_start", -1)
        raw_count = raw_group.get("vertex_index_count", 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0:
        return None
    return start, count

def _mesh_edit_descriptor_vertex_values(_state, _callbacks, raw_group: _state.Mapping[str, object]) -> _state.Sequence[int]:
    vertex_range = _callbacks._mesh_edit_descriptor_vertex_range(raw_group)
    if vertex_range is not None:
        start, count = vertex_range
        return range(start, start + count)
    raw_indices = raw_group.get("vertex_indices")
    return raw_indices if isinstance(raw_indices, (tuple, list, range)) else ()

def _mesh_edit_sparse_descriptor_groups(_state, _callbacks, raw_value: object) -> list[dict[str, object]]:
    if not isinstance(raw_value, _state.Mapping):
        return []
    raw_groups = raw_value.get("groups")
    candidates = tuple(raw_groups) if isinstance(raw_groups, (tuple, list)) else (raw_value,)
    groups: list[dict[str, object]] = []
    for raw_group in candidates:
        if not isinstance(raw_group, _state.Mapping):
            continue
        raw_indices = raw_group.get("vertex_indices")
        raw_binary = raw_group.get("before_positions_binary")
        raw_snapshot_id = str(
            raw_group.get("native_sparse_snapshot_id")
            or raw_group.get("sparse_snapshot_id")
            or ""
        ).strip()
        vertex_range = _callbacks._mesh_edit_descriptor_vertex_range(raw_group)
        if vertex_range is not None:
            indices: _state.Sequence[int] = range(vertex_range[0], vertex_range[0] + vertex_range[1])
            group: dict[str, object] = {
                "vertex_index_start": vertex_range[0],
                "vertex_index_count": vertex_range[1],
            }
        else:
            if not isinstance(raw_indices, (tuple, list, range)):
                continue
            parsed_indices: list[int] = []
            seen: set[int] = set()
            for raw_index in raw_indices:
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    parsed_indices = []
                    break
                if index < 0 or index in seen:
                    parsed_indices = []
                    break
                parsed_indices.append(index)
                seen.add(index)
            if not parsed_indices:
                continue
            indices = tuple(parsed_indices)
            group = {"vertex_indices": indices}
        if raw_snapshot_id:
            group["native_sparse_snapshot_id"] = raw_snapshot_id
        if not isinstance(raw_binary, _state.Mapping):
            if raw_snapshot_id:
                groups.append(group)
            continue
        try:
            count = int(raw_binary.get("count", len(indices)) or 0)
            components = int(raw_binary.get("components", 3) or 0)
        except (TypeError, ValueError):
            continue
        raw_path = str(raw_binary.get("path") or "").strip()
        raw_type = str(raw_binary.get("type") or "f64").strip().lower()
        if not raw_path or count != len(indices) or components != 3 or raw_type != "f64":
            continue
        group["before_positions_binary"] = {
            "path": raw_path,
            "count": len(indices),
            "components": 3,
            "type": "f64",
        }
        groups.append(group)
    return groups

def _mesh_edit_capture_native_stroke_delta(_state, _callbacks, mesh: object, changed_vertices_by_submesh: object) -> None:
    if mesh is None or not isinstance(changed_vertices_by_submesh, _state.Mapping):
        return
    submeshes = getattr(mesh, "submeshes", ()) or ()
    before_by_submesh = _state.mesh_edit_active_stroke.setdefault("native_before_positions_by_submesh", {})
    if not isinstance(before_by_submesh, dict):
        return
    for raw_submesh_index in changed_vertices_by_submesh.keys():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError):
            continue
        if submesh_index < 0 or submesh_index >= len(submeshes):
            continue
        submesh = submeshes[submesh_index]
        raw_delta = getattr(submesh, _state._NATIVE_STROKE_HISTORY_ATTR, None)
        if hasattr(submesh, _state._NATIVE_STROKE_HISTORY_ATTR):
            delattr(submesh, _state._NATIVE_STROKE_HISTORY_ATTR)
        if not isinstance(raw_delta, _state.Mapping):
            continue
        raw_indices = _callbacks._mesh_edit_descriptor_vertex_values(raw_delta)
        descriptor_groups = _callbacks._mesh_edit_sparse_descriptor_groups(raw_delta)
        if descriptor_groups:
            entry = before_by_submesh.setdefault(submesh_index, {"groups": []})
            if isinstance(entry, dict) and isinstance(entry.get("groups"), list):
                entry["groups"].extend(descriptor_groups)
            continue
        raw_positions = tuple(raw_delta.get("before_positions") or ())
        if len(raw_indices) != len(raw_positions):
            continue
        vertex_count = len(getattr(submesh, "vertices", ()) or ())
        positions_by_vertex = before_by_submesh.setdefault(submesh_index, {})
        if not isinstance(positions_by_vertex, dict):
            continue
        for raw_vertex_index, raw_position in zip(raw_indices, raw_positions):
            try:
                vertex_index = int(raw_vertex_index)
                position = (
                    float(raw_position[0]),  # type: ignore[index]
                    float(raw_position[1]),  # type: ignore[index]
                    float(raw_position[2]),  # type: ignore[index]
                )
            except (TypeError, ValueError, OverflowError, IndexError):
                continue
            if vertex_index < 0 or vertex_index >= vertex_count:
                continue
            if not all(-float("inf") < component < float("inf") for component in position):
                continue
            positions_by_vertex.setdefault(vertex_index, position)

def _mesh_edit_changed_vertex_range(_state, _callbacks, raw_vertices: object) -> range | None:
    if isinstance(raw_vertices, range) and raw_vertices.step == 1:
        return raw_vertices
    if not isinstance(raw_vertices, _state.Mapping):
        return None
    for start_key, count_key in (
        ("changed_vertex_start", "changed_vertex_count"),
        ("source_vertex_start", "source_vertex_count"),
    ):
        try:
            raw_start = raw_vertices.get(start_key, -1)
            raw_count = raw_vertices.get(count_key, 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if start >= 0 and count >= 0:
            return range(start, start + count)
    return None

def _mesh_edit_changed_vertices_for_source(_state, _callbacks, changed_vertices_by_submesh: object, source_submesh_index: int) -> object:
    if not isinstance(changed_vertices_by_submesh, _state.Mapping):
        return set()
    raw_vertices = changed_vertices_by_submesh.get(source_submesh_index, ())
    compact_range = _callbacks._mesh_edit_changed_vertex_range(raw_vertices)
    if compact_range is not None:
        return compact_range
    if isinstance(raw_vertices, _state.Mapping):
        return dict(raw_vertices)
    changed: set[int] = set()
    for raw_index in raw_vertices or ():
        try:
            vertex_index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if vertex_index >= 0:
            changed.add(vertex_index)
    return changed

def _mesh_edit_changed_vertex_groups_for_live_update(_state, _callbacks, changed_vertices_by_submesh: object) -> dict[int, object]:
    if not isinstance(changed_vertices_by_submesh, _state.Mapping):
        return {}
    changed: dict[int, object] = {}
    for raw_submesh_index, raw_vertices in changed_vertices_by_submesh.items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if submesh_index < 0:
            continue
        compact_range = _callbacks._mesh_edit_changed_vertex_range(raw_vertices)
        if compact_range is not None:
            changed[submesh_index] = compact_range
            continue
        if isinstance(raw_vertices, _state.Mapping):
            changed[submesh_index] = dict(raw_vertices)
            continue
        values: set[int] = set()
        for raw_index in raw_vertices or ():
            try:
                vertex_index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if vertex_index >= 0:
                values.add(vertex_index)
        if values:
            changed[submesh_index] = values
    return changed

def _mesh_edit_sparse_vertex_snapshot(_state, _callbacks, before_by_submesh: object) -> dict[str, object] | None:
    if not isinstance(before_by_submesh, _state.Mapping) or not before_by_submesh:
        return None
    positions: dict[int, object] = {}
    for raw_submesh_index, raw_positions_by_vertex in before_by_submesh.items():
        if not isinstance(raw_positions_by_vertex, _state.Mapping):
            continue
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError):
            continue
        descriptor_groups = _callbacks._mesh_edit_sparse_descriptor_groups(raw_positions_by_vertex)
        if descriptor_groups:
            positions[submesh_index] = {"groups": descriptor_groups}
            continue
        vertices: dict[int, tuple[float, float, float]] = {}
        for raw_vertex_index, raw_position in raw_positions_by_vertex.items():
            try:
                vertex_index = int(raw_vertex_index)
                position = (
                    float(raw_position[0]),  # type: ignore[index]
                    float(raw_position[1]),  # type: ignore[index]
                    float(raw_position[2]),  # type: ignore[index]
                )
            except (TypeError, ValueError, OverflowError, IndexError):
                continue
            if vertex_index >= 0 and all(-float("inf") < component < float("inf") for component in position):
                vertices[vertex_index] = position
        if vertices:
            positions[submesh_index] = vertices
    if not positions:
        return None
    return {
        "kind": "native_sparse_vertex_delta",
        "before_positions_by_submesh": positions,
    }

def _mesh_edit_is_sparse_vertex_snapshot(_state, _callbacks, snapshot: object) -> bool:
    return (
        isinstance(snapshot, _state.Mapping)
        and snapshot.get("kind") == "native_sparse_vertex_delta"
        and isinstance(snapshot.get("before_positions_by_submesh"), _state.Mapping)
    )

def _mesh_edit_current_sparse_vertex_snapshot(_state, _callbacks, snapshot: object) -> dict[str, object] | None:
    if not _callbacks._mesh_edit_is_sparse_vertex_snapshot(snapshot) or _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return None
    before_by_submesh = snapshot.get("before_positions_by_submesh")  # type: ignore[union-attr]
    try:
        from cdmw.services.mesh_workflow_service import snapshot_native_mesh_sparse_vertex_positions

        native_current = snapshot_native_mesh_sparse_vertex_positions(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            before_by_submesh,
        )
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_native_sparse_current_snapshot_exception", message=str(exc))
        native_current = None
    if native_current:
        native_snapshot = _callbacks._mesh_edit_sparse_vertex_snapshot(native_current)
        if native_snapshot is not None:
            return native_snapshot
    if not _callbacks._mesh_edit_python_sparse_current_fallback_allowed(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        before_by_submesh,
    ):
        return None
    return None

def _mesh_edit_restore_sparse_vertex_snapshot(_state, _callbacks,
        snapshot: object,
        *,
        increment_revision: bool,
        include_normals: bool,
    ) -> bool:
    mesh = _state._mesh_edit_state.replacement_mesh_for_mapping
    if mesh is None:
        return False
    if not _callbacks._mesh_edit_is_sparse_vertex_snapshot(snapshot):
        return False
    before_by_submesh = snapshot.get("before_positions_by_submesh")  # type: ignore[union-attr]
    changed_vertices_by_submesh: dict[int, object] = {}
    try:
        from cdmw.services.mesh_workflow_service import apply_native_mesh_sparse_vertex_restore

        native_restore = apply_native_mesh_sparse_vertex_restore(mesh, before_by_submesh)
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_native_sparse_restore_exception", message=str(exc))
        native_restore = None
    native_restore_applied = native_restore is not None
    if native_restore is not None:
        changed_vertices_by_submesh = _callbacks._mesh_edit_changed_vertex_groups_for_live_update(native_restore or {})
    else:
        _callbacks._mesh_edit_python_sparse_restore_fallback_allowed(mesh, before_by_submesh)
        return False
    if not changed_vertices_by_submesh:
        return False
    normal_changed_vertices_by_submesh: dict[int, object] = {}
    if include_normals:
        try:
            from cdmw.services.mesh_workflow_service import apply_native_mesh_recalculate_normals

            native_normals = apply_native_mesh_recalculate_normals(
                mesh,
                set(changed_vertices_by_submesh),
                return_changed_vertices=True,
            )
        except Exception as exc:
            _callbacks._record_mesh_edit_event("mesh_edit_native_sparse_normal_recalculate_exception", message=str(exc))
            native_normals = None
        if native_normals is not None:
            normal_changed_vertices_by_submesh = _callbacks._mesh_edit_changed_vertex_groups_for_live_update(native_normals or {})
        else:
            _callbacks._mesh_edit_python_normal_fallback_allowed(mesh, changed_vertices_by_submesh)
    _callbacks._mesh_editor_remember_static_replacement_session_mesh()
    _callbacks._mesh_edit_update_mesh_totals()
    if native_restore_applied and _state._alignment_d3d11_preview_active():
        _state.mesh_edit_preview_model_dirty["value"] = True
    else:
        _callbacks._morph_slider_capture_post_edit_deltas()
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    if increment_revision:
        _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _callbacks._sync_source_tree_enabled_checks()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    if _state._alignment_d3d11_preview_active():
        _callbacks._mesh_edit_update_live_preview(
            normal_changed_vertices_by_submesh or changed_vertices_by_submesh,
            include_normals=include_normals,
            immediate=include_normals,
        )
    else:
        _state._safe_refresh_static_dialog_preview(live_mesh_edit=True)
    return True

def _mesh_edit_restore_native_stroke_delta(_state, _callbacks, ) -> bool:
    return _callbacks._mesh_edit_restore_sparse_vertex_snapshot(
        _callbacks._mesh_edit_sparse_vertex_snapshot(_state.mesh_edit_active_stroke.get("native_before_positions_by_submesh")),
        increment_revision=False,
        include_normals=False,
    )

def _mesh_edit_replace_active_undo_with_native_sparse_snapshot(_state, _callbacks, ) -> None:
    snapshot = _callbacks._mesh_edit_sparse_vertex_snapshot(_state.mesh_edit_active_stroke.get("native_before_positions_by_submesh"))
    if snapshot is not None:
        if bool(_state.mesh_edit_active_stroke.get("undo_snapshot_pushed")) and _state.mesh_edit_undo_stack:
            _state.retain_mesh_history_snapshot(snapshot)
            _state.release_mesh_history_snapshot(_state.mesh_edit_undo_stack[-1])
            _state.mesh_edit_undo_stack[-1] = snapshot
        else:
            _state.mesh_edit_undo_stack.append(snapshot)
            _state.retain_mesh_history_snapshot(snapshot)
            _state.mesh_edit_undo_adjustment_stack.append(_state._mesh_edit_part_state_snapshot())
            if len(_state.mesh_edit_undo_stack) > 30:
                _state.release_mesh_history_snapshot(_state.mesh_edit_undo_stack.pop(0))
                if _state.mesh_edit_undo_adjustment_stack:
                    del _state.mesh_edit_undo_adjustment_stack[0]
            _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)
            _state.mesh_edit_redo_adjustment_stack.clear()
            _state.mesh_edit_active_stroke["undo_snapshot_pushed"] = True

def _mesh_edit_push_active_sparse_geometry_snapshot(_state, _callbacks, ) -> None:
    if bool(_state.mesh_edit_active_stroke.get("geometry_snapshot_pushed")):
        return
    if not callable(_state._push_geometry_sparse_mesh_edit_snapshot):
        return
    snapshot = _callbacks._mesh_edit_sparse_vertex_snapshot(_state.mesh_edit_active_stroke.get("native_before_positions_by_submesh"))
    if snapshot is None:
        return
    snapshot["mesh_edit_revision"] = int(
        _state.mesh_edit_active_stroke.get("geometry_history_mesh_edit_revision", _state.mesh_edit_revision.get("value", 0)) or 0
    )
    snapshot["source_geometry_revision"] = int(
        _state.mesh_edit_active_stroke.get("geometry_history_source_geometry_revision", _state.source_geometry_revision.get("value", 0)) or 0
    )
    snapshot["morph_slider_values"] = _state.copy.deepcopy(
        dict(_state.mesh_edit_active_stroke.get("geometry_history_morph_slider_values", _state.morph_slider_values) or {})
    )
    snapshot["morph_slider_post_edit_deltas"] = _state.copy.deepcopy(
        list(_state.mesh_edit_active_stroke.get("geometry_history_morph_slider_post_edit_deltas", _state.morph_slider_post_edit_deltas) or ())
    )
    snapshot["morph_slider_topology_blocked"] = _state.copy.deepcopy(
        dict(_state.mesh_edit_active_stroke.get("geometry_history_morph_slider_topology_blocked", _state.morph_slider_topology_blocked) or {})
    )
    if _state._push_geometry_sparse_mesh_edit_snapshot("Mesh edit stroke", snapshot):
        _state.mesh_edit_active_stroke["geometry_snapshot_pushed"] = True

def _mesh_edit_inverse_transform_disabled(_state, _callbacks, ) -> RuntimeError:
    return RuntimeError(
        "native mesh edit stroke payload did not include native screen update data; "
        "Python inverse transform fallback is disabled"
    )


_CALLBACKS = (
    _mesh_edit_begin_stroke,
    _mesh_edit_restore_snapshot,
    _mesh_edit_descriptor_vertex_range,
    _mesh_edit_descriptor_vertex_values,
    _mesh_edit_sparse_descriptor_groups,
    _mesh_edit_capture_native_stroke_delta,
    _mesh_edit_changed_vertex_range,
    _mesh_edit_changed_vertices_for_source,
    _mesh_edit_changed_vertex_groups_for_live_update,
    _mesh_edit_sparse_vertex_snapshot,
    _mesh_edit_is_sparse_vertex_snapshot,
    _mesh_edit_current_sparse_vertex_snapshot,
    _mesh_edit_restore_sparse_vertex_snapshot,
    _mesh_edit_restore_native_stroke_delta,
    _mesh_edit_replace_active_undo_with_native_sparse_snapshot,
    _mesh_edit_push_active_sparse_geometry_snapshot,
    _mesh_edit_inverse_transform_disabled,
)
