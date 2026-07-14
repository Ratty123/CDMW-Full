from __future__ import annotations

import math
import sys
from functools import wraps
from typing import Sequence

from cdmw.domain.mesh import (
    MeshAnimationClip,
    MeshSkeletonSummary,
    sample_mesh_animation_pose,
    summarize_mesh_skinning,
)
from cdmw.domain.mesh.weight_transfer import percentile_95, sample_weight_row, spatial_transfer_distance_limit
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.services.mesh_service_reports import _coerce_index
from cdmw.services.mesh_service_state import _MeshEditSession


def _service_dependency(name: str) -> object:
    return getattr(sys.modules["cdmw.services.mesh_service"], name)


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    return _service_dependency(name)(*args, **kwargs)  # type: ignore[operator]


def _allow_python_skin_weight_fallback(*args: object, **kwargs: object) -> object:
    return _service_call("_allow_python_skin_weight_fallback", *args, **kwargs)


def _clear_history_stack(*args: object, **kwargs: object) -> object:
    return _service_call("_clear_history_stack", *args, **kwargs)


def _discard_history_snapshot(*args: object, **kwargs: object) -> object:
    return _service_call("_discard_history_snapshot", *args, **kwargs)


def _prune_selection_to_mesh(*args: object, **kwargs: object) -> object:
    return _service_call("_prune_selection_to_mesh", *args, **kwargs)


def apply_native_mesh_skin_weights(*args: object, **kwargs: object) -> object:
    return _service_call("apply_native_mesh_skin_weights", *args, **kwargs)


def invalidate_native_mesh_session_submeshes(*args: object, **kwargs: object) -> object:
    return _service_call("invalidate_native_mesh_session_submeshes", *args, **kwargs)


def transfer_native_mesh_skin_weights_from_source(*args: object, **kwargs: object) -> object:
    return _service_call("transfer_native_mesh_skin_weights_from_source", *args, **kwargs)


def _with_session_export_lock(method):
    @wraps(method)
    def locked(self, session_id: str, *args: object, **kwargs: object):
        session = self._session(session_id)
        with session.export_lock:
            return method(self, session_id, *args, **kwargs)

    return locked


class MeshRiggingServiceMixin:
    @_with_session_export_lock
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

    @_with_session_export_lock
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

    @_with_session_export_lock
    def set_pose_preview(self, session_id: str, enabled: bool) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.pose_preview_enabled = bool(enabled)
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def select_bone(self, session_id: str, bone_index: int) -> MeshSkeletonSummary:
        session = self._session(session_id)
        requested = _coerce_index(bone_index)
        valid_indices = {bone.index for bone in self.skeleton_summary(session_id).bones}
        session.selected_bone_index = requested if requested is not None and requested in valid_indices else -1
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
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

    @_with_session_export_lock
    def reset_pose(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.bone_pose_rotations.clear()
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def attach_animation_clip(self, session_id: str, clip: MeshAnimationClip) -> MeshSkeletonSummary:
        if not isinstance(clip, MeshAnimationClip):
            raise TypeError("animation clip must be a MeshAnimationClip")
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_clip = clip
        session.animation_time_seconds = 0.0
        session.animation_playback_enabled = False
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def clear_animation_clip(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_clip = None
        session.animation_playback_enabled = False
        session.animation_time_seconds = 0.0
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def set_animation_playback(self, session_id: str, enabled: bool) -> MeshSkeletonSummary:
        session = self._session(session_id)
        summary = self.skeleton_summary(session_id)
        session.animation_playback_enabled = bool(enabled and summary.animation_playback.ready)
        if session.animation_playback_enabled:
            session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def set_animation_loop(self, session_id: str, enabled: bool) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_loop = bool(enabled)
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def set_animation_speed(self, session_id: str, speed: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_speed = _coerce_animation_speed(speed)
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def seek_animation(self, session_id: str, time_seconds: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        _require_clean_python_skeleton_state(session)
        session.animation_time_seconds = _coerce_time_seconds(time_seconds)
        if session.animation_clip is not None and self.skeleton_summary(session_id).animation_playback.ready:
            session.animation_playback_enabled = True
            session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
    def scrub_animation_fraction(self, session_id: str, fraction: object) -> MeshSkeletonSummary:
        session = self._session(session_id)
        summary = self.skeleton_summary(session_id)
        duration = float(summary.animation_playback.duration_seconds or 0.0)
        session.animation_time_seconds = duration * _coerce_fraction(fraction)
        if summary.animation_playback.ready:
            session.pose_preview_enabled = True
        return self.skeleton_summary(session_id)

    @_with_session_export_lock
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

    @_with_session_export_lock
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

    @_with_session_export_lock
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
            self._push_history(
                session,
                prefer_native=True,
                action="adjust_vertex_weights",
                label="Adjust Bone Weight",
            )
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
                self._push_history(
                    session,
                    action="adjust_vertex_weights",
                    label="Adjust Bone Weight",
                )
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

    @_with_session_export_lock
    def normalize_selected_vertex_weights(self, session_id: str) -> MeshSkeletonSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise RuntimeError("native mesh editor skin weight edit unavailable; Python mesh state is stale")
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        vertex_map = session.selection.vertex_map()
        if vertex_map:
            self._push_history(
                session,
                prefer_native=True,
                action="normalize_vertex_weights",
                label="Normalize Bone Weights",
            )
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
                self._push_history(
                    session,
                    action="normalize_vertex_weights",
                    label="Normalize Bone Weights",
                )
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

    @_with_session_export_lock
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
            self._push_history(
                session,
                prefer_native=True,
                action="transfer_vertex_weights",
                label="Transfer Bone Weights",
            )
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
            spatial_distances: list[float] = []
            for vertex_index in _transfer_vertex_indices(target, vertex_map.get(submesh_index, ()), submesh_index in session.selection.source_indices):
                next_indices, next_weights, distance = _source_weight_row_for_transfer(target, vertex_index, source)
                if distance is not None:
                    spatial_distances.append(distance)
                if bone_remap is not None:
                    next_indices, next_weights = _remap_weight_row(next_indices, next_weights, bone_remap)
                if not next_indices or not next_weights:
                    raise ValueError(f"Source skin weights for part {submesh_index}, vertex {vertex_index} are empty after bone mapping.")
                current_indices = tuple(target.bone_indices[vertex_index]) if vertex_index < len(target.bone_indices) else ()
                current_weights = tuple(target.bone_weights[vertex_index]) if vertex_index < len(target.bone_weights) else ()
                if next_indices == current_indices and next_weights == current_weights:
                    continue
                operations.append((vertex_index, next_indices, next_weights))
            limit = spatial_transfer_distance_limit(source_vertices)
            p95 = percentile_95(spatial_distances)
            if spatial_distances and p95 > limit:
                raise ValueError(
                    f"Skin-weight transfer is too far from source surface for part {submesh_index}: "
                    f"p95 {p95:.6g} exceeds 5% bbox limit {limit:.6g}."
                )
            if operations:
                operations_by_submesh[submesh_index] = operations
        if not operations_by_submesh:
            return self.skeleton_summary(session_id)
        self._push_history(
            session,
            action="transfer_vertex_weights",
            label="Transfer Bone Weights",
        )
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


def _require_clean_python_skeleton_state(session: _MeshEditSession) -> None:
    if session.native_editor_mesh_dirty:
        raise RuntimeError("native mesh editor skeleton controls unavailable; Python mesh state is stale")


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


def _source_weight_row_for_transfer(
    target: SubMesh,
    vertex_index: int,
    source: SubMesh,
) -> tuple[tuple[int, ...], tuple[float, ...], float | None]:
    if 0 <= vertex_index < len(target.source_vertex_map or ()):
        mapped = _coerce_index(target.source_vertex_map[vertex_index])
        if mapped is not None and 0 <= mapped < len(source.vertices or ()):
            indices, weights = _normalize_weight_row(
                source.bone_indices[mapped] if mapped < len(source.bone_indices) else (),
                source.bone_weights[mapped] if mapped < len(source.bone_weights) else (),
            )
            if not indices or not weights:
                raise ValueError(f"Source skin-weight row {mapped} is empty or invalid.")
            return indices, weights, None
    target_position = _position3((target.vertices or [])[vertex_index] if 0 <= vertex_index < len(target.vertices or ()) else ())
    if target_position is None:
        raise ValueError(f"Target skin-weight vertex {vertex_index} is not finite.")
    sample = sample_weight_row(
        target_position,
        source.vertices or (),
        source.faces or (),
        source.bone_indices or (),
        source.bone_weights or (),
    )
    return sample.bone_indices, sample.bone_weights, sample.distance


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
