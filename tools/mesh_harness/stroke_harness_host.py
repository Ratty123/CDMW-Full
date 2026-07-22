from __future__ import annotations

from collections.abc import Mapping, Sequence


class _HarnessSignal:
    def __init__(self) -> None:
        self.callbacks: list[object] = []
        self.results: list[object] = []

    def connect(self, callback: object) -> None:
        self.callbacks.append(callback)

    def emit(self, payload: object) -> None:
        self.results.clear()
        for callback in tuple(self.callbacks):
            self.results.append(callback(payload))


class _StandaloneStrokeHarnessHost:
    """In-process authoring host used to exercise MeshService stroke routing."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mesh_edit_states: list[dict[str, object]] = []
        self.vertex_group_counts: list[int] = []
        self.selection_group_counts: list[int] = []
        self.mesh_edit_stroke_started = _HarnessSignal()
        self.mesh_edit_stroke_previewed = _HarnessSignal()
        self.mesh_edit_stroke_finished = _HarnessSignal()
        self.mesh_edit_stroke_cancelled = _HarnessSignal()
        self.mesh_edit_selection_changed = _HarnessSignal()

    def set_mesh_edit_state(self, **kwargs: object) -> bool:
        self.calls.append("set_mesh_edit_state")
        self.mesh_edit_states.append(dict(kwargs))
        return True

    def update_mesh_edit_vertices(self, groups: Sequence[Mapping[str, object]]) -> bool:
        self.calls.append("update_mesh_edit_vertices")
        self.vertex_group_counts.append(len(tuple(groups or ())))
        return True

    def replace_mesh_edit_triangles(
        self,
        groups: Sequence[Mapping[str, object]],
        *,
        replace_all: bool = False,
        source_submesh_indices: Sequence[int] | None = None,
    ) -> bool:
        del groups, replace_all, source_submesh_indices
        self.calls.append("replace_mesh_edit_triangles")
        return True

    def set_mesh_edit_selection_groups(
        self, groups: Sequence[Mapping[str, object]]
    ) -> bool:
        self.calls.append("set_mesh_edit_selection")
        self.selection_group_counts.append(len(tuple(groups or ())))
        return True


__all__ = ["_HarnessSignal", "_StandaloneStrokeHarnessHost"]
