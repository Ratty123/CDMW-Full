"""Metrics callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_metrics_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _record_mesh_edit_event(_state, _callbacks, event_name: str, **payload: object) -> None:
    if callable(_state._record_runtime_event):
        _state._record_runtime_event(event_name, **payload)

def _mesh_edit_numeric_metrics(_state, _callbacks, raw_metrics: object) -> dict[str, float]:
    if not isinstance(raw_metrics, _state._MappingABC):
        return {}
    metrics: dict[str, float] = {}
    for raw_key, raw_value in raw_metrics.items():
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            continue
        if -float("inf") < value < float("inf"):
            metrics[str(raw_key)] = value
    return metrics

def _mesh_edit_result_metrics(_state, _callbacks, result: object) -> dict[str, float]:
    edit_result = getattr(result, "edit_result", None)
    return _callbacks._mesh_edit_numeric_metrics(getattr(edit_result, "metrics", None))

def _mesh_edit_last_d3d11_send_metrics(_state, _callbacks, ) -> dict[str, object]:
    reader = getattr(_state.alignment_d3d11_preview_host, "last_mesh_edit_send_metrics", None)
    if not callable(reader):
        return {}
    try:
        raw_metrics = reader()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # Best effort: D3D11 send metrics are diagnostic-only.
        return {}
    return dict(raw_metrics) if isinstance(raw_metrics, _state._MappingABC) else {}

def _mesh_edit_payload_frame_count(_state, _callbacks, payload: object) -> int:
    if not isinstance(payload, _state._MappingABC):
        return -1
    try:
        return int(payload.get("frame_count", -1) or -1)
    except (TypeError, ValueError, OverflowError):
        return -1

def _mesh_edit_changed_input_count(_state, _callbacks, changed_by_submesh: object) -> int:
    if not isinstance(changed_by_submesh, _state._MappingABC):
        return 0
    total = 0
    for raw_vertices in changed_by_submesh.values():
        if isinstance(raw_vertices, range):
            total += len(raw_vertices)
        elif isinstance(raw_vertices, _state._MappingABC):
            try:
                total += int(raw_vertices.get("changed_vertex_count", raw_vertices.get("source_vertex_count", 0)) or 0)
            except (TypeError, ValueError, OverflowError):
                pass
        else:
            try:
                total += len(raw_vertices)  # type: ignore[arg-type]
            except TypeError:
                pass
    return max(0, total)

def _record_mesh_edit_live_stroke_timing(_state, _callbacks,
        payload: object,
        result: object,
        *,
        tool: str,
        phase: object,
        callback_started: float,
        edit_apply_ms: float,
        d3d11_update_ms: float,
        native_update_applied: bool,
        changed_by_submesh: object,
    ) -> None:
    metrics = _callbacks._mesh_edit_result_metrics(result)
    _callbacks._record_mesh_edit_event(
        "mesh_edit_live_stroke_timing",
        stroke_id=_state._mesh_edit_stroke_id(payload),
        tool=str(tool or ""),
        phase=str(phase or ""),
        d3d11_frame_count=_callbacks._mesh_edit_payload_frame_count(payload),
        callback_ms=max(0.0, (_state.time.perf_counter() - callback_started) * 1000.0),
        edit_apply_ms=max(0.0, float(edit_apply_ms or 0.0)),
        d3d11_update_ms=max(0.0, float(d3d11_update_ms or 0.0)),
        native_update_applied=bool(native_update_applied),
        changed_submesh_count=len(changed_by_submesh) if isinstance(changed_by_submesh, _state._MappingABC) else 0,
        changed_vertex_input_count=_callbacks._mesh_edit_changed_input_count(changed_by_submesh),
        service_total_ms=float(metrics.get("service_total_ms", 0.0) or 0.0),
        service_dispatch_ms=float(metrics.get("service_dispatch_ms", 0.0) or 0.0),
        native_apply_roundtrip_ms=float(metrics.get("native_apply_roundtrip_ms", 0.0) or 0.0),
        native_apply_overhead_ms=float(metrics.get("native_apply_overhead_ms", 0.0) or 0.0),
        cpp_ms=float(metrics.get("cpp_ms", 0.0) or 0.0),
        io_serialization_ms=float(metrics.get("io_serialization_ms", 0.0) or 0.0),
        python_apply_ms=float(metrics.get("python_apply_ms", 0.0) or 0.0),
        editor_select_reused=float(metrics.get("editor_select_reused", 0.0) or 0.0),
        editor_select_inlined=float(metrics.get("editor_select_inlined", 0.0) or 0.0),
        d3d11_send_metrics=_callbacks._mesh_edit_last_d3d11_send_metrics(),
    )

def _mesh_edit_mark_native_preview_stale(_state, _callbacks, message: str, **payload: object) -> None:
    _callbacks._record_mesh_edit_event("mesh_edit_native_preview_stale", message=message, **payload)
    _state.self.set_status_message(message, error=True)

def _mesh_editor_queue_native_preview_rebuild_from_working_mesh(_state, _callbacks,
        reason: str,
        message: str,
        **payload: object,
    ) -> None:
    _state.mesh_edit_preview_model_dirty["value"] = True
    _state.mesh_edit_native_result_submesh_counts["value"] = ()
    _state.static_preview_geometry_cache.clear()
    _state.static_preview_prepared_cache.clear()
    if callable(_state._mark_alignment_d3d11_rebuild_reason):
        _state._mark_alignment_d3d11_rebuild_reason(str(reason or "mesh_edit_topology"))
    if callable(_state._alignment_d3d11_invalidate_package_cache):
        _state._alignment_d3d11_invalidate_package_cache(str(reason or "mesh_edit_topology"))
    _callbacks._mesh_edit_mark_native_preview_stale(message, **payload)
    if callable(_state._queue_latest_alignment_d3d11_rebuild_for_stale_reload):
        try:
            _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload(0, force_active_mesh_edit=True)
            return
        except TypeError:
            _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload(0)
            return
    if callable(_state._queue_static_preview_rebuild):
        _state._queue_static_preview_rebuild()

def _mesh_edit_capture_live_stroke_base_snapshot(_state, _callbacks, mesh: _state.ParsedMesh) -> object | None:
    try:
        from cdmw.services.mesh_workflow_service import snapshot_native_mesh_submeshes

        native_snapshot = snapshot_native_mesh_submeshes(mesh)
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_native_live_stroke_snapshot_exception", message=str(exc))
        native_snapshot = None
    if native_snapshot is not None:
        return native_snapshot
    _callbacks._record_mesh_edit_event(
        "mesh_edit_native_live_stroke_snapshot_failed",
        message="Native live stroke snapshot failed; Python full-mesh live stroke clone fallback is disabled.",
    )
    _state.self.set_status_message(
        "Native live stroke snapshot failed; Python full-mesh live stroke clone fallback is disabled.",
        error=True,
    )
    return None

def _mesh_edit_restore_live_stroke_base_snapshot(_state, _callbacks, snapshot: object) -> bool:
    if isinstance(snapshot, _state.Mapping) and snapshot.get("kind") == "native_submesh_snapshot":
        try:
            from cdmw.services.mesh_workflow_service import restore_native_mesh_submesh_snapshot

            restored = _state.ParsedMesh()
            if restore_native_mesh_submesh_snapshot(restored, snapshot):
                _state._mesh_edit_state.replacement_mesh_for_mapping = restored
                return True
        except Exception as exc:
            _callbacks._record_mesh_edit_event("mesh_edit_native_live_stroke_restore_exception", message=str(exc))
            return False
        return False
    if isinstance(snapshot, _state.ParsedMesh):
        return False
    return False

def _mesh_edit_clear_active_stroke(_state, _callbacks, ) -> None:
    _state.release_mesh_history_snapshot(_state.mesh_edit_active_stroke.get("base"))
    _state.mesh_edit_active_stroke.clear()

def _mesh_edit_python_normal_fallback_allowed(_state, _callbacks, mesh: _state.ParsedMesh, source_indices: _state.Iterable[int]) -> bool:
    normalized: set[int] = set()
    for raw_index in source_indices or ():
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if source_index >= 0:
            normalized.add(source_index)
    message = "Native normal recompute failed; Python normal fallback is disabled."
    _callbacks._record_mesh_edit_event(
        "mesh_edit_python_normals_fallback_blocked",
        source_indices=tuple(sorted(normalized)),
        message=message,
    )
    _state.self.set_status_message(message, error=True)
    return False

def _mesh_edit_sparse_restore_source_indices(_state, _callbacks, before_by_submesh: object) -> tuple[int, ...]:
    if not isinstance(before_by_submesh, _state.Mapping):
        return ()
    indices: set[int] = set()
    for raw_index in before_by_submesh:
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if source_index >= 0:
            indices.add(source_index)
    return tuple(sorted(indices))

def _mesh_edit_python_sparse_restore_fallback_allowed(_state, _callbacks, mesh: _state.ParsedMesh, before_by_submesh: object) -> bool:
    source_indices = _callbacks._mesh_edit_sparse_restore_source_indices(before_by_submesh)
    message = "Native sparse history restore failed; Python restore fallback is disabled."
    _callbacks._record_mesh_edit_event(
        "mesh_edit_python_sparse_restore_fallback_blocked",
        source_indices=source_indices,
        message=message,
    )
    _state.self.set_status_message(message, error=True)
    return False

def _mesh_edit_python_sparse_current_fallback_allowed(_state, _callbacks, mesh: _state.ParsedMesh, before_by_submesh: object) -> bool:
    source_indices = _callbacks._mesh_edit_sparse_restore_source_indices(before_by_submesh)
    message = "Native sparse history current snapshot failed; Python snapshot fallback is disabled."
    _callbacks._record_mesh_edit_event(
        "mesh_edit_python_sparse_current_fallback_blocked",
        source_indices=source_indices,
        message=message,
    )
    _state.self.set_status_message(message, error=True)
    return False

def _mesh_edit_source_to_preview_point(_state, _callbacks, point: _state.Sequence[object]) -> tuple[float, float, float]:
    normalizer = _state.original_reference_preview_model or _state._mesh_edit_state.replacement_preview_model
    return _state._mesh_edit_source_to_preview_point_helper(
        point,
        normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
        normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
    )

def _mesh_edit_update_mesh_totals(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    native_counts = tuple(_state.mesh_edit_native_result_submesh_counts.get("value") or ())
    if native_counts:
        _state._mesh_edit_state.replacement_mesh_for_mapping.total_vertices = sum(vertex_count for vertex_count, _ in native_counts)
        _state._mesh_edit_state.replacement_mesh_for_mapping.total_faces = sum(face_count for _, face_count in native_counts)
        return
    totals = _state._mesh_edit_mesh_totals_helper(_state._mesh_edit_state.replacement_mesh_for_mapping)
    _state._mesh_edit_state.replacement_mesh_for_mapping.total_vertices = int(totals["total_vertices"])
    _state._mesh_edit_state.replacement_mesh_for_mapping.total_faces = int(totals["total_faces"])
    _state._mesh_edit_state.replacement_mesh_for_mapping.has_uvs = bool(totals["has_uvs"])

def _mesh_edit_adjusted_sources_for_live_preview(_state, _callbacks, source_indices: _state.Iterable[int]) -> _state.Dict[int, object]:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return {}
    requested = _state._mesh_edit_requested_source_indices_helper(_state._mesh_edit_state.replacement_mesh_for_mapping, source_indices)
    if not requested:
        return {}
    transformed: _state.Dict[int, object] = {}
    for source_index in requested:
        source = _state._mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
        adjustment = _state.source_part_adjustments.get(source_index)
        transformed[source_index] = (
            source
            if adjustment is None or _state._is_default_source_part_adjustment(adjustment)
            else _state._copy_source_part_with_adjustment(source, adjustment)
        )
    return transformed

def _mesh_edit_transformed_sources_for_live_preview(_state, _callbacks, source_indices: _state.Iterable[int]) -> _state.Dict[int, object]:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return {}
    requested = _state._mesh_edit_requested_source_indices_helper(_state._mesh_edit_state.replacement_mesh_for_mapping, source_indices)
    if not requested:
        return {}
    if _state.original_mesh_for_mapping is None:
        return _callbacks._mesh_edit_adjusted_sources_for_live_preview(requested)
    if not all(
        callable(callback)
        for callback in (
            _state._transformed_replacement_sources,
            _state._current_dialog_mappings_for_preview,
            _state._current_static_alignment_transform,
            _state._current_source_part_adjustments,
            _state._current_texture_uv_transforms,
            _state._mapped_source_indices,
        )
    ):
        return _callbacks._mesh_edit_adjusted_sources_for_live_preview(requested)
    try:
        current_mappings = _state._current_dialog_mappings_for_preview()
        transformed_sources = _state._transformed_replacement_sources(
            _state.original_mesh_for_mapping,
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            _state._current_static_alignment_transform(),
            _state._current_source_part_adjustments(),
            _state._current_texture_uv_transforms(),
            global_transform_exempt_indices=set(_state.appended_source_indices),
            global_transform_source_indices=_state._mapped_source_indices(current_mappings),
            max_source_faces_per_submesh=0,
            output_source_indices=set(requested),
            alignment_basis_mesh=_state._mesh_edit_state.replacement_mesh_base_for_mapping or _state._mesh_edit_state.replacement_mesh_for_mapping,
        )
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_live_transform_error", message=str(exc))
        return _callbacks._mesh_edit_adjusted_sources_for_live_preview(requested)
    return {
        source_index: transformed_sources[source_index]
        for source_index in requested
        if 0 <= source_index < len(transformed_sources)
    }

def _mesh_edit_submesh_for_live_preview(_state, _callbacks, source_index: int):
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or source_index < 0 or source_index >= len(_state._mesh_edit_state.replacement_mesh_for_mapping.submeshes):
        return None
    return _callbacks._mesh_edit_transformed_sources_for_live_preview((source_index,)).get(source_index)

def _mesh_edit_source_space_live_update_allowed(_state, _callbacks, source_indices: _state.Iterable[int]) -> bool:
    if _state.original_mesh_for_mapping is not None:
        return False
    for source_index in source_indices or ():
        adjustment = _state.source_part_adjustments.get(source_index)
        if adjustment is not None and not _state._is_default_source_part_adjustment(adjustment):
            return False
    return True

def _mesh_edit_affine_preview_transforms(_state, _callbacks,
        source_indices: _state.Iterable[int],
        *,
        include_normals: bool = False,
    ) -> tuple[_state.Dict[int, tuple[float, ...]], _state.Dict[int, tuple[float, ...]]]:
    if (
        _state.original_mesh_for_mapping is None
        or _state._mesh_edit_state.replacement_mesh_for_mapping is None
        or not callable(_state.source_affine_for_transformed_preview)
        or (include_normals and not callable(_state.source_normal_transform_for_transformed_preview))
        or not all(
            callable(callback)
            for callback in (
                _state._current_dialog_mappings_for_preview,
                _state._current_static_alignment_transform,
                _state._current_source_part_adjustments,
                _state._mapped_source_indices,
            )
        )
    ):
        return {}, {}
    normalizer = _state.original_reference_preview_model or _state._mesh_edit_state.replacement_preview_model
    try:
        current_mappings = _state._current_dialog_mappings_for_preview()
        mapped_sources = _state._mapped_source_indices(current_mappings)
        transforms: _state.Dict[int, tuple[float, ...]] = {}
        normal_transforms: _state.Dict[int, tuple[float, ...]] = {}
        for source_index in source_indices or ():
            transform_args = {
                "source_part_adjustments": _state._current_source_part_adjustments(),
                "global_transform_exempt_indices": set(_state.appended_source_indices),
                "global_transform_source_indices": mapped_sources,
                "alignment_basis_mesh": _state._mesh_edit_state.replacement_mesh_base_for_mapping or _state._mesh_edit_state.replacement_mesh_for_mapping,
            }
            affine = _state.source_affine_for_transformed_preview(
                _state.original_mesh_for_mapping,
                _state._mesh_edit_state.replacement_mesh_for_mapping,
                _state._current_static_alignment_transform(),
                int(source_index),
                normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
                normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
                **transform_args,
            )
            if affine is None:
                return {}, {}
            transforms[int(source_index)] = affine
            if include_normals:
                normal_transform = _state.source_normal_transform_for_transformed_preview(
                    _state.original_mesh_for_mapping,
                    _state._mesh_edit_state.replacement_mesh_for_mapping,
                    _state._current_static_alignment_transform(),
                    int(source_index),
                    **transform_args,
                )
                if normal_transform is None:
                    return {}, {}
                normal_transforms[int(source_index)] = normal_transform
    except Exception as exc:
        _callbacks._record_mesh_edit_event("mesh_edit_live_affine_transform_error", message=str(exc))
        return {}, {}
    return transforms, normal_transforms

def _mesh_edit_live_vertex_update_groups(_state, _callbacks,
        changed_vertices_by_submesh: _state.Mapping[int, object] | None,
        *,
        include_normals: bool = False,
    ) -> _state.List[_state.Dict[str, object]]:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or not changed_vertices_by_submesh:
        return []
    requested_source_indices = _state._mesh_edit_requested_source_indices_helper(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        changed_vertices_by_submesh.keys(),
    )
    if not requested_source_indices:
        return []
    normalizer = _state.original_reference_preview_model or _state._mesh_edit_state.replacement_preview_model
    if callable(_state._mesh_edit_native_live_vertex_update_groups_helper):
        position_transforms, normal_transforms = _callbacks._mesh_edit_affine_preview_transforms(
            requested_source_indices,
            include_normals=include_normals,
        )
        native_groups = _state._mesh_edit_native_live_vertex_update_groups_helper(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            changed_vertices_by_submesh,
            normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
            normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
            include_normals=include_normals,
            position_transform_by_source=position_transforms or None,
            normal_transform_by_source=normal_transforms or None,
            allow_source_space=_callbacks._mesh_edit_source_space_live_update_allowed(requested_source_indices),
        )
        if native_groups:
            return native_groups
        if _callbacks._alignment_d3d11_mesh_edit_commands_active():
            return []
    transformed_sources_by_index = _callbacks._mesh_edit_transformed_sources_for_live_preview(
        requested_source_indices
    )
    return _state._mesh_edit_live_vertex_update_groups_helper(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        changed_vertices_by_submesh,
        transformed_sources_by_index,
        source_to_preview_point=_callbacks._mesh_edit_source_to_preview_point,
        include_normals=include_normals,
    )

def _flush_mesh_edit_live_vertex_updates(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or not _state.mesh_edit_pending_live_vertices:
        _state.mesh_edit_pending_live_vertices.clear()
        _state.mesh_edit_pending_live_normals["include"] = False
        return
    groups = _callbacks._mesh_edit_live_vertex_update_groups(
        _state.mesh_edit_pending_live_vertices,
        include_normals=bool(_state.mesh_edit_pending_live_normals.get("include")),
    )
    pending_source_indices = _state._mesh_edit_requested_source_indices_helper(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        _state.mesh_edit_pending_live_vertices.keys(),
    )
    _state.mesh_edit_pending_live_vertices.clear()
    _state.mesh_edit_pending_live_normals["include"] = False
    if _callbacks._alignment_d3d11_mesh_edit_commands_active():
        if not groups:
            _callbacks._record_mesh_edit_event(
                "mesh_edit_live_vertex_update_empty",
                source_indices=pending_source_indices,
            )
            _callbacks._mesh_edit_mark_native_preview_stale(
                ".NET/Vortice mesh edit preview produced no vertex update payload; preview is stale. Retry .NET/Vortice Preview to resync.",
                source_indices=pending_source_indices,
            )
            return
        if _state.alignment_d3d11_preview_host.update_mesh_edit_vertices(groups):
            return
        source_indices = _callbacks._mesh_edit_source_indices_from_groups(groups)
        _callbacks._record_mesh_edit_event(
            "mesh_edit_live_vertex_update_failed",
            source_indices=source_indices,
            group_count=len(groups),
        )
        if source_indices and _callbacks._mesh_edit_replace_live_triangles(source_indices):
            return
        _callbacks._mesh_edit_mark_native_preview_stale(
            ".NET/Vortice mesh edit preview update failed; preview is stale. Retry .NET/Vortice Preview to resync.",
            source_indices=source_indices,
            group_count=len(groups),
        )


_CALLBACKS = (
    _record_mesh_edit_event,
    _mesh_edit_numeric_metrics,
    _mesh_edit_result_metrics,
    _mesh_edit_last_d3d11_send_metrics,
    _mesh_edit_payload_frame_count,
    _mesh_edit_changed_input_count,
    _record_mesh_edit_live_stroke_timing,
    _mesh_edit_mark_native_preview_stale,
    _mesh_editor_queue_native_preview_rebuild_from_working_mesh,
    _mesh_edit_capture_live_stroke_base_snapshot,
    _mesh_edit_restore_live_stroke_base_snapshot,
    _mesh_edit_clear_active_stroke,
    _mesh_edit_python_normal_fallback_allowed,
    _mesh_edit_sparse_restore_source_indices,
    _mesh_edit_python_sparse_restore_fallback_allowed,
    _mesh_edit_python_sparse_current_fallback_allowed,
    _mesh_edit_source_to_preview_point,
    _mesh_edit_update_mesh_totals,
    _mesh_edit_adjusted_sources_for_live_preview,
    _mesh_edit_transformed_sources_for_live_preview,
    _mesh_edit_submesh_for_live_preview,
    _mesh_edit_source_space_live_update_allowed,
    _mesh_edit_affine_preview_transforms,
    _mesh_edit_live_vertex_update_groups,
    _flush_mesh_edit_live_vertex_updates,
)
