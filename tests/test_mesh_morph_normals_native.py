"""Morph and refit retain authored smooth seams without rounding hard edges."""
from copy import deepcopy

import numpy as np
import pytest

from tests.test_mesh_refit_tightening_native import _mesh
from tests.test_native_mesh_editor_morph_refit import _command, _open, _part, _snapshot, mesh_native_core


def _seam_mesh(material_seam, hard, scale):
    points = [(-1., 0., 0.), (0., 0., 0.), (0., 1., 0.), (1., 0., .5)]
    faces = [(0, 1, 2), (1, 3, 2)]
    face_normals = [np.cross(np.subtract(points[b], points[a]), np.subtract(points[c], points[a]))
                    for a, b, c in faces]
    smooth = sum(face_normals)
    smooth /= np.linalg.norm(smooth)
    pieces = []
    for f, face in enumerate(faces):
        part = _part(f"panel {f}", [tuple(scale * np.asarray(points[i])) for i in face], [(0, 1, 2)],
                     material=f"cloth {f}", texture=f"panel-{f}.dds")
        face_normal = face_normals[f] / np.linalg.norm(face_normals[f])
        part.normals = [tuple(face_normal if hard or i not in (1, 2) else smooth) for i in face]
        pieces.append(part)
    if not material_seam:
        first, second = pieces
        first.vertices += second.vertices
        first.normals += second.normals
        first.uvs += second.uvs
        first.tangents += second.tangents
        first.bone_indices += second.bone_indices
        first.bone_weights += second.bone_weights
        first.source_vertex_map = list(range(6))
        first.faces += [tuple(i + 3 for i in face) for face in second.faces]
        first.vertex_count = 6
        first.face_count = 2
        pieces = [first]
    return _mesh(*pieces)


def _profile(mesh, fields):
    return {"profile": {"profile_id": "seam normals", "name": "Seam normals",
                        "topology_fingerprint": "a" * 64,
                        "definitions": [{"definition_id": "bend", "label": "Bend", "category": "Cloth",
                                         "min_percent": 0., "max_percent": 100., "default_percent": 0.}],
                        "fields": [{"definition_id": "bend", "submesh_index": i,
                                    "vertex_indices": list(range(len(part.vertices))), "deltas": fields[i]}
                                   for i, part in enumerate(mesh.submeshes)]}}


def _assert_seam_normals(mesh, hard):
    triangles = [np.asarray(part.vertices)[face] for part in mesh.submeshes for face in map(list, part.faces)]
    normals = [np.cross(p[1] - p[0], p[2] - p[0]) for p in triangles]
    shared = sum(normals)
    shared /= np.linalg.norm(shared)
    flat_normals = np.concatenate([part.normals for part in mesh.submeshes])
    for i in (1, 2, 3, 5):
        expected = normals[i // 3] / np.linalg.norm(normals[i // 3]) if hard else shared
        assert flat_normals[i] == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("material_seam", (False, True), ids=("uv", "material"))
@pytest.mark.parametrize("hard", (False, True), ids=("smooth", "creased"))
@pytest.mark.parametrize("scale", (.01, 1., 100.))
@pytest.mark.parametrize("motion", ("both", "one-panel", "separated"))
def test_morph_preserves_authored_normal_seams_and_history(material_seam, hard, scale, motion):
    mesh = _seam_mesh(material_seam, hard, scale)
    baseline = deepcopy(mesh)
    fields = [[(0., 0., (scale * .1 if motion == "both" or motion == "separated" and (i == 1 or j >= 3)
                         else 0.) + .3 * max(0., x)) for j, (x, _, _) in enumerate(part.vertices)]
              for i, part in enumerate(mesh.submeshes)]
    session = _open(mesh)
    try:
        _command(session, "morph_upload", _profile(mesh, fields))
        payload = {"definition_id": "bend", "value": 100., "phase": "end", "change_id": "smooth-seam"}
        _command(session, "morph_change", payload)
        fitted = _snapshot(mesh, session)
        if motion == "separated":
            # The unmoved panel retains its authored normals; the moved panel
            # must not average with it after their positions have separated.
            normals = np.concatenate([part.normals for part in fitted.submeshes])
            original = np.concatenate([part.normals for part in baseline.submeshes])
            assert normals[:3] == pytest.approx(original[:3])
            vertices = np.concatenate([part.vertices for part in fitted.submeshes])
            normal = np.cross(vertices[4] - vertices[3], vertices[5] - vertices[3])
            normal /= np.linalg.norm(normal)
            assert normals[3:] == pytest.approx(np.tile(normal, (3, 1)), abs=1e-6)
        else:
            _assert_seam_normals(fitted, hard)
        for i, (before, after) in enumerate(zip(baseline.submeshes, fitted.submeshes)):
            assert after.vertices == pytest.approx(np.asarray(before.vertices) + np.asarray(fields[i]))
            assert after.faces == before.faces
            assert after.uvs == before.uvs
            assert after.bone_indices == before.bone_indices
            assert after.bone_weights == before.bone_weights
            assert (after.material, after.texture) == (before.material, before.texture)
        assert mesh_native_core.undo_native_mesh_editor_session(session, timeout_seconds=15.) is not None
        restored = _snapshot(mesh, session)
        assert [p.vertices for p in restored.submeshes] == [p.vertices for p in baseline.submeshes]
        assert [p.normals for p in restored.submeshes] == [p.normals for p in baseline.submeshes]
        assert mesh_native_core.redo_native_mesh_editor_session(session, timeout_seconds=15.) is not None
        assert [p.normals for p in _snapshot(mesh, session).submeshes] == [p.normals for p in fitted.submeshes]
        _command(session, "morph_change", dict(payload, change_id="same-fit"))
        assert [p.normals for p in _snapshot(mesh, session).submeshes] == [p.normals for p in fitted.submeshes]
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)


def test_back_to_back_linings_keep_opposite_normals_and_untouched_parts_keep_theirs():
    vertices = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
    lining = _part("two-sided lining", vertices + vertices, [(0, 1, 2), (3, 5, 4)], material="cloth", texture="")
    lining.normals = [(0., 0., 1.)] * 3 + [(0., 0., -1.)] * 3
    untouched = _part("untouched", [(x + 10., y, z) for x, y, z in vertices], [(0, 1, 2)], material="metal", texture="")
    untouched.normals = [(.6, 0., .8)] * 3
    mesh = _mesh(lining, untouched)
    session = _open(mesh)
    try:
        _command(session, "morph_upload", _profile(mesh, [[(0., 0., .2)] * 6, [(0., 0., 0.)] * 3]))
        _command(session, "morph_change", {"definition_id": "bend", "value": 100.,
                                           "phase": "end", "change_id": "lining"})
        fitted = _snapshot(mesh, session)
        assert fitted.submeshes[0].normals == lining.normals
        assert fitted.submeshes[1].normals == untouched.normals
        assert fitted.submeshes[1].vertices == untouched.vertices
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)


@pytest.mark.parametrize("material_seam", (False, True), ids=("uv", "material"))
@pytest.mark.parametrize("replace_session", (False, True), ids=("preview", "snapshot"))
def test_flattening_a_hard_seam_does_not_erase_its_authored_crease(material_seam, replace_session):
    mesh = _seam_mesh(material_seam, True, 1.)
    fields = [[(0., 0., -z) for _, _, z in part.vertices] for part in mesh.submeshes]
    session = _open(mesh)
    target = snapshot = None
    try:
        _command(session, "morph_upload", _profile(mesh, fields))
        for value in (100., 0.):
            active = target or session
            _command(active, "morph_change", {"definition_id": "bend", "value": value,
                                               "phase": "end", "change_id": f"crease-{value}"})
            geometry = _snapshot(mesh, active)
            _assert_seam_normals(geometry, True)
            if value == 100. and replace_session:
                snapshot = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(session, timeout_seconds=15.)
                assert snapshot is not None
                target = _open(geometry)
                assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, snapshot, timeout_seconds=15.) is not None
    finally:
        if target is not None:
            mesh_native_core.close_native_mesh_editor_session(target)
        mesh_native_core.close_native_mesh_editor_session(session)
        if snapshot is not None:
            assert mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(snapshot, timeout_seconds=15.)
