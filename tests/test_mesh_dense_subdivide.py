from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import MeshService


_FACE_COUNT = 300
_SELECTED_FACE_COUNT = 270


def _disconnected_triangle_submesh(name: str, y_offset: float) -> SubMesh:
    vertices: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for face_index in range(_FACE_COUNT):
        x = float((face_index % 30) * 2)
        y = y_offset + float((face_index // 30) * 2)
        start = len(vertices)
        vertices.extend(((x, y, 0.0), (x + 1.0, y, 0.0), (x, y + 1.0, 0.0)))
        uvs.extend(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)))
        faces.append((start, start + 1, start + 2))
    return SubMesh(
        name=name,
        material=f"{name}_material",
        texture=f"{name}.dds",
        vertices=vertices,
        uvs=uvs,
        normals=[(0.0, 0.0, 1.0)] * len(vertices),
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )


def _dense_two_part_mesh() -> ParsedMesh:
    submeshes = [
        _disconnected_triangle_submesh("dense_a", 0.0),
        _disconnected_triangle_submesh("dense_b", 30.0),
    ]
    return ParsedMesh(
        path="dense-subdivide.pac",
        format="pac",
        submeshes=submeshes,
        total_vertices=sum(item.vertex_count for item in submeshes),
        total_faces=sum(item.face_count for item in submeshes),
        has_uvs=True,
    )


def _selection_for_target(target: str) -> MeshEditSelection:
    if target == "face":
        return MeshEditSelection.from_maps(
            faces_by_submesh={index: range(_SELECTED_FACE_COUNT) for index in range(2)}
        )
    if target == "edge":
        return MeshEditSelection.from_maps(
            edges_by_submesh={
                index: tuple(
                    (face_index * 3, face_index * 3 + 1)
                    for face_index in range(_SELECTED_FACE_COUNT)
                )
                for index in range(2)
            }
        )
    return MeshEditSelection.from_maps(
        vertices_by_submesh={
            index: (face_index * 3 for face_index in range(_SELECTED_FACE_COUNT))
            for index in range(2)
        }
    )


def _selection_sizes(selection: MeshEditSelection, target: str) -> tuple[int, int]:
    mapping = {
        "vertex": selection.vertex_map,
        "edge": selection.edge_map,
        "face": selection.face_map,
    }[target]()
    return tuple(len(mapping[index]) for index in range(2))  # type: ignore[return-value]


@pytest.mark.skipif(not native_mesh_core_available(), reason="native mesh core is unavailable")
@pytest.mark.parametrize(
    ("target", "post_selection_count"),
    (("vertex", 1_080), ("edge", 540), ("face", 1_080)),
)
def test_dense_multi_part_subdivide_changes_every_selected_region_and_round_trips_selection(
    target: str,
    post_selection_count: int,
) -> None:
    service = MeshService()
    session_id = f"dense-subdivide-{target}"
    service.open_edit_session(_dense_two_part_mesh(), session_id=session_id, mode="edit")
    original_selection = _selection_for_target(target)

    subdivided = service.apply_command(
        session_id,
        MeshEditCommand(
            "subdivide",
            selection=original_selection,
            params={"max_faces_per_submesh": 200_000},
            mode="edit",
        ),
    )
    post_view = service.session_view(session_id)
    post_selection = post_view.selection

    assert subdivided.ok
    assert subdivided.topology_changed
    assert subdivided.affected_submesh_indices == (0, 1)
    assert subdivided.submesh_counts == ((1_710, 1_110), (1_710, 1_110))
    assert post_view.undo_count == 1
    assert _selection_sizes(post_selection, target) == (post_selection_count, post_selection_count)
    assert subdivided.session_view is not None
    assert subdivided.session_view.selection == post_selection

    undone = service.undo(session_id)
    undo_view = service.session_view(session_id)
    assert undone.ok
    assert undone.submesh_counts == ((900, 300), (900, 300))
    assert undo_view.selection == original_selection
    assert undo_view.undo_count == 0
    assert undo_view.redo_count == 1

    redone = service.redo(session_id)
    redo_view = service.session_view(session_id)
    assert redone.ok
    assert redone.submesh_counts == subdivided.submesh_counts
    assert redo_view.selection == post_selection
    assert redo_view.undo_count == 1
    assert redo_view.redo_count == 0


@pytest.mark.skipif(not native_mesh_core_available(), reason="native mesh core is unavailable")
def test_subdivide_rejects_predicted_face_cap_before_geometry_mutation() -> None:
    service = MeshService()
    session_id = "dense-subdivide-cap"
    service.open_edit_session(_dense_two_part_mesh(), session_id=session_id, mode="edit")
    selection = MeshEditSelection.from_maps(faces_by_submesh={0: range(_FACE_COUNT)})

    with pytest.raises(
        RuntimeError,
        match=r"submesh=0, predicted_faces=1200, limit=1000",
    ):
        service.apply_command(
            session_id,
            MeshEditCommand(
                "subdivide",
                selection=selection,
                params={"max_faces_per_submesh": 1_000},
                mode="edit",
            ),
        )

    view = service.session_view(session_id)
    assert (view.vertex_count, view.face_count) == (1_800, 600)
    assert view.undo_count == 0
    assert view.redo_count == 0
