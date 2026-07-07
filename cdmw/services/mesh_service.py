from __future__ import annotations

import copy
import math
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

from cdmw.domain.mesh import (
    DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS,
    MESH_EDIT_ACTIONS,
    MESH_EDIT_MODES,
    MeshAnimationClip,
    MeshEditCommand,
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
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
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
    dispose_native_mesh_sparse_vertex_snapshot,
    dispose_native_mesh_submesh_snapshot,
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
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, is_mesh_file, parse_mesh
from cdmw.modding.mesh_roundtrip import roundtrip_mesh_bytes
from cdmw.models import RunCancelled

_PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT = 10_000
_PYTHON_MESH_SELECTION_FALLBACK_FACE_LIMIT = 10_000
_CHANGED_VERTEX_RESULT_TUPLE_LIMIT = 10_000
_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)
_NATIVE_EDITOR_SCREEN_PAYLOAD_KEYS = frozenset({"screen_drag", "screen_brush", "screen_radius", "screen_region"})

_TANGENT_INVALIDATING_ACTIONS = frozenset(MESH_TOPOLOGY_ACTIONS) | frozenset(
    {
        "transform",
        "brush",
        "recalculate_normals",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
        "weighted_normals",
        "copy_normals",
        "uv_transform",
    }
)

_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})
_NATIVE_EDITOR_SESSION_ACTIONS = frozenset({"select"}) | (
    frozenset(MESH_GEOMETRY_ACTIONS) - _LEGACY_DISPLAY_CLEANUP_ACTIONS
)

_NATIVE_MATERIAL_OVERRIDE_KEYS = frozenset(
    {
        "texture_brightness",
        "roughness",
        "metalness",
        "specular",
        "height_scale",
        "emissive_intensity",
        "emissive_color",
        "contrast",
        "saturation",
        "gamma",
        "tint_color",
        "native_material_hints",
        "material_shader_family",
    }
)


@dataclass(slots=True)
class _MeshVertexPositionDelta:
    submesh_index: int
    vertex_indices: Sequence[int]
    positions: tuple[tuple[float, float, float], ...]
    native_sparse_snapshot_id: str = ""
    before_positions_binary: Mapping[str, object] | None = None


@dataclass(slots=True)
class _MeshHistorySnapshot:
    mesh: ParsedMesh | None
    mode: str
    selection: MeshEditSelection
    edit_operations: tuple[object, ...] = ()
    vertex_position_deltas: tuple[_MeshVertexPositionDelta, ...] = ()
    native_submesh_snapshot: Mapping[str, object] | None = None
    native_editor_history: bool = False
    native_editor_stroke_id: str = ""


@dataclass(slots=True)
class _MeshRestoreOutcome:
    snapshot: _MeshHistorySnapshot
    changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = field(default_factory=dict)
    native_preview_vertex_update_groups: tuple[Mapping[str, object], ...] = ()
    native_preview_triangle_groups: tuple[Mapping[str, object], ...] = ()
    topology_changed: bool = False
    affected_submesh_indices: set[int] = field(default_factory=set)
    submesh_count_delta: int = 0
    submesh_counts: tuple[tuple[int, int], ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class _NativeEditorApplyResult:
    affected: set[int]
    changed: dict[int, Sequence[int] | set[int]]
    metrics: dict[str, float] = field(default_factory=dict)
    native_preview_vertex_update_groups: tuple[Mapping[str, object], ...] = ()
    native_preview_triangle_groups: tuple[Mapping[str, object], ...] = ()
    native_stroke_id: str = ""
    native_stroke_phase: str = ""
    native_stroke_cancelled: bool = False
    topology_changed: bool | None = None
    submesh_count_delta: int = 0
    submesh_counts: tuple[tuple[int, int], ...] = ()


@dataclass(slots=True)
class _MeshEditSession:
    session_id: str
    base_mesh: ParsedMesh
    working_mesh: ParsedMesh
    original_data: bytes = b""
    mesh_asset_parse_confidence: str = ""
    mesh_asset_source_hash: str = ""
    mesh_asset_inferred_bone_count: int = 0
    no_op_roundtrip_report: Mapping[str, object] | None = None
    sidecar_warnings: tuple[object, ...] = ()
    edit_operations: tuple[object, ...] = ()
    requires_edit_operations: bool = False
    mode: str = "object"
    selection: MeshEditSelection = field(default_factory=MeshEditSelection)
    skeleton: object | None = None
    skeleton_source: str = ""
    skeleton_descriptor_source: str = ""
    skeleton_variation_source: str = ""
    animation_constraint_source: str = ""
    animation_constraint_evidence: dict[str, object] = field(default_factory=dict)
    socket_source: str = ""
    pose_preview_enabled: bool = False
    selected_bone_index: int = -1
    bone_pose_rotations: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    animation_clip: MeshAnimationClip | None = None
    animation_playback_enabled: bool = False
    animation_time_seconds: float = 0.0
    animation_loop: bool = True
    animation_speed: float = 1.0
    revision: int = 0
    native_editor_session_ready: bool = False
    native_editor_selection_signature: tuple[object, ...] = ()
    native_editor_active_stroke_id: str = ""
    native_editor_mesh_signature: tuple[object, ...] = ()
    native_editor_mesh_dirty: bool = False
    native_editor_mesh_dirty_counts: tuple[tuple[int, int], ...] = ()
    undo_stack: list[_MeshHistorySnapshot] = field(default_factory=list)
    redo_stack: list[_MeshHistorySnapshot] = field(default_factory=list)


def _attach_mesh_asset_status(mesh: ParsedMesh, original_data: bytes, *, run_roundtrip: bool) -> None:
    setattr(mesh, "_cdmw_original_data", bytes(original_data or b""))
    try:
        asset = mesh_asset_from_parsed_mesh(mesh, original_data, source_path=str(mesh.path or ""))
    except Exception:
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "failed")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "")
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
            original_data,
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
        "material_slots",
        "unknown_sections",
    ):
        if hasattr(source, name):
            setattr(target, name, copy.deepcopy(getattr(source, name)))
    for source_submesh, target_submesh in zip(tuple(source.submeshes or ()), tuple(target.submeshes or ())):
        if hasattr(source_submesh, "unknown_fields"):
            setattr(target_submesh, "unknown_fields", copy.deepcopy(getattr(source_submesh, "unknown_fields")))


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


@dataclass(slots=True)
class MeshService:
    settings: object | None = None
    max_history: int = 50
    _sessions: dict[str, _MeshEditSession] = field(default_factory=dict)

    def load_mesh_file(self, path: Path | str, *, run_roundtrip: bool = False) -> ParsedMesh:
        source_path = Path(path).expanduser()
        if not is_mesh_file(str(source_path)):
            raise ValueError(f"Unsupported mesh file type: {source_path.suffix or source_path}")
        data = source_path.read_bytes()
        mesh = parse_mesh(data, str(source_path))
        if not isinstance(mesh, ParsedMesh):
            raise TypeError("mesh parser did not return ParsedMesh")
        if not str(mesh.path or "").strip():
            mesh.path = str(source_path)
        refresh_mesh_totals(mesh)
        _attach_mesh_asset_status(mesh, data, run_roundtrip=run_roundtrip)
        return mesh

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
        working_mesh, base_mesh = _clone_mesh_pair_for_session_open(mesh)
        _copy_mesh_validation_metadata(mesh, working_mesh)
        _copy_mesh_validation_metadata(mesh, base_mesh)
        refresh_mesh_totals(working_mesh)
        self._sessions[session_key] = _MeshEditSession(
            session_id=session_key,
            base_mesh=base_mesh,
            working_mesh=working_mesh,
            original_data=bytes(getattr(mesh, "_cdmw_original_data", b"") or b""),
            mesh_asset_parse_confidence=str(getattr(mesh, "_cdmw_mesh_asset_parse_confidence", "") or ""),
            mesh_asset_source_hash=str(getattr(mesh, "_cdmw_mesh_asset_source_hash", "") or ""),
            mesh_asset_inferred_bone_count=_positive_int(getattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 0)),
            no_op_roundtrip_report=getattr(mesh, "_cdmw_no_op_roundtrip_report", None),
            sidecar_warnings=tuple(getattr(mesh, "_cdmw_sidecar_warnings", ()) or ()),
            edit_operations=tuple(getattr(mesh, "_cdmw_edit_operations", ()) or ()),
            requires_edit_operations=bool(getattr(mesh, "_cdmw_requires_edit_operations", False))
            or (
                bool(getattr(mesh, "_cdmw_imported_from_obj", False))
                and bool(getattr(mesh, "_cdmw_obj_sidecar_present", False))
            ),
            mode=mode,
        )
        return self.session_view(session_key)

    def close_edit_session(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id), None)
        if session is not None:
            _close_native_editor_session(session)
            _clear_history_stack(session.undo_stack)
            _clear_history_stack(session.redo_stack)

    def session_view(self, session_id: str) -> MeshEditSessionView:
        session = self._session(session_id)
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
        )

    def native_editor_mesh_dirty(self, session_id: str) -> bool:
        return bool(self._session(session_id).native_editor_mesh_dirty)

    def working_mesh(self, session_id: str, *, clone: bool = False) -> ParsedMesh:
        session = self._session(session_id)
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

    def replace_working_mesh(self, session_id: str, mesh: ParsedMesh) -> MeshEditSessionView:
        session = self._session(session_id)
        if not isinstance(mesh, ParsedMesh):
            raise TypeError("mesh must be a ParsedMesh")
        if session.native_editor_mesh_dirty and not _sync_native_editor_session_to_working_mesh(session):
            raise RuntimeError("native mesh editor session export failed; Python mesh state is stale")
        if bool(getattr(mesh, "_cdmw_imported_from_obj", False)) and bool(getattr(mesh, "_cdmw_obj_sidecar_present", False)):
            validate_obj_sidecar_source_identity(mesh, session.original_data)
        self._push_history(session, prefer_native=True)
        _clear_history_stack(session.redo_stack)
        _close_native_editor_session(session)
        working_mesh = apply_operation_channels_to_original(session.base_mesh, mesh)
        if session.original_data:
            setattr(working_mesh, "_cdmw_original_data", session.original_data)
        if not str(working_mesh.format or "").strip():
            working_mesh.format = session.base_mesh.format
        if not str(working_mesh.path or "").strip():
            working_mesh.path = session.base_mesh.path
        refresh_mesh_totals(working_mesh)
        session.working_mesh = working_mesh
        session.selection = MeshEditSelection()
        session.sidecar_warnings = tuple(getattr(working_mesh, "_cdmw_sidecar_warnings", ()) or ())
        session.edit_operations = tuple(getattr(working_mesh, "_cdmw_edit_operations", ()) or ())
        session.requires_edit_operations = bool(getattr(working_mesh, "_cdmw_requires_edit_operations", False)) or (
            bool(getattr(working_mesh, "_cdmw_imported_from_obj", False))
            and bool(getattr(working_mesh, "_cdmw_obj_sidecar_present", False))
        )
        session.revision += 1
        return self.session_view(session_id)

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
        return self._select_native_uv_vertices(session, incoming, operation, fallback_event_start)

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
        return self._select_native_uv_vertices(session, incoming, operation, fallback_event_start)

    def _select_native_uv_vertices(
        self,
        session: _MeshEditSession,
        selection: MeshEditSelection,
        operation: object,
        fallback_event_start: int,
    ) -> MeshEditResult:
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
        session.selection = selected
        return self._result(
            session,
            "select",
            diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + select_diagnostics,
            native_selection_groups=native_selection_groups,
            metrics=selection_metrics,
        )

    def skeleton_summary(
        self,
        session_id: str,
        *,
        skeleton_bone_count: int | None = None,
        skeleton_source: str = "",
        skeleton_descriptor_source: str = "",
        skeleton_variation_source: str = "",
        animation_constraint_source: str = "",
        animation_constraint_evidence: dict[str, object] | None = None,
        socket_source: str = "",
    ) -> MeshSkeletonSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor skeleton summary unavailable; Python mesh state is stale")
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return summarize_mesh_skinning(
            session.working_mesh,
            session.selection,
            skeleton=session.skeleton,
            skeleton_bone_count=skeleton_bone_count,
            skeleton_source=skeleton_source or session.skeleton_source,
            skeleton_descriptor_source=skeleton_descriptor_source or session.skeleton_descriptor_source,
            skeleton_variation_source=skeleton_variation_source or session.skeleton_variation_source,
            animation_constraint_source=animation_constraint_source or session.animation_constraint_source,
            animation_constraint_evidence=animation_constraint_evidence or session.animation_constraint_evidence,
            socket_source=socket_source or session.socket_source,
            pose_enabled=session.pose_preview_enabled,
            selected_bone_index=session.selected_bone_index,
            pose_rotations=_effective_pose_rotations(session),
            animation_clip=session.animation_clip,
            animation_enabled=session.animation_playback_enabled,
            animation_time_seconds=session.animation_time_seconds,
            animation_loop=session.animation_loop,
            animation_speed=session.animation_speed,
        )

    def attach_skeleton(
        self,
        session_id: str,
        skeleton: object,
        *,
        source_path: str = "",
        skeleton_descriptor_source: str = "",
        skeleton_variation_source: str = "",
        animation_constraint_source: str = "",
        animation_constraint_evidence: dict[str, object] | None = None,
        socket_source: str = "",
    ) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.skeleton = skeleton
        session.skeleton_source = str(source_path or getattr(skeleton, "path", "") or "")
        session.skeleton_descriptor_source = str(skeleton_descriptor_source or "")
        session.skeleton_variation_source = str(skeleton_variation_source or "")
        session.animation_constraint_source = str(animation_constraint_source or "")
        session.animation_constraint_evidence = dict(animation_constraint_evidence or {})
        session.socket_source = str(socket_source or "")
        return self.skeleton_summary(session_id)

    def set_pose_preview(self, session_id: str, enabled: bool) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.pose_preview_enabled = bool(enabled)
        return self.skeleton_summary(session_id)

    def select_bone(self, session_id: str, bone_index: int) -> MeshSkeletonSummary:
        session = self._session(session_id)
        requested = _coerce_index(bone_index)
        valid_indices = {bone.index for bone in self.skeleton_summary(session_id).bones}
        session.selected_bone_index = requested if requested is not None and requested in valid_indices else -1
        return self.skeleton_summary(session_id)

    def rotate_selected_bone(
        self,
        session_id: str,
        rotation_degrees: Sequence[object],
    ) -> MeshSkeletonSummary:
        session = self._session(session_id)
        selected = session.selected_bone_index
        if selected < 0 or selected not in {bone.index for bone in self.skeleton_summary(session_id).bones}:
            session.selected_bone_index = -1
            return self.skeleton_summary(session_id)
        delta = _rotation_vec3(rotation_degrees)
        if delta is None:
            return self.skeleton_summary(session_id)
        current = session.bone_pose_rotations.get(selected, (0.0, 0.0, 0.0))
        session.bone_pose_rotations[selected] = (
            current[0] + delta[0],
            current[1] + delta[1],
            current[2] + delta[2],
        )
        session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    def reset_pose(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.bone_pose_rotations.clear()
        return self.skeleton_summary(session_id)

    def attach_animation_clip(self, session_id: str, clip: MeshAnimationClip) -> MeshSkeletonSummary:
        if not isinstance(clip, MeshAnimationClip):
            raise TypeError("animation clip must be a MeshAnimationClip")
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_clip = clip
        session.animation_time_seconds = 0.0
        session.animation_playback_enabled = False
        return self.skeleton_summary(session_id)

    def clear_animation_clip(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_clip = None
        session.animation_playback_enabled = False
        session.animation_time_seconds = 0.0
        return self.skeleton_summary(session_id)

    def set_animation_playback(self, session_id: str, enabled: bool) -> MeshSkeletonSummary:
        session = self._session(session_id)
        summary = self.skeleton_summary(session_id)
        session.animation_playback_enabled = bool(enabled and summary.animation_playback.ready)
        if session.animation_playback_enabled:
            session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    def set_animation_loop(self, session_id: str, enabled: bool) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_loop = bool(enabled)
        return self.skeleton_summary(session_id)

    def set_animation_speed(self, session_id: str, speed: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_speed = _coerce_animation_speed(speed)
        return self.skeleton_summary(session_id)

    def seek_animation(self, session_id: str, time_seconds: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_time_seconds = _coerce_time_seconds(time_seconds)
        if session.animation_clip is not None and self.skeleton_summary(session_id).animation_playback.ready:
            session.animation_playback_enabled = True
            session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    def scrub_animation_fraction(self, session_id: str, fraction: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        summary = self.skeleton_summary(session_id)
        duration = float(summary.animation_playback.duration_seconds or 0.0)
        session.animation_time_seconds = duration * _coerce_fraction(fraction)
        if summary.animation_playback.ready:
            session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    def step_animation_frame(self, session_id: str, frames: object = 1) -> MeshSkeletonSummary:
        summary = self.skeleton_summary(session_id)
        frame_rate = float(summary.animation_playback.frame_rate or 0.0)
        if frame_rate <= 0.0:
            frame_rate = 30.0
        try:
            frame_count = float(frames)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            frame_count = 1.0
        if not math.isfinite(frame_count):
            frame_count = 1.0
        return self._step_animation(session_id, frame_count / frame_rate, use_speed=False)

    def step_animation(self, session_id: str, delta_seconds: object) -> MeshSkeletonSummary:
        return self._step_animation(session_id, delta_seconds, use_speed=True)

    def _step_animation(self, session_id: str, delta_seconds: object, *, use_speed: bool) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        delta = _coerce_time_seconds(delta_seconds)
        if use_speed:
            delta *= session.animation_speed
        session.animation_time_seconds = max(
            0.0,
            float(session.animation_time_seconds or 0.0) + delta,
        )
        if session.animation_clip is not None and self.skeleton_summary(session_id).animation_playback.ready:
            session.animation_playback_enabled = True
            session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    def adjust_selected_vertex_bone_weight(self, session_id: str, delta: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor skin weight edit unavailable; Python mesh state is stale")
        bone_index = session.selected_bone_index
        amount = _coerce_weight_delta(delta)
        if bone_index < 0 or amount is None:
            return self.skeleton_summary(session_id)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        vertex_map = session.selection.vertex_map()
        if vertex_map:
            self._push_history(session, prefer_native=True)
            native_result = apply_native_mesh_skin_weights(
                session.working_mesh,
                vertex_map,
                operation="adjust",
                bone_index=bone_index,
                delta=amount,
            )
            if native_result is not None:
                _affected, changed_vertices_by_submesh = native_result
                if any(changed_vertices_by_submesh.values()):
                    session.working_mesh.has_bones = True
                    _clear_history_stack(session.redo_stack)
                    session.revision += 1
                    refresh_mesh_totals(session.working_mesh)
                else:
                    _discard_history_snapshot(session.undo_stack)
                return self.skeleton_summary(session_id)
            _discard_history_snapshot(session.undo_stack)
            if not _allow_python_skin_weight_fallback(session.working_mesh, vertex_map, (), "skin_weights.adjust"):
                raise RuntimeError("native mesh editor skin weight edit unavailable; Python skin weight fallback is disabled")
        changed = False
        pushed = False
        for submesh_index, vertex_indices in vertex_map.items():
            if not 0 <= submesh_index < len(session.working_mesh.submeshes):
                continue
            submesh = session.working_mesh.submeshes[submesh_index]
            operations: list[tuple[int, tuple[int, ...], tuple[float, ...]]] = []
            for vertex_index in _valid_vertex_indices(submesh, vertex_indices):
                current_indices = tuple(submesh.bone_indices[vertex_index]) if vertex_index < len(submesh.bone_indices) else ()
                current_weights = tuple(submesh.bone_weights[vertex_index]) if vertex_index < len(submesh.bone_weights) else ()
                next_indices, next_weights = _nudge_bone_weight(current_indices, current_weights, bone_index, amount)
                if next_indices == current_indices and next_weights == current_weights:
                    continue
                operations.append((vertex_index, next_indices, next_weights))
            if not operations:
                continue
            if not pushed:
                self._push_history(session)
                pushed = True
            _ensure_skinning_rows(submesh)
            for vertex_index, next_indices, next_weights in operations:
                submesh.bone_indices[vertex_index] = next_indices
                submesh.bone_weights[vertex_index] = next_weights
                changed = True
        if changed:
            session.working_mesh.has_bones = True
            invalidate_native_mesh_session_submeshes(session.working_mesh, vertex_map.keys())
            _clear_history_stack(session.redo_stack)
            session.revision += 1
            refresh_mesh_totals(session.working_mesh)
        elif pushed:
            _discard_history_snapshot(session.undo_stack)
        return self.skeleton_summary(session_id)

    def normalize_selected_vertex_weights(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor skin weight edit unavailable; Python mesh state is stale")
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        vertex_map = session.selection.vertex_map()
        if vertex_map:
            self._push_history(session, prefer_native=True)
            native_result = apply_native_mesh_skin_weights(
                session.working_mesh,
                vertex_map,
                operation="normalize",
            )
            if native_result is not None:
                _affected, changed_vertices_by_submesh = native_result
                if any(changed_vertices_by_submesh.values()):
                    session.working_mesh.has_bones = True
                    _clear_history_stack(session.redo_stack)
                    session.revision += 1
                    refresh_mesh_totals(session.working_mesh)
                else:
                    _discard_history_snapshot(session.undo_stack)
                return self.skeleton_summary(session_id)
            _discard_history_snapshot(session.undo_stack)
            if not _allow_python_skin_weight_fallback(session.working_mesh, vertex_map, (), "skin_weights.normalize"):
                raise RuntimeError("native mesh editor skin weight edit unavailable; Python skin weight fallback is disabled")
        changed = False
        pushed = False
        for submesh_index, vertex_indices in vertex_map.items():
            if not 0 <= submesh_index < len(session.working_mesh.submeshes):
                continue
            submesh = session.working_mesh.submeshes[submesh_index]
            operations: list[tuple[int, tuple[int, ...], tuple[float, ...]]] = []
            for vertex_index in _valid_vertex_indices(submesh, vertex_indices):
                current_indices = tuple(submesh.bone_indices[vertex_index]) if vertex_index < len(submesh.bone_indices) else ()
                current_weights = tuple(submesh.bone_weights[vertex_index]) if vertex_index < len(submesh.bone_weights) else ()
                next_indices, next_weights = _normalize_weight_row(current_indices, current_weights)
                if next_indices == current_indices and next_weights == current_weights:
                    continue
                operations.append((vertex_index, next_indices, next_weights))
            if not operations:
                continue
            if not pushed:
                self._push_history(session)
                pushed = True
            _ensure_skinning_rows(submesh)
            for vertex_index, next_indices, next_weights in operations:
                submesh.bone_indices[vertex_index] = next_indices
                submesh.bone_weights[vertex_index] = next_weights
                changed = True
        if changed:
            session.working_mesh.has_bones = True
            invalidate_native_mesh_session_submeshes(session.working_mesh, vertex_map.keys())
            _clear_history_stack(session.redo_stack)
            session.revision += 1
            refresh_mesh_totals(session.working_mesh)
        elif pushed:
            _discard_history_snapshot(session.undo_stack)
        return self.skeleton_summary(session_id)

    def transfer_selected_vertex_weights_from_source(
        self,
        session_id: str,
        *,
        source_skeleton: object | None = None,
    ) -> MeshSkeletonSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor skin weight edit unavailable; Python mesh state is stale")
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        operations_by_submesh: dict[int, list[tuple[int, tuple[int, ...], tuple[float, ...]]]] = {}
        bone_remap = _bone_name_remap(source_skeleton, session.skeleton)
        vertex_map = session.selection.vertex_map()
        selected_submeshes = set(vertex_map) | set(session.selection.source_indices)
        if selected_submeshes:
            invalidate_native_mesh_session_submeshes(session.working_mesh, selected_submeshes)
            self._push_history(session, prefer_native=True)
            native_result = transfer_native_mesh_skin_weights_from_source(
                session.working_mesh,
                session.base_mesh,
                vertex_map,
                session.selection.source_indices,
                bone_remap=bone_remap,
            )
            if native_result is not None:
                _affected, changed_vertices_by_submesh = native_result
                if any(changed_vertices_by_submesh.values()):
                    session.working_mesh.has_bones = True
                    _clear_history_stack(session.redo_stack)
                    session.revision += 1
                    refresh_mesh_totals(session.working_mesh)
                else:
                    _discard_history_snapshot(session.undo_stack)
                return self.skeleton_summary(session_id)
            _discard_history_snapshot(session.undo_stack)
            if not _allow_python_skin_weight_fallback(
                session.working_mesh,
                vertex_map,
                session.selection.source_indices,
                "skin_weights.transfer",
            ):
                raise RuntimeError("native mesh editor skin weight edit unavailable; Python skin weight fallback is disabled")
        for submesh_index in sorted(selected_submeshes):
            if not 0 <= submesh_index < len(session.working_mesh.submeshes):
                continue
            if not 0 <= submesh_index < len(session.base_mesh.submeshes):
                continue
            target = session.working_mesh.submeshes[submesh_index]
            source = session.base_mesh.submeshes[submesh_index]
            source_vertices = source.vertices or ()
            if not source_vertices or not source.bone_indices or not source.bone_weights:
                continue
            operations: list[tuple[int, tuple[int, ...], tuple[float, ...]]] = []
            for vertex_index in _transfer_vertex_indices(target, vertex_map.get(submesh_index, ()), submesh_index in session.selection.source_indices):
                source_index = _source_vertex_index_for_transfer(target, vertex_index, source_vertices)
                if source_index < 0:
                    continue
                next_indices, next_weights = _normalize_weight_row(
                    source.bone_indices[source_index] if source_index < len(source.bone_indices) else (),
                    source.bone_weights[source_index] if source_index < len(source.bone_weights) else (),
                )
                if bone_remap is not None:
                    next_indices, next_weights = _remap_weight_row(next_indices, next_weights, bone_remap)
                current_indices = tuple(target.bone_indices[vertex_index]) if vertex_index < len(target.bone_indices) else ()
                current_weights = tuple(target.bone_weights[vertex_index]) if vertex_index < len(target.bone_weights) else ()
                if next_indices == current_indices and next_weights == current_weights:
                    continue
                operations.append((vertex_index, next_indices, next_weights))
            if operations:
                operations_by_submesh[submesh_index] = operations
        if not operations_by_submesh:
            return self.skeleton_summary(session_id)
        self._push_history(session)
        for submesh_index, operations in operations_by_submesh.items():
            target = session.working_mesh.submeshes[submesh_index]
            _ensure_skinning_rows(target)
            for vertex_index, next_indices, next_weights in operations:
                target.bone_indices[vertex_index] = next_indices
                target.bone_weights[vertex_index] = next_weights
        session.working_mesh.has_bones = True
        invalidate_native_mesh_session_submeshes(session.working_mesh, operations_by_submesh.keys())
        _clear_history_stack(session.redo_stack)
        session.revision += 1
        refresh_mesh_totals(session.working_mesh)
        return self.skeleton_summary(session_id)

    def texture_edit_target(self, session_id: str) -> MeshTextureEditTarget | None:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            return _mesh_texture_edit_target_from_native_summary(
                summarize_native_mesh_editor_session(session.session_id),
                session.selection,
            )
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return selected_mesh_texture_edit_target(session.working_mesh, session.selection)

    def validate_export(
        self,
        session_id: str,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
    ) -> MeshExportValidationReport:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty and not _sync_native_editor_session_to_working_mesh(session):
            raise RuntimeError("native mesh editor session export failed; Python mesh state is stale")
        if skeleton_bone_count is None:
            skeleton_bone_count = _session_validation_skeleton_bone_count(session)
        return validate_mesh_export(
            session.working_mesh,
            original_mesh=session.base_mesh,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
            parse_confidence=session.mesh_asset_parse_confidence,
            source_asset_hash=session.mesh_asset_source_hash,
            no_op_roundtrip_status=_session_roundtrip_status(session),
            no_op_byte_identical=_session_roundtrip_byte_identical(session),
            no_op_unexpected_differences=_session_roundtrip_unexpected_differences(session),
            sidecar_warnings=session.sidecar_warnings,
            edit_operations=session.edit_operations,
            requires_edit_operations=session.requires_edit_operations,
        )

    def rebuild_report(
        self,
        session_id: str,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
        output_path: str = "",
        developer_override: bool = False,
        developer_override_reason: str = "",
    ) -> MeshRebuildReport:
        _result, report = self._rebuild_result(
            session_id,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
            output_path=output_path,
            developer_override=developer_override,
            developer_override_reason=developer_override_reason,
        )
        return report

    def rebuild_asset(
        self,
        session_id: str,
        output_path: Path | str,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
        developer_override: bool = False,
        developer_override_reason: str = "",
    ) -> MeshRebuildReport:
        target = Path(output_path)
        if not str(target).strip():
            raise RuntimeError("mesh rebuild output path is required")
        session = self._session(session_id)
        source_text = str(getattr(session.base_mesh, "path", "") or getattr(session.working_mesh, "path", "") or "").strip()
        if source_text and target.resolve(strict=False) == Path(source_text).resolve(strict=False):
            raise RuntimeError("mesh rebuild output must not overwrite the original source asset")
        result, report = self._rebuild_result(
            session_id,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
            output_path=str(target),
            developer_override=developer_override,
            developer_override_reason=developer_override_reason,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.data)
        return report

    def _rebuild_result(
        self,
        session_id: str,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
        output_path: str = "",
        developer_override: bool = False,
        developer_override_reason: str = "",
    ):
        session = self._session(session_id)
        if not session.original_data:
            raise RuntimeError("mesh rebuild report requires original source bytes")
        validation = self.validate_export(
            session_id,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
        )
        overridden_blockers: tuple[str, ...] = ()
        if not validation.ok:
            overridden_blockers = _developer_override_blocker_codes(
                validation,
                enabled=developer_override,
                output_path=output_path,
            )
            if not overridden_blockers:
                codes = ", ".join(issue.code for issue in validation.blockers[:6]) or "validation blocked rebuild"
                raise RuntimeError(f"mesh rebuild blocked: {codes}")
        if session.edit_operations:
            setattr(session.working_mesh, "_cdmw_edit_operations", tuple(session.edit_operations))
        result = rebuild_mesh_with_report(
            session.working_mesh,
            session.original_data,
            validation_status="developer_override" if overridden_blockers else "passed",
            output_path=output_path,
        )
        override_entries = _developer_override_report_entries(
            developer_override_reason,
            overridden_blockers,
        )
        report = replace(
            result.report,
            validation_status="developer_override" if overridden_blockers else "passed",
            warnings=tuple(issue.code for issue in validation.warnings)
            + tuple(f"developer_override_blocker:{code}" for code in overridden_blockers),
            developer_overrides=tuple(getattr(result.report, "developer_overrides", ()) or ()) + override_entries,
            edit_operations=tuple(dict(operation) if isinstance(operation, Mapping) else operation for operation in session.edit_operations),
            output_path=str(output_path or result.report.output_path or ""),
        )
        return result, report

    def apply_command(self, session_id: str, command: MeshEditCommand | str) -> MeshEditResult:
        session = self._session(session_id)
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

        require_native_editor_session = action in _NATIVE_EDITOR_SESSION_ACTIONS
        if session.native_editor_mesh_dirty and action not in _NATIVE_EDITOR_SESSION_ACTIONS:
            raise RuntimeError(
                f"{action} cannot run while native mesh state is dirty; export/read the native mesh first"
            )

        selection = _command_selection(edit_command)
        if action == "select":
            params = dict(edit_command.params or {})
            selection_metrics: dict[str, float] = {}
            operation = params.get("operation", params.get("selection_operation", "replace"))
            stop_event = _stop_event_from_params(params)
            fallback_event_start = len(native_mesh_core_fallback_events())
            requires_native_screen_selection = isinstance(params.get("_native_screen_selection_payload"), Mapping)
            if native_mesh_core_available():
                native_selection_payload = _native_editor_select_payload_for_params(selection or MeshEditSelection(), params)
                selected, native_selection_groups, select_diagnostics, selection_metrics = _apply_native_editor_session_selection_operation(
                    session,
                    selection or MeshEditSelection(),
                    operation,
                    native_selection_payload=native_selection_payload,
                    stop_event=stop_event,
                )
                if selected is None:
                    return self._result(session, action, status="error", diagnostics=select_diagnostics, metrics=selection_metrics)
                session.selection = selected
                return self._result(
                    session,
                    action,
                    diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + select_diagnostics,
                    native_selection_groups=native_selection_groups,
                    metrics=selection_metrics,
                )
            if requires_native_screen_selection:
                return self._result(
                    session,
                    action,
                    status="error",
                    diagnostics=("Native screen selection is unavailable; Python selection fallback is blocked.",),
                    metrics=selection_metrics,
                )
            if session.native_editor_mesh_dirty:
                return self._result(
                    session,
                    action,
                    status="error",
                    diagnostics=("Native editor selection is unavailable and Python mesh state is stale.",),
                )
            return self._result(
                session,
                action,
                status="error",
                diagnostics=("Native editor selection is unavailable; Python selection fallback is blocked.",),
                metrics=selection_metrics,
            )
        if selection is None:
            if require_native_editor_session:
                selection = session.selection
            else:
                session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
                selection = session.selection

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

        service_started = time.perf_counter()
        if require_native_editor_session and not native_mesh_core_available():
            raise RuntimeError(f"native mesh editor unavailable for {action}; Python mesh-edit fallback is disabled")

        topology_signature_started = time.perf_counter()
        may_change_topology = _command_may_change_topology(action, edit_command, selection)
        topology_before = _session_mesh_structure_signature(session) if may_change_topology else None
        topology_signature_ms = max(0.0, (time.perf_counter() - topology_signature_started) * 1000.0)
        history_mode = session.mode
        history_selection = session.selection
        pushed_history = action in MESH_GEOMETRY_ACTIONS and _records_history(edit_command)
        native_editor_history = pushed_history and require_native_editor_session
        defer_native_live_history = (
            pushed_history and not native_editor_history and _can_defer_native_live_history(action, edit_command)
        )
        history_pushed = False
        command_for_apply = edit_command
        if defer_native_live_history:
            command_for_apply = replace(
                edit_command,
                params={**dict(edit_command.params or {}), "_require_native_history_delta": True},
            )
        elif pushed_history and not native_editor_history:
            self._push_history(session, prefer_native=True)
            history_pushed = True
        if edit_command.mode is not None:
            session.mode = command_mode

        fallback_event_start = len(native_mesh_core_fallback_events())
        used_native_editor_session = False
        native_editor_result: _NativeEditorApplyResult | None = None
        native_preview_vertex_update_groups: tuple[Mapping[str, object], ...] = ()
        native_preview_triangle_groups: tuple[Mapping[str, object], ...] = ()
        native_submesh_counts: tuple[tuple[int, int], ...] = ()
        result_metrics: dict[str, float] = {}
        result_metrics["service_prepare_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        result_metrics["service_topology_signature_ms"] = topology_signature_ms
        dispatch_started = time.perf_counter()
        try:
            native_editor_result = _apply_native_editor_session_geometry_action(session, command_for_apply, selection)
            if native_editor_result is not None:
                affected, changed = native_editor_result.affected, native_editor_result.changed
                native_preview_vertex_update_groups = native_editor_result.native_preview_vertex_update_groups
                native_preview_triangle_groups = native_editor_result.native_preview_triangle_groups
                native_submesh_counts = native_editor_result.submesh_counts
                result_metrics.update(native_editor_result.metrics)
                used_native_editor_session = True
            else:
                if require_native_editor_session:
                    raise RuntimeError(
                        f"native mesh editor session failed for {action}; Python mesh-edit fallback is disabled"
                    )
                if action not in _LEGACY_DISPLAY_CLEANUP_ACTIONS:
                    raise RuntimeError(f"unsupported non-native mesh edit action: {action}")
                affected, changed = apply_mesh_edit_geometry_action(session.working_mesh, command_for_apply, selection)
        except NativeLiveHistoryUnavailable:
            if not defer_native_live_history:
                raise
            fallback_snapshot = _snapshot(session, prefer_native=True)
            self._push_history_snapshot(
                session,
                _MeshHistorySnapshot(
                    mesh=fallback_snapshot.mesh,
                    mode=history_mode,
                    selection=history_selection,
                    edit_operations=fallback_snapshot.edit_operations,
                    vertex_position_deltas=fallback_snapshot.vertex_position_deltas,
                    native_submesh_snapshot=fallback_snapshot.native_submesh_snapshot,
                ),
            )
            history_pushed = True
            try:
                native_editor_result = _apply_native_editor_session_geometry_action(session, edit_command, selection)
                if native_editor_result is not None:
                    affected, changed = native_editor_result.affected, native_editor_result.changed
                    native_preview_vertex_update_groups = native_editor_result.native_preview_vertex_update_groups
                    native_preview_triangle_groups = native_editor_result.native_preview_triangle_groups
                    native_submesh_counts = native_editor_result.submesh_counts
                    result_metrics.update(native_editor_result.metrics)
                    used_native_editor_session = True
                else:
                    if require_native_editor_session:
                        raise RuntimeError(
                            f"native mesh editor session failed for {action}; Python mesh-edit fallback is disabled"
                        )
                    if action not in _LEGACY_DISPLAY_CLEANUP_ACTIONS:
                        raise RuntimeError(f"unsupported non-native mesh edit action: {action}")
                    affected, changed = apply_mesh_edit_geometry_action(session.working_mesh, edit_command, selection)
            except Exception:
                _discard_history_snapshot(session.undo_stack)
                history_pushed = False
                raise
        except Exception:
            if history_pushed:
                _discard_history_snapshot(session.undo_stack)
                history_pushed = False
            raise
        result_metrics["service_dispatch_ms"] = max(0.0, (time.perf_counter() - dispatch_started) * 1000.0)

        topology_compare_started = time.perf_counter()
        if native_editor_result is not None and native_editor_result.topology_changed is not None:
            topology_changed = bool(native_editor_result.topology_changed)
            submesh_count_delta = int(native_editor_result.submesh_count_delta)
        elif topology_before is None:
            topology_changed = False
            submesh_count_delta = 0
        else:
            topology_after = _session_mesh_structure_signature(session)
            topology_changed = topology_after != topology_before
            submesh_count_delta = len(topology_after) - len(topology_before)
        result_metrics["service_topology_compare_ms"] = max(0.0, (time.perf_counter() - topology_compare_started) * 1000.0)
        changed_any = bool(affected) or bool(changed) or topology_changed
        diagnostics: tuple[str, ...] = ()
        finalize_started = time.perf_counter()
        if history_pushed and not changed_any:
            _discard_history_snapshot(session.undo_stack)
            history_pushed = False
        elif changed_any:
            if defer_native_live_history and not history_pushed:
                native_snapshot = _native_live_history_snapshot(
                    session,
                    changed,
                    mode=history_mode,
                    selection=history_selection,
                )
                if native_snapshot is None:
                    raise RuntimeError("native live edit did not provide undo history delta")
                self._push_history_snapshot(session, native_snapshot)
            elif used_native_editor_session and pushed_history and not history_pushed:
                native_stroke_id = native_editor_result.native_stroke_id if native_editor_result is not None else ""
                native_stroke_cancelled = (
                    native_editor_result.native_stroke_cancelled if native_editor_result is not None else False
                )
                if native_stroke_cancelled and native_stroke_id:
                    if (
                        session.undo_stack
                        and session.undo_stack[-1].native_editor_history
                        and session.undo_stack[-1].native_editor_stroke_id == native_stroke_id
                    ):
                        _discard_history_snapshot(session.undo_stack)
                elif (
                    native_stroke_id
                    and session.undo_stack
                    and session.undo_stack[-1].native_editor_history
                    and session.undo_stack[-1].native_editor_stroke_id == native_stroke_id
                ):
                    history_pushed = True
                else:
                    self._push_history_snapshot(
                        session,
                        _MeshHistorySnapshot(
                            mesh=None,
                            mode=history_mode,
                            selection=history_selection,
                            edit_operations=tuple(session.edit_operations),
                            native_editor_history=True,
                            native_editor_stroke_id=native_stroke_id,
                        ),
                    )
                    history_pushed = True
            if used_native_editor_session and session.native_editor_mesh_dirty:
                tangent_indices = {int(index) for index in affected if 0 <= int(index) < len(session.working_mesh.submeshes)}
                tangent_indices.update(
                    int(index) for index in (changed or {}) if 0 <= int(index) < len(session.working_mesh.submeshes)
                )
                if topology_changed and not tangent_indices:
                    tangent_indices.update(range(len(session.working_mesh.submeshes)))
                invalidated_tangents = (
                    tuple(
                        index
                        for index in sorted(tangent_indices)
                        if action in _TANGENT_INVALIDATING_ACTIONS
                        and getattr(session.working_mesh.submeshes[index], "tangents", None)
                    )
                )
            else:
                invalidated_tangents = _invalidate_tangents_after_edit(
                    session.working_mesh,
                    action,
                    affected,
                    changed,
                    topology_changed=topology_changed,
                )
            if invalidated_tangents:
                diagnostics = (
                    f"Invalidated tangents for {len(invalidated_tangents)} part(s); run Generate Tangents before export.",
                )
            _clear_history_stack(session.redo_stack)
            session.revision += 1
            if session.native_editor_mesh_dirty:
                _apply_native_editor_dirty_counts(session)
            else:
                refresh_mesh_totals(session.working_mesh)
            if not used_native_editor_session:
                _close_native_editor_session(session)
            if action == "delete" and _truthy(edit_command.params.get("delete_parts")):
                session.selection = MeshEditSelection()
            elif used_native_editor_session and topology_changed and action == "delete":
                session.selection = MeshEditSelection()
            elif used_native_editor_session and topology_changed and session.native_editor_mesh_dirty:
                pass
            elif action in MESH_TOPOLOGY_ACTIONS or topology_changed:
                session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
            _record_session_edit_operations(session, action, edit_command, affected, changed, topology_changed=topology_changed)
        diagnostics = _append_unique_diagnostics(
            diagnostics,
            _native_blocked_fallback_diagnostics(fallback_event_start),
        )
        result_metrics["service_finalize_ms"] = max(0.0, (time.perf_counter() - finalize_started) * 1000.0)

        result_build_started = time.perf_counter()
        result = self._result(
            session,
            action,
            affected=affected,
            changed=changed,
            native_preview_vertex_update_groups=native_preview_vertex_update_groups,
            native_preview_triangle_groups=native_preview_triangle_groups,
            topology_changed=topology_changed or (action in MESH_TOPOLOGY_ACTIONS and (bool(affected) or bool(changed))),
            submesh_count_delta=submesh_count_delta,
            submesh_counts=native_submesh_counts,
            diagnostics=diagnostics,
            metrics=result_metrics,
        )
        final_metrics = dict(result.metrics)
        final_metrics["service_result_build_ms"] = max(0.0, (time.perf_counter() - result_build_started) * 1000.0)
        final_metrics["service_total_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        return replace(result, metrics=final_metrics)

    def undo(self, session_id: str) -> MeshEditResult:
        service_started = time.perf_counter()
        session = self._session(session_id)
        if not session.undo_stack:
            return self._result(session, "undo", status="noop")
        if session.native_editor_mesh_dirty and not session.undo_stack[-1].native_editor_history:
            raise RuntimeError("native mesh editor undo requires native history; Python mesh state is stale")
        snapshot = session.undo_stack.pop()
        if snapshot.native_editor_history:
            outcome = _restore_native_editor_history(session, snapshot, "undo")
        else:
            outcome = _restore_snapshot(session, snapshot)
        _dispose_history_snapshot(snapshot)
        session.redo_stack.append(outcome.snapshot)
        session.revision += 1
        finalize_started = time.perf_counter()
        if session.native_editor_mesh_dirty:
            _apply_native_editor_dirty_counts(session)
        else:
            refresh_mesh_totals(session.working_mesh)
            session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        metrics = dict(outcome.metrics)
        metrics["service_finalize_ms"] = max(0.0, (time.perf_counter() - finalize_started) * 1000.0)
        result = self._result(
            session,
            "undo",
            affected=outcome.affected_submesh_indices,
            changed=outcome.changed_vertices_by_submesh,
            native_preview_vertex_update_groups=outcome.native_preview_vertex_update_groups,
            native_preview_triangle_groups=outcome.native_preview_triangle_groups,
            topology_changed=outcome.topology_changed,
            submesh_count_delta=outcome.submesh_count_delta,
            submesh_counts=outcome.submesh_counts,
            metrics=metrics,
        )
        final_metrics = dict(result.metrics)
        final_metrics["service_total_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        return replace(result, metrics=final_metrics)

    def redo(self, session_id: str) -> MeshEditResult:
        service_started = time.perf_counter()
        session = self._session(session_id)
        if not session.redo_stack:
            return self._result(session, "redo", status="noop")
        if session.native_editor_mesh_dirty and not session.redo_stack[-1].native_editor_history:
            raise RuntimeError("native mesh editor redo requires native history; Python mesh state is stale")
        snapshot = session.redo_stack.pop()
        if snapshot.native_editor_history:
            outcome = _restore_native_editor_history(session, snapshot, "redo")
        else:
            outcome = _restore_snapshot(session, snapshot)
        _dispose_history_snapshot(snapshot)
        session.undo_stack.append(outcome.snapshot)
        session.revision += 1
        finalize_started = time.perf_counter()
        if session.native_editor_mesh_dirty:
            _apply_native_editor_dirty_counts(session)
        else:
            refresh_mesh_totals(session.working_mesh)
            session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        metrics = dict(outcome.metrics)
        metrics["service_finalize_ms"] = max(0.0, (time.perf_counter() - finalize_started) * 1000.0)
        result = self._result(
            session,
            "redo",
            affected=outcome.affected_submesh_indices,
            changed=outcome.changed_vertices_by_submesh,
            native_preview_vertex_update_groups=outcome.native_preview_vertex_update_groups,
            native_preview_triangle_groups=outcome.native_preview_triangle_groups,
            topology_changed=outcome.topology_changed,
            submesh_count_delta=outcome.submesh_count_delta,
            submesh_counts=outcome.submesh_counts,
            metrics=metrics,
        )
        final_metrics = dict(result.metrics)
        final_metrics["service_total_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        return replace(result, metrics=final_metrics)

    def _session(self, session_id: str) -> _MeshEditSession:
        session = self._sessions.get(str(session_id))
        if session is None:
            raise KeyError(f"Unknown mesh edit session: {session_id}")
        return session

    def _push_history(self, session: _MeshEditSession, *, prefer_native: bool = False) -> None:
        self._push_history_snapshot(session, _snapshot(session, prefer_native=prefer_native))

    def _push_history_snapshot(self, session: _MeshEditSession, snapshot: _MeshHistorySnapshot) -> None:
        session.undo_stack.append(snapshot)
        if len(session.undo_stack) > max(1, int(self.max_history or 1)):
            _discard_history_snapshot(session.undo_stack, 0)

    def _result(
        self,
        session: _MeshEditSession,
        action: str,
        *,
        status: str = "ok",
        affected: set[int] | tuple[int, ...] = (),
        changed: Mapping[int, object] | None = None,
        native_selection_groups: Sequence[Mapping[str, object]] = (),
        native_preview_vertex_update_groups: Sequence[Mapping[str, object]] = (),
        native_preview_triangle_groups: Sequence[Mapping[str, object]] = (),
        topology_changed: bool = False,
        submesh_count_delta: int = 0,
        submesh_counts: Sequence[tuple[int, int]] = (),
        diagnostics: tuple[str, ...] = (),
        metrics: Mapping[str, object] | None = None,
    ) -> MeshEditResult:
        changed_items: list[tuple[int, Sequence[int] | set[int]]] = []
        for raw_submesh_index, indices in sorted((changed or {}).items()):
            try:
                submesh_index = int(raw_submesh_index)
            except (TypeError, ValueError, OverflowError):
                continue
            normalized_indices = _changed_vertex_indices_for_result(indices)
            if normalized_indices:
                changed_items.append((submesh_index, normalized_indices))
        return MeshEditResult(
            action=action,
            status=status,
            revision=session.revision,
            affected_submesh_indices=tuple(sorted(set(affected))),
            changed_vertices_by_submesh=tuple(changed_items),
            native_selection_groups=tuple(dict(group) for group in native_selection_groups),
            native_preview_vertex_update_groups=tuple(dict(group) for group in native_preview_vertex_update_groups),
            native_preview_triangle_groups=tuple(dict(group) for group in native_preview_triangle_groups),
            topology_changed=topology_changed,
            submesh_count_delta=int(submesh_count_delta),
            submesh_counts=tuple((int(vertices), int(faces)) for vertices, faces in submesh_counts),
            diagnostics=diagnostics,
            metrics=_coerce_metrics(metrics),
        )


def _coerce_command(command: MeshEditCommand | str) -> MeshEditCommand:
    if isinstance(command, MeshEditCommand):
        return command
    return MeshEditCommand(action=str(command))


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
            )
        if not _allow_python_history_snapshot_fallback(session.working_mesh, "history.snapshot"):
            raise RuntimeError("native mesh history snapshot capture failed and Python fallback was blocked")
    return _clone_history_snapshot_for_python_fallback(session)


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
    return _MeshRestoreOutcome(
        snapshot=_MeshHistorySnapshot(
            mesh=None,
            mode=current_mode,
            selection=current_selection,
            edit_operations=current_edit_operations,
            native_editor_history=True,
            native_editor_stroke_id=snapshot.native_editor_stroke_id,
        ),
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
    session.mode = snapshot.mode
    session.selection = snapshot.selection
    session.edit_operations = tuple(snapshot.edit_operations)
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


def _changed_vertex_indices_for_result(indices: object) -> Sequence[int] | set[int]:
    if isinstance(indices, range):
        if indices.step != 1 or indices.start < 0 or len(indices) <= 0:
            return ()
        return indices
    if isinstance(indices, Mapping):
        descriptor = _changed_vertex_descriptor_for_result(indices)
        if descriptor is not None:
            return descriptor  # type: ignore[return-value]
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("vertex_index_start", "vertex_index_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            try:
                start = int(indices.get(start_key, -1))
                count = int(indices.get(count_key, 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if start >= 0 and count > 0:
                return range(start, start + count)
        return ()
    if isinstance(indices, set) and len(indices) > _CHANGED_VERTEX_RESULT_TUPLE_LIMIT:
        return indices
    normalized: set[int] = set()
    try:
        iterator = iter(indices)  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_index in iterator:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            normalized.add(index)
    return tuple(sorted(normalized))


def _changed_vertex_descriptor_for_result(indices: Mapping[object, object]) -> dict[str, object] | None:
    for key in ("changed_vertices_binary", "source_vertex_indices_binary"):
        descriptor = indices.get(key)
        if isinstance(descriptor, Mapping) and str(descriptor.get("path") or "").strip():
            result = {str(item_key): item_value for item_key, item_value in descriptor.items()}
            result.setdefault("components", 1)
            result.setdefault("type", "i32")
            return {key: result}
    if str(indices.get("path") or "").strip():
        result = {str(item_key): item_value for item_key, item_value in indices.items()}
        result.setdefault("components", 1)
        result.setdefault("type", "i32")
        return {"changed_vertices_binary": result}
    return None


def _close_native_editor_session(session: _MeshEditSession) -> None:
    if not session.native_editor_session_ready:
        return
    close_native_mesh_editor_session(session.session_id, timeout_seconds=2.0)
    session.native_editor_session_ready = False
    session.native_editor_selection_signature = ()
    session.native_editor_active_stroke_id = ""
    session.native_editor_mesh_signature = ()
    session.native_editor_mesh_dirty = False
    session.native_editor_mesh_dirty_counts = ()


def _refresh_native_editor_session_if_mesh_changed(session: _MeshEditSession) -> None:
    if not session.native_editor_session_ready:
        return
    if session.native_editor_mesh_dirty:
        return
    current = _native_editor_mesh_storage_signature(session.working_mesh)
    if current != session.native_editor_mesh_signature:
        _close_native_editor_session(session)


def _native_editor_report_submesh_counts(report: Mapping[str, object], expected_count: int) -> tuple[tuple[int, int], ...]:
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list) or expected_count < 0:
        return ()
    counts: list[tuple[int, int] | None] = [None] * expected_count
    ordered_counts: list[tuple[int, int]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        index = _coerce_index(raw_item.get("index"))
        vertex_count = _coerce_index(raw_item.get("vertex_count"))
        face_count = _coerce_index(raw_item.get("face_count"))
        if index is None or vertex_count is None or face_count is None:
            continue
        if vertex_count < 0 or face_count < 0:
            continue
        item_counts = (vertex_count, face_count)
        ordered_counts.append(item_counts)
        if 0 <= index < expected_count:
            counts[index] = item_counts
    if any(item is None for item in counts):
        return tuple(ordered_counts) if len(ordered_counts) == expected_count else ()
    return tuple(item for item in counts if item is not None)


def _apply_native_editor_dirty_counts(session: _MeshEditSession) -> None:
    counts = session.native_editor_mesh_dirty_counts
    if not counts:
        return
    session.working_mesh.total_vertices = sum(vertex_count for vertex_count, _ in counts)
    session.working_mesh.total_faces = sum(face_count for _, face_count in counts)


def _require_clean_python_skeleton_state(session: _MeshEditSession) -> None:
    if session.native_editor_mesh_dirty:
        raise RuntimeError("native mesh editor skeleton controls unavailable; Python mesh state is stale")


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


def _native_editor_mesh_storage_signature(mesh: ParsedMesh) -> tuple[object, ...]:
    signature: list[object] = [len(mesh.submeshes or ())]
    for submesh in mesh.submeshes or ():
        for attr_name in (
            "vertices",
            "faces",
            "normals",
            "uvs",
            "tangents",
            "bone_indices",
            "bone_weights",
            "source_vertex_map",
            "source_vertex_offsets",
        ):
            values = getattr(submesh, attr_name, ()) or ()
            signature.extend((len(values), id(values)))
        signature.extend(
            (
                str(getattr(submesh, "name", "") or ""),
                str(getattr(submesh, "material", "") or ""),
                str(getattr(submesh, "texture", "") or ""),
            )
        )
    return tuple(signature)


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


def _native_editor_report_affected_indices(report: Mapping[str, object], submesh_count: int) -> set[int]:
    affected: set[int] = set()
    raw_affected = report.get("affected_submesh_indices")
    if isinstance(raw_affected, list):
        for raw_index in raw_affected:
            index = _coerce_index(raw_index)
            if index is not None and 0 <= index < submesh_count:
                affected.add(index)
    edit_report = report.get("edit_report")
    raw_items = edit_report.get("submeshes") if isinstance(edit_report, Mapping) else None
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            index = _coerce_index(raw_item.get("index"))
            if index is not None and 0 <= index < submesh_count:
                affected.add(index)
    return affected


def _native_editor_report_changed_vertices(
    report: Mapping[str, object],
    submesh_counts: Sequence[tuple[int, int]],
) -> dict[int, Sequence[int] | set[int]]:
    edit_report = report.get("edit_report")
    raw_items = edit_report.get("submeshes") if isinstance(edit_report, Mapping) else None
    if not isinstance(raw_items, list):
        return {}
    changed: dict[int, Sequence[int] | set[int]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _coerce_index(raw_item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(submesh_counts):
            continue
        indices = _changed_vertex_indices_for_result(raw_item)
        if not indices and isinstance(raw_item.get("changed_vertices"), list):
            indices = _changed_vertex_indices_for_result(raw_item.get("changed_vertices"))
        if not indices:
            continue
        bounded = _bounded_native_editor_changed_vertices(indices, submesh_counts[submesh_index][0])
        if bounded:
            changed[submesh_index] = bounded
    return changed


def _bounded_native_editor_changed_vertices(
    indices: object,
    vertex_count: int,
) -> Sequence[int] | set[int]:
    if isinstance(indices, Mapping):
        return indices  # type: ignore[return-value]
    if isinstance(indices, range):
        if indices.step != 1:
            return ()
        start = max(0, int(indices.start))
        stop = min(max(0, int(vertex_count)), int(indices.stop))
        return range(start, stop) if start < stop else ()
    bounded: set[int] = set()
    try:
        iterator = iter(indices)  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_index in iterator:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= index < vertex_count:
            bounded.add(index)
    return bounded


def _native_editor_dirty_counts_from_report(
    report: Mapping[str, object],
    *,
    current_submesh_count: int,
) -> tuple[tuple[int, int], ...]:
    report_submesh_count = _coerce_index(report.get("submesh_count"))
    if report_submesh_count is None or report_submesh_count < 0:
        return ()
    if report_submesh_count != current_submesh_count and not bool(report.get("topology_changed")):
        return ()
    counts = _native_editor_report_submesh_counts(report, report_submesh_count)
    return counts


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


def _native_editor_selection_payload(selection: MeshEditSelection) -> dict[str, object]:
    payload: dict[str, object] = {
        "vertices_by_submesh": selection.vertex_map(),
        "edges_by_submesh": selection.edge_map(),
        "faces_by_submesh": selection.face_map(),
    }
    if selection.source_indices:
        payload["source_indices"] = selection.source_indices
    return payload


def _native_editor_select_payload_for_params(
    selection: MeshEditSelection,
    params: Mapping[str, object],
) -> dict[str, object]:
    raw_payload = params.get("_native_selection_payload")
    payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else _native_editor_selection_payload(selection)
    raw_screen_payload = params.get("_native_screen_selection_payload")
    if isinstance(raw_screen_payload, Mapping):
        _add_native_editor_screen_selection_payload(payload, raw_screen_payload)
    return payload


def _add_native_editor_screen_selection_payload(
    payload: dict[str, object],
    raw_screen_payload: Mapping[str, object],
) -> dict[str, object]:
    raw_screen_brush = raw_screen_payload.get("screen_brush")
    if isinstance(raw_screen_brush, Mapping):
        payload["screen_brush"] = _native_editor_screen_payload(raw_screen_brush)
    raw_screen_region = raw_screen_payload.get("screen_region")
    if isinstance(raw_screen_region, Mapping):
        payload["screen_region"] = _native_editor_screen_payload(raw_screen_region)
    if "falloff" in raw_screen_payload:
        payload["falloff"] = str(raw_screen_payload.get("falloff") or "smooth")
    if "target_mode" in raw_screen_payload:
        payload["target_mode"] = str(raw_screen_payload.get("target_mode") or "vertex")
    if "selection_depth_mode" in raw_screen_payload:
        payload["selection_depth_mode"] = str(raw_screen_payload.get("selection_depth_mode") or "visible")
    return payload


def _native_editor_screen_payload(payload: Mapping[object, object]) -> dict[object, object]:
    return {key: value for key, value in payload.items() if str(key) not in _LEGACY_SCREEN_CAMERA_FIELDS}


def _native_editor_selection_target_indices(selection: MeshEditSelection) -> set[int]:
    result = {_coerce_index(index) for index in selection.source_indices}
    for mapping in (selection.vertex_map(), selection.edge_map(), selection.face_map()):
        result.update(_coerce_index(index) for index in mapping)
    return {index for index in result if index is not None and index >= 0}


def _native_editor_edit_payload(action: str, params: Mapping[str, object]) -> dict[str, object]:
    if action == "transform":
        return _native_editor_transform_payload(params)
    payload: dict[str, object] = {
        "operation": "compact_orphans" if action == "delete_loose_vertices" else action
    }
    for key, value in params.items():
        key_text = str(key)
        if key in {"stop_event", "source_mesh", "stroke_phase", "stroke_id"} or key_text.startswith("_"):
            continue
        json_value = _native_editor_json_value(value)
        if json_value is not None:
            if key_text in _NATIVE_EDITOR_SCREEN_PAYLOAD_KEYS and isinstance(json_value, Mapping):
                payload[key_text] = _native_editor_screen_payload(json_value)
            else:
                payload[key_text] = json_value
    if action == "material_assign":
        material_extra_attrs = _native_editor_material_extra_attrs(params)
        if material_extra_attrs:
            payload["material_extra_attrs"] = material_extra_attrs
    if action in MESH_TOPOLOGY_ACTIONS:
        payload["suppress_vertex_remap_report"] = True
    return payload


def _native_editor_material_extra_attrs(params: Mapping[str, object]) -> dict[str, object]:
    attrs: dict[str, object] = {}
    profile = _first_param(params, "material_authority_profile", "material_profile", "complete_swap_material_profile")
    contract = _first_param(params, "authority_contract", "material_authority_contract")
    if not contract and profile:
        contract = complete_swap_material_authority_contract(profile)
    if profile:
        attrs["cdmw_material_authority_profile"] = str(profile)
    if contract:
        attrs["cdmw_material_authority_contract"] = sanitize_texture_component(contract)
    for param_key, attr_name in (
        ("source_material_name", "cdmw_source_material_name"),
        ("target_material_name", "cdmw_target_material_name"),
        ("slot_kind", "cdmw_material_slot_kind"),
        ("source_texture_set_key", "cdmw_source_texture_set_key"),
        ("route_status", "cdmw_material_route_status"),
        ("route_reason", "cdmw_material_route_reason"),
    ):
        if param_key in params:
            attrs[attr_name] = _material_route_value(params[param_key])
    slot_index = _first_param(params, "target_material_slot_index", "material_slot_index")
    if slot_index is not None:
        attrs["cdmw_target_material_slot_index"] = _optional_int(slot_index)
    overrides: dict[str, object] = {}
    raw_overrides = _first_param(params, "preview_native_material_overrides", "native_material_overrides")
    if isinstance(raw_overrides, Mapping):
        overrides.update({str(key): value for key, value in raw_overrides.items()})
    for key in _NATIVE_MATERIAL_OVERRIDE_KEYS:
        if key in params:
            overrides[key] = params[key]
    if overrides:
        attrs["preview_native_material_overrides"] = overrides
    result: dict[str, object] = {}
    for key, value in attrs.items():
        json_value = _native_editor_json_value(value)
        if json_value is not None:
            result[key] = json_value
    return result


def _first_param(params: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in params:
            return params[key]
    return None


def _material_route_value(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _optional_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return -1


def _native_editor_transform_payload(params: Mapping[str, object]) -> dict[str, object]:
    translate = _native_editor_transform_vec3_payload(
        params.get("translate", params.get("delta", (0.0, 0.0, 0.0))),
        fallback=(0.0, 0.0, 0.0),
    )
    scale = _native_editor_transform_vec3_payload(
        params.get("scale", (1.0, 1.0, 1.0)),
        fallback=(1.0, 1.0, 1.0),
    )
    rotate = _native_editor_transform_vec3_payload(
        params.get("rotate", params.get("rotate_degrees", (0.0, 0.0, 0.0))),
        fallback=(0.0, 0.0, 0.0),
    )
    pivot_value = params.get("pivot")
    payload: dict[str, object] = {
        "operation": "transform",
        "translate": translate,
        "scale": scale,
        "rotate": rotate,
        "pivot": _native_editor_vec3(pivot_value) if pivot_value is not None else (0.0, 0.0, 0.0),
        "pivot_from_selection": pivot_value is None,
        "snap": _native_editor_positive_float(params.get("snap", params.get("snap_increment", 0.0))),
        "mirror_x": bool(params.get("mirror_x", False)) and scale == (1.0, 1.0, 1.0) and rotate == (0.0, 0.0, 0.0),
        "recompute_normals": bool(params.get("recompute_normals", True)),
    }
    axis = str(params.get("axis", params.get("constraint_axis", "")) or "").strip().lower()
    if axis:
        payload["axis"] = axis
    screen_drag = _native_editor_json_value(params.get("screen_drag"))
    if isinstance(screen_drag, Mapping):
        payload["screen_drag"] = _native_editor_screen_payload(screen_drag)
    mirror_pairs = _native_editor_mirror_pairs_by_submesh(params.get("mirror_pairs_by_submesh"))
    if mirror_pairs:
        payload["mirror_pairs_by_submesh"] = mirror_pairs
    return payload


def _native_editor_transform_vec3_payload(
    value: object,
    *,
    fallback: tuple[float, float, float],
) -> object:
    parsed = _native_editor_json_value(value)
    if isinstance(parsed, Mapping):
        return parsed
    if isinstance(parsed, list) and len(parsed) >= 3:
        return tuple(parsed[:3])
    return fallback


def _native_editor_stroke_phase(params: Mapping[str, object]) -> str | None:
    value = params.get("stroke_phase")
    if value is None:
        return None
    text = str(value or "").strip().lower()
    return text or None


def _native_editor_stroke_id(params: Mapping[str, object]) -> str | None:
    value = params.get("stroke_id")
    if value is None:
        return None
    text = str(value or "").strip()
    return text or None


def _mesh_edit_selection_signature(selection: MeshEditSelection) -> tuple[object, ...]:
    return (
        selection.vertices_by_submesh,
        selection.edges_by_submesh,
        selection.faces_by_submesh,
        selection.source_indices,
    )


def _native_editor_selection_payload_for_apply(
    selection: MeshEditSelection,
    params: Mapping[str, object],
) -> dict[str, object]:
    raw_screen_payload = params.get("_native_screen_selection_payload")
    if isinstance(raw_screen_payload, Mapping):
        raw_payload = params.get("_native_selection_payload")
        payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
        return _add_native_editor_binary_vertex_selection_payload(
            _add_native_editor_screen_selection_payload(payload, raw_screen_payload),
            params,
        )
    payload = params.get("_native_selection_payload")
    if isinstance(payload, Mapping):
        return _add_native_editor_binary_vertex_selection_payload(dict(payload), params)
    return _add_native_editor_binary_vertex_selection_payload(_native_editor_selection_payload(selection), params)


def _add_native_editor_binary_vertex_selection_payload(
    payload: dict[str, object],
    params: Mapping[str, object],
) -> dict[str, object]:
    raw = params.get("native_selected_vertices_binary_by_submesh")
    if not isinstance(raw, Mapping):
        return payload
    existing = payload.get("vertices_by_submesh")
    vertices_by_submesh = dict(existing) if isinstance(existing, Mapping) else {}
    for raw_submesh_index, raw_descriptor in raw.items():
        descriptor = _native_editor_json_value(raw_descriptor)
        if isinstance(descriptor, Mapping):
            vertices_by_submesh[str(raw_submesh_index)] = {"selected_vertices_binary": dict(descriptor)}
    if vertices_by_submesh:
        payload["vertices_by_submesh"] = vertices_by_submesh
    return payload


def _native_editor_selection_signature_for_apply(
    selection: MeshEditSelection,
    params: Mapping[str, object],
) -> tuple[object, ...]:
    if isinstance(params.get("_native_screen_selection_payload"), Mapping):
        return ("native-screen", _freeze_native_selection_value(_native_editor_selection_payload_for_apply(selection, params)))
    payload = params.get("_native_selection_payload")
    if isinstance(payload, Mapping):
        return ("native", _freeze_native_selection_value(_add_native_editor_binary_vertex_selection_payload(dict(payload), params)))
    return ("selection", _freeze_native_selection_value(_native_editor_selection_payload_for_apply(selection, params)))


def _freeze_native_selection_value(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_native_selection_value(item)) for key, item in value.items()))
    if isinstance(value, (str, bytes)):
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    try:
        return tuple(_freeze_native_selection_value(item) for item in value)  # type: ignore[arg-type]
    except TypeError:
        return value


def _can_reuse_native_live_stroke_selection(
    session: _MeshEditSession,
    params: Mapping[str, object],
    selection_signature: tuple[object, ...],
) -> bool:
    phase = _native_editor_stroke_phase(params)
    if phase not in {"update", "end", "cancel"}:
        return False
    stroke_id = _native_editor_stroke_id(params)
    if not stroke_id or stroke_id != session.native_editor_active_stroke_id:
        return False
    if phase in {"end", "cancel"} and not isinstance(params.get("_native_selection_payload"), Mapping):
        return bool(session.native_editor_session_ready and session.native_editor_selection_signature)
    return bool(
        session.native_editor_session_ready
        and session.native_editor_selection_signature
        and selection_signature == session.native_editor_selection_signature
    )


def _can_reuse_native_stroke_begin_selection(
    session: _MeshEditSession,
    params: Mapping[str, object],
    selection_signature: tuple[object, ...],
) -> bool:
    if _native_editor_stroke_phase(params) != "begin":
        return False
    if isinstance(params.get("_native_selection_payload"), Mapping):
        return False
    if isinstance(params.get("_native_screen_selection_payload"), Mapping):
        return False
    return bool(
        session.native_editor_session_ready
        and session.native_editor_selection_signature
        and _native_editor_selection_signature_matches_resident(session.native_editor_selection_signature, selection_signature)
    )


def _can_reuse_native_stroke_begin_mesh_selection(
    session: _MeshEditSession,
    params: Mapping[str, object],
    selection: MeshEditSelection,
) -> bool:
    if _native_editor_stroke_phase(params) != "begin":
        return False
    if isinstance(params.get("_native_selection_payload"), Mapping):
        return False
    if isinstance(params.get("_native_screen_selection_payload"), Mapping):
        return False
    if isinstance(params.get("native_selected_vertices_binary_by_submesh"), Mapping):
        return False
    return bool(
        session.native_editor_session_ready
        and session.native_editor_selection_signature
        and session.native_editor_selection_signature == _mesh_edit_selection_signature(selection)
    )


def _native_editor_selection_signature_matches_resident(
    resident_signature: tuple[object, ...],
    selection_signature: tuple[object, ...],
) -> bool:
    if selection_signature == resident_signature:
        return True
    return (
        len(selection_signature) == 2
        and selection_signature[0] == "selection"
        and selection_signature[1] == resident_signature
    )


def _native_editor_vec3(value: object, fallback: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)):
        return fallback
    if isinstance(value, Mapping):
        items = (value.get("x"), value.get("y"), value.get("z"))
    else:
        try:
            items = tuple(value)  # type: ignore[arg-type]
        except TypeError:
            return fallback
    if len(items) < 3:
        return fallback
    result: list[float] = []
    for item in items[:3]:
        if isinstance(item, bool):
            return fallback
        try:
            number = float(item)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return fallback
        if not math.isfinite(number):
            return fallback
        result.append(number)
    return (result[0], result[1], result[2])


def _native_editor_positive_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number > 0.0 else 0.0


def _native_editor_mirror_pairs_by_submesh(value: object) -> dict[str, list[list[int]]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, list[list[int]]] = {}
    for raw_submesh, raw_pairs in value.items():
        submesh_index = _coerce_index(raw_submesh)
        if submesh_index is None or submesh_index < 0 or not isinstance(raw_pairs, Mapping):
            continue
        pairs: list[list[int]] = []
        for raw_left, raw_right in raw_pairs.items():
            left = _coerce_index(raw_left)
            right = _coerce_index(raw_right)
            if left is not None and right is not None and left >= 0 and right >= 0:
                pairs.append([left, right])
        if pairs:
            result[str(submesh_index)] = pairs
    return result


def _native_editor_metrics(report: Mapping[str, object]) -> dict[str, float]:
    raw_metrics = report.get("metrics")
    return _coerce_metrics(raw_metrics if isinstance(raw_metrics, Mapping) else None)


def _native_editor_stroke_metrics(report: Mapping[str, object]) -> tuple[dict[str, float], str, str, bool]:
    raw_stroke = report.get("stroke")
    if not isinstance(raw_stroke, Mapping):
        return {}, "", "", False
    stroke_id = str(raw_stroke.get("stroke_id") or "").strip()
    phase = str(raw_stroke.get("phase") or "").strip().lower()
    update_count = _coerce_index(raw_stroke.get("update_count"))
    metrics = {
        "native_stroke_active": 1.0 if bool(raw_stroke.get("active")) else 0.0,
        "native_stroke_history_coalesced": 1.0 if bool(raw_stroke.get("history_coalesced")) else 0.0,
        "native_stroke_history_cancelled": 1.0 if bool(raw_stroke.get("history_cancelled")) else 0.0,
    }
    if update_count is not None and update_count >= 0:
        metrics["native_stroke_update_count"] = float(update_count)
    return metrics, stroke_id, phase, bool(raw_stroke.get("history_cancelled"))


def _prefixed_metrics(metrics: Mapping[str, float], prefix: str) -> dict[str, float]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def _coerce_metrics(metrics: Mapping[str, object] | None) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in dict(metrics or {}).items():
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed):
            result[str(key)] = parsed
    return result


def _native_editor_json_value(value: object) -> object | None:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return value if math.isfinite(number) else None
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            parsed = _native_editor_json_value(item)
            if parsed is not None:
                result[str(key)] = parsed
        return result
    if isinstance(value, (tuple, list)):
        result: list[object] = []
        for item in value:
            parsed = _native_editor_json_value(item)
            if parsed is not None:
                result.append(parsed)
        return result
    return None


def _can_defer_native_live_history(action: str, command: MeshEditCommand) -> bool:
    if action not in {"transform", "brush"}:
        return False
    return True


def _stop_event_from_params(params: Mapping[str, object]) -> object | None:
    candidate = params.get("stop_event") if isinstance(params, Mapping) else None
    return candidate if callable(getattr(candidate, "is_set", None)) else None


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


def _effective_pose_rotations(session: _MeshEditSession) -> dict[int, tuple[float, float, float]]:
    rotations: dict[int, tuple[float, float, float]] = {}
    if session.pose_preview_enabled and session.animation_clip is not None and session.skeleton is not None:
        bones = summarize_mesh_skinning(
            session.working_mesh,
            session.selection,
            skeleton=session.skeleton,
        ).bones
        rotations.update(
            sample_mesh_animation_pose(
                bones,
                session.animation_clip,
                session.animation_time_seconds,
                loop=session.animation_loop,
            )
        )
    for bone_index, manual in session.bone_pose_rotations.items():
        base = rotations.get(bone_index, (0.0, 0.0, 0.0))
        rotations[bone_index] = (base[0] + manual[0], base[1] + manual[1], base[2] + manual[2])
    return rotations


def _mesh_workspace_summary_from_native(
    report: Mapping[str, object] | None,
    *,
    mesh_format: object,
) -> MeshWorkspaceSummary | None:
    if not isinstance(report, Mapping) or str(report.get("command") or "") != "summary":
        return None
    raw_parts = report.get("submeshes")
    if not isinstance(raw_parts, list):
        return None
    parts: list[MeshPartSummary] = []
    for raw_part in raw_parts:
        if not isinstance(raw_part, Mapping):
            return None
        index = _coerce_index(raw_part.get("index"))
        vertex_count = _coerce_index(raw_part.get("vertex_count"))
        face_count = _coerce_index(raw_part.get("face_count"))
        if index is None or vertex_count is None or face_count is None:
            return None
        parts.append(
            MeshPartSummary(
                index=index,
                name=str(raw_part.get("name") or f"part_{index}"),
                material=str(raw_part.get("material") or ""),
                texture=str(raw_part.get("texture") or ""),
                vertex_count=max(0, vertex_count),
                face_count=max(0, face_count),
                uv_count=max(0, _coerce_index(raw_part.get("uv_count")) or 0),
                normal_count=max(0, _coerce_index(raw_part.get("normal_count")) or 0),
                tangent_count=max(0, _coerce_index(raw_part.get("tangent_count")) or 0),
                selected=bool(raw_part.get("selected")),
                selected_vertex_count=max(0, _coerce_index(raw_part.get("selected_vertex_count")) or 0),
                selected_edge_count=max(0, _coerce_index(raw_part.get("selected_edge_count")) or 0),
                selected_face_count=max(0, _coerce_index(raw_part.get("selected_face_count")) or 0),
                has_skinning=bool(raw_part.get("has_skinning")),
            )
        )
    return MeshWorkspaceSummary(
        mesh_format=str(mesh_format or "").strip().lower(),
        part_count=len(parts),
        vertex_count=sum(part.vertex_count for part in parts),
        face_count=sum(part.face_count for part in parts),
        selected_part_count=sum(1 for part in parts if part.selected),
        parts=tuple(parts),
    )


def _mesh_texture_edit_target_from_native_summary(
    report: Mapping[str, object] | None,
    selection: MeshEditSelection,
) -> MeshTextureEditTarget | None:
    if not isinstance(report, Mapping) or str(report.get("command") or "") != "summary":
        raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
    raw_parts = report.get("submeshes")
    if not isinstance(raw_parts, list):
        raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
    parts: dict[int, Mapping[str, object]] = {}
    ordered_indices: list[int] = []
    for raw_part in raw_parts:
        if not isinstance(raw_part, Mapping):
            raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
        index = _coerce_index(raw_part.get("index"))
        if index is None or index < 0:
            raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
        parts[index] = raw_part
        ordered_indices.append(index)
    candidates: list[int] = []
    candidates.extend(int(index) for index in selection.source_indices)
    candidates.extend(int(index) for index in selection.vertex_map())
    candidates.extend(int(index) for index in selection.edge_map())
    candidates.extend(int(index) for index in selection.face_map())
    if candidates:
        seen: set[int] = set()
        ordered: list[int] = []
        for index in candidates:
            if index in seen:
                continue
            seen.add(index)
            ordered.append(index)
        indices = tuple(ordered)
    else:
        indices = tuple(ordered_indices)
    for index in indices:
        part = parts.get(index)
        if part is None:
            continue
        texture = str(part.get("texture") or "").strip()
        if not texture:
            continue
        extra_attrs = part.get("extra_attrs")
        source_texture_set_key = (
            str(extra_attrs.get("cdmw_source_texture_set_key") or "")
            if isinstance(extra_attrs, Mapping)
            else ""
        )
        return MeshTextureEditTarget(
            submesh_index=index,
            part_name=str(part.get("name") or f"part_{index}"),
            material=str(part.get("material") or ""),
            texture=texture,
            source_texture_set_key=source_texture_set_key,
        )
    return None


def _mesh_uv_summary_from_native(report: Mapping[str, object] | None) -> MeshUvSummary | None:
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "uv_summary":
        return None
    raw_islands = report.get("islands")
    if not isinstance(raw_islands, list):
        return None
    islands: list[MeshUvIslandSummary] = []
    for raw_island in raw_islands:
        if not isinstance(raw_island, Mapping):
            return None
        index = _coerce_index(raw_island.get("index"))
        submesh_index = _coerce_index(raw_island.get("submesh_index"))
        vertex_count = _coerce_index(raw_island.get("vertex_count"))
        face_count = _coerce_index(raw_island.get("face_count"))
        selected_vertex_count = _coerce_index(raw_island.get("selected_vertex_count"))
        selected_face_count = _coerce_index(raw_island.get("selected_face_count"))
        if (
            index is None
            or submesh_index is None
            or vertex_count is None
            or face_count is None
            or selected_vertex_count is None
            or selected_face_count is None
        ):
            return None
        islands.append(
            MeshUvIslandSummary(
                index=index,
                submesh_index=submesh_index,
                part_name=str(raw_island.get("part_name") or f"part_{submesh_index}"),
                material=str(raw_island.get("material") or ""),
                texture=str(raw_island.get("texture") or ""),
                vertex_count=max(0, vertex_count),
                face_count=max(0, face_count),
                uv_min=_vec2(raw_island.get("uv_min")),
                uv_max=_vec2(raw_island.get("uv_max")),
                selected=bool(raw_island.get("selected")),
                selected_vertex_count=max(0, selected_vertex_count),
                selected_face_count=max(0, selected_face_count),
            )
        )
    selected_island_count = _coerce_index(report.get("selected_island_count"))
    return MeshUvSummary(
        island_count=len(islands),
        selected_island_count=sum(1 for island in islands if island.selected) if selected_island_count is None else max(0, selected_island_count),
        islands=tuple(islands),
    )


def _command_selection(command: MeshEditCommand) -> MeshEditSelection | None:
    if command.selection is not None:
        return command.selection
    params = dict(command.params or {})
    keys = {"vertices_by_submesh", "edges_by_submesh", "faces_by_submesh", "source_indices"}
    if not any(key in params for key in keys):
        return None
    return MeshEditSelection.from_maps(
        vertices_by_submesh=params.get("vertices_by_submesh"),  # type: ignore[arg-type]
        edges_by_submesh=params.get("edges_by_submesh"),  # type: ignore[arg-type]
        faces_by_submesh=params.get("faces_by_submesh"),  # type: ignore[arg-type]
        source_indices=params.get("source_indices"),  # type: ignore[arg-type]
    )


def _apply_selection_operation(current: MeshEditSelection, incoming: MeshEditSelection, operation: object) -> MeshEditSelection:
    mode = str(operation or "replace").strip().lower()
    if mode == "replace":
        return incoming
    if mode == "extend":
        mode = "add"
    if mode == "remove":
        mode = "subtract"
    if mode not in {"add", "subtract", "toggle"}:
        return incoming
    return MeshEditSelection.from_maps(
        vertices_by_submesh=_combine_selection_map(current.vertex_map(), incoming.vertex_map(), mode),
        edges_by_submesh=_combine_selection_map(current.edge_map(), incoming.edge_map(), mode),
        faces_by_submesh=_combine_selection_map(current.face_map(), incoming.face_map(), mode),
        source_indices=_combine_selection_values(set(current.source_indices), set(incoming.source_indices), mode),
    )


def _apply_selection_operation_to_mesh(
    mesh: ParsedMesh,
    current: MeshEditSelection,
    incoming: MeshEditSelection,
    operation: object,
    *,
    stop_event: object | None = None,
    metrics_out: dict[str, float] | None = None,
) -> MeshEditSelection:
    mode = str(operation or "replace").strip().lower()
    if mode in {"grow", "shrink", "smooth"}:
        native_selection = apply_native_mesh_selection(
            mesh,
            incoming.vertex_map(),
            selected_edges_by_submesh=incoming.edge_map(),
            selected_faces_by_submesh=incoming.face_map(),
            source_indices=incoming.source_indices,
            operation=mode,
            iterations=1,
            stop_event=stop_event,  # type: ignore[arg-type]
            metrics_out=metrics_out,
        )
        if native_selection is not None:
            return MeshEditSelection.from_maps(vertices_by_submesh=native_selection)
        record_native_mesh_core_fallback(
            f"selection.{mode}.blocked",
            "Native selection edit failed; Python selection expansion fallback is disabled",
            vertex_count=sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in getattr(mesh, "submeshes", ()) or ()),
            face_count=sum(len(getattr(submesh, "faces", ()) or ()) for submesh in getattr(mesh, "submeshes", ()) or ()),
        )
        return current
    native_pruned = prune_native_mesh_selection(
        mesh,
        vertices_by_submesh=incoming.vertex_map(),
        edges_by_submesh=incoming.edge_map(),
        faces_by_submesh=incoming.face_map(),
        source_indices=incoming.source_indices,
        current_vertices_by_submesh=current.vertex_map(),
        current_edges_by_submesh=current.edge_map(),
        current_faces_by_submesh=current.face_map(),
        current_source_indices=current.source_indices,
        selection_operation=operation,
        metrics_out=metrics_out,
    )
    if native_pruned is not None:
        return MeshEditSelection.from_maps(
            vertices_by_submesh=native_pruned.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=native_pruned.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=native_pruned.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=native_pruned.get("source_indices"),  # type: ignore[arg-type]
        )
    if not _allow_python_selection_fallback(mesh, "selection.prune"):
        return _source_only_selection_after_operation(mesh, current, incoming, operation)
    return _prune_selection_to_mesh(mesh, _apply_selection_operation(current, incoming, operation))


def _combine_selection_map(left: dict[int, set[object]], right: dict[int, set[object]], mode: str) -> dict[int, set[object]]:
    result = {submesh: set(values) for submesh, values in left.items()}
    for submesh, values in right.items():
        result[submesh] = _combine_selection_values(result.get(submesh, set()), values, mode)
        if not result[submesh]:
            result.pop(submesh, None)
    return result


def _combine_selection_values(left: set[object], right: set[object], mode: str) -> set[object]:
    result = set(left)
    if mode == "add":
        result.update(right)
    elif mode == "subtract":
        result.difference_update(right)
    elif mode == "toggle":
        for value in right:
            if value in result:
                result.remove(value)
            else:
                result.add(value)
    return result


def _prune_selection_to_mesh(mesh: ParsedMesh, selection: MeshEditSelection) -> MeshEditSelection:
    native_pruned = prune_native_mesh_selection(
        mesh,
        vertices_by_submesh=selection.vertex_map(),
        edges_by_submesh=selection.edge_map(),
        faces_by_submesh=selection.face_map(),
        source_indices=selection.source_indices,
    )
    if native_pruned is not None:
        return MeshEditSelection.from_maps(
            vertices_by_submesh=native_pruned.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=native_pruned.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=native_pruned.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=native_pruned.get("source_indices"),  # type: ignore[arg-type]
        )
    if not _allow_python_selection_fallback(mesh, "selection.prune"):
        return _source_only_selection_for_mesh(mesh, selection.source_indices)

    submeshes = mesh.submeshes or ()
    vertices_by_submesh: dict[int, set[int]] = {}
    edges_by_submesh: dict[int, set[tuple[int, int]]] = {}
    faces_by_submesh: dict[int, set[int]] = {}
    source_indices: set[int] = set()

    for submesh_index, vertices in selection.vertex_map().items():
        if not 0 <= submesh_index < len(submeshes):
            continue
        vertex_count = len(submeshes[submesh_index].vertices or ())
        kept = {index for index in vertices if 0 <= index < vertex_count}
        if kept:
            vertices_by_submesh[submesh_index] = kept

    for submesh_index, edges in selection.edge_map().items():
        if not 0 <= submesh_index < len(submeshes):
            continue
        kept = _valid_selected_edges_for_submesh(submeshes[submesh_index], edges)
        if kept:
            edges_by_submesh[submesh_index] = kept

    for submesh_index, faces in selection.face_map().items():
        if not 0 <= submesh_index < len(submeshes):
            continue
        submesh = submeshes[submesh_index]
        kept = {
            index
            for index in faces
            if 0 <= index < len(submesh.faces or ())
            and len(_valid_face_vertices(submesh.faces[index], len(submesh.vertices or ()))) == 3
        }
        if kept:
            faces_by_submesh[submesh_index] = kept

    for index in selection.source_indices:
        if 0 <= index < len(submeshes):
            source_indices.add(index)

    return MeshEditSelection.from_maps(
        vertices_by_submesh=vertices_by_submesh,
        edges_by_submesh=edges_by_submesh,
        faces_by_submesh=faces_by_submesh,
        source_indices=source_indices,
    )


def _source_only_selection_after_operation(
    mesh: ParsedMesh,
    current: MeshEditSelection,
    incoming: MeshEditSelection,
    operation: object,
) -> MeshEditSelection:
    mode = str(operation or "replace").strip().lower()
    if mode == "extend":
        mode = "add"
    if mode == "remove":
        mode = "subtract"
    if mode not in {"replace", "add", "subtract", "toggle"}:
        mode = "replace"
    source_indices = (
        set(incoming.source_indices)
        if mode == "replace"
        else _combine_selection_values(set(current.source_indices), set(incoming.source_indices), mode)
    )
    return _source_only_selection_for_mesh(mesh, source_indices)


def _source_only_selection_for_mesh(mesh: ParsedMesh, source_indices: Iterable[int]) -> MeshEditSelection:
    submesh_count = len(mesh.submeshes or ())
    valid_sources: set[int] = set()
    for raw_index in source_indices:
        index = _coerce_index(raw_index)
        if index is not None and 0 <= index < submesh_count:
            valid_sources.add(index)
    return MeshEditSelection.from_maps(source_indices=tuple(sorted(valid_sources)))


def _valid_selected_edges_for_submesh(submesh: SubMesh, edges: set[tuple[int, int]]) -> set[tuple[int, int]]:
    vertex_count = len(submesh.vertices or ())
    selected = {
        _edge_key(a, b)
        for a, b in edges
        if 0 <= a < vertex_count and 0 <= b < vertex_count and a != b
    }
    if not selected:
        return set()
    if not submesh.faces:
        return selected
    return selected & _existing_face_edges(submesh)


def _existing_face_edges(submesh: SubMesh) -> set[tuple[int, int]]:
    vertex_count = len(submesh.vertices or ())
    edges: set[tuple[int, int]] = set()
    for face in submesh.faces or ():
        indices = _valid_face_vertices(face, vertex_count)
        if len(indices) == 3:
            a, b, c = indices
            edges.update((_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)))
    return edges


def _valid_face_vertices(face: object, vertex_count: int) -> list[int]:
    if not isinstance(face, (tuple, list)):
        return []
    items = tuple(face or ())
    if len(items) < 3:
        return []
    indices: list[int] = []
    for raw_index in items[:3]:
        vertex_index = _coerce_index(raw_index)
        if vertex_index is None:
            return []
        if vertex_index < 0 or vertex_index >= vertex_count:
            return []
        indices.append(vertex_index)
    return indices


def _coerce_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or any(marker in text for marker in ".eE"):
            return None
        try:
            return int(text, 10)
        except ValueError:
            return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _rotation_vec3(value: Sequence[object]) -> tuple[float, float, float] | None:
    try:
        items = tuple(value)
    except TypeError:
        return None
    if len(items) < 3:
        return None
    result: list[float] = []
    for item in items[:3]:
        if isinstance(item, bool):
            return None
        try:
            number = float(item)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number):
            return None
        result.append(number)
    return (result[0], result[1], result[2])


def _coerce_time_seconds(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return number


def _coerce_fraction(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return min(1.0, max(0.0, number))


def _coerce_animation_speed(value: object) -> float:
    if isinstance(value, bool):
        return 1.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 1.0
    if not math.isfinite(number):
        return 1.0
    return min(4.0, max(0.1, number))


def _coerce_weight_delta(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _ensure_skinning_rows(submesh: SubMesh) -> None:
    vertex_count = len(submesh.vertices or ())
    while len(submesh.bone_indices) < vertex_count:
        submesh.bone_indices.append(())
    while len(submesh.bone_weights) < vertex_count:
        submesh.bone_weights.append(())


def _valid_vertex_indices(submesh: SubMesh, vertex_indices: Iterable[int]) -> tuple[int, ...]:
    vertex_count = len(submesh.vertices or ())
    return tuple(sorted({int(index) for index in vertex_indices if 0 <= int(index) < vertex_count}))


def _transfer_vertex_indices(submesh: SubMesh, selected_vertices: Iterable[int], whole_part: bool) -> Sequence[int]:
    if whole_part:
        return range(len(submesh.vertices or ()))
    return _valid_vertex_indices(submesh, selected_vertices)


def _bone_name_remap(source_skeleton: object | None, target_skeleton: object | None) -> dict[int, int] | None:
    source_names = _bone_names_by_index(source_skeleton)
    target_indices = _bone_indices_by_name(target_skeleton)
    if not source_names or not target_indices:
        return None
    return {source_index: target_indices[name] for source_index, name in source_names.items() if name in target_indices}


def _bone_names_by_index(skeleton: object | None) -> dict[int, str]:
    result: dict[int, str] = {}
    for ordinal, bone in enumerate(tuple(getattr(skeleton, "bones", ()) or ())):
        name = _bone_name(bone)
        if not name:
            continue
        index = _coerce_index(getattr(bone, "index", ordinal))
        result[index if index is not None and index >= 0 else ordinal] = name
    return result


def _bone_indices_by_name(skeleton: object | None) -> dict[str, int]:
    result: dict[str, int] = {}
    for ordinal, bone in enumerate(tuple(getattr(skeleton, "bones", ()) or ())):
        name = _bone_name(bone)
        if not name:
            continue
        index = _coerce_index(getattr(bone, "index", ordinal))
        result[name] = index if index is not None and index >= 0 else ordinal
    return result


def _bone_name(bone: object) -> str:
    return str(getattr(bone, "name", "") or "").strip().lower()


def _source_vertex_index_for_transfer(target: SubMesh, vertex_index: int, source_vertices: Sequence[object]) -> int:
    if 0 <= vertex_index < len(target.source_vertex_map or ()):
        mapped = _coerce_index(target.source_vertex_map[vertex_index])
        if mapped is not None and 0 <= mapped < len(source_vertices):
            return mapped
    target_position = _position3((target.vertices or [])[vertex_index] if 0 <= vertex_index < len(target.vertices or ()) else ())
    if target_position is None:
        return -1
    best_index = -1
    best_distance = math.inf
    for source_index, source_position_raw in enumerate(source_vertices):
        source_position = _position3(source_position_raw)
        if source_position is None:
            continue
        distance = sum((target_position[axis] - source_position[axis]) ** 2 for axis in range(3))
        if distance < best_distance:
            best_distance = distance
            best_index = source_index
    return best_index


def _position3(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    result: list[float] = []
    for component in value[:3]:
        number = _coerce_weight_delta(component)
        if number is None:
            return None
        result.append(number)
    return result[0], result[1], result[2]


def _nudge_bone_weight(
    raw_indices: object,
    raw_weights: object,
    bone_index: int,
    delta: float,
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    pairs = _clean_weight_pairs(raw_indices, raw_weights)
    current = sum(weight for bone, weight in pairs if bone == bone_index)
    target = min(1.0, max(0.0, current + delta))
    others = [(bone, weight) for bone, weight in pairs if bone != bone_index]
    if target > 0.0:
        other_total = sum(weight for _bone, weight in others)
        if other_total > 0.0:
            scale = (1.0 - target) / other_total
            pairs = [(bone, weight * scale) for bone, weight in others] + [(bone_index, target)]
        else:
            pairs = [(bone_index, 1.0)]
    else:
        pairs = others
    return _pack_weight_pairs(pairs, preferred_bone=bone_index)


def _normalize_weight_row(raw_indices: object, raw_weights: object) -> tuple[tuple[int, ...], tuple[float, ...]]:
    return _pack_weight_pairs(_clean_weight_pairs(raw_indices, raw_weights))


def _remap_weight_row(
    raw_indices: object,
    raw_weights: object,
    bone_remap: dict[int, int],
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    pairs = [(bone_remap[bone], weight) for bone, weight in _clean_weight_pairs(raw_indices, raw_weights) if bone in bone_remap]
    return _pack_weight_pairs(pairs)


def _clean_weight_pairs(raw_indices: object, raw_weights: object) -> list[tuple[int, float]]:
    result: dict[int, float] = {}
    for raw_index, raw_weight in zip(_row_tuple(raw_indices), _row_tuple(raw_weights)):
        bone_index = _coerce_index(raw_index)
        weight = _coerce_weight_delta(raw_weight)
        if bone_index is None or bone_index < 0 or weight is None or weight <= 0.0:
            continue
        result[bone_index] = result.get(bone_index, 0.0) + weight
    return sorted(result.items())


def _pack_weight_pairs(
    pairs: list[tuple[int, float]],
    *,
    preferred_bone: int | None = None,
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    positive = [(bone, weight) for bone, weight in pairs if weight > 0.0]
    if not positive:
        return (), ()
    if len(positive) > 4:
        preferred = [(bone, weight) for bone, weight in positive if bone == preferred_bone]
        others = sorted(((bone, weight) for bone, weight in positive if bone != preferred_bone), key=lambda item: item[1], reverse=True)
        positive = (preferred[:1] + others)[:4]
    total = sum(weight for _bone, weight in positive)
    if total <= 0.0:
        return (), ()
    normalized = sorted((bone, weight / total) for bone, weight in positive)
    return tuple(bone for bone, _weight in normalized), tuple(weight for _bone, weight in normalized)


def _row_tuple(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return (value,)


def _edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def _vec2(value: Sequence[object], fallback: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    try:
        parsed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError, IndexError):
        return fallback
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _records_history(command: MeshEditCommand) -> bool:
    value = command.params.get("record_history", command.params.get("history", True))
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _record_session_edit_operations(
    session: _MeshEditSession,
    action: str,
    command: MeshEditCommand,
    affected: Iterable[int],
    changed: Mapping[int, object] | None,
    *,
    topology_changed: bool,
) -> None:
    operation_names = _operation_names_for_command(action, command)
    if not operation_names or topology_changed:
        return
    targets = _operation_target_indices(session, affected, changed)
    if not targets:
        return
    existing = [dict(operation) if isinstance(operation, Mapping) else operation for operation in session.edit_operations]
    for submesh_index in targets:
        if not 0 <= submesh_index < len(session.working_mesh.submeshes):
            continue
        submesh = session.working_mesh.submeshes[submesh_index]
        target_operations = list(operation_names)
        if any(name in {"replace_positions_same_count", "translate_vertices", "scale_vertices", "rotate_vertices"} for name in target_operations):
            if _submesh_channel_changed(session.base_mesh, session.working_mesh, submesh_index, "normals"):
                target_operations.append("replace_normals_same_count")
        for operation_name in dict.fromkeys(target_operations):
            existing.append(
                {
                    "operation": operation_name,
                    "lod_index": 0,
                    "submesh_index": submesh_index,
                    "vertex_count": len(submesh.vertices or ()),
                    "source": str(command.label or action or "Mesh Editor"),
                    "created_by": "Mesh Editor v2",
                    "metadata": {"service_action": action},
                }
            )
    session.edit_operations = tuple(existing)


def _operation_names_for_command(action: str, command: MeshEditCommand) -> tuple[str, ...]:
    if action == "transform":
        params = command.params or {}
        has_translate = _vector_has_value(params.get("translate", params.get("delta")))
        has_scale = _vector_has_non_identity_scale(params.get("scale"))
        has_rotate = _vector_has_value(params.get("rotate", params.get("rotate_degrees")))
        if has_translate and not has_scale and not has_rotate:
            return _with_recomputed_normals("translate_vertices", params)
        if has_scale and not has_translate and not has_rotate:
            return _with_recomputed_normals("scale_vertices", params)
        if has_rotate and not has_translate and not has_scale:
            return _with_recomputed_normals("rotate_vertices", params)
        return _with_recomputed_normals("replace_positions_same_count", params)
    if action == "brush":
        return _with_recomputed_normals("replace_positions_same_count", command.params or {})
    if action in {"recalculate_normals", "flip_normals", "sharpen_normals", "soften_normals", "weighted_normals", "copy_normals"}:
        return ("replace_normals_same_count",)
    if action == "generate_tangents":
        return ("replace_tangents_same_count",)
    if action == "uv_transform":
        return ("replace_uv0_same_count",)
    return ()


def _with_recomputed_normals(operation: str, params: Mapping[str, object]) -> tuple[str, ...]:
    if _truthy(params.get("recompute_normals", True)):
        return (operation, "replace_normals_same_count")
    return (operation,)


def _submesh_channel_changed(base_mesh: ParsedMesh, working_mesh: ParsedMesh, submesh_index: int, channel: str) -> bool:
    if not 0 <= submesh_index < len(base_mesh.submeshes or ()):
        return False
    if not 0 <= submesh_index < len(working_mesh.submeshes or ()):
        return False
    before = base_mesh.submeshes[submesh_index]
    after = working_mesh.submeshes[submesh_index]
    attr = {"normals": "normals", "uv0": "uvs", "tangents": "tangents"}.get(channel, channel)
    return tuple(getattr(before, attr, ()) or ()) != tuple(getattr(after, attr, ()) or ())


def _operation_target_indices(
    session: _MeshEditSession,
    affected: Iterable[int],
    changed: Mapping[int, object] | None,
) -> tuple[int, ...]:
    indices = {_coerce_index(value) for value in affected}
    indices.update(_coerce_index(value) for value in (changed or {}).keys())
    return tuple(sorted(index for index in indices if index is not None and 0 <= index < len(session.working_mesh.submeshes)))


def _vector_has_value(value: object) -> bool:
    vector = _native_editor_transform_vec3_payload(value, fallback=(0.0, 0.0, 0.0))
    if not isinstance(vector, (list, tuple)):
        return False
    try:
        return any(abs(float(component)) > 1e-8 for component in vector[:3])
    except (TypeError, ValueError, OverflowError):
        return False


def _vector_has_non_identity_scale(value: object) -> bool:
    vector = _native_editor_transform_vec3_payload(value, fallback=(1.0, 1.0, 1.0))
    if not isinstance(vector, (list, tuple)):
        return False
    try:
        return any(abs(float(component) - 1.0) > 1e-8 for component in vector[:3])
    except (TypeError, ValueError, OverflowError):
        return False


def _append_unique_diagnostics(existing: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    if not extra:
        return existing
    result: list[str] = []
    seen: set[str] = set()
    for message in (*existing, *extra):
        text = str(message or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return tuple(result)


def _allow_python_selection_fallback(mesh: ParsedMesh, operation: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not native_mesh_core_available():
        return True
    _record_blocked_python_selection_fallback(
        mesh,
        operation,
        "Python mesh selection fallback blocked while native mesh core is available",
    )
    return False


def _record_blocked_python_selection_fallback(mesh: ParsedMesh, operation: str, reason: str) -> None:
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        reason,
        vertex_count=vertex_count,
        face_count=face_count,
    )


def _selected_skin_weight_vertex_count(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    selected_all_submeshes: Iterable[int],
) -> int:
    limit = _PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT
    selected = 0
    selected_all = {index for index in (_coerce_index(value) for value in selected_all_submeshes) if index is not None}
    for submesh_index in selected_all:
        if 0 <= submesh_index < len(mesh.submeshes or ()):
            selected += len(mesh.submeshes[submesh_index].vertices or ())
            if selected > limit:
                return selected
    for vertex_indices in selected_vertices_by_submesh.values():
        try:
            selected += len(vertex_indices)  # type: ignore[arg-type]
        except TypeError:
            return limit + 1
        if selected > limit:
            return selected
    return selected


def _mesh_count_hint(mesh: ParsedMesh, attr: str) -> int:
    count = _diagnostic_count(getattr(mesh, attr, 0))
    return count if count is not None else 0


def _native_blocked_fallback_diagnostics(event_start: int) -> tuple[str, ...]:
    events = native_mesh_core_fallback_events()
    recent = events[event_start:] if 0 <= event_start <= len(events) else events
    messages: list[str] = []
    for event in recent:
        operation = str(event.get("operation") or "").strip()
        if not operation.endswith(".blocked"):
            continue
        label = operation[: -len(".blocked")] or "mesh edit"
        reason = str(event.get("reason") or "").strip()
        vertex_count = _diagnostic_count(event.get("vertex_count"))
        face_count = _diagnostic_count(event.get("face_count"))
        size = f" ({vertex_count:,} vertices, {face_count:,} faces)" if vertex_count is not None and face_count is not None else ""
        suffix = f" {reason}" if reason else ""
        messages.append(f"Edit was not applied: native mesh core failed and Python fallback was blocked for {label}{size}.{suffix}")
    return tuple(messages)


def _diagnostic_count(value: object) -> int | None:
    try:
        count = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return count if count >= 0 else None


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _mesh_structure_signature(mesh: ParsedMesh) -> tuple[tuple[int, int], ...]:
    return tuple((len(submesh.vertices or ()), len(submesh.faces or ())) for submesh in mesh.submeshes or ())


def _session_mesh_structure_signature(session: _MeshEditSession) -> tuple[tuple[int, int], ...]:
    if session.native_editor_mesh_dirty and session.native_editor_mesh_dirty_counts:
        return session.native_editor_mesh_dirty_counts
    return _mesh_structure_signature(session.working_mesh)


def _command_may_change_topology(action: str, command: MeshEditCommand, selection: MeshEditSelection) -> bool:
    if action in MESH_TOPOLOGY_ACTIONS:
        return True
    if action == "generate_tangents":
        return True
    if action in {"material_assign", "material_copy"}:
        return bool(selection.face_map())
    if action == "uv_transform":
        return _truthy(command.params.get("auto_uv")) and _truthy(
            command.params.get("allow_topology_change", command.params.get("confirm_topology_change", False))
        )
    return False


def _invalidate_tangents_after_edit(
    mesh: ParsedMesh,
    action: str,
    affected: set[int] | tuple[int, ...],
    changed: Mapping[int, object] | None,
    *,
    topology_changed: bool,
) -> tuple[int, ...]:
    if action not in _TANGENT_INVALIDATING_ACTIONS:
        return ()
    indices = {int(index) for index in affected if 0 <= int(index) < len(mesh.submeshes)}
    indices.update(int(index) for index in (changed or {}) if 0 <= int(index) < len(mesh.submeshes))
    if topology_changed and not indices:
        indices.update(range(len(mesh.submeshes)))
    invalidated: list[int] = []
    for index in sorted(indices):
        submesh = mesh.submeshes[index]
        if getattr(submesh, "tangents", None):
            submesh.tangents = []
            if getattr(submesh, "tangent_signs", None):
                submesh.tangent_signs = []
            if hasattr(submesh, "tangent_face_corner_report"):
                delattr(submesh, "tangent_face_corner_report")
            invalidated.append(index)
    return tuple(invalidated)


def _required_mode(action: str) -> str:
    if action == "brush":
        return "sculpt"
    if action in MESH_TOPOLOGY_ACTIONS or action in {
        "recalculate_normals",
        "generate_tangents",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
        "weighted_normals",
        "copy_normals",
        "uv_transform",
        "material_assign",
        "material_copy",
    }:
        return "edit"
    return ""


def _mode(value: object) -> str:
    mode = str(value or "object").strip().lower()
    if mode not in MESH_EDIT_MODES:
        raise ValueError(f"Unsupported mesh edit mode: {value!r}")
    return mode
