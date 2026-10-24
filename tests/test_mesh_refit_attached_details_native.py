"""Attached relief follows cloth away from a body-centered waist band."""
import math

import numpy as np
import pytest

from tests.test_mesh_refit_layer_boundaries_native import (
    _combined_part, _fitted_mesh, _waist_rope,
)
from tests.test_mesh_refit_tightening_native import _arm, _assert_no_surface_crossings, _bound, _fit, _mesh, _sleeve
from tests.test_native_mesh_editor_morph_refit import _command, _part, _refit_tube_part, _snapshot, _state


@pytest.mark.parametrize("packed", (False, True), ids=("separate-materials", "same-part"))
def test_local_relief_follows_a_broad_sleeve_off_the_body_center(packed):
    arm = _arm()
    torso = _arm()
    torso.vertices = [(x * 2.5 - .3, y, z * 2.5) for x, y, z in torso.vertices]
    body = _combined_part("body", (arm, torso))
    sleeve = _sleeve()
    rope = _waist_rope(radius=.101)
    used = [segment * 8 + side for segment in (31, 0, 1) for side in range(8)]
    remap = {vertex: local for local, vertex in enumerate(used)}
    relief = _part("raised trim", [rope.vertices[i] for i in used],
                   [tuple(remap[i] for i in face) for face in rope.faces
                    if all(i in remap for i in face)], material="trim", texture="")
    source = _mesh(body, *([_combined_part("sleeve and trim", (sleeve, relief))]
                          if packed else [sleeve, relief]))
    fitted = _fitted_mesh(source, (0,), range(1, len(source.submeshes)))
    points = np.asarray(fitted.submeshes[-1].vertices[-len(relief.vertices):])
    diameter = np.linalg.norm(points.reshape(3, 8, 3)[:, :4]
                              - points.reshape(3, 8, 3)[:, 4:], axis=2)
    assert diameter.min() > .0035 and diameter.max() < .0045
    assert max(math.hypot(x, z) for x, _, z in points) < .07
    _assert_no_surface_crossings(body, fitted.submeshes[-1])


@pytest.mark.parametrize("wide_cuff", (False, True), ids=("sleeve", "cuff-sized-fold"))
def test_a_bow_loop_keeps_its_relief_when_the_supporting_sleeve_tightens(wide_cuff):
    body = _arm()
    sleeve = _refit_tube_part("cuff", .10, 0., (.22, .25, .28), 32) if wide_cuff else _sleeve()
    # Only the root touches the cloth. The folded loop must not independently
    # seek the skin and turn its two sides into a flattened, pointed fan.
    profile = ((0., 0.), (.015, .03), (.04, .02), (.03, -.025), (0., 0.)) if wide_cuff else (
        (0., 0.), (.015, .013), (.04, .008), (.03, -.008), (0., 0.))
    half_width = .0525 if wide_cuff else .006
    vertices = [(.101 + x, .25 + y, z) for x, y in profile for z in (-half_width, half_width)]
    faces = [(a, a+1, a+3) for a in (0, 2, 4, 6)] + [(a, a+3, a+2) for a in (0, 2, 4, 6)]
    loop = _part("loop", vertices, faces, material="cloth", texture="")
    fitted = _fitted_mesh(_mesh(body, sleeve, loop), (0,), (1, 2))
    before, after = np.asarray(vertices), np.asarray(fitted.submeshes[2].vertices)
    source_distances = np.linalg.norm(before[:, None] - before[None, :], axis=2)
    fitted_distances = np.linalg.norm(after[:, None] - after[None, :], axis=2)
    assert np.max(np.abs(source_distances - fitted_distances)) < .004
    assert np.mean(after[:, 0] - before[:, 0]) < -.025
    _assert_no_surface_crossings(body, fitted.submeshes[2])


def test_a_point_touch_is_not_a_sewn_material_boundary():
    sleeve = _sleeve()
    ornament = _part("point contact", [sleeve.vertices[64], (.13, .18, -.01), (.13, .22, .01)],
                     [(0, 1, 2)], material="trim", texture="")
    mesh = _mesh(_arm(), sleeve, ornament)
    with _bound(mesh) as session:
        _fit(session, (1, 2), vertex_masks=[{
            "submesh_index": 2, "vertex_indices": [], "weights": [],
        }])
        effective = _command(session, "morph_state", {
            "include_effective_vertex_masks": True, "submesh_indices": [1, 2],
        })["effective_vertex_masks"]
        by_part = {item["submesh_index"]: item["weights"] for item in effective}
        assert by_part[1] == [1.] * len(sleeve.vertices)
        assert by_part[2] == [0.] * len(ornament.vertices)
        assert _snapshot(mesh, session).submeshes[2].vertices == ornament.vertices


@pytest.mark.parametrize("handling", ("auto", "surface", "rigid_component", "rigid_caps", "removed"),
                         ids=("default-solid", "explicit-surface", "rigid-dagger", "rigid-caps", "removed-dagger"))
def test_dagger_island_sharing_a_cloth_part_keeps_its_shape_or_is_excluded(handling):
    removed = handling == "removed"
    cloth = _sleeve(radius=.13)
    # A closed blade with a narrow point and a wider guard. It shares a material
    # Part with cloth, so a Part-wide stiffness guess would be incorrect.
    outline = ((.18, 0.), (.25, -.012), (.27, -.025), (.29, -.025),
               (.29, .025), (.27, .025), (.25, .012))
    vertices = [(x, y, z) for x in (.131, .138) for y, z in outline]
    n = len(outline)
    faces = [(0, i + 1, i) for i in range(1, n - 1)]
    faces += [(n, n + i, n + i + 1) for i in range(1, n - 1)]
    for i in range(n):
        j = (i + 1) % n
        faces += [(i, j, n + j), (i, n + j, n + i)]
    closed_faces = len(faces)
    if handling in ("auto", "rigid_caps"):
        # An open decorative cap sits across a small authored gap. It must keep
        # its dimensions and spacing with the closed blade, not seek skin alone.
        offset = len(vertices)
        vertices += [(.138, y, z) for y, z in
                     ((.2915, -.005), (.302, -.005), (.302, .005), (.2915, .005))]
        faces += [(offset, offset + 1, offset + 2), (offset, offset + 2, offset + 3)]
    blade = _part("dagger", vertices, faces, material="cloth", texture="")
    mesh = _mesh(_arm(), _combined_part("cloth and dagger", (cloth, blade)))
    blade_faces = list(range(len(cloth.faces), len(cloth.faces) + len(faces)))
    overrides = [] if removed or handling == "auto" else [{
        "face_indices": blade_faces, "mode": handling, "clearance_percent": 0.,
    }]
    if handling == "rigid_caps":
        overrides = [{"face_indices": group, "mode": "rigid_component", "clearance_percent": 0.}
                     for group in (blade_faces[:closed_faces], blade_faces[closed_faces:])]
    with _bound(mesh) as session:
        if removed:
            _command(session, "morph_bind", {"garment_submesh_indices": [1],
                     "excluded_faces": [{"submesh_index": 1, "face_indices": blade_faces}]})
        _command(session, "morph_configure_refit", {"garment_submesh_indices": [1], "garment_settings": [{
            "submesh_index": 1, "tightness_percent": 100., "clearance_percent": .1,
            "island_settings": overrides,
        }]})
        fitted = _snapshot(mesh, session)
        if handling == "auto":
            settings = _state(session)["refit"]["garment_settings"][0]
            assert settings["mode"] == "surface" and not settings.get("island_settings")
            _fit(session)
            assert _snapshot(mesh, session).submeshes[1].vertices == fitted.submeshes[1].vertices
    after = np.asarray(fitted.submeshes[1].vertices[len(cloth.vertices):])
    if removed:
        assert after.tolist() == [list(p) for p in vertices]
    else:
        before = np.asarray(vertices)
        assert np.max(np.abs(np.linalg.norm(before[:, None] - before[None, :], axis=2)
                             - np.linalg.norm(after[:, None] - after[None, :], axis=2))) < 1e-7
        assert np.max(np.linalg.norm(after - before, axis=1)) > .02
        _assert_no_surface_crossings(mesh.submeshes[0], fitted.submeshes[1])
    assert max(math.hypot(x, z) for x, _, z in fitted.submeshes[1].vertices[:len(cloth.vertices)]) < .08
    for field in ("faces", "uvs", "bone_weights", "bone_indices", "material"):
        assert getattr(fitted.submeshes[1], field) == getattr(mesh.submeshes[1], field)
