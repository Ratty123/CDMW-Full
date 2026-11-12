"""Remove collapsed faces, the Python fallback (P17 stage 3), on owned meshes built here."""

from __future__ import annotations

import copy

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_edit_ops import (
    MESH_TOPOLOGY_ACTIONS,
    apply_mesh_edit_geometry_action,
    find_collapsed_faces,
    remove_collapsed_faces,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _part(name="cloak"):
    # 0-3 a quad; 4 sits on 1; 5 is on the line from 0 to 1; 6 is used only by the flat face; 7 is loose already.
    vertices = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.), (1., 0., 0.), (.5, 0., 0.), (2., 0., 0.),
                (5., 5., 5.)]
    faces = [(0, 1, 2), (1, 3, 2),   # kept
             (1, 1, 3),              # repeats a corner
             (0, 5, 6),              # no area: three points on one line
             (1, 4, 3)]              # 4 is at 1's position: no area once the corners coincide
    return SubMesh(name=name, vertices=list(vertices), uvs=[(v[0], v[1]) for v in vertices],
                   normals=[(0., 0., 1.)] * len(vertices), faces=list(faces),
                   bone_indices=[(i % 4,) for i in range(len(vertices))],
                   bone_weights=[(1.0,)] * len(vertices))


def _mesh():
    clean = SubMesh(name="belt", vertices=[(0., 0., 1.), (1., 0., 1.), (0., 1., 1.)], faces=[(0, 1, 2)],
                    uvs=[(0., 0.), (1., 0.), (0., 1.)], normals=[(0., 0., 1.)] * 3)
    return ParsedMesh(path="owned.pac", format="pac", submeshes=[_part(), clean])


def test_finding_collapsed_faces_changes_nothing():
    mesh = _mesh()
    before = copy.deepcopy(mesh)
    assert find_collapsed_faces(mesh) == {0: (2, 3, 4)}
    assert find_collapsed_faces(mesh, (1,)) == {}
    assert mesh == before


def test_removal_drops_only_collapsed_faces_and_the_vertices_they_alone_used():
    mesh = _mesh()
    kept = [mesh.submeshes[0].faces[i] for i in (0, 1)]
    result = remove_collapsed_faces(mesh)
    assert result.faces_removed == ((0, 3),) and result.face_count == 3
    part = mesh.submeshes[0]
    assert len(part.faces) == 2
    # Vertices 4, 5 and 6 were used only by removed faces; 7 was already loose. Compaction keeps 0 to 3 in order.
    assert result.vertices_removed == ((0, 4),) and result.vertex_count == 4
    assert part.vertices == [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.)]
    assert part.faces == kept and len(part.uvs) == len(part.bone_indices) == len(part.bone_weights) == 4
    assert mesh.submeshes[1].faces == [(0, 1, 2)] and len(mesh.submeshes[1].vertices) == 3
    assert result.affected_submesh_indices == (0,)
    assert remove_collapsed_faces(mesh).face_count == 0  # nothing left to remove


def _authored(part):
    """Normals and tangents no smoothing would produce, one per vertex, all different."""
    part.normals = [(0.6, 0.0, 0.8), (0.0, 0.6, 0.8), (-0.6, 0.0, 0.8), (0.0, -0.6, 0.8),
                    (0.8, 0.6, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)]
    part.tangents = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.6, 0.8, 0.0),
                     (0.8, 0.0, 0.6), (0.0, 0.8, 0.6), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)]
    return part


@pytest.mark.parametrize("remove_unused_vertices", [True, False])
def test_kept_vertices_keep_their_stored_normals_and_tangents(remove_unused_vertices):
    mesh = _mesh()
    part = _authored(mesh.submeshes[0])
    normals, tangents = list(part.normals), list(part.tangents)
    belt_normals = list(mesh.submeshes[1].normals)
    remove_collapsed_faces(mesh, remove_unused_vertices=remove_unused_vertices)
    kept = range(4) if remove_unused_vertices else range(8)
    assert part.normals == [normals[i] for i in kept]
    assert part.tangents == [tangents[i] for i in kept]
    assert mesh.submeshes[1].normals == belt_normals


def test_a_part_with_an_out_of_range_face_loses_its_collapsed_faces_but_is_not_compacted():
    mesh = _mesh()
    part = mesh.submeshes[0]
    part.faces.append((0, 1, 99))
    result = remove_collapsed_faces(mesh)
    assert result.face_count == 3 and result.vertices_removed == ()
    assert (0, 1, 99) in part.faces and len(part.vertices) == 8


def test_vertices_can_be_left_for_delete_loose_vertices():
    mesh = _mesh()
    result = remove_collapsed_faces(mesh, remove_unused_vertices=False)
    assert result.face_count == 3 and result.vertices_removed == ()
    assert len(mesh.submeshes[0].vertices) == 8 and len(mesh.submeshes[0].faces) == 2


def test_a_face_with_an_out_of_range_corner_is_left_alone():
    mesh = ParsedMesh(submeshes=[SubMesh(vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                                         faces=[(0, 1, 2), (0, 1, 9)])])
    assert find_collapsed_faces(mesh) == {}
    assert remove_collapsed_faces(mesh).face_count == 0 and mesh.submeshes[0].faces == [(0, 1, 2), (0, 1, 9)]


def test_a_thin_face_with_area_is_kept_and_the_tolerance_is_a_parameter():
    thin = SubMesh(vertices=[(0., 0., 0.), (1., 0., 0.), (.5, 1e-5, 0.)], faces=[(0, 1, 2)])
    mesh = ParsedMesh(submeshes=[thin])
    assert find_collapsed_faces(mesh) == {}
    assert find_collapsed_faces(mesh, area_epsilon=1e-3) == {0: (0,)}


def test_the_operation_table_runs_it_on_the_selected_parts(monkeypatch):
    monkeypatch.setenv("CDMW_DISABLE_NATIVE_MESH_CORE", "1")  # the Python fallback, as without the native core
    assert "remove_collapsed_faces" in MESH_TOPOLOGY_ACTIONS
    mesh = _mesh()
    command = MeshEditCommand(action="remove_collapsed_faces", params={"remove_unused_vertices": True})
    affected, changed = apply_mesh_edit_geometry_action(mesh, command, MeshEditSelection.from_maps(
        vertices_by_submesh={1: {0}}))
    assert affected == set() and changed == {}  # only the belt was selected; it has nothing collapsed
    affected, _changed = apply_mesh_edit_geometry_action(mesh, command, MeshEditSelection())
    assert affected == {0} and len(mesh.submeshes[0].faces) == 2


@pytest.mark.parametrize("value", ["not a number", -1, float("nan")])
def test_a_bad_tolerance_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("CDMW_DISABLE_NATIVE_MESH_CORE", "1")
    mesh = _mesh()
    command = MeshEditCommand(action="remove_collapsed_faces", params={"area_epsilon": value})
    assert apply_mesh_edit_geometry_action(mesh, command, MeshEditSelection())[0] == {0}
