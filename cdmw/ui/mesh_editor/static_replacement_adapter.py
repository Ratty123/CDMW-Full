"""Static replacement bridge for Mesh Editor service commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from cdmw.domain.mesh import MeshEditResult, MeshEditSelection, MeshEditSessionView
from cdmw.services.mesh_workflow_service import ParsedMesh
from cdmw.ui.mesh_editor.controller import MeshEditorController, MeshEditorNativeUpdate


@dataclass(frozen=True, slots=True)
class StaticReplacementMeshEditResult:
    mesh: ParsedMesh
    edit_result: MeshEditResult
    native_update: MeshEditorNativeUpdate
    affected_submesh_indices: tuple[int, ...] = ()
    emptied_submesh_indices: tuple[int, ...] = ()
    changed_vertices_by_submesh: dict[int, object] | None = None
    removed_face_count: int = 0
    removed_vertex_count: int = 0
    added_face_count: int = 0
    added_vertex_count: int = 0
    source_submesh_index: int = -1
    new_submesh_index: int = -1
    moved_face_count: int = 0
    moved_vertex_count: int = 0
    previous_submesh_count: int = 0
    selected_source_indices: tuple[int, ...] = ()
    new_submesh_source_indices: tuple[tuple[int, int], ...] = ()


@dataclass(slots=True)
class StaticReplacementMeshEditSession:
    session_id: str = "static-replacement"
    mode: str = "edit"
    controller: MeshEditorController = field(default_factory=MeshEditorController)
    submesh_counts: tuple[tuple[int, int], ...] = ()
    mesh: ParsedMesh | None = None

    def open(self, mesh: ParsedMesh) -> None:
        self.controller.open_mesh(mesh, session_id=self.session_id, mode=self.mode)
        self.mesh = mesh
        self.submesh_counts = _mesh_counts(self.mesh)

    def close(self) -> None:
        self.controller.close_active_session()

    def sync_working_mesh(self) -> ParsedMesh:
        # The service-owned working mesh is already the independent compatibility
        # copy created when this edit session opened. Reading it is the explicit
        # resident-to-Python hydration boundary; cloning it again can fail after
        # valid topology edits and incorrectly force the UI into legacy fallback.
        mesh = self.controller.working_mesh(clone=False)
        self.mesh = mesh
        self.submesh_counts = _mesh_counts(mesh)
        return mesh

    def view(self) -> MeshEditSessionView:
        return self.controller.session_view()

    def select(
        self,
        *,
        operation: str = "replace",
        vertices_by_submesh: Mapping[int, Iterable[int]] | None = None,
        edges_by_submesh: Mapping[int, Iterable[Sequence[int]]] | None = None,
        faces_by_submesh: Mapping[int, Iterable[int]] | None = None,
        source_indices: Iterable[int] | None = None,
        **params: object,
    ) -> MeshEditResult:
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh=vertices_by_submesh,
            edges_by_submesh=edges_by_submesh,
            faces_by_submesh=faces_by_submesh,
            source_indices=source_indices,
        )
        return self.controller.apply("select", selection=selection, operation=operation, **params)

    def apply(
        self,
        action: str,
        *,
        vertices_by_submesh: Mapping[int, Iterable[int]] | None = None,
        edges_by_submesh: Mapping[int, Iterable[Sequence[int]]] | None = None,
        faces_by_submesh: Mapping[int, Iterable[int]] | None = None,
        source_indices: Iterable[int] | None = None,
        **params: object,
    ) -> StaticReplacementMeshEditResult:
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh=vertices_by_submesh,
            edges_by_submesh=edges_by_submesh,
            faces_by_submesh=faces_by_submesh,
            source_indices=source_indices,
        )
        before = self.submesh_counts
        service_action = "separate" if str(action or "").strip().lower() == "split" else action
        action_params = dict(params)
        command_mode = action_params.pop("mode", None) or ("sculpt" if str(service_action).strip().lower() == "brush" else "edit")
        edit_result = self.controller.apply(service_action, selection=selection, mode=str(command_mode), **action_params)
        return self._result(edit_result, before=before, selection=selection)

    def apply_current_selection(self, action: str, **params: object) -> StaticReplacementMeshEditResult:
        before = self.submesh_counts
        service_action = "separate" if str(action or "").strip().lower() == "split" else action
        action_params = dict(params)
        command_mode = action_params.pop("mode", None) or ("sculpt" if str(service_action).strip().lower() == "brush" else "edit")
        selection = self.controller.session_view().selection
        edit_result = self.controller.apply(service_action, selection=None, mode=str(command_mode), **action_params)
        return self._result(edit_result, before=before, selection=selection)

    def undo(self) -> StaticReplacementMeshEditResult:
        before = self.submesh_counts
        return self._result(self.controller.undo(), before=before, selection=MeshEditSelection())

    def redo(self) -> StaticReplacementMeshEditResult:
        before = self.submesh_counts
        return self._result(self.controller.redo(), before=before, selection=MeshEditSelection())

    def _result(
        self,
        edit_result: MeshEditResult,
        *,
        before: tuple[tuple[int, int], ...],
        selection: MeshEditSelection,
    ) -> StaticReplacementMeshEditResult:
        native_update = self.controller.native_update_for_result(edit_result)
        if not edit_result.submesh_counts:
            raise RuntimeError(
                f"native {edit_result.action} result did not include submesh counts; "
                "Python working mesh hydration is disabled"
            )
        mesh = self.mesh
        if mesh is None:
            raise RuntimeError("static replacement edit session has no compatibility mesh; Python working mesh hydration is disabled")
        after = edit_result.submesh_counts
        self.submesh_counts = after
        return _static_result(
            mesh,
            edit_result,
            native_update,
            before=before,
            after=after,
            selection=selection,
        )


def apply_static_replacement_edit(
    mesh: ParsedMesh,
    action: str,
    *,
    vertices_by_submesh: Mapping[int, Iterable[int]] | None = None,
    edges_by_submesh: Mapping[int, Iterable[Sequence[int]]] | None = None,
    faces_by_submesh: Mapping[int, Iterable[int]] | None = None,
    source_indices: Iterable[int] | None = None,
    mode: str = "edit",
    **params: object,
) -> StaticReplacementMeshEditResult:
    session = StaticReplacementMeshEditSession(session_id="static-replacement", mode=mode)
    session.open(mesh)
    try:
        return session.apply(
            action,
            vertices_by_submesh=vertices_by_submesh,
            edges_by_submesh=edges_by_submesh,
            faces_by_submesh=faces_by_submesh,
            source_indices=source_indices,
            **params,
        )
    finally:
        session.close()


def _static_result(
    mesh: ParsedMesh,
    edit_result: MeshEditResult,
    native_update: MeshEditorNativeUpdate,
    *,
    before: tuple[tuple[int, int], ...],
    after: tuple[tuple[int, int], ...] | None = None,
    selection: MeshEditSelection,
) -> StaticReplacementMeshEditResult:
    after = after or _mesh_counts(mesh)
    before_vertices = sum(vertex_count for vertex_count, _face_count in before)
    before_faces = sum(face_count for _vertex_count, face_count in before)
    after_vertices = sum(vertex_count for vertex_count, _face_count in after)
    after_faces = sum(face_count for _vertex_count, face_count in after)
    affected = tuple(int(index) for index in edit_result.affected_submesh_indices)
    emptied = tuple(index for index in affected if 0 <= index < len(after) and after[index][1] <= 0)
    changed = _changed_vertices_for_static_result(edit_result)
    source_index = _selection_source_index(selection)
    new_index = max(affected, default=-1) if len(after) > len(before) else -1
    new_sources = _new_submesh_source_indices(native_update, len(before), len(after))
    moved_face_count = _moved_face_count(before, after, source_index) if new_index >= 0 else 0
    moved_vertex_count = after[new_index][0] if 0 <= new_index < len(after) else 0
    return StaticReplacementMeshEditResult(
        mesh=mesh,
        edit_result=edit_result,
        native_update=native_update,
        affected_submesh_indices=affected,
        emptied_submesh_indices=emptied,
        changed_vertices_by_submesh=changed or None,
        removed_face_count=max(0, before_faces - after_faces),
        removed_vertex_count=max(0, before_vertices - after_vertices),
        added_face_count=max(0, after_faces - before_faces),
        added_vertex_count=max(0, after_vertices - before_vertices),
        source_submesh_index=source_index,
        new_submesh_index=new_index,
        moved_face_count=moved_face_count,
        moved_vertex_count=moved_vertex_count,
        previous_submesh_count=len(before),
        selected_source_indices=tuple(selection.source_indices),
        new_submesh_source_indices=new_sources,
    )


def _new_submesh_source_indices(
    native_update: MeshEditorNativeUpdate,
    previous_count: int,
    current_count: int,
) -> tuple[tuple[int, int], ...]:
    pairs: dict[int, int] = {}
    for group in native_update.triangle_groups:
        try:
            new_index = int(group.get("source_submesh_index", -1))
            source_index = int(group.get("material_source_submesh_index", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if previous_count <= new_index < current_count and 0 <= source_index < previous_count:
            pairs[new_index] = source_index
    return tuple(sorted(pairs.items()))


def _mesh_counts(mesh: ParsedMesh) -> tuple[tuple[int, int], ...]:
    return tuple((len(submesh.vertices), len(submesh.faces)) for submesh in mesh.submeshes)


def _changed_vertices_for_static_result(edit_result: MeshEditResult) -> dict[int, object]:
    changed: dict[int, object] = {}
    for raw_submesh, indices in edit_result.changed_vertices_by_submesh:
        try:
            submesh = int(raw_submesh)
        except (TypeError, ValueError, OverflowError):
            continue
        if isinstance(indices, Mapping):
            changed[submesh] = dict(indices)
            continue
        if isinstance(indices, range) and indices.step == 1:
            changed[submesh] = indices
        else:
            changed[submesh] = {int(index) for index in indices}
    return changed


def _selection_source_index(selection: MeshEditSelection) -> int:
    if selection.faces_by_submesh:
        return int(selection.faces_by_submesh[0][0])
    if selection.vertices_by_submesh:
        return int(selection.vertices_by_submesh[0][0])
    if selection.source_indices:
        return int(selection.source_indices[0])
    return -1


def _moved_face_count(before: tuple[tuple[int, int], ...], after: tuple[tuple[int, int], ...], source_index: int) -> int:
    if 0 <= source_index < len(before) and source_index < len(after):
        return max(0, before[source_index][1] - after[source_index][1])
    return 0


__all__ = [
    "StaticReplacementMeshEditResult",
    "StaticReplacementMeshEditSession",
    "apply_static_replacement_edit",
]
