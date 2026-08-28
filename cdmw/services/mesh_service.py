from __future__ import annotations

import copy
import hashlib
import math
import os
import threading
import time
from dataclasses import dataclass, field, replace
from functools import wraps
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.mesh import (
    DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS,
    MESH_EDIT_ACTIONS,
    MESH_EDIT_MODES,
    MESH_MORPH_ACTIONS,
    MeshAnimationClip,
    MeshEditCommand,
    MeshEditHistoryEntry,
    MeshEditResult,
    MeshEditSelection,
    MeshEditSessionView,
    MeshObjectTransformState,
    MeshCompareSummary,
    MeshExportValidationReport,
    MeshPartSummary,
    MeshSkeletonSummary,
    MeshTextureEditTarget,
    MeshUvIslandSummary,
    MeshUvSummary,
    MeshWorkspaceSummary,
    compare_meshes,
    mesh_pose_deformed_vertices,
    sample_mesh_animation_pose,
    selected_mesh_texture_edit_target,
    summarize_mesh_skinning,
    summarize_mesh_uvs,
    summarize_mesh_workspace,
    validate_mesh_export,
)
from cdmw.domain.mesh.operations import MeshEditOperation
from cdmw.domain.mesh.topology import (
    topology_operation_for_native_action,
    topology_operation_metadata,
    validate_topology_provenance,
)
from cdmw.domain.textures.material_authority import complete_swap_material_authority_contract, sanitize_texture_component
from cdmw.modding.mesh_deformer import clone_mesh_for_editing, copy_extra_submesh_attrs
from cdmw.modding.mesh_deformer import recompute_mesh_normals
from cdmw.modding.mesh_edit_ops import (
    MESH_GEOMETRY_ACTIONS,
    MESH_TOPOLOGY_ACTIONS,
    NativeLiveHistoryUnavailable,
    apply_mesh_edit_geometry_action,
    refresh_mesh_totals,
)
from cdmw.modding.mesh_native_core import (
    NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    apply_native_mesh_editor_session,
    copy_native_mesh_editor_session,
    last_native_mesh_core_job_error,
    last_native_mesh_editor_apply_error,
    apply_native_mesh_pose_preview,
    apply_native_mesh_recalculate_normals,
    apply_native_mesh_selection,
    apply_native_mesh_sparse_vertex_restore,
    apply_native_mesh_skin_weights,
    close_native_mesh_editor_session,
    dispose_native_mesh_history_delta,
    dispose_native_mesh_sparse_vertex_snapshot,
    dispose_native_mesh_submesh_snapshot,
    export_native_mesh_editor_session_snapshot,
    export_native_mesh_editor_session_to_mesh,
    invalidate_native_mesh_session_submeshes,
    native_mesh_history_delta_positions,
    native_mesh_core_available,
    native_mesh_core_fallback_events,
    native_mesh_editor_session_preview_triangle_groups,
    native_mesh_editor_session_preview_vertex_update_groups,
    native_mesh_editor_session_selection_from_report,
    native_mesh_editor_session_selection_groups_from_report,
    native_mesh_editor_source_normals_payload,
    prune_native_mesh_selection,
    record_native_mesh_core_fallback,
    restore_native_mesh_submesh_snapshot,
    open_native_mesh_editor_session,
    redo_native_mesh_editor_session,
    select_native_mesh_uv_vertices,
    select_native_mesh_editor_session,
    snapshot_native_mesh_submeshes,
    summarize_native_mesh_editor_session,
    summarize_native_mesh_uvs,
    transfer_native_mesh_skin_weights_from_source,
    undo_native_mesh_editor_session,
)
from cdmw.modding.mesh_asset import mesh_asset_from_parsed_mesh
from cdmw.modding.mesh_importer import MeshRebuildReport, apply_operation_channels_to_original, rebuild_mesh_with_report
from cdmw.modding.mesh_obj_importer import validate_obj_sidecar_source_identity
from cdmw.modding.mesh_parser import ParsedMesh, is_mesh_file, parse_mesh
from cdmw.modding.mesh_roundtrip import roundtrip_mesh_bytes
from cdmw.models import RunCancelled
from cdmw.services.mesh_service_state import (
    _MeshCommandExecution,
    _MeshEditSession,
    _MeshGeometryLayer,
    _MeshHistorySnapshot,
    _MeshRestoreOutcome,
    _MeshVertexPositionDelta,
    _NativeEditorApplyResult,
    MeshPreparedWorkingMeshReplacement,
)
from cdmw.services.mesh_layer_project_service import (
    discover_mesh_layer_project_context,
    load_mesh_layer_project,
    save_mesh_layer_project,
)
from cdmw.services.mesh_service_rigging import (
    MeshRiggingServiceMixin,
    _bone_indices_by_name,
    _bone_name,
    _bone_name_remap,
    _bone_names_by_index,
    _clean_weight_pairs,
    _coerce_animation_speed,
    _coerce_fraction,
    _coerce_time_seconds,
    _coerce_weight_delta,
    _effective_pose_rotations,
    _ensure_skinning_rows,
    _normalize_weight_row,
    _nudge_bone_weight,
    _pack_weight_pairs,
    _position3,
    _remap_weight_row,
    _require_clean_python_skeleton_state,
    _rotation_vec3,
    _row_tuple,
    _source_vertex_index_for_transfer,
    _transfer_vertex_indices,
    _valid_vertex_indices,
)
from cdmw.services.mesh_service_rebuild import MeshRebuildServiceMixin, _native_source_parse_eligible
from cdmw.services.mesh_service_replacement import MeshWorkingReplacementServiceMixin
from cdmw.services.mesh_service_materials import MeshResidentMaterialServiceMixin
from cdmw.services.mesh_service_selection import (
    _apply_selection_operation_to_mesh,
    _command_selection,
    _prune_selection_to_mesh,
    _record_blocked_python_selection_fallback,
    _selected_skin_weight_vertex_count,
    _selection_after_working_mesh_replace,
)
from cdmw.services.mesh_service_reports import (
    _CHANGED_VERTEX_RESULT_TUPLE_LIMIT,
    _bounded_native_editor_changed_vertices,
    _changed_vertex_descriptor_for_result,
    _changed_vertex_indices_for_result,
    _coerce_index,
    _mesh_texture_edit_target_from_native_summary,
    _mesh_uv_summary_from_native,
    _mesh_workspace_summary_from_native,
    _native_editor_dirty_counts_from_report,
    _native_editor_report_affected_indices,
    _native_editor_report_changed_vertices,
    _native_editor_report_submesh_counts,
    _vec2,
)
from cdmw.services.mesh_service_payloads import (
    _LEGACY_SCREEN_CAMERA_FIELDS,
    _NATIVE_EDITOR_SCREEN_PAYLOAD_KEYS,
    _NATIVE_MATERIAL_OVERRIDE_KEYS,
    _native_editor_selection_payload,
    _native_editor_select_payload_for_params,
    _add_native_editor_screen_selection_payload,
    _native_editor_screen_payload,
    _native_editor_selection_target_indices,
    _native_editor_edit_payload,
    _native_editor_material_extra_attrs,
    _first_param,
    _material_route_value,
    _optional_int,
    _native_editor_transform_payload,
    _native_editor_transform_vec3_payload,
    _native_editor_stroke_phase,
    _native_editor_stroke_id,
    _mesh_edit_selection_signature,
    _native_editor_selection_payload_for_apply,
    _add_native_editor_binary_vertex_selection_payload,
    _native_editor_selection_request_for_apply, _native_editor_selection_signature_for_apply,
    _freeze_native_selection_value,
    _can_reuse_native_live_stroke_selection,
    _can_reuse_native_stroke_begin_selection,
    _can_reuse_native_stroke_begin_mesh_selection,
    _native_editor_selection_signature_matches_resident,
    _native_editor_vec3,
    _native_editor_positive_float,
    _native_editor_mirror_pairs_by_submesh,
    _native_editor_metrics,
    _native_editor_stroke_metrics,
    _prefixed_metrics,
    _coerce_metrics,
    _native_editor_json_value,
    _can_defer_native_live_history,
    _stop_event_from_params,
)
from cdmw.services.mesh_service_history import (
    MeshHistoryServiceMixin,
    _history_metrics,
    _history_snapshot_retained_bytes,
    _history_stack_retained_bytes,
    _history_value_retained_bytes,
    _native_submesh_snapshot_payload_bytes,
)
from cdmw.services.mesh_service_morph import MeshMorphServiceMixin
from cdmw.services.mesh_service_object_transform import (
    MeshObjectTransformServiceMixin,
    mesh_source_bounds_pivot,
)
from cdmw.services.mesh_service_kernel import (
    _TANGENT_INVALIDATING_ACTIONS,
    _append_unique_diagnostics,
    _apply_native_editor_dirty_counts,
    _brush_selection_for_command,
    _command_may_change_topology,
    _diagnostic_count,
    _invalidate_tangents_after_edit,
    _mesh_count_hint,
    _mesh_structure_signature,
    _mode,
    _native_blocked_fallback_diagnostics,
    _native_editor_mesh_storage_signature,
    _operation_names_for_command,
    _operation_target_indices,
    _record_session_edit_operations,
    _records_history,
    _required_mode,
    _submesh_channel_changed,
    _truthy,
    _vector_has_non_identity_scale,
    _vector_has_value,
    _with_recomputed_normals,
)
_DEFAULT_MESH_HISTORY_BYTES = 256 * 1024 * 1024
from cdmw.services.mesh_service_native_session import (
    _LEGACY_DISPLAY_CLEANUP_ACTIONS,
    _NATIVE_EDITOR_SESSION_ACTIONS,
    _abandon_lost_native_editor_session,
    _allow_python_history_restore_fallback,
    _allow_python_history_snapshot_fallback,
    _allow_python_pose_preview_fallback,
    _allow_python_service_clone_fallback,
    _allow_python_skin_weight_fallback,
    _apply_native_editor_session_geometry_action,
    _apply_native_editor_session_selection_operation,
    _close_native_editor_session,
    _coerce_vertex_position_delta,
    _current_vertex_position_deltas,
    _delta_positions_by_vertex,
    _native_live_history_snapshot,
    _refresh_native_editor_session_if_mesh_changed,
    _restore_vertex_position_deltas,
    _sync_native_editor_session_to_working_mesh,
)
from cdmw.services.mesh_service_native_clone import (
    _clone_history_snapshot_for_python_fallback,
    _clone_mesh_for_service_native_snapshot,
    _clone_mesh_for_service_python_fallback,
    _clone_mesh_pair_for_service_python_fallback,
    _clone_mesh_pair_for_session_open,
    _copy_mesh_validation_metadata,
    _service_session_native_clone_supported,
)


def _active_geometry_layer_indices(session: _MeshEditSession) -> tuple[int, ...]:
    for layer in session.geometry_layers:
        if layer.layer_id == session.active_geometry_layer_id:
            return layer.submesh_indices
    return session.geometry_layers[0].submesh_indices if session.geometry_layers else ()


def _visible_geometry_layer_indices(session: _MeshEditSession) -> tuple[int, ...]:
    visible: set[int] = set()
    for layer in session.geometry_layers:
        if layer.base or layer.visible:
            visible.update(layer.submesh_indices)
    return tuple(sorted(visible))


def _geometry_layer_state_payload(session: _MeshEditSession) -> dict[str, object]:
    return {
        "revision": session.geometry_layer_revision,
        "active_layer_id": session.active_geometry_layer_id,
        "clipboard_ready": session.native_clipboard_ready,
        "autosave_pending": (
            session.mesh_layer_project_path is not None
            and (session.revision, session.geometry_layer_revision) != session.mesh_layer_autosave_saved_key
        ),
        "autosave_error": session.mesh_layer_autosave_error,
        "workspace_mode": session.mesh_layer_workspace_mode,
        "loaded_generation": session.mesh_layer_loaded_generation,
        "layers": [
            {
                "layer_id": layer.layer_id,
                "name": layer.name,
                "submesh_indices": layer.submesh_indices,
                "visible": layer.visible,
                "base": layer.base,
                "active": layer.layer_id == session.active_geometry_layer_id,
            }
            for layer in session.geometry_layers
        ],
    }


def _geometry_layers_from_project_payload(
    payload: Mapping[str, object],
    submesh_count: int,
) -> tuple[_MeshGeometryLayer, ...]:
    raw_layers = payload.get("layers")
    if not isinstance(raw_layers, list):
        raise ValueError("Mesh layer project omitted its layer list")
    layers: list[_MeshGeometryLayer] = []
    seen_ids: set[str] = set()
    assigned_indices: set[int] = set()
    for raw_layer in raw_layers:
        if not isinstance(raw_layer, Mapping):
            raise ValueError("Mesh layer project contains a malformed layer")
        layer_id = str(raw_layer.get("layer_id") or "").strip()
        name = str(raw_layer.get("name") or "").strip()
        raw_indices = raw_layer.get("submesh_indices")
        if not layer_id or layer_id in seen_ids or not name or not isinstance(raw_indices, (list, tuple)):
            raise ValueError("Mesh layer project contains invalid layer identity metadata")
        try:
            indices = tuple(sorted({int(value) for value in raw_indices}))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Mesh layer project contains invalid submesh indices") from exc
        if any(index < 0 or index >= submesh_count for index in indices):
            raise ValueError("Mesh layer project layer indices exceed the saved mesh")
        if assigned_indices.intersection(indices):
            raise ValueError("Mesh layer project assigns one submesh to multiple layers")
        base = bool(raw_layer.get("base", False))
        visible = True if base else bool(raw_layer.get("visible", True))
        layers.append(
            _MeshGeometryLayer(
                layer_id=layer_id,
                name=name,
                submesh_indices=indices,
                visible=visible,
                base=base,
            )
        )
        seen_ids.add(layer_id)
        assigned_indices.update(indices)
    if not layers or layers[0].layer_id != "base" or not layers[0].base:
        raise ValueError("Mesh layer project must begin with Base mesh")
    if assigned_indices != set(range(submesh_count)):
        raise ValueError("Mesh layer project does not account for every saved submesh")
    return tuple(layers)


def _project_non_negative_int(value: object, *, field: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Mesh layer project contains an invalid {field}") from exc
    if parsed < 0:
        raise ValueError(f"Mesh layer project contains an invalid {field}")
    return parsed


def _selection_params_for_active_geometry_layer(
    session: _MeshEditSession,
    params: Mapping[str, object],
) -> dict[str, object]:
    result = dict(params)
    allowed = _active_geometry_layer_indices(session)
    result["allowed_submesh_indices"] = allowed
    raw_screen = result.get("_native_screen_selection_payload")
    if not isinstance(raw_screen, Mapping):
        return result
    screen = dict(raw_screen)
    for key in ("screen_brush", "screen_region"):
        value = screen.get(key)
        if isinstance(value, Mapping):
            screen[key] = {**dict(value), "source_submesh_indices": allowed}
    for key in ("screen_brushes", "screen_regions"):
        value = screen.get(key)
        if isinstance(value, (tuple, list)):
            screen[key] = [
                {**dict(item), "source_submesh_indices": allowed}
                for item in value
                if isinstance(item, Mapping)
            ]
    result["_native_screen_selection_payload"] = screen
    return result


def _with_mesh_session_export_lock(method):
    @wraps(method)
    def locked(self, session_id: str, *args: object, **kwargs: object):
        session = self._session(session_id)
        with session.export_lock:
            return method(self, session_id, *args, **kwargs)

    return locked



def _attach_mesh_asset_status(mesh: ParsedMesh, original_data: bytes, *, run_roundtrip: bool) -> None:
    source_data = bytes(original_data or b"")
    setattr(mesh, "_cdmw_original_data", source_data)
    setattr(mesh, "_cdmw_mesh_asset_source_hash", hashlib.sha256(source_data).hexdigest() if source_data else "")
    asset = None
    try:
        asset = mesh_asset_from_parsed_mesh(mesh, source_data, source_path=str(mesh.path or ""))
    except Exception:
        asset = None
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "failed")
        setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 0)
        setattr(mesh, "_cdmw_mesh_asset_lods", ())
        setattr(mesh, "_cdmw_mesh_asset_material_slots", ())
        setattr(mesh, "_cdmw_mesh_asset_unknown_sections", ())
    else:
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", asset.parse_confidence)
        setattr(mesh, "_cdmw_mesh_asset_source_hash", asset.original_file_hash)
        setattr(mesh, "_cdmw_mesh_asset_lods", tuple(asset.lods))
        setattr(mesh, "_cdmw_mesh_asset_material_slots", tuple(asset.material_slots))
        setattr(mesh, "_cdmw_mesh_asset_unknown_sections", tuple(asset.unknown_sections))
        skeleton_info = asset.skeleton_info if isinstance(asset.skeleton_info, Mapping) else {}
        bone_count = _positive_int(skeleton_info.get("skeleton_bone_count")) or _positive_int(
            skeleton_info.get("inferred_bone_count")
        )
        setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", bone_count)
    if not run_roundtrip:
        return
    try:
        # The asset view above describes exactly the mesh the parser lambda
        # returns, so the roundtrip reuses it instead of walking every vertex
        # a second time.
        result = roundtrip_mesh_bytes(
            source_data,
            str(mesh.path or ""),
            parser=lambda _data, _filename: mesh,
            asset=asset,
        )
        setattr(mesh, "_cdmw_no_op_roundtrip_report", dict(result.report))
    except Exception as exc:
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "FAIL", "parse": "FAIL", "rebuild": "NOT_RUN", "error": str(exc)},
        )


def _session_roundtrip_status(session: _MeshEditSession) -> str:
    report = session.no_op_roundtrip_report
    if not isinstance(report, Mapping):
        return "not_run" if session.original_data else ""
    return str(report.get("result") or "FAIL")


def _session_roundtrip_byte_identical(session: _MeshEditSession) -> bool | None:
    report = session.no_op_roundtrip_report
    if not isinstance(report, Mapping) or "byte_identical" not in report:
        return None
    return bool(report.get("byte_identical"))


def _session_roundtrip_unexpected_differences(session: _MeshEditSession) -> int:
    report = session.no_op_roundtrip_report
    if not isinstance(report, Mapping):
        return 0
    try:
        return max(0, int(report.get("unexpected_differences") or 0))
    except (TypeError, ValueError):
        return 0


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if number > 0 else 0


def _session_validation_skeleton_bone_count(session: _MeshEditSession) -> int | None:
    if session.skeleton is not None:
        return len(tuple(getattr(session.skeleton, "bones", ()) or ()))
    return session.mesh_asset_inferred_bone_count or None


def _developer_override_blocker_codes(
    report: MeshExportValidationReport,
    *,
    enabled: bool,
    output_path: str,
) -> tuple[str, ...]:
    if not enabled or not str(output_path or "").strip():
        return ()
    codes = tuple(str(issue.code or "").strip() for issue in report.blockers)
    if codes and all(code in DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS for code in codes):
        return codes
    return ()


def _developer_override_report_entries(reason: str, codes: Sequence[str]) -> tuple[str, ...]:
    if not codes:
        return ()
    text = str(reason or "").strip() or "Developer-mode unsafe rebuild override."
    return (
        "developer_override=true",
        f"override_reason={text}",
        f"unsafe_conditions={', '.join(codes)}",
    )


def _load_mesh_bytes(data: bytes, source_path: Path | str, *, run_roundtrip: bool) -> ParsedMesh:
    source_name = str(source_path)
    if not is_mesh_file(source_name):
        raise ValueError(f"Unsupported mesh file type: {Path(source_name).suffix or source_name}")
    source_data = bytes(data)
    mesh = parse_mesh(source_data, source_name)
    if not isinstance(mesh, ParsedMesh):
        raise TypeError("mesh parser did not return ParsedMesh")
    if not str(mesh.path or "").strip():
        mesh.path = source_name
    refresh_mesh_totals(mesh)
    _attach_mesh_asset_status(mesh, source_data, run_roundtrip=run_roundtrip)
    return mesh


def _load_mesh_file(path: Path | str, *, run_roundtrip: bool) -> ParsedMesh:
    source_path = Path(path).expanduser()
    if not is_mesh_file(str(source_path)):
        raise ValueError(f"Unsupported mesh file type: {source_path.suffix or source_path}")
    return _load_mesh_bytes(source_path.read_bytes(), source_path, run_roundtrip=run_roundtrip)


@dataclass(slots=True)
class _MeshServiceSessionLayerCore(
    MeshRiggingServiceMixin,
    MeshResidentMaterialServiceMixin,
    MeshWorkingReplacementServiceMixin,
    MeshRebuildServiceMixin,
    MeshHistoryServiceMixin,
    MeshMorphServiceMixin,
    MeshObjectTransformServiceMixin,
):
    settings: object | None = None
    max_history: int = 64
    max_history_bytes: int = _DEFAULT_MESH_HISTORY_BYTES
    _sessions: dict[str, _MeshEditSession] = field(default_factory=dict)
    _morph_sessions: dict[str, object] = field(default_factory=dict)

    def load_mesh_bytes(self, data: bytes, source_path: Path | str, *, run_roundtrip: bool = False) -> ParsedMesh:
        return _load_mesh_bytes(data, source_path, run_roundtrip=run_roundtrip)

    def load_mesh_file(self, path: Path | str, *, run_roundtrip: bool = False) -> ParsedMesh:
        return _load_mesh_file(path, run_roundtrip=run_roundtrip)

    def open_edit_session(
        self,
        mesh: ParsedMesh,
        *,
        session_id: str | None = None,
        mode: str = "object",
    ) -> MeshEditSessionView:
        if not isinstance(mesh, ParsedMesh):
            raise TypeError("mesh must be a ParsedMesh")
        mode = _mode(mode)
        session_key = str(session_id or uuid4())
        original_data = bytes(getattr(mesh, "_cdmw_original_data", b"") or b"")
        discovered_project = discover_mesh_layer_project_context(mesh)
        source_asset_hash = str(
            getattr(mesh, "_cdmw_mesh_asset_source_hash", "")
            or getattr(mesh, "_cdmw_sidecar_source_asset_hash", "")
            or discovered_project.get("source_asset_sha256", "")
            or (hashlib.sha256(original_data).hexdigest() if original_data else "")
        ).strip().lower()
        project_path_text = str(
            getattr(mesh, "_cdmw_mesh_layer_project_path", "")
            or discovered_project.get("project_path", "")
            or ""
        ).strip()
        project_path = Path(project_path_text).expanduser().resolve() if project_path_text else None
        workspace_manifest_text = str(
            getattr(mesh, "_cdmw_modify_original_workspace_manifest_path", "")
            or discovered_project.get("manifest_path", "")
            or ""
        ).strip()
        workspace_manifest_path = (
            Path(workspace_manifest_text).expanduser().resolve() if workspace_manifest_text else None
        )
        working_mesh, base_mesh = _clone_mesh_pair_for_session_open(mesh)
        loaded_layer_project: Mapping[str, object] | None = None
        if project_path is not None and project_path.is_file():
            loaded_layer_project = load_mesh_layer_project(
                working_mesh,
                project_path,
                expected_source_asset_sha256=source_asset_hash,
            )
            if loaded_layer_project is not None:
                base_mesh = _clone_mesh_for_service_native_snapshot(
                    working_mesh,
                    "session.layer_project_base_clone",
                    "Python layer-project base clone fallback blocked while native mesh core is available",
                )
        _copy_mesh_validation_metadata(mesh, working_mesh)
        _copy_mesh_validation_metadata(mesh, base_mesh)
        refresh_mesh_totals(working_mesh)
        session = _MeshEditSession(
            session_id=session_key,
            base_mesh=base_mesh,
            working_mesh=working_mesh,
            original_data=original_data,
            mesh_asset_parse_confidence=str(getattr(mesh, "_cdmw_mesh_asset_parse_confidence", "") or ""),
            mesh_asset_source_hash=source_asset_hash,
            mesh_asset_source_size=(
                _positive_int(getattr(mesh, "_cdmw_sidecar_source_asset_size", 0)) or len(original_data)
            ),
            mesh_asset_inferred_bone_count=_positive_int(getattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 0)),
            no_op_roundtrip_report=getattr(mesh, "_cdmw_no_op_roundtrip_report", None),
            sidecar_warnings=tuple(getattr(mesh, "_cdmw_sidecar_warnings", ()) or ()),
            edit_operations=tuple(getattr(mesh, "_cdmw_edit_operations", ()) or ()),
            requires_edit_operations=bool(getattr(mesh, "_cdmw_requires_edit_operations", False))
            or (
                bool(getattr(mesh, "_cdmw_imported_from_obj", False))
                and bool(getattr(mesh, "_cdmw_obj_sidecar_present", False))
            ),
            base_mesh_is_original_parse=_native_source_parse_eligible(mesh, original_data),
            mode=mode,
            object_transform=MeshObjectTransformState(
                pivot=mesh_source_bounds_pivot(base_mesh),
            ),
            mesh_layer_project_path=project_path,
            mesh_layer_workspace_manifest_path=workspace_manifest_path,
            mesh_layer_workspace_mode=str(
                getattr(mesh, "_cdmw_modify_original_workspace_mode", "")
                or discovered_project.get("workspace_mode", "")
                or ""
            ),
        )
        if loaded_layer_project is not None:
            raw_object_transform = loaded_layer_project.get("object_transform")
            if isinstance(raw_object_transform, Mapping) and raw_object_transform:
                session.object_transform = MeshObjectTransformState(
                    location=tuple(raw_object_transform.get("location", (0.0, 0.0, 0.0))),
                    rotation_degrees=tuple(
                        raw_object_transform.get("rotation_degrees", (0.0, 0.0, 0.0))
                    ),
                    scale=tuple(raw_object_transform.get("scale", (1.0, 1.0, 1.0))),
                    pivot=tuple(
                        raw_object_transform.get("pivot", session.object_transform.pivot)
                    ),
                )
            session.geometry_layers = _geometry_layers_from_project_payload(
                loaded_layer_project,
                len(working_mesh.submeshes),
            )
            session.active_geometry_layer_id = str(
                loaded_layer_project.get("active_layer_id") or "base"
            )
            if not any(
                layer.layer_id == session.active_geometry_layer_id and layer.visible
                for layer in session.geometry_layers
            ):
                session.active_geometry_layer_id = "base"
            session.geometry_layer_copy_counter = _project_non_negative_int(
                loaded_layer_project.get("copy_counter"),
                field="copy counter",
            )
            session.geometry_layer_revision = _project_non_negative_int(
                loaded_layer_project.get("layer_revision"),
                field="layer revision",
            )
            session.mesh_layer_loaded_generation = str(
                loaded_layer_project.get("loaded_generation") or ""
            )
            session.mesh_layer_autosave_saved_key = (session.revision, session.geometry_layer_revision)
        else:
            session.geometry_layers = (
                _MeshGeometryLayer(
                    layer_id="base",
                    name="Base mesh",
                    submesh_indices=tuple(range(len(working_mesh.submeshes))),
                    visible=True,
                    base=True,
                ),
            )
        self._sessions[session_key] = session
        return self.session_view(session_key)

    def geometry_layer_state(self, session_id: str) -> dict[str, object]:
        session = self._session(session_id)
        with session.export_lock:
            return _geometry_layer_state_payload(session)

    def copy_selection(
        self,
        session_id: str,
        *,
        target: str = "vertex",
        selection: MeshEditSelection | None = None,
        stop_event: threading.Event | None = None,
    ) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            normalized_target = str(target or "vertex").strip().lower()
            normalized_target = {"vertices": "vertex", "wires": "edge", "wire": "edge", "edges": "edge", "faces": "face"}.get(
                normalized_target, normalized_target
            )
            if normalized_target not in {"vertex", "edge", "face"}:
                raise ValueError(f"Unsupported Mesh Editor copy target: {target}")
            if not native_mesh_core_available():
                raise RuntimeError("native Mesh Editor clipboard is unavailable")
            _refresh_native_editor_session_if_mesh_changed(session)
            if not session.native_editor_session_ready:
                opened = open_native_mesh_editor_session(
                    session.working_mesh,
                    session.session_id,
                    stop_event=stop_event,
                    timeout_seconds=10.0,
                )
                if opened is None:
                    raise RuntimeError("native Mesh Editor clipboard session failed to open")
                session.native_editor_session_ready = True
                session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
            effective_selection = selection if selection is not None else session.selection
            effective_selection = _prune_selection_to_mesh(session.working_mesh, effective_selection)
            selection_payload = _native_editor_selection_payload(effective_selection)
            selected = select_native_mesh_editor_session(
                session.session_id,
                selection_payload,
                operation="replace",
                stop_event=stop_event,
                timeout_seconds=5.0,
            )
            if selected is None:
                raise RuntimeError("native Mesh Editor clipboard selection sync failed")
            report = copy_native_mesh_editor_session(
                session.session_id,
                target=normalized_target,
                stop_event=stop_event,
                timeout_seconds=5.0,
            )
            if report is None:
                message = str(last_native_mesh_core_job_error() or "").strip()
                if "No complete faces selected to copy" in message:
                    raise RuntimeError("No complete faces selected to copy")
                raise RuntimeError(message or "native Mesh Editor copy failed")
            session.native_editor_selection_signature = _mesh_edit_selection_signature(effective_selection)
            session.native_clipboard_ready = True
            return self._result(session, "copy", metrics=_native_editor_metrics(report))

    def paste_selection(self, session_id: str) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            if not session.native_clipboard_ready:
                raise RuntimeError("Mesh Editor clipboard is empty")
            layers_before = session.geometry_layers
            active_before = session.active_geometry_layer_id
            counter_before = session.geometry_layer_copy_counter
            result = self.apply_command(
                session_id,
                MeshEditCommand(
                    action="paste",
                    selection=session.selection,
                    params={"_geometry_layer_paste_internal": True},
                    mode="edit",
                    label="Paste",
                ),
            )
            if not result.ok:
                return result
            pasted_indices = tuple(sorted(set(result.affected_submesh_indices)))
            if not pasted_indices:
                raise RuntimeError("Mesh Editor paste returned no geometry")
            session.geometry_layer_copy_counter += 1
            layer_id = f"selection-copy-{session.geometry_layer_copy_counter}"
            session.geometry_layers = session.geometry_layers + (
                _MeshGeometryLayer(
                    layer_id=layer_id,
                    name=f"Selection copy {session.geometry_layer_copy_counter}",
                    submesh_indices=pasted_indices,
                ),
            )
            session.active_geometry_layer_id = layer_id
            session.geometry_layer_revision += 1
            if session.undo_stack and session.undo_stack[-1].native_editor_history:
                marker = session.undo_stack[-1]
                marker.geometry_layers = layers_before
                marker.active_geometry_layer_id = active_before
                marker.geometry_layer_copy_counter = counter_before
                marker.retained_bytes = 0
                marker.retained_bytes = _history_snapshot_retained_bytes(marker)
            self._schedule_mesh_layer_autosave(session)
            return result

    def activate_geometry_layer(self, session_id: str, layer_id: str) -> dict[str, object]:
        session = self._session(session_id)
        with session.export_lock:
            requested = str(layer_id or "").strip()
            if not any(layer.layer_id == requested for layer in session.geometry_layers):
                raise KeyError(f"Unknown Mesh Editor layer: {requested}")
            if session.active_geometry_layer_id != requested:
                session.active_geometry_layer_id = requested
                self._clear_geometry_layer_selection_locked(session)
                session.geometry_layer_revision += 1
                self._schedule_mesh_layer_autosave(session)
            return _geometry_layer_state_payload(session)

    def rename_geometry_layer(self, session_id: str, layer_id: str, name: str) -> dict[str, object]:
        session = self._session(session_id)
        with session.export_lock:
            requested = str(layer_id or "").strip()
            normalized_name = str(name or "").strip()
            if not normalized_name:
                raise ValueError("Layer name cannot be empty")
            updated: list[_MeshGeometryLayer] = []
            found = False
            for layer in session.geometry_layers:
                if layer.layer_id != requested:
                    updated.append(layer)
                    continue
                found = True
                if layer.base:
                    raise ValueError("Base mesh cannot be renamed")
                updated.append(replace(layer, name=normalized_name))
            if not found:
                raise KeyError(f"Unknown Mesh Editor layer: {requested}")
            session.geometry_layers = tuple(updated)
            session.geometry_layer_revision += 1
            self._schedule_mesh_layer_autosave(session)
            return _geometry_layer_state_payload(session)

    def set_geometry_layer_visibility(
        self,
        session_id: str,
        layer_id: str,
        visible: bool,
    ) -> dict[str, object]:
        session = self._session(session_id)
        with session.export_lock:
            requested = str(layer_id or "").strip()
            updated: list[_MeshGeometryLayer] = []
            changed = False
            found = False
            for layer in session.geometry_layers:
                if layer.layer_id != requested:
                    updated.append(layer)
                    continue
                found = True
                if layer.base and not visible:
                    raise ValueError("Base mesh is always visible")
                replacement = replace(layer, visible=bool(visible))
                changed = replacement != layer
                updated.append(replacement)
            if not found:
                raise KeyError(f"Unknown Mesh Editor layer: {requested}")
            session.geometry_layers = tuple(updated)
            if changed and not visible and session.active_geometry_layer_id == requested:
                session.active_geometry_layer_id = "base"
                self._clear_geometry_layer_selection_locked(session)
            if changed:
                session.geometry_layer_revision += 1
                self._schedule_mesh_layer_autosave(session)
            return _geometry_layer_state_payload(session)

    def move_geometry_layer(self, session_id: str, layer_id: str, direction: int) -> dict[str, object]:
        session = self._session(session_id)
        with session.export_lock:
            requested = str(layer_id or "").strip()
            layers = list(session.geometry_layers)
            index = next((offset for offset, layer in enumerate(layers) if layer.layer_id == requested), -1)
            if index < 0:
                raise KeyError(f"Unknown Mesh Editor layer: {requested}")
            if layers[index].base:
                raise ValueError("Base mesh cannot be reordered")
            destination = index + (-1 if int(direction) < 0 else 1)
            destination = max(1, min(len(layers) - 1, destination))
            if destination != index:
                layers.insert(destination, layers.pop(index))
                session.geometry_layers = tuple(layers)
                session.geometry_layer_revision += 1
                self._schedule_mesh_layer_autosave(session)
            return _geometry_layer_state_payload(session)

    def delete_geometry_layer(self, session_id: str, layer_id: str) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            requested = str(layer_id or "").strip()
            layer = next((item for item in session.geometry_layers if item.layer_id == requested), None)
            if layer is None:
                raise KeyError(f"Unknown Mesh Editor layer: {requested}")
            if layer.base:
                raise ValueError("Base mesh cannot be deleted")
            layers_before = session.geometry_layers
            active_before = session.active_geometry_layer_id
            counter_before = session.geometry_layer_copy_counter
            selection = MeshEditSelection.from_maps(source_indices=layer.submesh_indices)
            result = self.apply_command(
                session_id,
                MeshEditCommand(
                    action="delete",
                    selection=selection,
                    params={"delete_parts": True, "geometry_layer_delete": True},
                    mode="edit",
                    label="Delete Layer",
                ),
            )
            if not result.ok:
                return result
            deleted_indices = tuple(sorted(set(layer.submesh_indices)))
            deleted_set = set(deleted_indices)

            def remap_index(index: int) -> int | None:
                if index in deleted_set:
                    return None
                return index - sum(1 for deleted in deleted_indices if deleted < index)

            remapped_layers: list[_MeshGeometryLayer] = []
            for item in session.geometry_layers:
                if item.layer_id == requested:
                    continue
                remapped = tuple(
                    mapped
                    for source_index in item.submesh_indices
                    if (mapped := remap_index(source_index)) is not None
                )
                remapped_layers.append(replace(item, submesh_indices=remapped))
            session.geometry_layers = tuple(remapped_layers)
            session.active_geometry_layer_id = "base"
            session.geometry_layer_revision += 1
            if session.undo_stack and session.undo_stack[-1].native_editor_history:
                marker = session.undo_stack[-1]
                marker.geometry_layers = layers_before
                marker.active_geometry_layer_id = active_before
                marker.geometry_layer_copy_counter = counter_before
                marker.retained_bytes = 0
                marker.retained_bytes = _history_snapshot_retained_bytes(marker)
            self._schedule_mesh_layer_autosave(session)
            return result

    def _clear_geometry_layer_selection_locked(self, session: _MeshEditSession) -> None:
        session.selection = MeshEditSelection()
        session.selection_stroke_id = ""
        session.selection_stroke_sequence = -1
        session.selection_stroke_start = None
        session.native_editor_selection_signature = ()
        if not session.native_editor_session_ready:
            return
        report = select_native_mesh_editor_session(
            session.session_id,
            _native_editor_selection_payload(session.selection),
            operation="replace",
            timeout_seconds=5.0,
        )
        if report is None:
            session.native_editor_session_ready = False

    def _reconcile_geometry_layers_after_topology(
        self,
        session: _MeshEditSession,
        *,
        action: str,
        command: MeshEditCommand,
        selection: MeshEditSelection,
        before_count: int,
        after_count: int,
    ) -> bool:
        if action == "paste" or _truthy(command.params.get("geometry_layer_delete")):
            return False
        layers = list(session.geometry_layers)
        if not layers or before_count == after_count:
            return False
        if after_count < before_count:
            if action != "delete" or not _truthy(command.params.get("delete_parts")):
                return False
            removed = tuple(sorted({int(index) for index in selection.source_indices if 0 <= int(index) < before_count}))
            if before_count - len(removed) != after_count:
                return False
            removed_set = set(removed)

            def remap_index(index: int) -> int | None:
                if index in removed_set:
                    return None
                return index - sum(1 for removed_index in removed if removed_index < index)

            layers = [
                replace(
                    layer,
                    submesh_indices=tuple(
                        mapped
                        for index in layer.submesh_indices
                        if (mapped := remap_index(index)) is not None
                    ),
                )
                for layer in layers
            ]
        assigned = {index for layer in layers for index in layer.submesh_indices if 0 <= index < after_count}
        missing = tuple(index for index in range(after_count) if index not in assigned)
        if missing:
            active_index = next(
                (index for index, layer in enumerate(layers) if layer.layer_id == session.active_geometry_layer_id),
                0,
            )
            active = layers[active_index]
            layers[active_index] = replace(
                active,
                submesh_indices=tuple(sorted(set(active.submesh_indices).union(missing))),
            )
        updated = tuple(layers)
        if updated == session.geometry_layers:
            return False
        session.geometry_layers = updated
        session.geometry_layer_revision += 1
        return True

    def _schedule_mesh_layer_autosave(self, session: _MeshEditSession) -> None:
        if session.mesh_layer_project_path is None or len(session.mesh_asset_source_hash) != 64:
            return
        session.mesh_layer_autosave_requested_key = (session.revision, session.geometry_layer_revision)
        session.mesh_layer_autosave_error = ""
        timer = session.mesh_layer_autosave_timer
        if timer is not None:
            timer.cancel()
        if session.mesh_layer_autosave_stop_event is not None:
            session.mesh_layer_autosave_stop_event.set()
        timer = threading.Timer(0.75, self._start_mesh_layer_autosave, args=(session.session_id,))
        timer.daemon = True
        session.mesh_layer_autosave_timer = timer
        timer.start()

    def _start_mesh_layer_autosave(self, session_id: str) -> None:
        session = self._sessions.get(str(session_id))
        if session is None or session.closed:
            return
        running = session.mesh_layer_autosave_thread
        if running is not None and running.is_alive():
            if session.mesh_layer_autosave_stop_event is not None:
                session.mesh_layer_autosave_stop_event.set()
            retry = threading.Timer(0.05, self._start_mesh_layer_autosave, args=(session.session_id,))
            retry.daemon = True
            session.mesh_layer_autosave_timer = retry
            retry.start()
            return
        expected_key = session.mesh_layer_autosave_requested_key
        stop_event = threading.Event()
        session.mesh_layer_autosave_stop_event = stop_event
        worker = threading.Thread(
            target=self._run_mesh_layer_autosave,
            args=(session.session_id, expected_key, stop_event),
            name=f"mesh-layer-autosave-{session.session_id}",
            daemon=True,
        )
        session.mesh_layer_autosave_thread = worker
        worker.start()

    def _run_mesh_layer_autosave(
        self,
        session_id: str,
        expected_key: tuple[int, int],
        stop_event: threading.Event,
    ) -> None:
        session = self._sessions.get(str(session_id))
        if session is None:
            return
        try:
            with session.export_lock:
                if session.closed or expected_key != session.mesh_layer_autosave_requested_key:
                    return
                self._save_mesh_layer_project_locked(session, stop_event=stop_event)
        except RunCancelled:
            return
        except Exception as exc:
            with session.export_lock:
                if expected_key == session.mesh_layer_autosave_requested_key:
                    session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"

    def _save_mesh_layer_project_locked(
        self,
        session: _MeshEditSession,
        *,
        stop_event: threading.Event | None = None,
    ) -> None:
        if session.mesh_layer_project_path is None:
            return
        layer_payload = _geometry_layer_state_payload(session)
        promote = len(session.geometry_layers) > 1
        descriptor = save_mesh_layer_project(
            session_id=session.session_id,
            mesh=session.working_mesh,
            project_path=session.mesh_layer_project_path,
            source_asset_sha256=session.mesh_asset_source_hash,
            layers=layer_payload["layers"],
            active_layer_id=session.active_geometry_layer_id,
            copy_counter=session.geometry_layer_copy_counter,
            mesh_revision=session.revision,
            layer_revision=session.geometry_layer_revision,
            object_transform={
                "location": session.object_transform.location,
                "rotation_degrees": session.object_transform.rotation_degrees,
                "scale": session.object_transform.scale,
                "pivot": session.object_transform.pivot,
            },
            workspace_manifest_path=session.mesh_layer_workspace_manifest_path,
            promote_persistent_draft=promote,
            stop_event=stop_event,
        )
        session.mesh_layer_loaded_generation = str(descriptor.get("current_generation") or "")
        session.mesh_layer_autosave_saved_key = (session.revision, session.geometry_layer_revision)
        session.mesh_layer_autosave_error = ""
        if promote and session.mesh_layer_workspace_mode == "internal_app_session":
            session.mesh_layer_workspace_mode = "persistent_app_draft"

    def retry_mesh_layer_autosave(self, session_id: str) -> None:
        session = self._session(session_id)
        with session.export_lock:
            session.mesh_layer_autosave_requested_key = (session.revision, session.geometry_layer_revision)
            self._save_mesh_layer_project_locked(session)


@dataclass(slots=True)
class MeshService(_MeshServiceSessionLayerCore):
    def close_edit_session(self, session_id: str, *, force_without_saving: bool = False) -> None:
        session_key = str(session_id)
        session = self._sessions.get(session_key)
        if session is not None:
            with session.export_lock:
                if self._sessions.get(session_key) is not session:
                    return
                timer = session.mesh_layer_autosave_timer
                if timer is not None:
                    timer.cancel()
                if session.mesh_layer_autosave_stop_event is not None:
                    session.mesh_layer_autosave_stop_event.set()
                current_key = (session.revision, session.geometry_layer_revision)
                if (
                    not force_without_saving
                    and session.mesh_layer_project_path is not None
                    and current_key != session.mesh_layer_autosave_saved_key
                ):
                    try:
                        self._save_mesh_layer_project_locked(session)
                    except Exception as exc:
                        session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"
                        raise RuntimeError(
                            "Mesh Editor has unsaved geometry layers; retry saving or explicitly close without saving"
                        ) from exc
                self._sessions.pop(session_key, None)
                self._morph_sessions.pop(session_key, None)
                session.closed = True
            _close_native_editor_session(session)
            _clear_history_stack(session.undo_stack)
            _clear_history_stack(session.redo_stack)
            self.dispose_export_resources(session)

    def session_view(self, session_id: str) -> MeshEditSessionView:
        session = self._session(session_id)
        with session.export_lock:
            return self._session_view_locked(session)

    def _session_view_locked(
        self,
        session: _MeshEditSession,
        *,
        selection_is_authoritative: bool = False,
    ) -> MeshEditSessionView:
        if session.native_editor_mesh_dirty:
            if not session.native_editor_mesh_dirty_counts:
                raise RuntimeError("native mesh editor session view requires native submesh counts; Python mesh state is stale")
            _apply_native_editor_dirty_counts(session)
            submesh_count = len(session.native_editor_mesh_dirty_counts)
        else:
            refresh_mesh_totals(session.working_mesh)
            if not selection_is_authoritative:
                session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
            submesh_count = len(session.working_mesh.submeshes)
        return MeshEditSessionView(
            session_id=session.session_id,
            mode=session.mode,
            revision=session.revision,
            selection=session.selection,
            submesh_count=submesh_count,
            vertex_count=int(session.working_mesh.total_vertices or 0),
            face_count=int(session.working_mesh.total_faces or 0),
            undo_count=len(session.undo_stack),
            redo_count=len(session.redo_stack),
            history_entries=_history_entries(session),
            history_cursor=len(session.undo_stack),
            object_transform=session.object_transform,
        )

    def native_editor_mesh_dirty(self, session_id: str) -> bool:
        return bool(self._session(session_id).native_editor_mesh_dirty)

    def history_usage(self, session_id: str) -> dict[str, int]:
        """Return retained undo/redo evidence without exporting the resident mesh."""
        session = self._session(session_id)
        python_undo_bytes = _history_stack_retained_bytes(session.undo_stack)
        python_redo_bytes = _history_stack_retained_bytes(session.redo_stack)
        return {
            "undo_count": len(session.undo_stack),
            "redo_count": len(session.redo_stack),
            "python_retained_bytes": python_undo_bytes + python_redo_bytes,
            "native_undo_count": session.native_history_undo_count,
            "native_redo_count": session.native_history_redo_count,
            "native_retained_bytes": session.native_history_retained_bytes,
            "retained_bytes": python_undo_bytes + python_redo_bytes + session.native_history_retained_bytes,
            "max_operations": max(1, int(self.max_history or 1)),
            "max_bytes": max(0, int(self.max_history_bytes or 0)),
        }

    def working_mesh(self, session_id: str, *, clone: bool = False) -> ParsedMesh:
        session = self._session(session_id)
        with session.export_lock:
            return self._working_mesh_locked(session, clone=clone)

    def _working_mesh_locked(self, session: _MeshEditSession, *, clone: bool) -> ParsedMesh:
        if session.native_editor_mesh_dirty and not _sync_native_editor_session_to_working_mesh(session):
            raise RuntimeError("native mesh editor session export failed; Python mesh state is stale")
        mesh = session.working_mesh
        if not clone:
            return mesh
        return _clone_mesh_for_service_native_snapshot(
            mesh,
            "session.working_mesh_clone",
            "Python working mesh clone fallback blocked while native mesh core is available",
        )

    def pose_preview_mesh(self, session_id: str) -> ParsedMesh:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor pose preview unavailable; Python mesh state is stale")
        pose_rotations = _effective_pose_rotations(session)
        mesh = _clone_mesh_for_service_native_snapshot(
            session.working_mesh,
            "preview.pose_clone",
            "Python pose preview mesh clone fallback blocked while native mesh core is available",
        )
        if not (session.pose_preview_enabled and session.skeleton is not None and pose_rotations):
            return mesh
        native_deformed = apply_native_mesh_pose_preview(session.working_mesh, session.skeleton, pose_rotations)
        if native_deformed is None:
            if not _allow_python_pose_preview_fallback(session.working_mesh, "preview.pose_deform"):
                raise RuntimeError("native mesh editor pose preview unavailable; Python pose preview fallback is disabled")
            deformed = mesh_pose_deformed_vertices(mesh, session.skeleton, pose_rotations)
        else:
            deformed = native_deformed
        for submesh_index, vertices in deformed.items():
            if 0 <= submesh_index < len(mesh.submeshes):
                mesh.submeshes[submesh_index].vertices = list(vertices)
        if deformed:
            native_normals = apply_native_mesh_recalculate_normals(mesh, deformed.keys())
            if native_normals is None:
                if not _allow_python_pose_preview_fallback(mesh, "preview.pose_normals"):
                    raise RuntimeError("native mesh editor pose preview normals unavailable; Python pose preview fallback is disabled")
                recompute_mesh_normals(mesh)
            refresh_mesh_totals(mesh)
        return mesh

    def pose_preview_native_context(
        self,
        session_id: str,
    ) -> tuple[ParsedMesh, object, Mapping[int, tuple[float, float, float]]] | None:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor pose preview unavailable; Python mesh state is stale")
        pose_rotations = _effective_pose_rotations(session)
        if not (session.pose_preview_enabled and session.skeleton is not None and pose_rotations):
            return None
        return session.working_mesh, session.skeleton, pose_rotations

    def base_mesh(self, session_id: str, *, clone: bool = False) -> ParsedMesh:
        mesh = self._session(session_id).base_mesh
        if not clone:
            return mesh
        return _clone_mesh_for_service_native_snapshot(
            mesh,
            "session.base_mesh_clone",
            "Python base mesh clone fallback blocked while native mesh core is available",
        )

    def workspace_summary(self, session_id: str) -> MeshWorkspaceSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            native_summary = _mesh_workspace_summary_from_native(
                summarize_native_mesh_editor_session(session.session_id),
                mesh_format=session.working_mesh.format,
            )
            if native_summary is None:
                raise RuntimeError("native mesh editor workspace summary failed; Python mesh state is stale")
            return native_summary
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return summarize_mesh_workspace(session.working_mesh, session.selection)

    def compare_summary(self, session_id: str) -> MeshCompareSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor compare summary unavailable; Python mesh state is stale")
        return compare_meshes(session.base_mesh, session.working_mesh)

    def uv_summary(self, session_id: str) -> MeshUvSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor UV summary unavailable; Python mesh state is stale")
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        native_summary = summarize_native_mesh_uvs(session.working_mesh, session.selection)
        parsed_native_summary = _mesh_uv_summary_from_native(native_summary)
        if parsed_native_summary is not None:
            return parsed_native_summary
        return summarize_mesh_uvs(session.working_mesh, session.selection)

    @_with_mesh_session_export_lock
    def select_uv_region(
        self,
        session_id: str,
        uv_min: Sequence[object],
        uv_max: Sequence[object],
        *,
        operation: str = "replace",
    ) -> MeshEditResult:
        session = self._session(session_id)
        fallback_event_start = len(native_mesh_core_fallback_events())
        native_vertices = select_native_mesh_uv_vertices(
            session.working_mesh,
            mode="region",
            uv_min=_vec2(uv_min),
            uv_max=_vec2(uv_max),
        )
        if native_vertices is None:
            _record_blocked_python_selection_fallback(
                session.working_mesh,
                "uv.region",
                "Native UV region selection is unavailable; Python selection fallback is blocked",
            )
            return self._result(
                session,
                "select",
                status="error",
                diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start),
            )
        incoming = MeshEditSelection.from_maps(vertices_by_submesh=native_vertices)
        return self._select_native_uv_vertices(
            session,
            incoming,
            operation,
            fallback_event_start,
            label="Select UV Region",
        )

    @_with_mesh_session_export_lock
    def select_uv_lasso(
        self,
        session_id: str,
        points: Iterable[Sequence[object]],
        *,
        operation: str = "replace",
    ) -> MeshEditResult:
        session = self._session(session_id)
        polygon = tuple(_vec2(point) for point in points)
        fallback_event_start = len(native_mesh_core_fallback_events())
        native_vertices = select_native_mesh_uv_vertices(
            session.working_mesh,
            mode="lasso",
            points=polygon,
        )
        if native_vertices is None:
            _record_blocked_python_selection_fallback(
                session.working_mesh,
                "uv.lasso",
                "Native UV lasso selection is unavailable; Python selection fallback is blocked",
            )
            return self._result(
                session,
                "select",
                status="error",
                diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start),
            )
        incoming = MeshEditSelection.from_maps(vertices_by_submesh=native_vertices)
        return self._select_native_uv_vertices(
            session,
            incoming,
            operation,
            fallback_event_start,
            label="Select UV Lasso",
        )

    def _select_native_uv_vertices(
        self,
        session: _MeshEditSession,
        selection: MeshEditSelection,
        operation: object,
        fallback_event_start: int,
        *,
        label: str,
    ) -> MeshEditResult:
        previous_selection = session.selection
        selected, native_selection_groups, select_diagnostics, selection_metrics = _apply_native_editor_session_selection_operation(
            session,
            selection,
            operation,
        )
        if selected is None:
            return self._result(
                session,
                "select",
                status="error",
                diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + select_diagnostics,
                metrics=selection_metrics,
            )
        self._record_selection_history(
            session,
            previous_selection,
            selected,
            label=label,
        )
        session.selection = selected
        return self._result(
            session,
            "select",
            diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + select_diagnostics,
            native_selection_groups=native_selection_groups,
            metrics=selection_metrics,
        )



    def apply_command(self, session_id: str, command: MeshEditCommand | str) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            if session.closed:
                raise KeyError(f"Unknown mesh edit session: {session_id}")
            return self._apply_command_locked(session, command)

    def _apply_command_locked(
        self,
        session: _MeshEditSession,
        command: MeshEditCommand | str,
    ) -> MeshEditResult:
        edit_command = _coerce_command(command)
        action = str(edit_command.action or "").strip().lower()
        if action not in (*MESH_EDIT_ACTIONS, *MESH_MORPH_ACTIONS):
            raise ValueError(f"Unsupported mesh edit action: {edit_command.action!r}")
        if action == "copy":
            return self.copy_selection(
                session.session_id,
                target=str(edit_command.params.get("target_mode", "vertex") or "vertex"),
                selection=_command_selection(edit_command),
                stop_event=_stop_event_from_params(edit_command.params),
            )
        if action == "paste" and not _truthy(edit_command.params.get("_geometry_layer_paste_internal")):
            return self.paste_selection(session.session_id)
        if action == "layer_delete":
            return self.delete_geometry_layer(
                session.session_id,
                str(edit_command.params.get("layer_id", "") or ""),
            )
        if action in MESH_MORPH_ACTIONS:
            return self._apply_morph_edit_command_locked(session, edit_command)
        if action == "set_mode":
            session.mode = _mode(edit_command.mode or edit_command.params.get("mode", session.mode))
            return self._result(session, action)
        if action in _LEGACY_DISPLAY_CLEANUP_ACTIONS and not _truthy(
            edit_command.params.get("allow_legacy_display_cleanup")
        ):
            raise RuntimeError(
                f"{action} is legacy display-shape cleanup; pass allow_legacy_display_cleanup=True "
                "from an explicit legacy/archive path"
            )
        require_native = action in _NATIVE_EDITOR_SESSION_ACTIONS
        if session.native_editor_mesh_dirty and not require_native:
            raise RuntimeError(f"{action} cannot run while native mesh state is dirty; export/read the native mesh first")
        selection = _command_selection(edit_command)
        if action == "select":
            return self._apply_selection_command(session, edit_command, selection)
        if selection is None:
            if require_native:
                selection = session.selection
            else:
                session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
                selection = session.selection
        if action == "brush" and not (
            selection.source_indices or selection.vertex_map() or selection.edge_map() or selection.face_map()
        ):
            selection = _brush_selection_for_command(session.working_mesh, edit_command) or selection
        command_mode = _mode(edit_command.mode) if edit_command.mode is not None else session.mode
        required_mode = _required_mode(action)
        if required_mode and command_mode != required_mode:
            if edit_command.mode is not None:
                session.mode = command_mode
            return self._result(
                session,
                action,
                status="noop",
                diagnostics=(f"Mesh edit action requires {required_mode} mode: {action}.",),
            )
        if action == "copy_normals" and "source_mesh" not in edit_command.params:
            edit_command = replace(edit_command, params={**dict(edit_command.params or {}), "source_mesh": session.base_mesh})
        return self._apply_geometry_command(session, edit_command, action, selection, require_native, command_mode)

    def _apply_selection_command(
        self,
        session: _MeshEditSession,
        command: MeshEditCommand,
        selection: MeshEditSelection | None,
    ) -> MeshEditResult:
        params = _selection_params_for_active_geometry_layer(session, command.params or {})
        metrics: dict[str, float] = {}
        operation = params.get("operation", params.get("selection_operation", "replace"))
        stop_event = _stop_event_from_params(params)
        fallback_event_start = len(native_mesh_core_fallback_events())
        stroke_id = str(params.get("selection_stroke_id", params.get("stroke_id", "")) or "").strip()
        stroke_phase = str(params.get("selection_stroke_phase", params.get("stroke_phase", "")) or "").strip().lower()
        try:
            stroke_sequence = int(params.get("selection_stroke_sequence", params.get("stroke_sequence", -1)))
        except (TypeError, ValueError, OverflowError):
            stroke_sequence = -1
        if stroke_phase:
            if stroke_phase not in {"begin", "update", "end", "cancel"} or not stroke_id or stroke_sequence < 0:
                return self._result(
                    session,
                    "select",
                    status="error",
                    diagnostics=("Selection stroke requires an id, non-negative sequence, and valid phase.",),
                )
            if stroke_phase == "begin":
                if session.selection_stroke_id and session.selection_stroke_id != stroke_id:
                    return self._result(
                        session,
                        "select",
                        status="error",
                        diagnostics=("Another selection stroke is still active.",),
                    )
                session.selection_stroke_id = stroke_id
                session.selection_stroke_sequence = stroke_sequence
                session.selection_stroke_start = session.selection
                return self._result(session, "select")
            if session.selection_stroke_id != stroke_id or session.selection_stroke_start is None:
                return self._result(
                    session,
                    "select",
                    status="error",
                    diagnostics=("Selection stroke is stale or was retired.",),
                )
            if stroke_sequence <= session.selection_stroke_sequence:
                return self._result(session, "select", status="noop")
            session.selection_stroke_sequence = stroke_sequence
            if stroke_phase == "cancel":
                baseline = session.selection_stroke_start
                selected, groups, diagnostics, metrics = _apply_native_editor_session_selection_operation(
                    session,
                    baseline,
                    "replace",
                    native_selection_payload=_native_editor_selection_payload(baseline),
                    stop_event=stop_event,
                )
                if selected is None:
                    return self._result(session, "select", status="error", diagnostics=diagnostics, metrics=metrics)
                session.selection = selected
                session.selection_stroke_id = ""
                session.selection_stroke_sequence = -1
                session.selection_stroke_start = None
                return self._result(
                    session,
                    "select",
                    diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + diagnostics,
                    native_selection_groups=groups,
                    metrics=metrics,
                )
        previous_selection = session.selection
        if native_mesh_core_available():
            native_payload = _native_editor_select_payload_for_params(selection or MeshEditSelection(), params)
            selected, groups, diagnostics, metrics = _apply_native_editor_session_selection_operation(
                session,
                selection or MeshEditSelection(),
                operation,
                native_selection_payload=native_payload,
                stop_event=stop_event,
            )
            if selected is None:
                return self._result(session, "select", status="error", diagnostics=diagnostics, metrics=metrics)
            if stroke_phase == "end":
                baseline = session.selection_stroke_start or previous_selection
                self._record_selection_history(
                    session,
                    baseline,
                    selected,
                    label=_history_action_label("select", command),
                )
                session.selection_stroke_id = ""
                session.selection_stroke_sequence = -1
                session.selection_stroke_start = None
            elif not stroke_phase and _records_history(command):
                self._record_selection_history(
                    session,
                    previous_selection,
                    selected,
                    label=_history_action_label("select", command),
                )
            session.selection = selected
            return self._result(
                session,
                "select",
                diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + diagnostics,
                native_selection_groups=groups,
                metrics=metrics,
            )
        if isinstance(params.get("_native_screen_selection_payload"), Mapping):
            diagnostics = ("Native screen selection is unavailable; Python selection fallback is blocked.",)
        elif session.native_editor_mesh_dirty:
            diagnostics = ("Native editor selection is unavailable and Python mesh state is stale.",)
        else:
            diagnostics = ("Native editor selection is unavailable; Python selection fallback is blocked.",)
        return self._result(session, "select", status="error", diagnostics=diagnostics, metrics=metrics)

    def _record_selection_history(
        self,
        session: _MeshEditSession,
        previous_selection: MeshEditSelection,
        selected: MeshEditSelection,
        *,
        label: str,
    ) -> None:
        if previous_selection == selected:
            return
        _clear_history_stack(session.redo_stack)
        self._push_history_snapshot(
            session,
            _MeshHistorySnapshot(
                mesh=None,
                mode=session.mode,
                selection=previous_selection,
                edit_operations=tuple(session.edit_operations),
                history_action="select",
                history_label=str(label or "Select"),
                selection_only=True,
                object_transform=session.object_transform,
            ),
        )
        self._trim_session_history(session)

    def _apply_geometry_command(
        self,
        session: _MeshEditSession,
        command: MeshEditCommand,
        action: str,
        selection: MeshEditSelection,
        require_native: bool,
        command_mode: str,
    ) -> MeshEditResult:
        service_started = time.perf_counter()
        geometry_layers_before = session.geometry_layers
        active_geometry_layer_before = session.active_geometry_layer_id
        geometry_layer_copy_counter_before = session.geometry_layer_copy_counter
        if require_native and not native_mesh_core_available():
            raise RuntimeError(f"native mesh editor unavailable for {action}; Python mesh-edit fallback is disabled")
        topology_started = time.perf_counter()
        topology_before = (
            _session_mesh_structure_signature(session)
            if _command_may_change_topology(action, command, selection)
            else None
        )
        topology_ms = max(0.0, (time.perf_counter() - topology_started) * 1000.0)
        pushed_history = action in MESH_GEOMETRY_ACTIONS and _records_history(command)
        native_history = pushed_history and require_native
        defer_history = pushed_history and not native_history and _can_defer_native_live_history(action, command)
        history_mode = session.mode
        command_for_apply = command
        history_pushed = False
        if defer_history:
            command_for_apply = replace(
                command,
                params={**dict(command.params or {}), "_require_native_history_delta": True},
            )
        elif pushed_history and not native_history:
            self._push_history(
                session,
                prefer_native=True,
                action=action,
                label=_history_action_label(action, command),
            )
            history_pushed = True
        if command.mode is not None:
            session.mode = command_mode
        execution = _MeshCommandExecution(
            session=session,
            command=command,
            action=action,
            selection=selection,
            service_started=service_started,
            topology_before=topology_before,
            history_mode=history_mode,
            history_selection=session.selection,
            pushed_history=pushed_history,
            defer_native_live_history=defer_history,
            history_pushed=history_pushed,
            fallback_event_start=len(native_mesh_core_fallback_events()),
            result_metrics={
                "service_prepare_ms": max(0.0, (time.perf_counter() - service_started) * 1000.0),
                "service_topology_signature_ms": topology_ms,
            },
        )
        self._dispatch_geometry_command(execution, command_for_apply, require_native)
        result = self._finish_geometry_command(execution)
        if result.ok and result.topology_changed:
            self._record_topology_edit_operations(session, action, command, result)
        if result.ok and result.topology_changed and topology_before is not None:
            after_count = (
                len(result.submesh_counts)
                if result.submesh_counts
                else max(0, len(topology_before) + int(result.submesh_count_delta or 0))
            )
            layers_changed = self._reconcile_geometry_layers_after_topology(
                session,
                action=action,
                command=command,
                selection=selection,
                before_count=len(topology_before),
                after_count=after_count,
            )
            if layers_changed:
                if execution.history_pushed and session.undo_stack:
                    marker = session.undo_stack[-1]
                    marker.geometry_layers = geometry_layers_before
                    marker.active_geometry_layer_id = active_geometry_layer_before
                    marker.geometry_layer_copy_counter = geometry_layer_copy_counter_before
                    marker.retained_bytes = 0
                    marker.retained_bytes = _history_snapshot_retained_bytes(marker)
                self._schedule_mesh_layer_autosave(session)
        return result

    def _record_topology_edit_operations(
        self,
        session: _MeshEditSession,
        action: str,
        command: MeshEditCommand,
        result: MeshEditResult,
    ) -> None:
        """Record one stable operation per submesh that came back rebuildable.

        Recorded from the contract the native session actually produced, not from
        the action name: an admitted action whose submesh came back
        non-rebuildable records nothing, so the operation list never claims a
        lineage the geometry does not carry.
        """
        operation_name = topology_operation_for_native_action(action)
        if not operation_name:
            return
        if action == "delete" and _truthy(command.params.get("delete_parts")):
            # Deleting whole parts is not Face Delete. It removes submeshes
            # rather than triangles, and recording it as the face operation would
            # claim a lineage for geometry that is simply gone.
            return
        affected = set(int(index) for index in tuple(result.affected_submesh_indices or ()))
        recorded: list[MeshEditOperation] = []
        for summary in tuple(session.native_editor_topology_summaries or ()):
            submesh_index = int(summary.get("index", -1))
            if submesh_index < 0 or (affected and submesh_index not in affected):
                continue
            previous = session.topology_operation_revision
            session.topology_operation_revision = previous + 1
            recorded.append(
                MeshEditOperation(
                    operation=operation_name,
                    lod_index=0,
                    submesh_index=submesh_index,
                    vertex_count=int(summary.get("vertex_count", 0)),
                    source="resident_native",
                    metadata=topology_operation_metadata(
                        input_vertex_count=int(summary.get("original_vertex_count", 0)),
                        input_face_count=int(summary.get("original_face_count", 0)),
                        output_vertex_count=int(summary.get("vertex_count", 0)),
                        output_face_count=int(summary.get("face_count", 0)),
                        source_revision=previous,
                        result_revision=previous + 1,
                    ),
                )
            )
        if recorded:
            session.edit_operations = tuple(session.edit_operations) + tuple(recorded)

    def _dispatch_geometry_command(
        self,
        execution: _MeshCommandExecution,
        command_for_apply: MeshEditCommand,
        require_native: bool,
    ) -> None:
        dispatch_started = time.perf_counter()
        try:
            result = _apply_native_editor_session_geometry_action(
                execution.session,
                command_for_apply,
                execution.selection,
            )
            if result is not None:
                self._accept_native_geometry_result(execution, result)
            elif require_native:
                # Say which of the six refusal branches this was. Without it the
                # reader gets one sentence for six causes, and a session where
                # every stroke, Clear Selection and Finish Edit Mesh failed
                # cannot be told apart from a missing native module.
                refusal = str(getattr(execution.session, "native_editor_last_refusal", "") or "unrecorded")
                # The sentence itself is a translated key, so it stays exactly as
                # it shipped; the branch name is appended outside it rather than
                # folded in, which would orphan the key in all fourteen catalogs.
                message = (
                    f"native mesh editor session failed for {execution.action}; Python mesh-edit fallback is disabled"
                )
                raise RuntimeError(f"{message} [{refusal}]")
            elif execution.action not in _LEGACY_DISPLAY_CLEANUP_ACTIONS:
                raise RuntimeError(f"unsupported non-native mesh edit action: {execution.action}")
            else:
                execution.affected, execution.changed = apply_mesh_edit_geometry_action(
                    execution.session.working_mesh,
                    command_for_apply,
                    execution.selection,
                )
        except NativeLiveHistoryUnavailable:
            if not execution.defer_native_live_history:
                raise
            snapshot = _snapshot(execution.session, prefer_native=True)
            self._push_history_snapshot(
                execution.session,
                _MeshHistorySnapshot(
                    mesh=snapshot.mesh,
                    mode=execution.history_mode,
                    selection=execution.history_selection,
                    edit_operations=snapshot.edit_operations,
                    vertex_position_deltas=snapshot.vertex_position_deltas,
                    native_submesh_snapshot=snapshot.native_submesh_snapshot,
                    history_action=execution.action,
                    history_label=_history_action_label(execution.action, execution.command),
                    object_transform=snapshot.object_transform,
                ),
            )
            execution.history_pushed = True
            try:
                result = _apply_native_editor_session_geometry_action(
                    execution.session,
                    execution.command,
                    execution.selection,
                )
                if result is not None:
                    self._accept_native_geometry_result(execution, result)
                elif require_native:
                    raise RuntimeError(
                        f"native mesh editor session failed for {execution.action}; Python mesh-edit fallback is disabled"
                    )
                elif execution.action not in _LEGACY_DISPLAY_CLEANUP_ACTIONS:
                    raise RuntimeError(f"unsupported non-native mesh edit action: {execution.action}")
                else:
                    execution.affected, execution.changed = apply_mesh_edit_geometry_action(
                        execution.session.working_mesh,
                        execution.command,
                        execution.selection,
                    )
            except Exception:
                _discard_history_snapshot(execution.session.undo_stack)
                execution.history_pushed = False
                raise
        except Exception:
            if execution.history_pushed:
                _discard_history_snapshot(execution.session.undo_stack)
                execution.history_pushed = False
            raise
        execution.result_metrics["service_dispatch_ms"] = max(
            0.0,
            (time.perf_counter() - dispatch_started) * 1000.0,
        )

    @staticmethod
    def _accept_native_geometry_result(
        execution: _MeshCommandExecution,
        result: _NativeEditorApplyResult,
    ) -> None:
        execution.native_editor_result = result
        execution.affected, execution.changed = result.affected, result.changed
        execution.native_preview_vertex_update_groups = result.native_preview_vertex_update_groups
        execution.native_preview_triangle_groups = result.native_preview_triangle_groups
        execution.native_selection_groups = result.native_selection_groups
        # Geometry commands may carry the operation's explicit target selection
        # even when they are no-ops. Only topology results own/remap the live
        # selection; non-topology commands must not turn their target argument
        # into a persistent session selection.
        if result.native_selection is not None and bool(result.topology_changed):
            execution.session.selection = result.native_selection
        execution.native_submesh_counts = result.submesh_counts
        execution.result_metrics.update(result.metrics)
        execution.used_native_editor_session = True

    def _finish_geometry_command(self, execution: _MeshCommandExecution) -> MeshEditResult:
        topology_started = time.perf_counter()
        native_result = execution.native_editor_result
        if native_result is not None and native_result.topology_changed is not None:
            topology_changed = bool(native_result.topology_changed)
            submesh_count_delta = int(native_result.submesh_count_delta)
        elif execution.topology_before is None:
            topology_changed = False
            submesh_count_delta = 0
        else:
            topology_after = _session_mesh_structure_signature(execution.session)
            topology_changed = topology_after != execution.topology_before
            submesh_count_delta = len(topology_after) - len(execution.topology_before)
        execution.result_metrics["service_topology_compare_ms"] = max(
            0.0,
            (time.perf_counter() - topology_started) * 1000.0,
        )
        finalize_started = time.perf_counter()
        diagnostics = self._commit_geometry_command(execution, topology_changed)
        if topology_changed and execution.action == "delete":
            # Delete intentionally leaves no element selection. The native
            # report still describes the pre-delete target in some PAC paths;
            # publishing those face indices against compacted topology lights
            # unrelated faces and makes the deletion look random.
            execution.native_selection_groups = ()
        diagnostics = _append_unique_diagnostics(
            diagnostics,
            _native_blocked_fallback_diagnostics(execution.fallback_event_start),
        )
        execution.result_metrics["service_finalize_ms"] = max(
            0.0,
            (time.perf_counter() - finalize_started) * 1000.0,
        )
        result_started = time.perf_counter()
        result = self._result(
            execution.session,
            execution.action,
            affected=execution.affected,
            changed=execution.changed,
            native_selection_groups=execution.native_selection_groups,
            native_preview_vertex_update_groups=execution.native_preview_vertex_update_groups,
            native_preview_triangle_groups=execution.native_preview_triangle_groups,
            topology_changed=topology_changed
            or (
                execution.action in MESH_TOPOLOGY_ACTIONS
                and (bool(execution.affected) or bool(execution.changed))
            ),
            submesh_count_delta=submesh_count_delta,
            submesh_counts=execution.native_submesh_counts,
            diagnostics=diagnostics,
            metrics=execution.result_metrics,
        )
        metrics = dict(result.metrics)
        metrics["service_result_build_ms"] = max(0.0, (time.perf_counter() - result_started) * 1000.0)
        metrics["service_total_ms"] = max(0.0, (time.perf_counter() - execution.service_started) * 1000.0)
        return replace(result, metrics=metrics)

    def _commit_geometry_command(
        self,
        execution: _MeshCommandExecution,
        topology_changed: bool,
    ) -> tuple[str, ...]:
        session = execution.session
        changed_any = bool(execution.affected) or bool(execution.changed) or topology_changed
        if execution.history_pushed and not changed_any:
            _discard_history_snapshot(session.undo_stack)
            execution.history_pushed = False
        elif changed_any:
            if execution.defer_native_live_history and not execution.history_pushed:
                snapshot = _native_live_history_snapshot(
                    session,
                    execution.changed,
                    mode=execution.history_mode,
                    selection=execution.history_selection,
                )
                if snapshot is None:
                    raise RuntimeError("native live edit did not provide undo history delta")
                snapshot.history_action = execution.action
                snapshot.history_label = _history_action_label(execution.action, execution.command)
                self._push_history_snapshot(session, snapshot)
            elif execution.used_native_editor_session and execution.pushed_history and not execution.history_pushed:
                result = execution.native_editor_result
                stroke_id = result.native_stroke_id if result is not None else ""
                cancelled = result.native_stroke_cancelled if result is not None else False
                if cancelled and stroke_id:
                    if (
                        session.undo_stack
                        and session.undo_stack[-1].native_editor_history
                        and session.undo_stack[-1].native_editor_stroke_id == stroke_id
                    ):
                        _discard_history_snapshot(session.undo_stack)
                elif (
                    stroke_id
                    and session.undo_stack
                    and session.undo_stack[-1].native_editor_history
                    and session.undo_stack[-1].native_editor_stroke_id == stroke_id
                ):
                    execution.history_pushed = True
                else:
                    self._push_history_snapshot(
                        session,
                        _MeshHistorySnapshot(
                            mesh=None,
                            mode=execution.history_mode,
                            selection=execution.history_selection,
                            edit_operations=tuple(session.edit_operations),
                            native_editor_history=True,
                            native_editor_stroke_id=stroke_id,
                            history_action=execution.action,
                            history_label=_history_action_label(execution.action, execution.command),
                            object_transform=session.object_transform,
                        ),
                    )
                    execution.history_pushed = True
            if execution.used_native_editor_session:
                counts = _update_native_history_usage(session, execution.result_metrics)
                _trim_native_history_markers(session, *counts)
                self._trim_session_history(session)
            diagnostics = self._finalize_changed_geometry(execution, topology_changed)
            if topology_changed:
                self._invalidate_morph_after_topology_locked(session)
            self._schedule_mesh_layer_autosave(session)
            return diagnostics
        return ()

    def _finalize_changed_geometry(
        self,
        execution: _MeshCommandExecution,
        topology_changed: bool,
    ) -> tuple[str, ...]:
        session = execution.session
        if execution.used_native_editor_session and session.native_editor_mesh_dirty:
            indices = {int(index) for index in execution.affected if 0 <= int(index) < len(session.working_mesh.submeshes)}
            indices.update(
                int(index)
                for index in execution.changed
                if 0 <= int(index) < len(session.working_mesh.submeshes)
            )
            if topology_changed and not indices:
                indices.update(range(len(session.working_mesh.submeshes)))
            invalidated = tuple(
                index
                for index in sorted(indices)
                if execution.action in _TANGENT_INVALIDATING_ACTIONS
                and getattr(session.working_mesh.submeshes[index], "tangents", None)
            )
        else:
            invalidated = _invalidate_tangents_after_edit(
                session.working_mesh,
                execution.action,
                execution.affected,
                execution.changed,
                topology_changed=topology_changed,
            )
        diagnostics = (
            (f"Invalidated tangents for {len(invalidated)} part(s); run Generate Tangents before export.",)
            if invalidated
            else ()
        )
        _clear_history_stack(session.redo_stack)
        session.revision += 1
        if session.native_editor_mesh_dirty:
            _apply_native_editor_dirty_counts(session)
        else:
            refresh_mesh_totals(session.working_mesh)
        if not execution.used_native_editor_session:
            _close_native_editor_session(session)
        if execution.action == "delete" and _truthy(execution.command.params.get("delete_parts")):
            session.selection = MeshEditSelection()
        elif execution.used_native_editor_session and topology_changed and execution.action == "delete":
            session.selection = MeshEditSelection()
        elif execution.used_native_editor_session and topology_changed and session.native_editor_mesh_dirty:
            pass
        elif execution.action in MESH_TOPOLOGY_ACTIONS or topology_changed:
            session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        _record_session_edit_operations(
            session,
            execution.action,
            execution.command,
            execution.affected,
            execution.changed,
            topology_changed=topology_changed,
        )
        if execution.action in {"material_assign", "material_copy"}:
            texture = execution.command.params.get("texture") if execution.action == "material_assign" else None
            source = Path(str(texture or "")).expanduser() if texture is not None else None
            if source is not None and source.is_file():
                self.record_committed_texture_assignment(
                    session.session_id,
                    source,
                    resource_id=str(
                        execution.command.params.get(
                            "resource_id",
                            execution.command.params.get("texture_resource_id", ""),
                        )
                        or ""
                    ),
                    channel=str(execution.command.params.get("channel", "base") or "base"),
                    affected_submeshes=tuple(execution.affected),
                    logical_path=str(texture or ""),
                )
            else:
                session.material_generation += 1
        return diagnostics



def _coerce_command(command: MeshEditCommand | str) -> MeshEditCommand:
    if isinstance(command, MeshEditCommand):
        return command
    return MeshEditCommand(action=str(command))


def _history_action_label(action: str, command: MeshEditCommand | None = None) -> str:
    if command is not None and str(command.label or "").strip():
        return str(command.label).strip()
    normalized = str(action or "mesh_edit").strip().lower()
    params = dict(command.params or {}) if command is not None else {}
    if normalized == "select":
        operation = str(params.get("operation", params.get("selection_operation", "replace")) or "replace").strip().lower()
        return {
            "all": "Select All",
            "add": "Add Selection",
            "subtract": "Subtract Selection",
            "toggle": "Toggle Selection",
            "grow": "Grow Selection",
            "shrink": "Shrink Selection",
            "invert": "Invert Selection",
        }.get(operation, "Select")
    if normalized == "brush":
        tool = str(params.get("tool") or "brush").strip().replace("_", " ")
        return tool.title()
    if normalized == "transform":
        return "Move"
    return normalized.replace("_", " ").title() or "Mesh Edit"


def _history_entries(session: _MeshEditSession) -> tuple[MeshEditHistoryEntry, ...]:
    def entry(snapshot: _MeshHistorySnapshot, state: str) -> MeshEditHistoryEntry:
        action = str(snapshot.history_action or "mesh_edit").strip().lower()
        label = str(snapshot.history_label or "").strip() or _history_action_label(action)
        return MeshEditHistoryEntry(action=action, label=label, state=state)

    return tuple(entry(snapshot, "applied") for snapshot in session.undo_stack) + tuple(
        entry(snapshot, "undone") for snapshot in reversed(session.redo_stack)
    )


def _snapshot(session: _MeshEditSession, *, prefer_native: bool = False) -> _MeshHistorySnapshot:
    if _service_session_native_clone_supported(session.working_mesh):
        native_snapshot = snapshot_native_mesh_submeshes(session.working_mesh)
        if native_snapshot is not None:
            return _MeshHistorySnapshot(
                mesh=None,
                mode=session.mode,
                selection=session.selection,
                edit_operations=tuple(session.edit_operations),
                native_submesh_snapshot=native_snapshot,
                material_generation=session.material_generation,
                committed_texture_resources=tuple(
                    session.committed_texture_resources[key]
                    for key in sorted(session.committed_texture_resources)
                ),
                object_transform=session.object_transform,
            )
        if not _allow_python_history_snapshot_fallback(session.working_mesh, "history.snapshot"):
            raise RuntimeError("native mesh history snapshot capture failed and Python fallback was blocked")
    return _clone_history_snapshot_for_python_fallback(session)


def _capture_history_material_state(
    session: _MeshEditSession,
    snapshot: _MeshHistorySnapshot,
) -> _MeshHistorySnapshot:
    if snapshot.material_generation is None:
        snapshot.material_generation = int(session.material_generation)
    if snapshot.committed_texture_resources is None:
        snapshot.committed_texture_resources = tuple(
            session.committed_texture_resources[key]
            for key in sorted(session.committed_texture_resources)
        )
    return snapshot


def _restore_history_material_state(session: _MeshEditSession, snapshot: _MeshHistorySnapshot) -> None:
    resources = snapshot.committed_texture_resources
    if resources is None:
        return
    current = dict(session.committed_texture_resources)
    target = {(resource.resource_id, resource.channel): resource for resource in resources}
    assignment_keys = {
        key
        for key in set(current) | set(target)
        if bool(getattr(current.get(key), "source_dds_path", ""))
        or bool(getattr(target.get(key), "source_dds_path", ""))
    }
    restored = dict(current)
    for key in assignment_keys:
        if key in target:
            restored[key] = target[key]
        else:
            restored.pop(key, None)
    if restored != current:
        session.committed_texture_resources = restored
        session.material_generation = max(
            int(session.material_generation),
            int(snapshot.material_generation or 0),
        ) + 1


def _dispose_history_snapshot(snapshot: _MeshHistorySnapshot) -> None:
    if snapshot.native_submesh_snapshot is not None:
        dispose_native_mesh_submesh_snapshot(snapshot.native_submesh_snapshot)
    disposed_sparse_ids: set[str] = set()
    for delta in snapshot.vertex_position_deltas:
        if delta.before_positions_binary is not None:
            dispose_native_mesh_history_delta(delta.before_positions_binary)
        snapshot_id = str(delta.native_sparse_snapshot_id or "").strip()
        if snapshot_id and snapshot_id not in disposed_sparse_ids:
            dispose_native_mesh_sparse_vertex_snapshot(snapshot_id)
            disposed_sparse_ids.add(snapshot_id)


def _discard_history_snapshot(stack: list[_MeshHistorySnapshot], index: int = -1) -> None:
    snapshot = stack.pop(index)
    _dispose_history_snapshot(snapshot)


def _clear_history_stack(stack: list[_MeshHistorySnapshot]) -> None:
    while stack:
        _discard_history_snapshot(stack)




def _update_native_history_usage(
    session: _MeshEditSession,
    metrics: Mapping[str, object] | None,
) -> tuple[bool, bool]:
    raw = dict(metrics or {})
    undo_count = _coerce_index(raw.get("native_history_undo_count"))
    redo_count = _coerce_index(raw.get("native_history_redo_count"))
    retained_bytes = _coerce_index(raw.get("native_history_retained_bytes"))
    if undo_count is not None and undo_count >= 0:
        session.native_history_undo_count = undo_count
    if redo_count is not None and redo_count >= 0:
        session.native_history_redo_count = redo_count
    if retained_bytes is not None and retained_bytes >= 0:
        session.native_history_retained_bytes = retained_bytes
    return undo_count is not None and undo_count >= 0, redo_count is not None and redo_count >= 0


def _trim_native_history_markers(
    session: _MeshEditSession,
    undo_count_known: bool,
    redo_count_known: bool,
) -> None:
    for stack, retained_count, count_known in (
        (session.undo_stack, session.native_history_undo_count, undo_count_known),
        (session.redo_stack, session.native_history_redo_count, redo_count_known),
    ):
        if not count_known:
            continue
        while sum(1 for snapshot in stack if snapshot.native_editor_history) > retained_count:
            oldest = next(index for index, snapshot in enumerate(stack) if snapshot.native_editor_history)
            _discard_history_snapshot(stack, oldest)




def _restore_native_editor_history(
    session: _MeshEditSession,
    snapshot: _MeshHistorySnapshot,
    action: str,
) -> _MeshRestoreOutcome:
    if not session.native_editor_session_ready:
        raise RuntimeError("native mesh editor history is unavailable for this session")
    current_mode = session.mode
    current_selection = session.selection
    current_edit_operations = tuple(session.edit_operations)
    current_geometry_layers = session.geometry_layers
    current_active_geometry_layer_id = session.active_geometry_layer_id
    current_geometry_layer_copy_counter = session.geometry_layer_copy_counter
    current_object_transform = session.object_transform
    dirty_at_start = session.native_editor_mesh_dirty
    before_signature = (
        session.native_editor_mesh_dirty_counts
        if dirty_at_start and session.native_editor_mesh_dirty_counts
        else _mesh_structure_signature(session.working_mesh)
    )
    command = "redo" if action == "redo" else "undo"
    native_history_started = time.perf_counter()
    report = (
        redo_native_mesh_editor_session(session.session_id, timeout_seconds=20.0)
        if command == "redo"
        else undo_native_mesh_editor_session(session.session_id, timeout_seconds=20.0)
    )
    native_history_roundtrip_ms = max(0.0, (time.perf_counter() - native_history_started) * 1000.0)
    if report is None:
        raise RuntimeError(f"native mesh editor {command} failed")
    native_preview_vertex_update_groups = native_mesh_editor_session_preview_vertex_update_groups(report)
    native_preview_triangle_groups = native_mesh_editor_session_preview_triangle_groups(report)
    native_selection_payload = native_mesh_editor_session_selection_from_report(report)
    native_selection = (
        MeshEditSelection.from_maps(
            vertices_by_submesh=native_selection_payload.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=native_selection_payload.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=native_selection_payload.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=native_selection_payload.get("source_indices"),  # type: ignore[arg-type]
        )
        if native_selection_payload is not None
        else None
    )
    native_selection_groups = native_mesh_editor_session_selection_groups_from_report(report)
    apply_started = time.perf_counter()
    current_submesh_count = len(before_signature)
    dirty_counts = _native_editor_dirty_counts_from_report(
        report,
        current_submesh_count=current_submesh_count,
    )
    if dirty_counts:
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = dirty_counts
        _apply_native_editor_dirty_counts(session)
        applied = (
            _native_editor_report_affected_indices(report, len(dirty_counts)),
            _native_editor_report_changed_vertices(report, dirty_counts),
        )
    else:
        session.native_editor_session_ready = False
        raise RuntimeError(f"native mesh editor {command} did not return dirty submesh counts")
    python_apply_ms = max(0.0, (time.perf_counter() - apply_started) * 1000.0)
    if not session.native_editor_mesh_dirty:
        session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
    affected, changed_vertices_by_submesh = applied
    session.mode = snapshot.mode
    session.selection = native_selection if native_selection is not None else snapshot.selection
    session.edit_operations = tuple(snapshot.edit_operations)
    if snapshot.object_transform is not None:
        session.object_transform = snapshot.object_transform
    if snapshot.geometry_layers is not None:
        session.geometry_layers = _restore_geometry_layer_structure(
            snapshot.geometry_layers,
            current_geometry_layers,
        )
        layer_action_changes_active = (
            str(snapshot.history_action or "").strip().lower() == "paste"
            or str(snapshot.history_label or "").strip().lower() == "delete layer"
        )
        requested_active = (
            snapshot.active_geometry_layer_id
            if layer_action_changes_active
            else current_active_geometry_layer_id
        ) or "base"
        session.active_geometry_layer_id = (
            requested_active
            if any(layer.layer_id == requested_active for layer in session.geometry_layers)
            else "base"
        )
        session.geometry_layer_copy_counter = int(snapshot.geometry_layer_copy_counter or 0)
        session.geometry_layer_revision += 1
    session.native_editor_selection_signature = ()
    after_signature = session.native_editor_mesh_dirty_counts if session.native_editor_mesh_dirty else _mesh_structure_signature(session.working_mesh)
    topology_changed, topology_affected, submesh_count_delta = _restore_topology_delta(
        before_signature,
        after_signature,
    )
    metrics = _native_editor_metrics(report)
    metrics["native_history_roundtrip_ms"] = native_history_roundtrip_ms
    metrics["native_history_overhead_ms"] = max(
        0.0,
        native_history_roundtrip_ms - metrics.get("cpp_ms", 0.0) - metrics.get("io_serialization_ms", 0.0),
    )
    metrics["python_apply_ms"] = python_apply_ms
    metrics["python_apply_deferred"] = 1.0 if session.native_editor_mesh_dirty else 0.0
    current_snapshot = _capture_history_material_state(
        session,
        _MeshHistorySnapshot(
            mesh=None,
            mode=current_mode,
            selection=current_selection,
            edit_operations=current_edit_operations,
            native_editor_history=True,
            native_editor_stroke_id=snapshot.native_editor_stroke_id,
            history_action=snapshot.history_action,
            history_label=snapshot.history_label,
            geometry_layers=(current_geometry_layers if snapshot.geometry_layers is not None else None),
            active_geometry_layer_id=(
                current_active_geometry_layer_id if snapshot.geometry_layers is not None else None
            ),
            geometry_layer_copy_counter=(
                current_geometry_layer_copy_counter if snapshot.geometry_layers is not None else None
            ),
            object_transform=current_object_transform,
        ),
    )
    _restore_history_material_state(session, snapshot)
    return _MeshRestoreOutcome(
        snapshot=current_snapshot,
        changed_vertices_by_submesh=dict(changed_vertices_by_submesh),
        native_preview_vertex_update_groups=native_preview_vertex_update_groups,
        native_preview_triangle_groups=native_preview_triangle_groups,
        native_selection_groups=native_selection_groups,
        topology_changed=topology_changed,
        affected_submesh_indices=set(affected) | topology_affected,
        submesh_count_delta=submesh_count_delta,
        submesh_counts=after_signature,
        metrics=metrics,
    )


def _restore_geometry_layer_structure(
    target_layers: tuple[_MeshGeometryLayer, ...],
    current_layers: tuple[_MeshGeometryLayer, ...],
) -> tuple[_MeshGeometryLayer, ...]:
    """Restore geometry membership without rolling back non-history metadata."""

    current_by_id = {layer.layer_id: layer for layer in current_layers}
    target_by_id = {layer.layer_id: layer for layer in target_layers}
    restored_by_id = {
        layer.layer_id: (
            replace(
                layer,
                name=current_by_id[layer.layer_id].name,
                visible=current_by_id[layer.layer_id].visible,
            )
            if layer.layer_id in current_by_id
            else layer
        )
        for layer in target_layers
    }

    # Existing layers keep the user's current Move Up/Down order. A layer that
    # the geometry action removed is reinserted beside its closest historical
    # neighbour, so Undo Delete restores its former position without moving the
    # layers that remained editable in the meantime.
    ordered_ids = [layer.layer_id for layer in current_layers if layer.layer_id in target_by_id]
    for target_index, target in enumerate(target_layers):
        if target.layer_id in ordered_ids:
            continue
        previous = next(
            (
                target_layers[index].layer_id
                for index in range(target_index - 1, -1, -1)
                if target_layers[index].layer_id in ordered_ids
            ),
            None,
        )
        if previous is not None:
            ordered_ids.insert(ordered_ids.index(previous) + 1, target.layer_id)
            continue
        following = next(
            (
                target_layers[index].layer_id
                for index in range(target_index + 1, len(target_layers))
                if target_layers[index].layer_id in ordered_ids
            ),
            None,
        )
        ordered_ids.insert(ordered_ids.index(following) if following is not None else len(ordered_ids), target.layer_id)

    return tuple(restored_by_id[layer_id] for layer_id in ordered_ids)


def _restore_snapshot(session: _MeshEditSession, snapshot: _MeshHistorySnapshot) -> _MeshRestoreOutcome:
    current_mode = session.mode
    current_selection = session.selection
    current_edit_operations = tuple(session.edit_operations)
    current_object_transform = session.object_transform
    before_signature = _mesh_structure_signature(session.working_mesh)
    if snapshot.selection_only:
        current_snapshot = _capture_history_material_state(
            session,
            _MeshHistorySnapshot(
                mesh=None,
                mode=current_mode,
                selection=current_selection,
                edit_operations=current_edit_operations,
                history_action=snapshot.history_action,
                history_label=snapshot.history_label,
                selection_only=True,
                object_transform=current_object_transform,
            ),
        )
        session.mode = snapshot.mode
        session.selection = snapshot.selection
        session.edit_operations = tuple(snapshot.edit_operations)
        if snapshot.object_transform is not None:
            session.object_transform = snapshot.object_transform
        session.native_editor_selection_signature = ()
        _restore_history_material_state(session, snapshot)
        return _MeshRestoreOutcome(
            snapshot=current_snapshot,
            submesh_counts=before_signature,
        )
    changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = {}
    if snapshot.mesh is not None:
        current_snapshot = _snapshot(session)
        session.working_mesh = snapshot.mesh
    elif snapshot.native_submesh_snapshot is not None:
        current_snapshot = _snapshot(session, prefer_native=True)
        if not restore_native_mesh_submesh_snapshot(session.working_mesh, snapshot.native_submesh_snapshot):
            raise RuntimeError("native mesh history snapshot restore failed")
    elif snapshot.vertex_position_deltas:
        current_deltas = _restore_vertex_position_deltas(session.working_mesh, snapshot.vertex_position_deltas)
        current_snapshot = _MeshHistorySnapshot(
            mesh=None,
            mode=current_mode,
            selection=current_selection,
            edit_operations=current_edit_operations,
            vertex_position_deltas=current_deltas,
            object_transform=current_object_transform,
        )
        changed_vertices_by_submesh = _changed_vertices_from_deltas(
            session.working_mesh,
            current_deltas or snapshot.vertex_position_deltas,
        )
    else:
        current_snapshot = _snapshot(session)
    current_snapshot.history_action = snapshot.history_action
    current_snapshot.history_label = snapshot.history_label
    _capture_history_material_state(session, current_snapshot)
    session.mode = snapshot.mode
    session.selection = snapshot.selection
    session.edit_operations = tuple(snapshot.edit_operations)
    if snapshot.object_transform is not None:
        session.object_transform = snapshot.object_transform
    session.native_editor_selection_signature = ()
    _restore_history_material_state(session, snapshot)
    after_signature = _mesh_structure_signature(session.working_mesh)
    topology_changed, affected_submesh_indices, submesh_count_delta = _restore_topology_delta(
        before_signature,
        after_signature,
    )
    return _MeshRestoreOutcome(
        snapshot=current_snapshot,
        changed_vertices_by_submesh=changed_vertices_by_submesh,
        topology_changed=topology_changed,
        affected_submesh_indices=affected_submesh_indices,
        submesh_count_delta=submesh_count_delta,
        submesh_counts=after_signature,
    )


def _restore_topology_delta(
    before: tuple[tuple[int, int], ...],
    after: tuple[tuple[int, int], ...],
) -> tuple[bool, set[int], int]:
    if before == after:
        return False, set(), 0
    affected = {
        index
        for index in range(min(len(before), len(after)))
        if before[index] != after[index]
    }
    affected.update(range(min(len(before), len(after)), max(len(before), len(after))))
    return True, affected, len(after) - len(before)


def _changed_vertices_from_deltas(
    mesh: ParsedMesh,
    deltas: tuple[_MeshVertexPositionDelta, ...],
) -> dict[int, Sequence[int] | set[int]]:
    changed: dict[int, Sequence[int] | set[int]] = {}
    for delta in deltas:
        submesh_index = int(delta.submesh_index)
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        vertex_count = len(mesh.submeshes[submesh_index].vertices or ())
        if (
            isinstance(delta.vertex_indices, range)
            and delta.vertex_indices.step == 1
            and delta.vertex_indices.start >= 0
            and delta.vertex_indices.stop <= vertex_count
        ):
            changed[submesh_index] = delta.vertex_indices
            continue
        indices = {
            int(index)
            for index in delta.vertex_indices
            if 0 <= int(index) < vertex_count
        }
        if indices:
            changed[submesh_index] = indices
    return changed




def _session_mesh_structure_signature(session: _MeshEditSession) -> tuple[tuple[int, int], ...]:
    if session.native_editor_mesh_dirty and session.native_editor_mesh_dirty_counts:
        return session.native_editor_mesh_dirty_counts
    return _mesh_structure_signature(session.working_mesh)
