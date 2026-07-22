"""Live Preview callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_live_preview_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _queue_mesh_edit_live_vertex_updates(_state, _callbacks,
        changed_vertices_by_submesh: _state.Mapping[int, object] | None,
        *,
        include_normals: bool = False,
        immediate: bool = False,
    ) -> None:
    if not changed_vertices_by_submesh:
        return
    _state._mesh_edit_queue_live_vertex_updates_helper(_state.mesh_edit_pending_live_vertices, changed_vertices_by_submesh)
    _state.mesh_edit_pending_live_normals["include"] = bool(_state.mesh_edit_pending_live_normals.get("include") or include_normals)
    if immediate:
        _state.mesh_edit_live_update_timer.stop()
        _callbacks._flush_mesh_edit_live_vertex_updates()
    elif not _state.mesh_edit_live_update_timer.isActive():
        _state.mesh_edit_live_update_timer.start()

def _mesh_edit_triangle_replace_groups(_state, _callbacks, source_indices: _state.Iterable[int]) -> _state.List[_state.Dict[str, object]]:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return []
    requested_source_indices = _state._mesh_edit_requested_source_indices_helper(_state._mesh_edit_state.replacement_mesh_for_mapping, source_indices)
    normalizer = _state.original_reference_preview_model or _state._mesh_edit_state.replacement_preview_model
    position_transforms, normal_transforms = _callbacks._mesh_edit_affine_preview_transforms(
        requested_source_indices,
        include_normals=True,
    )
    groups = _state._mesh_edit_triangle_replace_groups_helper(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        requested_source_indices,
        {},
        source_to_preview_point=_callbacks._mesh_edit_source_to_preview_point,
        normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
        normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
        position_transform_by_source=position_transforms or None,
        normal_transform_by_source=normal_transforms or None,
        allow_source_space=_callbacks._mesh_edit_source_space_live_update_allowed(requested_source_indices),
    )
    covered = {
        int(group.get("source_submesh_index", -1))
        for group in groups
        if hasattr(group, "get")
    }
    missing_source_indices = tuple(index for index in requested_source_indices if int(index) not in covered)
    if not missing_source_indices:
        return groups
    if _callbacks._alignment_d3d11_mesh_edit_commands_active():
        return []
    transformed_sources_by_index = _callbacks._mesh_edit_transformed_sources_for_live_preview(missing_source_indices)
    groups.extend(
        _state._mesh_edit_triangle_replace_groups_helper(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            missing_source_indices,
            transformed_sources_by_index,
            source_to_preview_point=_callbacks._mesh_edit_source_to_preview_point,
        )
    )
    return groups

def _mesh_edit_source_indices_from_groups(_state, _callbacks, groups: _state.Iterable[_state.Mapping[str, object]]) -> tuple[int, ...]:
    indices: set[int] = set()
    for group in groups or ():
        if not hasattr(group, "get"):
            continue
        try:
            source_index = int(group.get("source_submesh_index", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if source_index >= 0:
            indices.add(source_index)
    return tuple(sorted(indices))

def _mesh_edit_reusable_source_indices(_state, _callbacks, source_indices: _state.Iterable[int] | None) -> _state.Iterable[int]:
    if source_indices is None:
        return ()
    if isinstance(source_indices, _state._SequenceABC):
        return source_indices
    return tuple(source_indices or ())

def _mesh_edit_replace_live_triangles(_state, _callbacks, source_indices: _state.Iterable[int], *, replace_all: bool = False) -> bool:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return False
    if _callbacks._alignment_d3d11_mesh_edit_commands_active():
        _state.mesh_edit_live_update_timer.stop()
        _callbacks._flush_mesh_edit_live_vertex_updates()
        requested_source_indices = _state._mesh_edit_requested_source_indices_helper(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            source_indices,
        )
        groups = _callbacks._mesh_edit_triangle_replace_groups(source_indices)
        missing_group_sources = _state.mesh_edit_missing_nonempty_triangle_group_sources(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            requested_source_indices,
            groups,
        )
        if missing_group_sources:
            _callbacks._record_mesh_edit_event(
                "mesh_edit_live_triangle_replace_missing_groups",
                source_indices=missing_group_sources,
                requested_source_indices=requested_source_indices,
                group_count=len(groups),
                replace_all=bool(replace_all),
            )
            return False
        if groups or requested_source_indices:
            if _state.alignment_d3d11_preview_host.replace_mesh_edit_triangles(
                groups,
                replace_all=replace_all,
                source_submesh_indices=requested_source_indices,
            ):
                return True
            _callbacks._record_mesh_edit_event(
                "mesh_edit_live_triangle_replace_failed",
                source_indices=requested_source_indices,
                group_count=len(groups),
                replace_all=bool(replace_all),
            )
        return False
    return False

def _mesh_edit_replace_live_triangles_or_queue_rebuild(_state, _callbacks, source_indices: _state.Iterable[int], *, replace_all: bool = False) -> None:
    requested_source_indices = _callbacks._mesh_edit_reusable_source_indices(source_indices)
    if _callbacks._mesh_edit_replace_live_triangles(requested_source_indices, replace_all=replace_all):
        return
    if _callbacks._alignment_d3d11_mesh_edit_commands_active():
        _callbacks._mesh_editor_queue_native_preview_rebuild_from_working_mesh(
            "mesh_edit_topology",
            ".NET/Vortice mesh edit triangle update failed; rebuilding the resident preview from the working mesh.",
            source_indices=tuple(requested_source_indices or ()),
            replace_all=bool(replace_all),
        )
        return
    if _state._alignment_d3d11_preview_active():
        _callbacks._mesh_edit_mark_native_preview_stale(
            ".NET/Vortice mesh edit commands are unavailable; preview is stale. Retry .NET/Vortice Preview to resync.",
            source_indices=tuple(requested_source_indices or ()),
            replace_all=bool(replace_all),
        )
        return
    if _state._mesh_edit_tab_active():
        _callbacks._mesh_edit_mark_native_preview_stale(
            "Active Mesh Editor triangle refresh requires .NET/Vortice refresh; Python preview rebuild fallback is disabled.",
            source_indices=tuple(requested_source_indices or ()),
            replace_all=bool(replace_all),
        )
        return
    _state._queue_static_preview_rebuild()

def _mesh_editor_apply_native_update(_state, _callbacks, native_update: object) -> bool:
    if not _callbacks._alignment_d3d11_mesh_edit_commands_active():
        return False
    _state.mesh_edit_live_update_timer.stop()
    _callbacks._flush_mesh_edit_live_vertex_updates()
    return _state.apply_native_update_to_host(_state.alignment_d3d11_preview_host, native_update)

def _mesh_editor_apply_result_native_update(_state, _callbacks, result: object) -> bool:
    native_update = getattr(result, "native_update", None)
    active_commands = _callbacks._alignment_d3d11_mesh_edit_commands_active()
    if native_update is None:
        if _callbacks._mesh_editor_result_has_deferred_native_python_apply(result):
            _callbacks._mesh_editor_queue_native_preview_rebuild_from_working_mesh(
                "mesh_edit_topology",
                "Native deferred mesh edit result had no preview payload; rebuilding native preview from the working mesh.",
            )
            return False
        if active_commands and _callbacks._mesh_editor_result_changes_mesh(result):
            _callbacks._mesh_editor_queue_native_preview_rebuild_from_working_mesh(
                "mesh_edit_topology",
                "Active native mesh edit result had no preview payload; rebuilding native preview from the working mesh.",
            )
            return False
        return False
    applied = _callbacks._mesh_editor_apply_native_update(native_update)
    if not applied and _callbacks._mesh_editor_result_has_deferred_native_python_apply(result):
        _callbacks._mesh_editor_queue_native_preview_rebuild_from_working_mesh(
            "mesh_edit_topology",
            "Native deferred mesh edit preview payload was rejected; rebuilding native preview from the working mesh.",
        )
        return False
    if not applied and active_commands:
        _callbacks._mesh_editor_queue_native_preview_rebuild_from_working_mesh(
            "mesh_edit_topology",
            "Active native mesh edit preview payload was rejected; rebuilding native preview from the working mesh.",
        )
        return False
    return applied

def _mesh_edit_update_live_preview(_state, _callbacks,
        changed_vertices_by_submesh: _state.Mapping[int, object] | None = None,
        *,
        include_normals: bool = False,
        immediate: bool = False,
    ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    _callbacks._mesh_edit_update_mesh_totals()
    if _callbacks._alignment_d3d11_mesh_edit_commands_active():
        if changed_vertices_by_submesh:
            _callbacks._queue_mesh_edit_live_vertex_updates(
                changed_vertices_by_submesh,
                include_normals=include_normals,
                immediate=immediate,
            )
            return
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices())
        return
    if changed_vertices_by_submesh and not immediate and _state._alignment_d3d11_preview_active():
        _callbacks._record_mesh_edit_event(
            "mesh_edit_live_preview_deferred",
            reason="native mesh edit commands unavailable",
        )
        return
    if _state._alignment_d3d11_preview_active():
        _callbacks._mesh_edit_mark_native_preview_stale(
            ".NET/Vortice mesh edit commands are unavailable; preview is stale. Retry .NET/Vortice Preview to resync.",
            reason="native mesh edit commands unavailable",
        )
        return
    if _state._mesh_edit_tab_active():
        _state.self.set_status_message(
            "Active Mesh Editor live preview requires .NET/Vortice; Python preview rebuild fallback is disabled.",
            error=True,
        )
        _callbacks._record_mesh_edit_event(
            "mesh_edit_live_preview_rebuild_blocked",
            reason=".NET/Vortice unavailable",
        )
        return
    _callbacks._mesh_edit_refresh_replacement_preview_model()
    _state._safe_refresh_static_dialog_preview(live_mesh_edit=True)


_CALLBACKS = (
    _queue_mesh_edit_live_vertex_updates,
    _mesh_edit_triangle_replace_groups,
    _mesh_edit_source_indices_from_groups,
    _mesh_edit_reusable_source_indices,
    _mesh_edit_replace_live_triangles,
    _mesh_edit_replace_live_triangles_or_queue_rebuild,
    _mesh_editor_apply_native_update,
    _mesh_editor_apply_result_native_update,
    _mesh_edit_update_live_preview,
)
