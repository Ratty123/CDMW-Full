"""Mesh Editor topology regressions found by the 2026-10 tool review.

Each case drives the shadow ``MeshService`` through the resident native editor
session, which is what the embedded Mesh Editor runs for every topology tool.
"""

from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import MeshService


@pytest.fixture
def service():
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("rebuilt native mesh core is required")
    owner = MeshService()
    yield owner
    for session_id in tuple(owner._sessions):
        owner.close_edit_session(session_id, force_without_saving=True)


def _quad(name: str, x: float = 0.0) -> SubMesh:
    return SubMesh(
        name=name,
        material=f"mat_{name}",
        texture=f"{name}.dds",
        vertices=[(x, 0.0, 0.0), (x + 1.0, 0.0, 0.0), (x, 1.0, 0.0), (x + 1.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=4,
        face_count=2,
    )


def _mesh(*parts: SubMesh) -> ParsedMesh:
    return ParsedMesh(
        path="regression.pac",
        format="pac",
        submeshes=list(parts),
        total_vertices=sum(len(part.vertices) for part in parts),
        total_faces=sum(len(part.faces) for part in parts),
        has_uvs=True,
    )


def _open(service: MeshService, mesh: ParsedMesh, session_id: str) -> str:
    return service.open_edit_session(mesh, session_id=session_id, mode="edit").session_id


def _apply(service: MeshService, session_id: str, action: str, selection: MeshEditSelection, **params):
    return service.apply_command(
        session_id,
        MeshEditCommand(action, selection=selection, params=params, mode="edit"),
    )


def _faces_by_part(service: MeshService, session_id: str) -> list[tuple[str, int]]:
    return [(part.name, len(part.faces)) for part in service.working_mesh(session_id).submeshes]


def test_edits_after_delete_part_reach_the_part_at_that_index(service):
    """Native Part keys shift with the host list, so later Parts stay addressable."""

    session_id = _open(service, _mesh(_quad("A"), _quad("B", 10.0), _quad("C", 20.0)), "delete-part-shift")

    assert _apply(service, session_id, "delete", MeshEditSelection.from_maps(source_indices=(0,)), delete_parts=True).ok
    assert _faces_by_part(service, session_id) == [("B", 2), ("C", 2)]

    deleted_face = _apply(service, session_id, "delete", MeshEditSelection.from_maps(faces_by_submesh={1: [0]}))
    assert deleted_face.ok and tuple(deleted_face.affected_submesh_indices) == (1,)
    assert _faces_by_part(service, session_id) == [("B", 2), ("C", 1)]

    moved = _apply(
        service, session_id, "transform", MeshEditSelection.from_maps(source_indices=(0,)), translate=(0.0, 0.0, 5.0),
    )
    assert moved.ok
    parts = service.working_mesh(session_id).submeshes
    assert [vertex[2] for vertex in parts[0].vertices] == [5.0] * 4
    assert all(vertex[2] == 0.0 for vertex in parts[1].vertices)


def _with_descriptor(part: SubMesh, offset: int) -> SubMesh:
    part.source_index_offset = offset * 10
    part.source_index_count = 6
    part.source_descriptor_offset = offset
    part.source_vertex_stride = 40
    part.source_lod_count = 4
    return part


def _descriptor(part: SubMesh) -> tuple[int, int, int, int, int]:
    return (
        part.source_index_offset, part.source_index_count, part.source_descriptor_offset,
        part.source_vertex_stride, part.source_lod_count,
    )


def test_separated_part_owns_no_source_section_and_material_copy_keeps_its_own(service):
    session_id = _open(
        service, _mesh(_with_descriptor(_quad("A"), 100), _with_descriptor(_quad("B", 10.0), 200)), "descriptor-owners",
    )

    assert _apply(service, session_id, "separate", MeshEditSelection.from_maps(faces_by_submesh={0: [0]})).ok
    parts = service.working_mesh(session_id).submeshes
    assert [_descriptor(part) for part in parts] == [
        (1000, 6, 100, 40, 4), (2000, 6, 200, 40, 4), (-1, 0, -1, 40, 4),
    ]

    copied = _apply(
        service, session_id, "material_copy", MeshEditSelection.from_maps(source_indices=(1,)), source_submesh_index=0,
    )
    assert copied.ok
    parts = service.working_mesh(session_id).submeshes
    assert parts[1].material == "mat_A"
    assert _descriptor(parts[1]) == (2000, 6, 200, 40, 4)


def test_delete_part_undo_redo_keeps_later_parts_addressable(service):
    session_id = _open(service, _mesh(_quad("A"), _quad("B", 10.0), _quad("C", 20.0)), "delete-part-history")

    assert _apply(service, session_id, "delete", MeshEditSelection.from_maps(source_indices=(1,)), delete_parts=True).ok
    assert service.undo(session_id).ok
    assert _faces_by_part(service, session_id) == [("A", 2), ("B", 2), ("C", 2)]
    assert service.redo(session_id).ok
    assert _faces_by_part(service, session_id) == [("A", 2), ("C", 2)]

    assert _apply(service, session_id, "delete", MeshEditSelection.from_maps(faces_by_submesh={1: [0]})).ok
    assert _faces_by_part(service, session_id) == [("A", 2), ("C", 1)]
    assert service.undo(session_id).ok
    assert service.undo(session_id).ok
    assert _faces_by_part(service, session_id) == [("A", 2), ("B", 2), ("C", 2)]
    assert _apply(service, session_id, "delete", MeshEditSelection.from_maps(faces_by_submesh={2: [0]})).ok
    assert _faces_by_part(service, session_id) == [("A", 2), ("B", 2), ("C", 1)]


def _part(name: str, vertices, faces, *, uvs=None, normals=None) -> SubMesh:
    return SubMesh(
        name=name,
        material=f"mat_{name}",
        texture=f"{name}.dds",
        vertices=list(vertices),
        uvs=list(uvs) if uvs is not None else [(vertex[0], vertex[1]) for vertex in vertices],
        normals=list(normals) if normals is not None else [(0.0, 0.0, 1.0)] * len(vertices),
        faces=list(faces),
        vertex_count=len(vertices),
        face_count=len(faces),
    )


def _signed_areas(part: SubMesh) -> list[float]:
    areas = []
    for a, b, c in part.faces:
        (ax, ay, _), (bx, by, _), (cx, cy, _) = part.vertices[a], part.vertices[b], part.vertices[c]
        areas.append((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
    return areas


_UNIT_SQUARE = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]


@pytest.mark.parametrize(
    ("faces", "edge", "rotated_edge"),
    [
        (((0, 1, 2), (1, 3, 2)), (1, 2), {0, 3}),
        # The first face runs the shared edge from its higher to its lower vertex,
        # which used to give both replacements the opposite winding.
        (((0, 1, 3), (0, 3, 2)), (0, 3), {1, 2}),
    ],
)
def test_dissolve_rotates_an_interior_edge_and_keeps_the_winding(service, faces, edge, rotated_edge):
    session_id = _open(service, _mesh(_part("Q", _UNIT_SQUARE, faces)), f"dissolve-{edge}")

    assert _apply(service, session_id, "dissolve", MeshEditSelection.from_maps(edges_by_submesh={0: [edge]})).ok

    part = service.working_mesh(session_id).submeshes[0]
    assert len(part.faces) == 2
    assert all(area > 0.0 for area in _signed_areas(part))
    assert all(rotated_edge <= set(face) for face in part.faces)


def test_dissolve_leaves_border_and_concave_edges_alone(service):
    border = _open(service, _mesh(_part("Q", _UNIT_SQUARE, ((0, 1, 2), (1, 3, 2)))), "dissolve-border")
    # Dissolve on a border edge used to delete the face beside it.
    _apply(service, border, "dissolve", MeshEditSelection.from_maps(edges_by_submesh={0: [(0, 1)]}))
    part = service.working_mesh(border).submeshes[0]
    assert (part.faces, len(part.vertices)) == ([(0, 1, 2), (1, 3, 2)], 4)

    dart = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.5, 0.5, 0.0)]
    concave = _open(service, _mesh(_part("D", dart, ((0, 1, 3), (0, 3, 2)))), "dissolve-concave")
    _apply(service, concave, "dissolve", MeshEditSelection.from_maps(edges_by_submesh={0: [(0, 3)]}))
    assert service.working_mesh(concave).submeshes[0].faces == [(0, 1, 3), (0, 3, 2)]


def test_dissolve_of_edges_sharing_a_triangle_rotates_instead_of_deleting(service):
    strip = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (2.0, 1.0, 0.0)]
    faces = ((0, 1, 4), (0, 4, 3), (1, 2, 5), (1, 5, 4))
    session_id = _open(service, _mesh(_part("S", strip, faces)), "dissolve-shared")

    # Both edges border triangle (0, 1, 4). This used to abandon the rotation and
    # delete every face touching either edge instead.
    assert _apply(service, session_id, "dissolve", MeshEditSelection.from_maps(edges_by_submesh={0: [(0, 4), (1, 4)]})).ok

    part = service.working_mesh(session_id).submeshes[0]
    assert (len(part.faces), len(part.vertices)) == (4, 6)
    assert all(area > 0.0 for area in _signed_areas(part))
    assert not any({0, 4} <= set(face) for face in part.faces)


def _seam_mesh(second_uvs) -> ParsedMesh:
    tilted = (0.0, 0.6, 0.8)
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    uvs = [(0.0, 0.0), (0.5, 0.0), (0.0, 0.5), *second_uvs]
    return _mesh(_part("S", vertices, ((0, 1, 2), (3, 4, 5)), uvs=uvs, normals=[tilted] * 6))


def test_remove_doubles_keeps_a_uv_seam_and_every_untouched_normal(service):
    seam = _open(service, _seam_mesh([(0.6, 0.0), (1.0, 1.0), (0.6, 0.5)]), "doubles-seam")
    _apply(service, seam, "remove_doubles", MeshEditSelection.from_maps(vertices_by_submesh={0: [1, 3]}), threshold=1e-4)
    part = service.working_mesh(seam).submeshes[0]
    assert len(part.vertices) == 6
    assert part.uvs[3] == (0.6, 0.0)
    assert all(normal == pytest.approx((0.0, 0.6, 0.8)) for normal in part.normals)

    doubles = _open(service, _seam_mesh([(0.5, 0.0), (1.0, 1.0), (0.6, 0.5)]), "doubles-weld")
    assert _apply(
        service, doubles, "remove_doubles", MeshEditSelection.from_maps(vertices_by_submesh={0: [1, 3]}), threshold=1e-4,
    ).ok
    part = service.working_mesh(doubles).submeshes[0]
    assert len(part.vertices) == 5
    # Welding one pair used to replace every normal in the Part with a smooth one.
    assert all(normal == pytest.approx((0.0, 0.6, 0.8)) for normal in part.normals)


def _directed_edges(part: SubMesh) -> list[tuple[int, int]]:
    return [(face[corner], face[(corner + 1) % 3]) for face in part.faces for corner in range(3)]


def _assert_consistently_wound_manifold(part: SubMesh) -> None:
    directed = _directed_edges(part)
    # Two faces running an edge the same way are wound against each other, and
    # a third face on an edge makes it non-manifold.
    assert len(directed) == len(set(directed))
    undirected = [tuple(sorted(edge)) for edge in directed]
    assert max(undirected.count(edge) for edge in set(undirected)) <= 2


def test_extrude_turns_the_selected_face_into_the_cap(service):
    session_id = _open(service, _mesh(_quad("Q")), "extrude-face")

    assert _apply(service, session_id, "extrude", MeshEditSelection.from_maps(faces_by_submesh={0: [0]}), offset=[0.0, 0.0, 0.5]).ok

    part = service.working_mesh(session_id).submeshes[0]
    # One untouched face, the cap and two walls on each of the face's three edges.
    assert len(part.faces) == 8
    _assert_consistently_wound_manifold(part)
    base = [face for face in part.faces if all(part.vertices[index][2] == 0.0 for index in face)]
    assert base == [(1, 3, 2)]


def test_extrude_raises_no_walls_along_a_seam_inside_the_selection(service):
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    uvs = [(0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.6, 0.0), (1.0, 1.0), (0.6, 0.5)]
    session_id = _open(service, _mesh(_part("S", vertices, ((0, 1, 2), (3, 4, 5)), uvs=uvs)), "extrude-seam")

    assert _apply(service, session_id, "extrude", MeshEditSelection.from_maps(faces_by_submesh={0: [0, 1]}), offset=[0.0, 0.0, 0.5]).ok

    # Two caps and two walls on each of the four outer edges; the split diagonal is interior.
    assert len(service.working_mesh(session_id).submeshes[0].faces) == 10


def test_extrude_edges_adds_one_strip_wound_with_its_face(service):
    session_id = _open(service, _mesh(_quad("Q")), "extrude-edge")

    assert _apply(service, session_id, "extrude", MeshEditSelection.from_maps(edges_by_submesh={0: [(0, 1)]}), offset=[0.0, -0.5, 0.0]).ok

    part = service.working_mesh(session_id).submeshes[0]
    # Extrude Edges used to extrude the whole triangle beside the edge.
    assert (len(part.vertices), len(part.faces)) == (6, 4)
    _assert_consistently_wound_manifold(part)
    assert all(area > 0.0 for area in _signed_areas(part))


_STRIP = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (2.0, 1.0, 0.0)]
_STRIP_FACES = ((0, 1, 4), (0, 4, 3), (1, 2, 5), (1, 5, 4))


def test_edge_split_separates_only_along_the_selected_edge(service):
    session_id = _open(service, _mesh(_part("S", _STRIP, _STRIP_FACES)), "edge-split")

    assert _apply(service, session_id, "edge_split", MeshEditSelection.from_maps(edges_by_submesh={0: [(1, 4)]})).ok

    part = service.working_mesh(session_id).submeshes[0]
    left, right = part.faces[:2], part.faces[2:]
    assert len(part.vertices) == 8
    assert not set(left[0] + left[1]) & set(right[0] + right[1])
    # Each half keeps its own diagonal. Copying both ends of the split edge for
    # the right half's second face used to cut that diagonal as well.
    assert len(set(left[0]) & set(left[1])) == 2
    assert len(set(right[0]) & set(right[1])) == 2


def test_edge_split_cut_once_through_a_closed_fan_keeps_its_centre_shared(service):
    fan = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)]
    session_id = _open(service, _mesh(_part("F", fan, ((0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1)))), "edge-split-fan")

    assert _apply(service, session_id, "edge_split", MeshEditSelection.from_maps(edges_by_submesh={0: [(0, 1)]})).ok

    part = service.working_mesh(session_id).submeshes[0]
    # Only the border end splits: the slit opens from the rim to the centre.
    assert len(part.vertices) == 6
    assert all(0 in face for face in part.faces)
    assert not set(part.faces[0]) & set(part.faces[3]) - {0}


def _split_diagonal_quad() -> SubMesh:
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    uvs = [(0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.6, 0.0), (1.0, 1.0), (0.6, 0.5)]
    return _part("S", vertices, ((0, 1, 2), (3, 4, 5)), uvs=uvs)


def test_refine_smooth_keeps_seam_corners_together(service):
    session_id = _open(service, _mesh(_split_diagonal_quad()), "refine-seam")

    assert _apply(
        service, session_id, "refine_smooth", MeshEditSelection.from_maps(faces_by_submesh={0: [0, 1]}),
        smooth_strength=1.0, smooth_iterations=2,
    ).ok

    vertices = service.working_mesh(session_id).submeshes[0].vertices
    assert vertices[1] == pytest.approx(vertices[3])
    assert vertices[2] == pytest.approx(vertices[5])
    positions = {tuple(round(component, 6) for component in vertex) for vertex in vertices}
    # Six corners and seven midpoints, the shared diagonal's twins on one point each.
    assert len(positions) == 4 + 5


def test_subdivide_stitches_the_face_across_a_seam(service):
    session_id = _open(service, _mesh(_split_diagonal_quad()), "subdivide-seam")

    assert _apply(service, session_id, "subdivide", MeshEditSelection.from_maps(faces_by_submesh={0: [0]})).ok

    part = service.working_mesh(session_id).submeshes[0]
    # Four children of the split face; the face over the seam is split in two
    # at the diagonal's midpoint instead of keeping a T-junction against it.
    assert len(part.faces) == 6
    on_seam = [index for index, vertex in enumerate(part.vertices) if vertex == pytest.approx((0.5, 0.5, 0.0))]
    assert len(on_seam) == 2
    assert any(set(on_seam) & set(face) and 4 in face for face in part.faces)


_COLOURS = [(1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0)]


def _quad_with_extras() -> SubMesh:
    part = _quad("Q")
    part.vertex_colors = list(_COLOURS)
    part.uv_sets = {1: [(0.0, 0.0), (2.0, 0.0), (0.0, 2.0), (2.0, 2.0)]}
    part.morph_targets = {"lift": [(0.0, 0.0, 0.1), (0.0, 0.0, 0.2), (0.0, 0.0, 0.3), (0.0, 0.0, 0.4)]}
    part.interchange_vertex_ids = [10, 11, 12, 13]
    return part


def _extras(part: SubMesh) -> tuple[int, int, int, int]:
    return (
        len(part.vertex_colors),
        len(next(iter(part.uv_sets.values()))),
        len(part.morph_targets["lift"]),
        len(part.interchange_vertex_ids),
    )


def test_vertex_extras_follow_a_face_delete(service):
    session_id = _open(service, _mesh(_quad_with_extras()), "extras-delete")

    assert _apply(service, session_id, "delete", MeshEditSelection.from_maps(faces_by_submesh={0: [1]})).ok

    part = service.working_mesh(session_id).submeshes[0]
    # Vertex 3 went with the face; its colour, UV and morph rows used to stay.
    assert len(part.vertices) == 3
    assert _extras(part) == (3, 3, 3, 3)
    assert [tuple(colour) for colour in part.vertex_colors] == _COLOURS[:3]
    assert list(part.interchange_vertex_ids) == [10, 11, 12]


def test_vertex_extras_blend_onto_subdivide_midpoints(service):
    session_id = _open(service, _mesh(_quad_with_extras()), "extras-subdivide")

    assert _apply(service, session_id, "subdivide", MeshEditSelection.from_maps(faces_by_submesh={0: [0]})).ok

    part = service.working_mesh(session_id).submeshes[0]
    count = len(part.vertices)
    assert count > 4 and _extras(part) == (count, count, count, count)
    midpoint = next(
        index for index, vertex in enumerate(part.vertices) if vertex == pytest.approx((0.5, 0.0, 0.0))
    )
    assert tuple(part.vertex_colors[midpoint]) == pytest.approx((0.5, 0.5, 0.0, 1.0))
    assert tuple(part.morph_targets["lift"][midpoint]) == pytest.approx((0.0, 0.0, 0.15))
    assert part.interchange_vertex_ids[midpoint] in {10, 11}
