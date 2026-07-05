"""Mesh editor workflow coordinator boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Iterable, Mapping, Sequence

from cdmw.domain.mesh import (
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
)
from cdmw.models import HkxPhysicsOverlayBone, HkxPhysicsOverlayData
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.actions import MeshEditorAction, NATIVE_EDITOR_SESSION_COMMANDS, mesh_editor_actions_by_key
from cdmw.ui.mesh_editor.native_preview_payloads import (
    mesh_edit_material_override_groups,
    mesh_edit_selection_groups,
    mesh_edit_triangle_groups,
    mesh_edit_vertex_update_groups,
    mesh_pose_to_native_preview,
    mesh_to_native_preview,
)


@dataclass(frozen=True, slots=True)
class MeshEditorNativeUpdate:
    vertex_groups: Sequence[Mapping[str, object]] = ()
    triangle_groups: Sequence[Mapping[str, object]] = ()
    triangle_source_submesh_indices: Sequence[int] = ()
    selection_groups: Sequence[Mapping[str, object]] = ()
    refresh_selection: bool = False
    material_override_groups: Sequence[Mapping[str, object]] = ()
    replace_all_triangles: bool = False


@dataclass(frozen=True, slots=True)
class MeshEditorActionExecution:
    edit_result: MeshEditResult
    native_update: MeshEditorNativeUpdate


_MATERIAL_OVERRIDE_KEYS = (
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
)
_DEFAULT_MATERIAL_OVERRIDES: Mapping[str, object] = {
    "texture_brightness": 1.0,
    "roughness": 0.0,
    "metalness": 0.0,
    "specular": 0.0,
    "height_scale": 0.0,
    "emissive_intensity": 0.0,
    "emissive_color": [0.35, 0.68, 1.0],
    "contrast": 1.0,
    "saturation": 1.0,
    "gamma": 1.0,
    "tint_color": [1.0, 1.0, 1.0],
}
_NATIVE_ACTIONS_WITHOUT_PREVIEW_PAYLOAD = frozenset({"generate_tangents"})
_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})

def apply_native_update_to_host(host: object, update: MeshEditorNativeUpdate) -> bool:
    if update.vertex_groups:
        sender = getattr(host, "update_mesh_edit_vertices", None)
        if not (callable(sender) and sender(update.vertex_groups)):
            return False
    if update.triangle_groups or update.triangle_source_submesh_indices or update.replace_all_triangles:
        sender = getattr(host, "replace_mesh_edit_triangles", None)
        if not (
            callable(sender)
            and sender(
                update.triangle_groups,
                replace_all=update.replace_all_triangles,
                source_submesh_indices=update.triangle_source_submesh_indices,
            )
        ):
            return False
    if update.material_override_groups:
        sender = getattr(host, "set_material_overrides", None)
        if not callable(sender):
            return False
        for group in update.material_override_groups:
            kwargs = {
                "source_submesh_indices": tuple(group.get("source_submesh_indices", ()) or ()),
                **{key: group[key] for key in _MATERIAL_OVERRIDE_KEYS if key in group},
            }
            if not sender(**kwargs):
                return False
    if update.refresh_selection:
        sender = getattr(host, "set_mesh_edit_selection_groups", None)
        if callable(sender):
            if not sender(update.selection_groups):
                return False
        else:
            clear = getattr(host, "clear_mesh_edit_vertex_selection", None)
            if not (not update.selection_groups and callable(clear) and clear()):
                return False
    return True


class MeshEditorController:
    def __init__(self, context: object | None = None, *, mesh_service: MeshService | None = None) -> None:
        self.context = context
        self.mesh_service = mesh_service or MeshService()
        self.active_session_id = ""
        self.active_action_key = ""
        self.active_selection_mode = "vertex"

    def open_mesh(self, mesh: ParsedMesh, *, session_id: str | None = None, mode: str = "object") -> MeshEditSessionView:
        view = self.mesh_service.open_edit_session(mesh, session_id=session_id, mode=mode)
        self.active_session_id = view.session_id
        return view

    def open_mesh_file(self, path: Path | str, *, session_id: str | None = None, mode: str = "object") -> MeshEditSessionView:
        mesh = self.mesh_service.load_mesh_file(path)
        return self.open_mesh(mesh, session_id=session_id, mode=mode)

    def attach_session(self, session_id: str) -> MeshEditSessionView:
        view = self.mesh_service.session_view(session_id)
        self.active_session_id = view.session_id
        return view

    def close_active_session(self) -> None:
        if self.active_session_id:
            self.mesh_service.close_edit_session(self.active_session_id)
        self.active_session_id = ""

    def session_view(self) -> MeshEditSessionView:
        return self.mesh_service.session_view(self._session_id())

    def native_editor_mesh_dirty(self) -> bool:
        return self.mesh_service.native_editor_mesh_dirty(self._session_id())

    def working_mesh(self, *, clone: bool = True) -> ParsedMesh:
        return self.mesh_service.working_mesh(self._session_id(), clone=clone)

    def pose_preview_mesh(self) -> ParsedMesh:
        return self.mesh_service.pose_preview_mesh(self._session_id())

    def pose_preview_native_context(
        self,
    ) -> tuple[ParsedMesh, object, Mapping[int, tuple[float, float, float]]] | None:
        return self.mesh_service.pose_preview_native_context(self._session_id())

    def base_mesh(self, *, clone: bool = True) -> ParsedMesh:
        return self.mesh_service.base_mesh(self._session_id(), clone=clone)

    def export_validation_report(
        self,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
    ) -> MeshExportValidationReport:
        return self.mesh_service.validate_export(
            self._session_id(),
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
        )

    def workspace_summary(self) -> MeshWorkspaceSummary:
        return self.mesh_service.workspace_summary(self._session_id())

    def compare_summary(self) -> MeshCompareSummary:
        return self.mesh_service.compare_summary(self._session_id())

    def uv_summary(self) -> MeshUvSummary:
        return self.mesh_service.uv_summary(self._session_id())

    def select_uv_region(
        self,
        uv_min: Sequence[object],
        uv_max: Sequence[object],
        *,
        operation: str = "replace",
    ) -> MeshEditResult:
        return self.mesh_service.select_uv_region(self._session_id(), uv_min, uv_max, operation=operation)

    def select_uv_lasso(
        self,
        points: Iterable[Sequence[object]],
        *,
        operation: str = "replace",
    ) -> MeshEditResult:
        return self.mesh_service.select_uv_lasso(self._session_id(), points, operation=operation)

    def skeleton_summary(
        self,
        *,
        skeleton_bone_count: int | None = None,
        skeleton_source: str = "",
        skeleton_descriptor_source: str = "",
        skeleton_variation_source: str = "",
        animation_constraint_source: str = "",
        animation_constraint_evidence: dict[str, object] | None = None,
        socket_source: str = "",
    ) -> MeshSkeletonSummary:
        return self.mesh_service.skeleton_summary(
            self._session_id(),
            skeleton_bone_count=skeleton_bone_count,
            skeleton_source=skeleton_source,
            skeleton_descriptor_source=skeleton_descriptor_source,
            skeleton_variation_source=skeleton_variation_source,
            animation_constraint_source=animation_constraint_source,
            animation_constraint_evidence=animation_constraint_evidence,
            socket_source=socket_source,
        )

    def attach_skeleton(
        self,
        skeleton: object,
        *,
        source_path: str = "",
        skeleton_descriptor_source: str = "",
        skeleton_variation_source: str = "",
        animation_constraint_source: str = "",
        animation_constraint_evidence: dict[str, object] | None = None,
        socket_source: str = "",
    ) -> MeshSkeletonSummary:
        return self.mesh_service.attach_skeleton(
            self._session_id(),
            skeleton,
            source_path=source_path,
            skeleton_descriptor_source=skeleton_descriptor_source,
            skeleton_variation_source=skeleton_variation_source,
            animation_constraint_source=animation_constraint_source,
            animation_constraint_evidence=animation_constraint_evidence,
            socket_source=socket_source,
        )

    def set_pose_preview(self, enabled: bool) -> MeshSkeletonSummary:
        return self.mesh_service.set_pose_preview(self._session_id(), enabled)

    def select_bone(self, bone_index: int) -> MeshSkeletonSummary:
        return self.mesh_service.select_bone(self._session_id(), bone_index)

    def rotate_selected_bone(self, rotation_degrees: Sequence[object]) -> MeshSkeletonSummary:
        return self.mesh_service.rotate_selected_bone(self._session_id(), rotation_degrees)

    def reset_pose(self) -> MeshSkeletonSummary:
        return self.mesh_service.reset_pose(self._session_id())

    def attach_animation_clip(self, clip: MeshAnimationClip) -> MeshSkeletonSummary:
        return self.mesh_service.attach_animation_clip(self._session_id(), clip)

    def clear_animation_clip(self) -> MeshSkeletonSummary:
        return self.mesh_service.clear_animation_clip(self._session_id())

    def set_animation_playback(self, enabled: bool) -> MeshSkeletonSummary:
        return self.mesh_service.set_animation_playback(self._session_id(), enabled)

    def set_animation_loop(self, enabled: bool) -> MeshSkeletonSummary:
        return self.mesh_service.set_animation_loop(self._session_id(), enabled)

    def set_animation_speed(self, speed: object) -> MeshSkeletonSummary:
        return self.mesh_service.set_animation_speed(self._session_id(), speed)

    def seek_animation(self, time_seconds: object) -> MeshSkeletonSummary:
        return self.mesh_service.seek_animation(self._session_id(), time_seconds)

    def scrub_animation_fraction(self, fraction: object) -> MeshSkeletonSummary:
        return self.mesh_service.scrub_animation_fraction(self._session_id(), fraction)

    def step_animation_frame(self, frames: object = 1) -> MeshSkeletonSummary:
        return self.mesh_service.step_animation_frame(self._session_id(), frames)

    def step_animation(self, delta_seconds: object) -> MeshSkeletonSummary:
        return self.mesh_service.step_animation(self._session_id(), delta_seconds)

    def adjust_selected_vertex_bone_weight(self, delta: object) -> MeshSkeletonSummary:
        return self.mesh_service.adjust_selected_vertex_bone_weight(self._session_id(), delta)

    def normalize_selected_vertex_weights(self) -> MeshSkeletonSummary:
        return self.mesh_service.normalize_selected_vertex_weights(self._session_id())

    def transfer_selected_vertex_weights_from_source(self, *, source_skeleton: object | None = None) -> MeshSkeletonSummary:
        return self.mesh_service.transfer_selected_vertex_weights_from_source(
            self._session_id(),
            source_skeleton=source_skeleton,
        )

    def skeleton_overlay_data(self) -> HkxPhysicsOverlayData | None:
        summary = self.skeleton_summary()
        if not summary.bones:
            return None
        by_index = {bone.index: bone for bone in summary.bones}
        pose = summary.pose
        overlay_bones = []
        for bone in summary.bones:
            parent = by_index.get(bone.parent_index)
            overlay_bones.append(
                HkxPhysicsOverlayBone(
                    name=bone.name,
                    source_path=summary.skeleton_source,
                    index=bone.index,
                    parent_index=bone.parent_index,
                    parent_name=bone.parent_name,
                    position=bone.position,
                    parent_position=parent.position if parent is not None else (),
                    confidence="mesh_editor_attached_skeleton",
                )
            )
        return HkxPhysicsOverlayData(
            summary=f"Mesh Editor skeleton overlay: {len(overlay_bones)} bone(s).",
            source_paths=(summary.skeleton_source,) if summary.skeleton_source else (),
            bones=tuple(overlay_bones),
            skeleton_pose_enabled=pose.enabled,
            skeleton_selected_bone_index=pose.selected_bone_index,
            skeleton_pose_rotations=pose.rotations,
            limitations=("PABC skeleton variation and animation clips are not applied unless parsed into pose data.",),
        )

    def texture_edit_target(self) -> MeshTextureEditTarget | None:
        return self.mesh_service.texture_edit_target(self._session_id())

    def set_mode(self, mode: str) -> MeshEditResult:
        return self.apply_command(MeshEditCommand("set_mode", mode=mode))

    def select(
        self,
        *,
        vertices_by_submesh: Mapping[int, Iterable[int]] | None = None,
        edges_by_submesh: Mapping[int, Iterable[Sequence[int]]] | None = None,
        faces_by_submesh: Mapping[int, Iterable[int]] | None = None,
        source_indices: Iterable[int] | None = None,
        operation: str = "replace",
    ) -> MeshEditResult:
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh=vertices_by_submesh,
            edges_by_submesh=edges_by_submesh,
            faces_by_submesh=faces_by_submesh,
            source_indices=source_indices,
        )
        return self.apply_command(MeshEditCommand("select", selection=selection, params={"operation": operation}))

    def apply(self, action: str, *, selection: MeshEditSelection | None = None, mode: str | None = None, **params: object) -> MeshEditResult:
        return self.apply_command(MeshEditCommand(action=action, selection=selection, params=params, mode=mode))

    def apply_editor_action(
        self,
        action: MeshEditorAction | str,
        *,
        selection: MeshEditSelection | None = None,
        mode: str | None = None,
        **params: object,
    ) -> MeshEditResult:
        descriptor = _action_descriptor(action)
        self.active_action_key = descriptor.key
        if descriptor.selection_mode:
            self.active_selection_mode = descriptor.selection_mode
        if descriptor.command == "undo":
            return self.undo()
        if descriptor.command == "redo":
            return self.redo()
        if descriptor.command == "select" and selection is None:
            view = self.session_view()
            return MeshEditResult(action="select", status="noop", revision=view.revision)
        if descriptor.requires_selection:
            view = self.session_view()
            action_selection = selection if selection is not None else view.selection
            if action_selection.is_empty():
                return MeshEditResult(
                    action=descriptor.command,
                    status="noop",
                    revision=view.revision,
                    diagnostics=(f"Mesh Editor action needs a selection: {descriptor.key}.",),
                )
        command_params = dict(descriptor.params)
        command_params.update(params)
        command_mode = mode or descriptor.mode or None
        return self.apply(descriptor.command, selection=selection, mode=command_mode, **command_params)

    def run_editor_action(
        self,
        action: MeshEditorAction | str,
        *,
        selection: MeshEditSelection | None = None,
        mode: str | None = None,
        **params: object,
    ) -> MeshEditorActionExecution:
        edit_result = self.apply_editor_action(action, selection=selection, mode=mode, **params)
        stop_event = params.get("stop_event")
        return MeshEditorActionExecution(
            edit_result=edit_result,
            native_update=self.native_update_for_result(
                edit_result,
                stop_event=stop_event if isinstance(stop_event, threading.Event) else None,
            ),
        )

    def apply_command(self, command: MeshEditCommand) -> MeshEditResult:
        action = str(command.action or "").strip().lower()
        if action in _LEGACY_DISPLAY_CLEANUP_ACTIONS:
            raise RuntimeError(
                f"{action} is legacy display-shape cleanup and is not available in active Mesh Editor"
            )
        return self.mesh_service.apply_command(self._session_id(), command)

    def undo(self) -> MeshEditResult:
        return self.mesh_service.undo(self._session_id())

    def redo(self) -> MeshEditResult:
        return self.mesh_service.redo(self._session_id())

    def native_preview_data(self) -> object:
        pose_context = self.pose_preview_native_context()
        if pose_context is not None:
            mesh, skeleton, pose_rotations = pose_context
            return mesh_pose_to_native_preview(
                mesh,
                skeleton=skeleton,
                pose_rotations=pose_rotations,
            )
        return mesh_to_native_preview(self.pose_preview_mesh())

    def source_preview_data(self) -> object:
        return mesh_to_native_preview(self.base_mesh(clone=False))

    def native_update_for_result(
        self,
        result: MeshEditResult,
        *,
        stop_event: threading.Event | None = None,
    ) -> MeshEditorNativeUpdate:
        changed_vertices = _changed_vertices_by_submesh_for_preview(result)
        native_selection_groups = _native_selection_groups_for_result(result)
        native_vertex_groups = _native_preview_vertex_update_groups_for_result(result)
        native_triangle_groups = _native_preview_triangle_groups_for_result(result)
        current_selection: MeshEditSelection | None = None
        if (
            result.action in {"select", "undo", "redo"}
            or (result.topology_changed and result.ok and result.submesh_count_delta < 0)
        ):
            current_selection = _current_selection_or_empty(self)
        direct_selection_groups = (
            _selection_groups_from_selection_descriptor(current_selection)
            if current_selection is not None
            else ()
        )
        selection_groups = native_selection_groups or direct_selection_groups
        if (
            result.action == "select"
            and result.ok
            and current_selection is not None
            and not current_selection.is_empty()
            and not selection_groups
        ):
            raise RuntimeError("native selection result did not include selection groups; Python selection rebuild is disabled")
        if result.action == "select" and result.ok and current_selection is not None:
            return MeshEditorNativeUpdate(
                selection_groups=selection_groups,
                refresh_selection=True,
            )
        if result.ok and native_vertex_groups:
            return MeshEditorNativeUpdate(
                vertex_groups=native_vertex_groups,
                selection_groups=selection_groups,
                refresh_selection=current_selection is not None,
            )
        if (
            result.topology_changed
            and result.ok
            and result.submesh_count_delta < 0
            and native_triangle_groups
            and (current_selection is None or current_selection.is_empty() or selection_groups)
        ):
            requested = _native_topology_refresh_source_indices(result, native_triangle_groups)
            return MeshEditorNativeUpdate(
                triangle_groups=native_triangle_groups,
                triangle_source_submesh_indices=requested,
                selection_groups=selection_groups,
                refresh_selection=True,
                material_override_groups=_material_override_groups_for_native_triangle_groups(native_triangle_groups),
            )
        if (
            result.topology_changed
            and result.ok
            and native_triangle_groups
            and (
                result.action not in {"undo", "redo"}
                or current_selection is None
                or current_selection.is_empty()
                or selection_groups
            )
        ):
            requested = _native_topology_refresh_source_indices(result, native_triangle_groups)
            return MeshEditorNativeUpdate(
                triangle_groups=native_triangle_groups,
                triangle_source_submesh_indices=requested,
                selection_groups=selection_groups,
                refresh_selection=True,
                material_override_groups=_material_override_groups_for_native_triangle_groups(native_triangle_groups),
            )
        if result.ok and native_triangle_groups:
            requested = _native_topology_refresh_source_indices(result, native_triangle_groups)
            return MeshEditorNativeUpdate(
                triangle_groups=native_triangle_groups,
                triangle_source_submesh_indices=requested,
                material_override_groups=_material_override_groups_for_native_triangle_groups(native_triangle_groups),
            )
        if (
            result.ok
            and changed_vertices
            and _result_has_native_editor_metrics(result)
            and result.action not in _NATIVE_ACTIONS_WITHOUT_PREVIEW_PAYLOAD
        ):
            raise RuntimeError(
                f"native vertex update result for {result.action} did not include preview vertex groups; "
                "Python vertex preview rebuild is disabled"
            )
        if (
            result.ok
            and result.action in NATIVE_EDITOR_SESSION_COMMANDS
            and result.action not in _NATIVE_ACTIONS_WITHOUT_PREVIEW_PAYLOAD
            and (result.affected_submesh_indices or result.topology_changed or changed_vertices)
        ):
            raise RuntimeError(
                f"active native {result.action} result did not include preview payload; "
                "Python preview rebuild is disabled"
            )
        if (
            result.topology_changed
            and result.ok
            and result.submesh_count_delta < 0
            and (current_selection is None or current_selection.is_empty() or selection_groups)
        ):
            requested = tuple(sorted({int(index) for index in result.affected_submesh_indices if int(index) >= 0}))
            if requested:
                return MeshEditorNativeUpdate(
                    triangle_source_submesh_indices=requested,
                    selection_groups=selection_groups,
                    refresh_selection=True,
                )
        if result.topology_changed and result.ok and (result.submesh_counts or result.metrics.get("python_apply_deferred") == 1.0):
            raise RuntimeError(
                f"native topology result for {result.action} did not include preview triangle groups; "
                "Python preview rebuild is disabled"
            )
        if result.ok and _result_has_native_editor_metrics(result):
            if (
                result.action in _NATIVE_ACTIONS_WITHOUT_PREVIEW_PAYLOAD
                or not (result.affected_submesh_indices or result.topology_changed or changed_vertices)
            ):
                if current_selection is not None:
                    return MeshEditorNativeUpdate(
                        selection_groups=selection_groups,
                        refresh_selection=True,
                    )
                return MeshEditorNativeUpdate()
            raise RuntimeError(
                f"native {result.action} result did not include preview payload; "
                "Python preview rebuild is disabled"
            )
        if (
            result.ok
            and result.action in NATIVE_EDITOR_SESSION_COMMANDS
            and not (result.affected_submesh_indices or result.topology_changed or changed_vertices)
        ):
            if current_selection is not None:
                return MeshEditorNativeUpdate(
                    selection_groups=selection_groups,
                    refresh_selection=True,
                )
            return MeshEditorNativeUpdate()
        if result.ok and not (result.affected_submesh_indices or result.topology_changed or changed_vertices):
            return MeshEditorNativeUpdate()
        if str(result.status or "").strip().lower() == "noop" and not (
            result.affected_submesh_indices or result.topology_changed or changed_vertices
        ):
            return MeshEditorNativeUpdate()
        raise RuntimeError(
            f"active Mesh Editor result for {result.action} did not include native preview payload; "
            "legacy Python preview rebuild is disabled"
        )

    def legacy_python_update_for_result(
        self,
        result: MeshEditResult,
        *,
        stop_event: threading.Event | None = None,
        allow_archive_legacy_preview_rebuild: bool = False,
    ) -> MeshEditorNativeUpdate:
        if not allow_archive_legacy_preview_rebuild:
            raise RuntimeError(
                "legacy Python preview rebuild is archive-only; active Mesh Editor requires native preview payloads"
            )
        changed_vertices = _changed_vertices_by_submesh_for_preview(result)
        mesh = self.working_mesh(clone=False)
        if result.action == "select" and result.ok:
            return MeshEditorNativeUpdate(
                selection_groups=mesh_edit_selection_groups(
                    mesh,
                    self.session_view().selection,
                    stop_event=stop_event,
                    allow_python_fallback=True,
                ),
                refresh_selection=True,
            )
        if result.action in {"undo", "redo"} and result.ok and not result.topology_changed:
            if changed_vertices and not result.topology_changed:
                return MeshEditorNativeUpdate(
                    vertex_groups=mesh_edit_vertex_update_groups(
                        mesh,
                        changed_vertices,
                        allow_python_fallback=True,
                    ),
                    selection_groups=mesh_edit_selection_groups(
                        mesh,
                        self.session_view().selection,
                        stop_event=stop_event,
                        allow_python_fallback=True,
                    ),
                    refresh_selection=True,
                )
            affected = range(len(mesh.submeshes))
            return MeshEditorNativeUpdate(
                triangle_groups=mesh_edit_triangle_groups(mesh, allow_python_fallback=True),
                triangle_source_submesh_indices=affected,
                selection_groups=mesh_edit_selection_groups(
                    mesh,
                    self.session_view().selection,
                    stop_event=stop_event,
                    allow_python_fallback=True,
                ),
                refresh_selection=True,
                material_override_groups=mesh_edit_material_override_groups(mesh, affected, include_defaults=True),
                replace_all_triangles=True,
            )
        if result.topology_changed:
            affected, requested = _topology_refresh_source_indices(mesh, result)
            replace_all = bool(result.submesh_count_delta < 0 or not requested)
            refresh_sources = affected if not replace_all else range(len(mesh.submeshes))
            return MeshEditorNativeUpdate(
                triangle_groups=mesh_edit_triangle_groups(
                    mesh,
                    refresh_sources,
                    allow_python_fallback=True,
                ),
                triangle_source_submesh_indices=requested if not replace_all else refresh_sources,
                selection_groups=mesh_edit_selection_groups(
                    mesh,
                    self.session_view().selection,
                    stop_event=stop_event,
                    allow_python_fallback=True,
                ),
                refresh_selection=True,
                material_override_groups=mesh_edit_material_override_groups(mesh, refresh_sources, include_defaults=True),
                replace_all_triangles=replace_all,
            )
        if result.action in {"material_assign", "material_copy"} and result.affected_submesh_indices:
            affected = result.affected_submesh_indices
            return MeshEditorNativeUpdate(
                triangle_groups=mesh_edit_triangle_groups(
                    mesh,
                    affected,
                    allow_python_fallback=True,
                ),
                triangle_source_submesh_indices=affected,
                material_override_groups=mesh_edit_material_override_groups(mesh, affected, include_defaults=True),
            )
        if result.action == "flip_normals" and result.affected_submesh_indices:
            affected = result.affected_submesh_indices
            return MeshEditorNativeUpdate(
                triangle_groups=mesh_edit_triangle_groups(
                    mesh,
                    affected,
                    allow_python_fallback=True,
                ),
                triangle_source_submesh_indices=affected,
            )
        if changed_vertices:
            return MeshEditorNativeUpdate(vertex_groups=mesh_edit_vertex_update_groups(
                mesh,
                changed_vertices,
                allow_python_fallback=True,
            ))
        if result.action == "recalculate_normals" and result.affected_submesh_indices:
            affected_vertices = _all_vertices_by_submesh(mesh, result.affected_submesh_indices)
            return MeshEditorNativeUpdate(vertex_groups=mesh_edit_vertex_update_groups(
                mesh,
                affected_vertices,
                allow_python_fallback=True,
            ))
        return MeshEditorNativeUpdate()

    def _session_id(self) -> str:
        if not self.active_session_id:
            raise RuntimeError("Mesh Editor has no active edit session.")
        return self.active_session_id


def _action_descriptor(action: MeshEditorAction | str) -> MeshEditorAction:
    if isinstance(action, MeshEditorAction):
        return action
    actions = mesh_editor_actions_by_key()
    key = str(action or "").strip()
    try:
        return actions[key]
    except KeyError as exc:
        raise ValueError(f"Unknown Mesh Editor action: {key!r}") from exc


def _all_vertices_by_submesh(mesh: ParsedMesh, submesh_indices: Iterable[int]) -> dict[int, range]:
    return {
        index: range(len(mesh.submeshes[index].vertices))
        for index in sorted({int(raw_index) for raw_index in submesh_indices})
        if 0 <= index < len(mesh.submeshes)
    }


def _changed_vertices_by_submesh_for_preview(result: MeshEditResult) -> dict[int, object]:
    changed: dict[int, object] = {}
    for raw_submesh_index, indices in result.changed_vertices_by_submesh or ():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if submesh_index < 0:
            continue
        if isinstance(indices, Mapping):
            changed[submesh_index] = indices
        elif isinstance(indices, (tuple, range, set)):
            changed[submesh_index] = indices
        else:
            changed[submesh_index] = tuple(int(index) for index in indices)
    return changed


def _native_preview_triangle_groups_for_result(result: MeshEditResult) -> tuple[Mapping[str, object], ...]:
    groups: list[Mapping[str, object]] = []
    for raw_group in result.native_preview_triangle_groups or ():
        if not isinstance(raw_group, Mapping):
            continue
        if str(raw_group.get("preview_backend") or "") != "cdmw_mesh_core":
            continue
        source_index = _coerce_source_index(raw_group.get("source_submesh_index"))
        if source_index is None or source_index < 0:
            continue
        group = dict(raw_group)
        group["source_submesh_index"] = source_index
        groups.append(group)
    return tuple(groups)


def _native_preview_vertex_update_groups_for_result(result: MeshEditResult) -> tuple[Mapping[str, object], ...]:
    groups: list[Mapping[str, object]] = []
    for raw_group in result.native_preview_vertex_update_groups or ():
        if not isinstance(raw_group, Mapping):
            continue
        if str(raw_group.get("preview_backend") or "") != "cdmw_mesh_core":
            continue
        source_index = _coerce_source_index(raw_group.get("source_submesh_index"))
        if source_index is None or source_index < 0:
            continue
        group = dict(raw_group)
        group["source_submesh_index"] = source_index
        groups.append(group)
    return tuple(groups)


def _result_has_native_editor_metrics(result: MeshEditResult) -> bool:
    metrics = result.metrics or {}
    return bool(
        metrics.get("native_apply_roundtrip_ms")
        or metrics.get("native_history_roundtrip_ms")
        or metrics.get("editor_open_roundtrip_ms")
        or metrics.get("editor_select_roundtrip_ms")
        or metrics.get("python_apply_deferred") == 1.0
    )


def _material_override_groups_for_native_triangle_groups(
    triangle_groups: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    groups: list[Mapping[str, object]] = []
    for triangle_group in triangle_groups:
        source_index = _coerce_source_index(triangle_group.get("source_submesh_index"))
        if source_index is None or source_index < 0:
            continue
        group: dict[str, object] = {"source_submesh_indices": [source_index], "editor_role": "replacement_preview"}
        if "material_name" in triangle_group:
            group["material_name"] = triangle_group["material_name"]
        if "texture_name" in triangle_group:
            group["texture_name"] = triangle_group["texture_name"]
        if "material_name" in group or "texture_name" in group:
            group.update(_DEFAULT_MATERIAL_OVERRIDES)
        for key in _MATERIAL_OVERRIDE_KEYS:
            if key in triangle_group:
                group[key] = triangle_group[key]
        if len(group) > 2:
            groups.append(group)
    return tuple(groups)


def _native_selection_groups_for_result(result: MeshEditResult) -> tuple[Mapping[str, object], ...]:
    raw_groups = getattr(result, "native_selection_groups", ()) or ()
    return tuple(dict(group) for group in raw_groups if isinstance(group, Mapping))


def _native_topology_refresh_source_indices(
    result: MeshEditResult,
    triangle_groups: Sequence[Mapping[str, object]],
) -> tuple[int, ...]:
    requested = {
        int(group["source_submesh_index"])
        for group in triangle_groups
        if _coerce_source_index(group.get("source_submesh_index")) is not None
    }
    if result.submesh_count_delta < 0:
        requested.update(int(index) for index in result.affected_submesh_indices if int(index) >= 0)
    return tuple(sorted(requested))


def _selection_groups_from_selection_descriptor(
    selection: MeshEditSelection | None,
) -> tuple[Mapping[str, object], ...]:
    if selection is None or selection.is_empty():
        return ()
    vertices_by_submesh = selection.vertex_map()
    edges_by_submesh = selection.edge_map()
    faces_by_submesh = selection.face_map()
    source_indices = {int(index) for index in selection.source_indices if int(index) >= 0}
    submesh_indices = set(vertices_by_submesh) | set(edges_by_submesh) | set(faces_by_submesh) | source_indices
    groups: list[Mapping[str, object]] = []
    for submesh_index in sorted(index for index in submesh_indices if int(index) >= 0):
        group: dict[str, object] = {"source_submesh_index": int(submesh_index)}
        vertices = sorted(index for index in vertices_by_submesh.get(submesh_index, ()) if int(index) >= 0)
        if vertices:
            group["source_vertex_indices"] = vertices
        edges = sorted(
            (int(left), int(right))
            for left, right in edges_by_submesh.get(submesh_index, ())
            if int(left) >= 0 and int(right) >= 0 and int(left) != int(right)
        )
        if edges:
            group["source_edges"] = [[left, right] for left, right in edges]
        faces = sorted(index for index in faces_by_submesh.get(submesh_index, ()) if int(index) >= 0)
        if faces:
            group["source_face_indices"] = faces
        if submesh_index in source_indices:
            group["source_selected"] = True
        if len(group) > 1:
            groups.append(group)
    return tuple(groups)


def _current_selection_or_empty(controller: MeshEditorController) -> MeshEditSelection:
    try:
        return controller.session_view().selection
    except RuntimeError:
        return MeshEditSelection()


def _topology_refresh_source_indices(mesh: ParsedMesh, result: MeshEditResult) -> tuple[tuple[int, ...], tuple[int, ...]]:
    requested = tuple(sorted({int(index) for index in result.affected_submesh_indices if int(index) >= 0}))
    affected = {index for index in requested if index < len(mesh.submeshes)}
    for index in tuple(affected):
        submesh = mesh.submeshes[index]
        topology_source = _coerce_source_index(getattr(submesh, "cdmw_mesh_edit_topology_source_submesh_index", None))
        material_source = _coerce_source_index(getattr(submesh, "cdmw_mesh_edit_material_source_submesh_index", index))
        source_index = topology_source if topology_source is not None else material_source
        if source_index is not None and 0 <= source_index < len(mesh.submeshes):
            affected.add(source_index)
    return tuple(sorted(affected)), requested


def _coerce_source_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["MeshEditorActionExecution", "MeshEditorController", "MeshEditorNativeUpdate", "apply_native_update_to_host"]
