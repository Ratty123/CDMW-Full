from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4

from cdmw.domain.mesh import (
    MESH_EDIT_ACTIONS,
    MESH_EDIT_MODES,
    MeshAnimationClip,
    MeshEditCommand,
    MeshEditResult,
    MeshEditSelection,
    MeshEditSessionView,
    MeshCompareSummary,
    MeshExportValidationReport,
    MeshSkeletonSummary,
    MeshTextureEditTarget,
    MeshUvSummary,
    MeshWorkspaceSummary,
    compare_meshes,
    mesh_pose_deformed_vertices,
    sample_mesh_animation_pose,
    mesh_uv_lasso_selection,
    mesh_uv_region_selection,
    selected_mesh_texture_edit_target,
    summarize_mesh_skinning,
    summarize_mesh_uvs,
    summarize_mesh_workspace,
    validate_mesh_export,
)
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_deformer import recompute_mesh_normals
from cdmw.modding.mesh_edit_ops import (
    MESH_GEOMETRY_ACTIONS,
    MESH_TOPOLOGY_ACTIONS,
    apply_mesh_edit_geometry_action,
    refresh_mesh_totals,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, is_mesh_file, parse_mesh


@dataclass(slots=True)
class _MeshHistorySnapshot:
    mesh: ParsedMesh
    mode: str
    selection: MeshEditSelection


@dataclass(slots=True)
class _MeshEditSession:
    session_id: str
    base_mesh: ParsedMesh
    working_mesh: ParsedMesh
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
    undo_stack: list[_MeshHistorySnapshot] = field(default_factory=list)
    redo_stack: list[_MeshHistorySnapshot] = field(default_factory=list)


@dataclass(slots=True)
class MeshService:
    settings: object | None = None
    max_history: int = 50
    _sessions: dict[str, _MeshEditSession] = field(default_factory=dict)

    def load_mesh_file(self, path: Path | str) -> ParsedMesh:
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
        working_mesh = clone_mesh_for_editing(mesh)
        refresh_mesh_totals(working_mesh)
        self._sessions[session_key] = _MeshEditSession(
            session_id=session_key,
            base_mesh=clone_mesh_for_editing(mesh),
            working_mesh=working_mesh,
            mode=mode,
        )
        return self.session_view(session_key)

    def close_edit_session(self, session_id: str) -> None:
        self._sessions.pop(str(session_id), None)

    def session_view(self, session_id: str) -> MeshEditSessionView:
        session = self._session(session_id)
        refresh_mesh_totals(session.working_mesh)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return MeshEditSessionView(
            session_id=session.session_id,
            mode=session.mode,
            revision=session.revision,
            selection=session.selection,
            submesh_count=len(session.working_mesh.submeshes),
            vertex_count=int(session.working_mesh.total_vertices or 0),
            face_count=int(session.working_mesh.total_faces or 0),
            undo_count=len(session.undo_stack),
            redo_count=len(session.redo_stack),
        )

    def working_mesh(self, session_id: str, *, clone: bool = False) -> ParsedMesh:
        mesh = self._session(session_id).working_mesh
        return clone_mesh_for_editing(mesh) if clone else mesh

    def pose_preview_mesh(self, session_id: str) -> ParsedMesh:
        session = self._session(session_id)
        mesh = clone_mesh_for_editing(session.working_mesh)
        pose_rotations = _effective_pose_rotations(session)
        if not (session.pose_preview_enabled and session.skeleton is not None and pose_rotations):
            return mesh
        deformed = mesh_pose_deformed_vertices(mesh, session.skeleton, pose_rotations)
        for submesh_index, vertices in deformed.items():
            if 0 <= submesh_index < len(mesh.submeshes):
                mesh.submeshes[submesh_index].vertices = list(vertices)
        if deformed:
            recompute_mesh_normals(mesh)
            refresh_mesh_totals(mesh)
        return mesh

    def base_mesh(self, session_id: str, *, clone: bool = False) -> ParsedMesh:
        mesh = self._session(session_id).base_mesh
        return clone_mesh_for_editing(mesh) if clone else mesh

    def workspace_summary(self, session_id: str) -> MeshWorkspaceSummary:
        session = self._session(session_id)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return summarize_mesh_workspace(session.working_mesh, session.selection)

    def compare_summary(self, session_id: str) -> MeshCompareSummary:
        session = self._session(session_id)
        return compare_meshes(session.base_mesh, session.working_mesh)

    def uv_summary(self, session_id: str) -> MeshUvSummary:
        session = self._session(session_id)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
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
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        incoming = mesh_uv_region_selection(session.working_mesh, _vec2(uv_min), _vec2(uv_max))
        session.selection = _prune_selection_to_mesh(
            session.working_mesh,
            _apply_selection_operation(session.selection, incoming, operation),
        )
        return self._result(session, "select")

    def select_uv_lasso(
        self,
        session_id: str,
        points: Iterable[Sequence[object]],
        *,
        operation: str = "replace",
    ) -> MeshEditResult:
        session = self._session(session_id)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        incoming = mesh_uv_lasso_selection(session.working_mesh, tuple(_vec2(point) for point in points))
        session.selection = _prune_selection_to_mesh(
            session.working_mesh,
            _apply_selection_operation(session.selection, incoming, operation),
        )
        return self._result(session, "select")

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
        session.bone_pose_rotations.clear()
        return self.skeleton_summary(session_id)

    def attach_animation_clip(self, session_id: str, clip: MeshAnimationClip) -> MeshSkeletonSummary:
        if not isinstance(clip, MeshAnimationClip):
            raise TypeError("animation clip must be a MeshAnimationClip")
        session = self._session(session_id)
        session.animation_clip = clip
        session.animation_time_seconds = 0.0
        session.animation_playback_enabled = False
        return self.skeleton_summary(session_id)

    def clear_animation_clip(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
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
        session.animation_loop = bool(enabled)
        return self.skeleton_summary(session_id)

    def set_animation_speed(self, session_id: str, speed: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        session.animation_speed = _coerce_animation_speed(speed)
        return self.skeleton_summary(session_id)

    def seek_animation(self, session_id: str, time_seconds: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
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
        bone_index = session.selected_bone_index
        amount = _coerce_weight_delta(delta)
        if bone_index < 0 or amount is None:
            return self.skeleton_summary(session_id)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        changed = False
        pushed = False
        for submesh_index, vertex_indices in session.selection.vertex_map().items():
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
            session.redo_stack.clear()
            session.revision += 1
            refresh_mesh_totals(session.working_mesh)
        elif pushed:
            session.undo_stack.pop()
        return self.skeleton_summary(session_id)

    def normalize_selected_vertex_weights(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        changed = False
        pushed = False
        for submesh_index, vertex_indices in session.selection.vertex_map().items():
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
            session.redo_stack.clear()
            session.revision += 1
            refresh_mesh_totals(session.working_mesh)
        elif pushed:
            session.undo_stack.pop()
        return self.skeleton_summary(session_id)

    def transfer_selected_vertex_weights_from_source(
        self,
        session_id: str,
        *,
        source_skeleton: object | None = None,
    ) -> MeshSkeletonSummary:
        session = self._session(session_id)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        operations_by_submesh: dict[int, list[tuple[int, tuple[int, ...], tuple[float, ...]]]] = {}
        bone_remap = _bone_name_remap(source_skeleton, session.skeleton)
        vertex_map = session.selection.vertex_map()
        selected_submeshes = set(vertex_map) | set(session.selection.source_indices)
        for submesh_index in sorted(selected_submeshes):
            if not 0 <= submesh_index < len(session.working_mesh.submeshes):
                continue
            if not 0 <= submesh_index < len(session.base_mesh.submeshes):
                continue
            target = session.working_mesh.submeshes[submesh_index]
            source = session.base_mesh.submeshes[submesh_index]
            source_vertices = tuple(source.vertices or ())
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
        session.redo_stack.clear()
        session.revision += 1
        refresh_mesh_totals(session.working_mesh)
        return self.skeleton_summary(session_id)

    def texture_edit_target(self, session_id: str) -> MeshTextureEditTarget | None:
        session = self._session(session_id)
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
        if skeleton_bone_count is None and session.skeleton is not None:
            skeleton_bone_count = len(tuple(getattr(session.skeleton, "bones", ()) or ()))
        return validate_mesh_export(
            session.working_mesh,
            original_mesh=session.base_mesh,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
        )

    def apply_command(self, session_id: str, command: MeshEditCommand | str) -> MeshEditResult:
        session = self._session(session_id)
        edit_command = _coerce_command(command)
        action = str(edit_command.action or "").strip().lower()
        if action not in MESH_EDIT_ACTIONS:
            raise ValueError(f"Unsupported mesh edit action: {edit_command.action!r}")

        if action == "set_mode":
            session.mode = _mode(edit_command.mode or edit_command.params.get("mode", session.mode))
            return self._result(session, action)

        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        selection = _command_selection(edit_command)
        if action == "select":
            selection = _prune_selection_to_mesh(session.working_mesh, selection or MeshEditSelection())
            session.selection = _prune_selection_to_mesh(
                session.working_mesh,
                _apply_selection_operation(
                    session.selection,
                    selection,
                    edit_command.params.get("operation", edit_command.params.get("selection_operation", "replace")),
                ),
            )
            return self._result(session, action)
        selection = selection if selection is not None else session.selection

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

        topology_before = _mesh_structure_signature(session.working_mesh) if action in MESH_GEOMETRY_ACTIONS else None
        pushed_history = action in MESH_GEOMETRY_ACTIONS and _records_history(edit_command)
        if pushed_history:
            self._push_history(session)
        if edit_command.mode is not None:
            session.mode = command_mode

        try:
            affected, changed = apply_mesh_edit_geometry_action(session.working_mesh, edit_command, selection)
        except Exception:
            if pushed_history:
                session.undo_stack.pop()
            raise

        topology_changed = topology_before is not None and _mesh_structure_signature(session.working_mesh) != topology_before
        changed_any = bool(affected) or bool(changed) or topology_changed
        if pushed_history and not changed_any:
            session.undo_stack.pop()
        elif changed_any:
            session.redo_stack.clear()
            session.revision += 1
            refresh_mesh_totals(session.working_mesh)
            session.selection = (
                MeshEditSelection()
                if action == "delete" and _truthy(edit_command.params.get("delete_parts"))
                else _prune_selection_to_mesh(session.working_mesh, session.selection)
            )

        return self._result(
            session,
            action,
            affected=affected,
            changed=changed,
            topology_changed=topology_changed or (action in MESH_TOPOLOGY_ACTIONS and (bool(affected) or bool(changed))),
        )

    def undo(self, session_id: str) -> MeshEditResult:
        session = self._session(session_id)
        if not session.undo_stack:
            return self._result(session, "undo", status="noop")
        session.redo_stack.append(_snapshot(session))
        _restore_snapshot(session, session.undo_stack.pop())
        session.revision += 1
        refresh_mesh_totals(session.working_mesh)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return self._result(session, "undo")

    def redo(self, session_id: str) -> MeshEditResult:
        session = self._session(session_id)
        if not session.redo_stack:
            return self._result(session, "redo", status="noop")
        session.undo_stack.append(_snapshot(session))
        _restore_snapshot(session, session.redo_stack.pop())
        session.revision += 1
        refresh_mesh_totals(session.working_mesh)
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return self._result(session, "redo")

    def _session(self, session_id: str) -> _MeshEditSession:
        session = self._sessions.get(str(session_id))
        if session is None:
            raise KeyError(f"Unknown mesh edit session: {session_id}")
        return session

    def _push_history(self, session: _MeshEditSession) -> None:
        session.undo_stack.append(_snapshot(session))
        if len(session.undo_stack) > max(1, int(self.max_history or 1)):
            del session.undo_stack[0]

    def _result(
        self,
        session: _MeshEditSession,
        action: str,
        *,
        status: str = "ok",
        affected: set[int] | tuple[int, ...] = (),
        changed: dict[int, set[int]] | None = None,
        topology_changed: bool = False,
        diagnostics: tuple[str, ...] = (),
    ) -> MeshEditResult:
        changed_items = tuple(
            (submesh_index, tuple(sorted(indices)))
            for submesh_index, indices in sorted((changed or {}).items())
            if indices
        )
        return MeshEditResult(
            action=action,
            status=status,
            revision=session.revision,
            affected_submesh_indices=tuple(sorted(set(affected))),
            changed_vertices_by_submesh=changed_items,
            topology_changed=topology_changed,
            diagnostics=diagnostics,
        )


def _coerce_command(command: MeshEditCommand | str) -> MeshEditCommand:
    if isinstance(command, MeshEditCommand):
        return command
    return MeshEditCommand(action=str(command))


def _snapshot(session: _MeshEditSession) -> _MeshHistorySnapshot:
    return _MeshHistorySnapshot(
        mesh=clone_mesh_for_editing(session.working_mesh),
        mode=session.mode,
        selection=session.selection,
    )


def _restore_snapshot(session: _MeshEditSession, snapshot: _MeshHistorySnapshot) -> None:
    session.working_mesh = snapshot.mesh
    session.mode = snapshot.mode
    session.selection = snapshot.selection


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
    submeshes = tuple(mesh.submeshes or ())
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
    for face in tuple(submesh.faces or ()):
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


def _transfer_vertex_indices(submesh: SubMesh, selected_vertices: Iterable[int], whole_part: bool) -> tuple[int, ...]:
    if whole_part:
        return tuple(range(len(submesh.vertices or ())))
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


def _source_vertex_index_for_transfer(target: SubMesh, vertex_index: int, source_vertices: tuple[object, ...]) -> int:
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


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _mesh_structure_signature(mesh: ParsedMesh) -> tuple[tuple[int, int], ...]:
    return tuple((len(submesh.vertices or ()), len(submesh.faces or ())) for submesh in mesh.submeshes or ())


def _required_mode(action: str) -> str:
    if action == "brush":
        return "sculpt"
    if action in MESH_TOPOLOGY_ACTIONS or action in {
        "recalculate_normals",
        "generate_tangents",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
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
