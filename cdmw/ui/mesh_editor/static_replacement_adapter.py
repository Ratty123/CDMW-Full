"""Static replacement bridge for Mesh Editor service commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from cdmw.domain.mesh import MeshEditResult, MeshEditSelection, MeshEditSessionView
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.ui.mesh_editor.controller import MeshEditorController, MeshEditorNativeUpdate


@dataclass(frozen=True, slots=True)
class StaticReplacementMeshEditResult:
    mesh: ParsedMesh
    edit_result: MeshEditResult
    native_update: MeshEditorNativeUpdate
    affected_submesh_indices: tuple[int, ...] = ()
    emptied_submesh_indices: tuple[int, ...] = ()
    changed_vertices_by_submesh: dict[int, set[int]] | None = None
    removed_face_count: int = 0
    removed_vertex_count: int = 0
    added_face_count: int = 0
    added_vertex_count: int = 0
    source_submesh_index: int = -1
    new_submesh_index: int = -1
    moved_face_count: int = 0
    moved_vertex_count: int = 0


@dataclass(slots=True)
class StaticReplacementMeshEditSession:
    session_id: str = "static-replacement"
    mode: str = "edit"
    controller: MeshEditorController = field(default_factory=MeshEditorController)

    def open(self, mesh: ParsedMesh) -> None:
        self.controller.open_mesh(mesh, session_id=self.session_id, mode=self.mode)

    def close(self) -> None:
        self.controller.close_active_session()

    def view(self) -> MeshEditSessionView:
        return self.controller.session_view()

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
        before = _mesh_counts(self.controller.working_mesh(clone=False))
        service_action = "separate" if str(action or "").strip().lower() == "split" else action
        edit_result = self.controller.apply(service_action, selection=selection, **params)
        return self._result(edit_result, before=before, selection=selection)

    def undo(self) -> StaticReplacementMeshEditResult:
        before = _mesh_counts(self.controller.working_mesh(clone=False))
        return self._result(self.controller.undo(), before=before, selection=MeshEditSelection())

    def redo(self) -> StaticReplacementMeshEditResult:
        before = _mesh_counts(self.controller.working_mesh(clone=False))
        return self._result(self.controller.redo(), before=before, selection=MeshEditSelection())

    def _result(
        self,
        edit_result: MeshEditResult,
        *,
        before: tuple[tuple[int, int], ...],
        selection: MeshEditSelection,
    ) -> StaticReplacementMeshEditResult:
        native_update = self.controller.native_update_for_result(edit_result)
        return _static_result(
            self.controller.working_mesh(clone=True),
            edit_result,
            native_update,
            before=before,
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
    selection: MeshEditSelection,
) -> StaticReplacementMeshEditResult:
    after = _mesh_counts(mesh)
    before_vertices = sum(vertex_count for vertex_count, _face_count in before)
    before_faces = sum(face_count for _vertex_count, face_count in before)
    after_vertices = sum(vertex_count for vertex_count, _face_count in after)
    after_faces = sum(face_count for _vertex_count, face_count in after)
    affected = tuple(int(index) for index in edit_result.affected_submesh_indices)
    emptied = tuple(index for index in affected if 0 <= index < len(mesh.submeshes) and not mesh.submeshes[index].faces)
    changed = {
        int(submesh): set(int(index) for index in indices)
        for submesh, indices in edit_result.changed_vertices_by_submesh
    }
    source_index = _selection_source_index(selection)
    new_index = max(affected, default=-1) if len(after) > len(before) else -1
    moved_face_count = _moved_face_count(before, after, source_index) if new_index >= 0 else 0
    moved_vertex_count = len(mesh.submeshes[new_index].vertices) if new_index >= 0 else 0
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
    )


def _mesh_counts(mesh: ParsedMesh) -> tuple[tuple[int, int], ...]:
    return tuple((len(submesh.vertices), len(submesh.faces)) for submesh in mesh.submeshes)


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
