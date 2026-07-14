from __future__ import annotations

import copy
import hashlib
import math
import os
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
    MeshAnimationClip,
    MeshEditCommand,
    MeshEditHistoryEntry,
    MeshEditResult,
    MeshEditSelection,
    MeshEditSessionView,
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
    _MeshHistorySnapshot,
    _MeshRestoreOutcome,
    _MeshVertexPositionDelta,
    _NativeEditorApplyResult,
    MeshPreparedWorkingMeshReplacement,
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
    _native_editor_selection_signature_for_apply,
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
_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})
_NATIVE_EDITOR_SESSION_ACTIONS = frozenset({"select"}) | (
    frozenset(MESH_GEOMETRY_ACTIONS) - _LEGACY_DISPLAY_CLEANUP_ACTIONS
)


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
    try:
        asset = mesh_asset_from_parsed_mesh(mesh, source_data, source_path=str(mesh.path or ""))
    except Exception:
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
        result = roundtrip_mesh_bytes(
            source_data,
            str(mesh.path or ""),
            parser=lambda _data, _filename: mesh,
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


def _copy_mesh_validation_metadata(source: ParsedMesh, target: ParsedMesh) -> None:
    for name in (
        "_cdmw_original_data",
        "_cdmw_mesh_asset_parse_confidence",
        "_cdmw_mesh_asset_source_hash",
        "_cdmw_mesh_asset_inferred_bone_count",
        "_cdmw_no_op_roundtrip_report",
        "_cdmw_mesh_asset_lods",
        "_cdmw_mesh_asset_material_slots",
        "_cdmw_mesh_asset_unknown_sections",
        "_cdmw_sidecar_source_asset_hash",
        "_cdmw_sidecar_source_asset_size",
        "material_slots",
        "unknown_sections",
    ):
        if hasattr(source, name):
            setattr(target, name, copy.deepcopy(getattr(source, name)))
    for source_submesh, target_submesh in zip(tuple(source.submeshes or ()), tuple(target.submeshes or ())):
        copy_extra_submesh_attrs(source_submesh, target_submesh)


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
class MeshService(
    MeshRiggingServiceMixin,
    MeshResidentMaterialServiceMixin,
    MeshWorkingReplacementServiceMixin,
    MeshRebuildServiceMixin,
    MeshHistoryServiceMixin,
):
    settings: object | None = None
    max_history: int = 64
    max_history_bytes: int = _DEFAULT_MESH_HISTORY_BYTES
    _sessions: dict[str, _MeshEditSession] = field(default_factory=dict)

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
        working_mesh, base_mesh = _clone_mesh_pair_for_session_open(mesh)
        _copy_mesh_validation_metadata(mesh, working_mesh)
        _copy_mesh_validation_metadata(mesh, base_mesh)
        refresh_mesh_totals(working_mesh)
        self._sessions[session_key] = _MeshEditSession(
            session_id=session_key,
            base_mesh=base_mesh,
            working_mesh=working_mesh,
            original_data=original_data,
            mesh_asset_parse_confidence=str(getattr(mesh, "_cdmw_mesh_asset_parse_confidence", "") or ""),
            mesh_asset_source_hash=str(
                getattr(mesh, "_cdmw_mesh_asset_source_hash", "")
                or getattr(mesh, "_cdmw_sidecar_source_asset_hash", "")
                or (hashlib.sha256(original_data).hexdigest() if original_data else "")
            ),
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
        )
        return self.session_view(session_key)

    def close_edit_session(self, session_id: str) -> None:
        session_key = str(session_id)
        session = self._sessions.get(session_key)
        if session is not None:
            with session.export_lock:
                if self._sessions.get(session_key) is not session:
                    return
                self._sessions.pop(session_key, None)
                session.closed = True
            _close_native_editor_session(session)
            _clear_history_stack(session.undo_stack)
            _clear_history_stack(session.redo_stack)
            self.dispose_export_resources(session)

    def session_view(self, session_id: str) -> MeshEditSessionView:
        session = self._session(session_id)
        with session.export_lock:
            return self._session_view_locked(session)

    def _session_view_locked(self, session: _MeshEditSession) -> MeshEditSessionView:
        if session.native_editor_mesh_dirty:
            if not session.native_editor_mesh_dirty_counts:
                raise RuntimeError("native mesh editor session view requires native submesh counts; Python mesh state is stale")
            _apply_native_editor_dirty_counts(session)
            submesh_count = len(session.native_editor_mesh_dirty_counts)
        else:
            refresh_mesh_totals(session.working_mesh)
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
        if action not in MESH_EDIT_ACTIONS:
            raise ValueError(f"Unsupported mesh edit action: {edit_command.action!r}")
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
        params = dict(command.params or {})
        metrics: dict[str, float] = {}
        operation = params.get("operation", params.get("selection_operation", "replace"))
        stop_event = _stop_event_from_params(params)
        fallback_event_start = len(native_mesh_core_fallback_events())
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
            if _records_history(command):
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
        return self._finish_geometry_command(execution)

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
                raise RuntimeError(
                    f"native mesh editor session failed for {execution.action}; Python mesh-edit fallback is disabled"
                )
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
                        ),
                    )
                    execution.history_pushed = True
            if execution.used_native_editor_session:
                counts = _update_native_history_usage(session, execution.result_metrics)
                _trim_native_history_markers(session, *counts)
                self._trim_session_history(session)
            diagnostics = self._finalize_changed_geometry(execution, topology_changed)
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


def _clone_mesh_pair_for_session_open(mesh: ParsedMesh) -> tuple[ParsedMesh, ParsedMesh]:
    if not _service_session_native_clone_supported(mesh):
        return _clone_mesh_pair_for_service_python_fallback(
            mesh,
            "session.open_clone_unsupported_topology",
            "Python edit-session open clone fallback used for unsupported topology",
            guard_native_supported=False,
        )
    native_snapshot: Mapping[str, object] | None = None
    try:
        native_snapshot = snapshot_native_mesh_submeshes(mesh)
        if native_snapshot is not None:
            working_mesh = ParsedMesh()
            base_mesh = ParsedMesh()
            if (
                restore_native_mesh_submesh_snapshot(working_mesh, native_snapshot)
                and restore_native_mesh_submesh_snapshot(base_mesh, native_snapshot)
            ):
                refresh_mesh_totals(working_mesh)
                refresh_mesh_totals(base_mesh)
                return working_mesh, base_mesh
    except Exception:
        pass
    finally:
        if native_snapshot is not None:
            dispose_native_mesh_submesh_snapshot(native_snapshot)
    return _clone_mesh_pair_for_service_python_fallback(
        mesh,
        "session.open_clone",
        "Python edit-session open clone fallback blocked while native mesh core is available",
    )


def _clone_mesh_for_service_native_snapshot(mesh: ParsedMesh, operation: str, reason: str) -> ParsedMesh:
    if not _service_session_native_clone_supported(mesh):
        return _clone_mesh_for_service_python_fallback(
            mesh,
            f"{operation}.unsupported_topology",
            reason,
            guard_native_supported=False,
        )
    native_snapshot: Mapping[str, object] | None = None
    try:
        native_snapshot = snapshot_native_mesh_submeshes(mesh)
        if native_snapshot is not None:
            restored_mesh = ParsedMesh()
            if restore_native_mesh_submesh_snapshot(restored_mesh, native_snapshot):
                refresh_mesh_totals(restored_mesh)
                _copy_mesh_validation_metadata(mesh, restored_mesh)
                return restored_mesh
    except Exception:
        pass
    finally:
        if native_snapshot is not None:
            dispose_native_mesh_submesh_snapshot(native_snapshot)
    return _clone_mesh_for_service_python_fallback(mesh, operation, reason)


def _clone_history_snapshot_for_python_fallback(session: _MeshEditSession) -> _MeshHistorySnapshot:
    return _MeshHistorySnapshot(
        mesh=clone_mesh_for_editing(session.working_mesh),
        mode=session.mode,
        selection=session.selection,
        edit_operations=tuple(session.edit_operations),
        material_generation=session.material_generation,
        committed_texture_resources=tuple(
            session.committed_texture_resources[key]
            for key in sorted(session.committed_texture_resources)
        ),
    )


def _clone_mesh_pair_for_service_python_fallback(
    mesh: ParsedMesh,
    operation: str,
    reason: str,
    *,
    guard_native_supported: bool = True,
) -> tuple[ParsedMesh, ParsedMesh]:
    if guard_native_supported and not _allow_python_service_clone_fallback(mesh, operation, reason):
        raise RuntimeError("native edit-session clone failed and Python fallback was blocked")
    return clone_mesh_for_editing(mesh), clone_mesh_for_editing(mesh)


def _clone_mesh_for_service_python_fallback(
    mesh: ParsedMesh,
    operation: str,
    reason: str,
    *,
    guard_native_supported: bool = True,
) -> ParsedMesh:
    if guard_native_supported and not _allow_python_service_clone_fallback(mesh, operation, reason):
        raise RuntimeError("native mesh clone failed and Python fallback was blocked")
    cloned = clone_mesh_for_editing(mesh)
    _copy_mesh_validation_metadata(mesh, cloned)
    return cloned


def _service_session_native_clone_supported(mesh: ParsedMesh) -> bool:
    for submesh in mesh.submeshes or ():
        vertex_count = len(submesh.vertices or ())
        for raw_face in submesh.faces or ():
            if len(raw_face) != 3:
                return False
            for raw_index in raw_face:
                try:
                    vertex_index = int(raw_index)
                except (TypeError, ValueError, OverflowError):
                    return False
                if vertex_index < 0 or vertex_index >= vertex_count:
                    return False
    return True


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
    session.selection = snapshot.selection
    session.edit_operations = tuple(snapshot.edit_operations)
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
        ),
    )
    _restore_history_material_state(session, snapshot)
    return _MeshRestoreOutcome(
        snapshot=current_snapshot,
        changed_vertices_by_submesh=dict(changed_vertices_by_submesh),
        native_preview_vertex_update_groups=native_preview_vertex_update_groups,
        native_preview_triangle_groups=native_preview_triangle_groups,
        topology_changed=topology_changed,
        affected_submesh_indices=set(affected) | topology_affected,
        submesh_count_delta=submesh_count_delta,
        submesh_counts=after_signature,
        metrics=metrics,
    )


def _restore_snapshot(session: _MeshEditSession, snapshot: _MeshHistorySnapshot) -> _MeshRestoreOutcome:
    current_mode = session.mode
    current_selection = session.selection
    current_edit_operations = tuple(session.edit_operations)
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
            ),
        )
        session.mode = snapshot.mode
        session.selection = snapshot.selection
        session.edit_operations = tuple(snapshot.edit_operations)
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




def _close_native_editor_session(session: _MeshEditSession) -> None:
    if not session.native_editor_session_ready:
        session.native_history_undo_count = 0
        session.native_history_redo_count = 0
        session.native_history_retained_bytes = 0
        return
    close_native_mesh_editor_session(session.session_id, timeout_seconds=2.0)
    session.native_editor_session_ready = False
    session.native_editor_selection_signature = ()
    session.native_editor_active_stroke_id = ""
    session.native_editor_mesh_signature = ()
    session.native_editor_mesh_dirty = False
    session.native_editor_mesh_dirty_counts = ()
    session.native_history_undo_count = 0
    session.native_history_redo_count = 0
    session.native_history_retained_bytes = 0


def _refresh_native_editor_session_if_mesh_changed(session: _MeshEditSession) -> None:
    if not session.native_editor_session_ready:
        return
    if session.native_editor_mesh_dirty:
        return
    current = _native_editor_mesh_storage_signature(session.working_mesh)
    if current != session.native_editor_mesh_signature:
        _close_native_editor_session(session)








def _sync_native_editor_session_to_working_mesh(session: _MeshEditSession) -> bool:
    if not session.native_editor_mesh_dirty:
        return True
    if not session.native_editor_session_ready:
        return False
    if not export_native_mesh_editor_session_to_mesh(session.working_mesh, session.session_id, timeout_seconds=20.0):
        session.native_editor_session_ready = False
        session.native_editor_selection_signature = ()
        session.native_editor_active_stroke_id = ""
        return False
    refresh_mesh_totals(session.working_mesh)
    session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
    session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
    session.native_editor_mesh_dirty = False
    session.native_editor_mesh_dirty_counts = ()
    return True




def _apply_native_editor_session_selection_operation(
    session: _MeshEditSession,
    selection: MeshEditSelection,
    operation: object,
    *,
    native_selection_payload: Mapping[str, object] | None = None,
    stop_event: object | None = None,
) -> tuple[MeshEditSelection | None, tuple[Mapping[str, object], ...], tuple[str, ...], dict[str, float]]:
    metrics: dict[str, float] = {}
    try:
        _refresh_native_editor_session_if_mesh_changed(session)
        if not session.native_editor_session_ready:
            if session.native_editor_mesh_dirty:
                return None, (), ("Native editor selection failed; resident C++ mesh is dirty and Python mesh state is stale.",), metrics
            open_started = time.perf_counter()
            opened = open_native_mesh_editor_session(
                session.working_mesh,
                session.session_id,
                stop_event=stop_event,  # type: ignore[arg-type]
                timeout_seconds=10.0,
            )
            open_roundtrip_ms = max(0.0, (time.perf_counter() - open_started) * 1000.0)
            if opened is None:
                session.native_editor_session_ready = False
                session.native_editor_selection_signature = ()
                session.native_editor_active_stroke_id = ""
                return None, (), ("Native editor selection session failed to open; Python fallback is disabled while native core is available.",), metrics
            session.native_editor_session_ready = True
            session.native_editor_selection_signature = ()
            session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
            metrics.update(_prefixed_metrics(_native_editor_metrics(opened), "editor_open"))
            metrics["editor_open_roundtrip_ms"] = open_roundtrip_ms
        select_started = time.perf_counter()
        selected = select_native_mesh_editor_session(
            session.session_id,
            native_selection_payload if native_selection_payload is not None else _native_editor_selection_payload(selection),
            operation=operation,
            iterations=1,
            stop_event=stop_event,  # type: ignore[arg-type]
            timeout_seconds=5.0,
        )
        select_roundtrip_ms = max(0.0, (time.perf_counter() - select_started) * 1000.0)
        if selected is None:
            session.native_editor_session_ready = False
            session.native_editor_selection_signature = ()
            session.native_editor_active_stroke_id = ""
            return None, (), ("Native editor selection command failed; Python fallback is disabled while native core is available.",), metrics
        selected_payload = native_mesh_editor_session_selection_from_report(selected)
        if selected_payload is None:
            session.native_editor_session_ready = False
            session.native_editor_selection_signature = ()
            session.native_editor_active_stroke_id = ""
            return None, (), ("Native editor selection command returned an invalid selection report.",), metrics
        result = MeshEditSelection.from_maps(
            vertices_by_submesh=selected_payload.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=selected_payload.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=selected_payload.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=selected_payload.get("source_indices"),  # type: ignore[arg-type]
        )
        native_selection_groups = native_mesh_editor_session_selection_groups_from_report(selected)
        select_metrics = _native_editor_metrics(selected)
        metrics.update(select_metrics)
        metrics.update(_prefixed_metrics(select_metrics, "editor_select"))
        try:
            source_pick_count = selected.get("source_pick_count") if isinstance(selected, Mapping) else None
            if source_pick_count is not None:
                metrics["editor_select_source_pick_count"] = float(source_pick_count)
        except (TypeError, ValueError):
            pass
        metrics["editor_select_roundtrip_ms"] = select_roundtrip_ms
        metrics["editor_select_resident_operation"] = 1.0
        session.native_editor_selection_signature = _mesh_edit_selection_signature(result)
        return result, native_selection_groups, (), metrics
    except RunCancelled:
        session.native_editor_session_ready = False
        raise




def _apply_native_editor_session_geometry_action(
    session: _MeshEditSession,
    command: MeshEditCommand,
    selection: MeshEditSelection,
) -> _NativeEditorApplyResult | None:
    action = command.action.strip().lower()
    if action not in _NATIVE_EDITOR_SESSION_ACTIONS:
        return None
    if not native_mesh_core_available():
        return None
    params = dict(command.params or {})
    stop_event = _stop_event_from_params(params)
    dirty_at_start = session.native_editor_mesh_dirty
    if dirty_at_start and (not session.native_editor_session_ready or (action == "delete" and _truthy(params.get("delete_parts")))):
        return None
    stroke_phase = _native_editor_stroke_phase(params)
    stroke_id = _native_editor_stroke_id(params)
    reuse_selection = (
        stroke_phase in {"update", "end", "cancel"}
        and not isinstance(params.get("_native_selection_payload"), Mapping)
        and bool(stroke_id)
        and stroke_id == session.native_editor_active_stroke_id
        and session.native_editor_session_ready
        and bool(session.native_editor_selection_signature)
    )
    if reuse_selection:
        selection_payload: dict[str, object] = {}
        selection_signature: tuple[object, ...] = ()
    elif _can_reuse_native_stroke_begin_mesh_selection(session, params, selection):
        selection_payload = {}
        selection_signature = session.native_editor_selection_signature
        reuse_selection = True
    else:
        selection_signature = _native_editor_selection_signature_for_apply(selection, params)
        reuse_selection = (
            _can_reuse_native_live_stroke_selection(session, params, selection_signature)
            or _can_reuse_native_stroke_begin_selection(session, params, selection_signature)
        )
        selection_payload = {} if reuse_selection else _native_editor_selection_payload_for_apply(selection, params)
    try:
        _refresh_native_editor_session_if_mesh_changed(session)
        if reuse_selection and not session.native_editor_session_ready:
            reuse_selection = False
            selection_payload = _native_editor_selection_payload_for_apply(selection, params)
            selection_signature = _native_editor_selection_signature_for_apply(selection, params)
        if not session.native_editor_session_ready:
            open_started = time.perf_counter()
            opened = open_native_mesh_editor_session(
                session.working_mesh,
                session.session_id,
                stop_event=stop_event,  # type: ignore[arg-type]
                timeout_seconds=10.0,
            )
            open_roundtrip_ms = max(0.0, (time.perf_counter() - open_started) * 1000.0)
            if opened is None:
                return None
            session.native_editor_session_ready = True
            session.native_editor_selection_signature = ()
            session.native_editor_active_stroke_id = ""
            session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
        else:
            open_roundtrip_ms = 0.0
        select_roundtrip_ms = 0.0
        selection_inlined = not reuse_selection
        edit_payload = _native_editor_edit_payload(action, params)
        if action == "copy_normals":
            source_mesh = params.get("source_mesh")
            if isinstance(source_mesh, ParsedMesh):
                source_normals = native_mesh_editor_source_normals_payload(
                    source_mesh,
                    _native_editor_selection_target_indices(selection),
                )
                if source_normals:
                    edit_payload["source_normals_by_submesh"] = source_normals
        native_before_submesh_count = (
            len(session.native_editor_mesh_dirty_counts)
            if dirty_at_start and session.native_editor_mesh_dirty_counts
            else len(session.working_mesh.submeshes or ())
        )
        native_apply_started = time.perf_counter()
        report = apply_native_mesh_editor_session(
            session.session_id,
            edit_payload,
            selection=selection_payload if selection_inlined else None,
            include_preview_deltas=bool(params.get("_include_preview_deltas", True)),
            binary_preview_deltas=not bool(stroke_phase),
            stroke_phase=stroke_phase,
            stroke_id=stroke_id,
            stop_event=stop_event,  # type: ignore[arg-type]
            timeout_seconds=20.0,
        )
        native_apply_roundtrip_ms = max(0.0, (time.perf_counter() - native_apply_started) * 1000.0)
        if report is None:
            session.native_editor_session_ready = False
            return None
        native_preview_vertex_update_groups = native_mesh_editor_session_preview_vertex_update_groups(report)
        native_preview_triangle_groups = native_mesh_editor_session_preview_triangle_groups(report)
        report_submesh_count = _coerce_index(report.get("submesh_count"))
        native_submesh_counts = (
            _native_editor_report_submesh_counts(report, report_submesh_count)
            if report_submesh_count is not None and report_submesh_count >= 0
            else ()
        )
        current_submesh_count = native_before_submesh_count
        dirty_counts = _native_editor_dirty_counts_from_report(
            report,
            current_submesh_count=current_submesh_count,
        )
        apply_started = time.perf_counter()
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
            return None
        python_apply_ms = max(0.0, (time.perf_counter() - apply_started) * 1000.0)
        if not session.native_editor_mesh_dirty:
            session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
    except RunCancelled:
        session.native_editor_session_ready = False
        session.native_editor_selection_signature = ()
        session.native_editor_active_stroke_id = ""
        session.native_editor_mesh_dirty = False
        session.native_editor_mesh_dirty_counts = ()
        raise
    affected, changed = applied
    metrics = _native_editor_metrics(report)
    stroke_metrics, native_stroke_id, native_stroke_phase, native_stroke_cancelled = _native_editor_stroke_metrics(report)
    metrics.update(stroke_metrics)
    metrics["python_apply_ms"] = python_apply_ms
    metrics["python_apply_deferred"] = 1.0 if session.native_editor_mesh_dirty else 0.0
    metrics["editor_open_roundtrip_ms"] = open_roundtrip_ms
    metrics["editor_select_roundtrip_ms"] = select_roundtrip_ms
    metrics["editor_select_reused"] = 1.0 if reuse_selection else 0.0
    metrics["editor_select_inlined"] = 1.0 if selection_inlined else 0.0
    metrics["native_apply_roundtrip_ms"] = native_apply_roundtrip_ms
    metrics["native_apply_overhead_ms"] = max(
        0.0,
        native_apply_roundtrip_ms - metrics.get("cpp_ms", 0.0) - metrics.get("io_serialization_ms", 0.0),
    )
    if native_stroke_phase == "begin" and native_stroke_id:
        session.native_editor_active_stroke_id = native_stroke_id
    elif native_stroke_phase in {"end", "cancel"}:
        session.native_editor_active_stroke_id = ""
    elif native_stroke_phase == "update" and native_stroke_id:
        session.native_editor_active_stroke_id = native_stroke_id
    report_topology_changed = bool(report.get("topology_changed")) if "topology_changed" in report else None
    if report_topology_changed:
        session.native_editor_selection_signature = ()
    elif selection_inlined:
        session.native_editor_selection_signature = selection_signature
    return _NativeEditorApplyResult(
        set(affected),
        dict(changed),
        metrics,
        native_preview_vertex_update_groups=native_preview_vertex_update_groups,
        native_preview_triangle_groups=native_preview_triangle_groups,
        native_stroke_id=native_stroke_id,
        native_stroke_phase=native_stroke_phase,
        native_stroke_cancelled=native_stroke_cancelled,
        topology_changed=report_topology_changed,
        submesh_count_delta=(
            int(report_submesh_count) - native_before_submesh_count
            if report_submesh_count is not None
            else 0
        ),
        submesh_counts=dirty_counts or native_submesh_counts,
    )










def _native_live_history_snapshot(
    session: _MeshEditSession,
    changed: Mapping[int, object] | None,
    *,
    mode: str,
    selection: MeshEditSelection,
) -> _MeshHistorySnapshot | None:
    deltas: list[_MeshVertexPositionDelta] = []
    for submesh_index in sorted(changed or {}):
        if not 0 <= int(submesh_index) < len(session.working_mesh.submeshes):
            continue
        submesh = session.working_mesh.submeshes[int(submesh_index)]
        raw_delta = getattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, None)
        if hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
            delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)
        delta = _coerce_vertex_position_delta(raw_delta, int(submesh_index), len(submesh.vertices or ()))
        if delta is None:
            dispose_native_mesh_history_delta(raw_delta)
            for captured in deltas:
                if captured.before_positions_binary is not None:
                    dispose_native_mesh_history_delta(captured.before_positions_binary)
            return None
        deltas.append(delta)
    if not deltas:
        return None
    return _MeshHistorySnapshot(
        mesh=None,
        mode=mode,
        selection=selection,
        edit_operations=tuple(session.edit_operations),
        vertex_position_deltas=tuple(deltas),
    )


def _coerce_vertex_position_delta(
    raw_delta: object,
    submesh_index: int,
    vertex_count: int,
) -> _MeshVertexPositionDelta | None:
    if not isinstance(raw_delta, Mapping):
        return None
    indices = _vertex_indices_from_delta_descriptor(raw_delta, vertex_count)
    if indices is None:
        return None
    native_sparse_snapshot_id = str(raw_delta.get("native_sparse_snapshot_id") or "").strip()
    raw_positions_binary = raw_delta.get("before_positions_binary")
    if isinstance(raw_positions_binary, Mapping):
        raw_path = str(raw_positions_binary.get("path") or "").strip()
        count = _coerce_index(raw_positions_binary.get("count"))
        components = _coerce_index(raw_positions_binary.get("components"))
        kind = str(raw_positions_binary.get("type") or "f64").strip().lower()
        if not raw_path or count != len(indices) or components not in (None, 3) or kind != "f64":
            return None
        return _MeshVertexPositionDelta(
            submesh_index=submesh_index,
            vertex_indices=indices,
            positions=(),
            native_sparse_snapshot_id=native_sparse_snapshot_id,
            before_positions_binary={
                "path": raw_path,
                "count": len(indices),
                "components": 3,
                "type": "f64",
            },
        )
    if native_sparse_snapshot_id and raw_delta.get("before_positions") is None:
        return _MeshVertexPositionDelta(
            submesh_index=submesh_index,
            vertex_indices=indices,
            positions=(),
            native_sparse_snapshot_id=native_sparse_snapshot_id,
        )
    positions = native_mesh_history_delta_positions(raw_delta)
    if positions is None or len(positions) != len(indices):
        return None
    return _MeshVertexPositionDelta(
        submesh_index=submesh_index,
        vertex_indices=indices,
        positions=tuple(positions),
        native_sparse_snapshot_id=native_sparse_snapshot_id,
    )


def _vertex_indices_from_delta_descriptor(raw_delta: Mapping[str, object], vertex_count: int) -> Sequence[int] | None:
    try:
        if "vertex_index_start" in raw_delta or "vertex_index_count" in raw_delta:
            raw_start = raw_delta.get("vertex_index_start", -1)
            raw_count = raw_delta.get("vertex_index_count", 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
            if start < 0 or count <= 0 or start + count > max(0, int(vertex_count)):
                return None
            return range(start, start + count)
    except (TypeError, ValueError, OverflowError):
        return None
    raw_indices = raw_delta.get("vertex_indices")
    if not isinstance(raw_indices, (tuple, list, range)):
        return None
    indices: list[int] = []
    seen: set[int] = set()
    for raw_index in raw_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            return None
        if index < 0 or index >= vertex_count or index in seen:
            return None
        indices.append(index)
        seen.add(index)
    if len(indices) != len(raw_indices):
        return None
    return tuple(indices) if not isinstance(raw_indices, range) else raw_indices


def _delta_vertex_indices_payload(vertex_indices: Sequence[int]) -> dict[str, object]:
    if isinstance(vertex_indices, range) and vertex_indices.step == 1 and vertex_indices.start >= 0 and len(vertex_indices) > 0:
        return {
            "vertex_index_start": int(vertex_indices.start),
            "vertex_index_count": len(vertex_indices),
        }
    return {"vertex_indices": tuple(int(index) for index in vertex_indices)}


def _vertex_position(value: object) -> tuple[float, float, float] | None:
    try:
        position = (float(value[0]), float(value[1]), float(value[2]))  # type: ignore[index]
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    if not all(math.isfinite(component) for component in position):
        return None
    return position


def _current_vertex_position_deltas(
    mesh: ParsedMesh,
    template_deltas: tuple[_MeshVertexPositionDelta, ...],
) -> tuple[_MeshVertexPositionDelta, ...]:
    current: list[_MeshVertexPositionDelta] = []
    for delta in template_deltas:
        if not 0 <= delta.submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[delta.submesh_index]
        vertices = submesh.vertices or ()
        positions: list[tuple[float, float, float]] = []
        for index in delta.vertex_indices:
            if not 0 <= index < len(vertices):
                continue
            position = _vertex_position(vertices[index])
            if position is not None:
                positions.append(position)
        if len(positions) == len(delta.vertex_indices):
            current.append(
                _MeshVertexPositionDelta(
                    submesh_index=delta.submesh_index,
                    vertex_indices=delta.vertex_indices,
                    positions=tuple(positions),
                )
            )
    return tuple(current)


def _restore_vertex_position_deltas(
    mesh: ParsedMesh,
    deltas: tuple[_MeshVertexPositionDelta, ...],
) -> tuple[_MeshVertexPositionDelta, ...]:
    restore_positions: dict[int, object] = {}
    for delta in deltas:
        if not 0 <= delta.submesh_index < len(mesh.submeshes):
            continue
        if delta.native_sparse_snapshot_id or delta.before_positions_binary is not None:
            group: dict[str, object] = _delta_vertex_indices_payload(delta.vertex_indices)
            if delta.native_sparse_snapshot_id:
                group["native_sparse_snapshot_id"] = delta.native_sparse_snapshot_id
            if delta.before_positions_binary is not None:
                group["before_positions_binary"] = delta.before_positions_binary
            restore_positions[int(delta.submesh_index)] = group
            continue
        positions_by_vertex: dict[int, tuple[float, float, float]] = {}
        vertex_count = len(mesh.submeshes[delta.submesh_index].vertices or ())
        for index, position in zip(delta.vertex_indices, delta.positions):
            if 0 <= index < vertex_count:
                positions_by_vertex[int(index)] = position
        if positions_by_vertex:
            restore_positions[int(delta.submesh_index)] = positions_by_vertex
    if not restore_positions:
        return ()

    affected: set[int] = set()
    current_deltas: tuple[_MeshVertexPositionDelta, ...] = ()
    native_restore = apply_native_mesh_sparse_vertex_restore(mesh, restore_positions, history_delta=True)
    if native_restore is not None:
        affected = {
            int(submesh_index)
            for submesh_index, changed_vertices in (native_restore or {}).items()
            if changed_vertices
        }
        if affected:
            captured: list[_MeshVertexPositionDelta] = []
            for submesh_index in sorted(affected):
                if not 0 <= submesh_index < len(mesh.submeshes):
                    continue
                submesh = mesh.submeshes[submesh_index]
                raw_delta = getattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, None)
                if hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
                    delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)
                delta = _coerce_vertex_position_delta(raw_delta, submesh_index, len(submesh.vertices or ()))
                if delta is not None:
                    captured.append(delta)
            current_deltas = tuple(captured)
    if not affected:
        if not _allow_python_history_restore_fallback(mesh, deltas, "history.sparse_restore"):
            raise RuntimeError("native sparse history restore failed and Python fallback was blocked")
        current_deltas = _current_vertex_position_deltas(mesh, deltas)
        for delta in deltas:
            submesh_index = int(delta.submesh_index)
            positions_by_vertex = _delta_positions_by_vertex(delta)
            if not positions_by_vertex or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertices = list(submesh.vertices or ())
            if not vertices:
                continue
            changed = False
            for index, position in positions_by_vertex.items():
                vertices[index] = position
                changed = True
            if changed:
                submesh.vertices = vertices
                submesh.vertex_count = len(vertices)
                affected.add(submesh_index)
    if affected:
        native_normals = apply_native_mesh_recalculate_normals(mesh, affected)
        if native_normals is None:
            if not _allow_python_history_restore_fallback(mesh, deltas, "history.restore_normals"):
                raise RuntimeError("native history normal recompute failed and Python fallback was blocked")
            for submesh_index in affected:
                if 0 <= submesh_index < len(mesh.submeshes):
                    recompute_mesh_normals(mesh)
                    break
    return current_deltas


def _allow_python_history_restore_fallback(
    mesh: ParsedMesh,
    deltas: tuple[_MeshVertexPositionDelta, ...],
    operation: str,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not native_mesh_core_available():
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    changed_vertex_count = sum(len(delta.vertex_indices or ()) for delta in deltas)
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python mesh history restore fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
        changed_vertex_count=changed_vertex_count,
    )
    return False


def _allow_python_history_snapshot_fallback(mesh: ParsedMesh, operation: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not native_mesh_core_available():
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python mesh history snapshot fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return False


def _allow_python_service_clone_fallback(mesh: ParsedMesh, operation: str, reason: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not native_mesh_core_available():
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        reason,
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return False


def _allow_python_pose_preview_fallback(mesh: ParsedMesh, operation: str) -> bool:
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python pose preview fallback blocked; native mesh core is required for active Mesh Editor pose preview",
        vertex_count=vertex_count,
        face_count=face_count,
        native_core_available=native_mesh_core_available(),
        native_core_disabled=bool(os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip()),
    )
    return False


def _allow_python_skin_weight_fallback(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    selected_all_submeshes: Iterable[int],
    operation: str,
) -> bool:
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    selected_vertex_count = _selected_skin_weight_vertex_count(mesh, selected_vertices_by_submesh, selected_all_submeshes)
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python skin weight fallback blocked; native mesh core is required for active Mesh Editor skin-weight edits",
        vertex_count=vertex_count,
        face_count=face_count,
        selected_vertex_count=selected_vertex_count,
        native_core_available=native_mesh_core_available(),
        native_core_disabled=bool(os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip()),
    )
    return False


def _delta_positions_by_vertex(delta: _MeshVertexPositionDelta) -> dict[int, tuple[float, float, float]]:
    if delta.positions:
        return {
            int(index): position
            for index, position in zip(delta.vertex_indices, delta.positions)
        }
    raw_delta = {
        **_delta_vertex_indices_payload(delta.vertex_indices),
        "before_positions_binary": delta.before_positions_binary,
    }
    positions = native_mesh_history_delta_positions(raw_delta)
    if positions is None or len(positions) != len(delta.vertex_indices):
        return {}
    return {
        int(index): position
        for index, position in zip(delta.vertex_indices, positions)
    }






def _session_mesh_structure_signature(session: _MeshEditSession) -> tuple[tuple[int, int], ...]:
    if session.native_editor_mesh_dirty and session.native_editor_mesh_dirty_counts:
        return session.native_editor_mesh_dirty_counts
    return _mesh_structure_signature(session.working_mesh)
