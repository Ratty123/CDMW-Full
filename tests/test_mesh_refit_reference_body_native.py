"""Fit to body with the body the garments were authored on (reference-body transfer)."""
from contextlib import contextmanager
import math

import numpy as np
import pytest

from cdmw.modding import mesh_native_core
from tests.test_native_mesh_editor_morph_refit import (
    _command, _open, _part, _refit_tube_part, _snapshot, _state,
)
from tests.test_mesh_refit_tightening_native import _mesh

AUTHORED_RADIUS = .06
DRIVER_RADIUS = .08
LABEL = "character/model/test/nude/authored_arm.pac"


def _arm(radius):
    # Dense like a real body: the field smooths over mesh neighbours, not metres.
    return _refit_tube_part("body", radius, 0., tuple(i * .01 for i in range(51)), 64)


def _plate():
    # A small rigid buckle outside both sleeves, on the +x side.
    vertices = [(.085, y, z) for y, z in ((.22, -.01), (.22, .01), (.26, .01), (.26, -.01))]
    return _part("buckle", vertices, [(0, 1, 2), (0, 2, 3)], material="metal", texture="")


def _outfit():
    sleeve = _refit_tube_part("sleeve", .065, 0., (.1, .15, .2, .25, .3, .35, .4), 32)
    # Close enough to the sleeve to be held as an authored layer.
    outer = _refit_tube_part("outer", .0675, 0., (.15, .2, .25, .3, .35), 32)
    return _mesh(_arm(DRIVER_RADIUS), sleeve, outer, _plate())


def _reference(radius=AUTHORED_RADIUS):
    arm = _arm(radius)
    points = np.asarray(arm.vertices, float).ravel().tolist()
    # Same skeleton on both sides: the retarget leaves the authored body in place.
    return {"label": LABEL, "source_positions": points, "fitted_positions": points,
            "faces": np.asarray(arm.faces).ravel().tolist()}


def _settings():
    return [{"submesh_index": 1, "mode": "surface", "clearance_percent": .1, "tightness_percent": 100.},
            {"submesh_index": 2, "mode": "surface", "clearance_percent": .1, "tightness_percent": 100.},
            {"submesh_index": 3, "mode": "rigid_component", "clearance_percent": .1, "tightness_percent": 100.}]


@contextmanager
def _bound(mesh):
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1, 2, 3]})
        yield session
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)


def _fit(session, reference=None):
    return _command(session, "morph_set_reference_body", {
        "reference_body": _reference() if reference is None else reference,
        "garment_submesh_indices": [1, 2, 3], "garment_settings": _settings(),
    })


def _radii(part):
    points = np.asarray(part.vertices, float)
    return np.hypot(points[:, 0], points[:, 2])


def _assert_fitted(mesh, fitted):
    # The garments follow the fatter driver instead of staying on the authored arm.
    sleeve, outer = _radii(fitted.submeshes[1]), _radii(fitted.submeshes[2])
    assert sleeve.min() >= DRIVER_RADIUS - 2e-4
    assert outer.min() >= DRIVER_RADIUS - 2e-4
    assert np.median(sleeve) == pytest.approx(.065 + DRIVER_RADIUS - AUTHORED_RADIUS, abs=3e-3)
    # Authored stacking holds: every outer vertex stays outside the inner sleeve beside it.
    inner = np.asarray(fitted.submeshes[1].vertices, float)
    for point in np.asarray(fitted.submeshes[2].vertices, float):
        nearest = inner[np.argmin(np.linalg.norm(inner - point, axis=1))]
        assert math.hypot(point[0], point[2]) > math.hypot(nearest[0], nearest[2])
    # The buckle moves as one rigid piece, out with the body.
    before, after = np.asarray(mesh.submeshes[3].vertices), np.asarray(fitted.submeshes[3].vertices)
    for a in range(len(before)):
        for b in range(a):
            assert np.linalg.norm(after[a] - after[b]) == pytest.approx(np.linalg.norm(before[a] - before[b]), abs=1e-6)
    assert after[:, 0].min() > before[:, 0].min() + .01
    # The driver itself is never moved.
    assert fitted.submeshes[0].vertices == mesh.submeshes[0].vertices


def test_reference_fit_follows_the_new_body_keeps_layers_and_rigid_shapes():
    mesh = _outfit()
    with _bound(mesh) as session:
        report = _fit(session)
        assert report["history_published"] is True
        fitted = _snapshot(mesh, session)
        _assert_fitted(mesh, fitted)
        reference = _state(session)["refit"]["reference_body"]
        assert reference["label"] == LABEL
        assert reference["vertex_count"] == len(_arm(AUTHORED_RADIUS).vertices)
        last = reference["last_fit"]
        assert last["method"] == "reference_body" and last["reference_label"] == LABEL
        assert last["rigid_groups"] == 1 and last["layer_constraints"] > 0
        assert last["remaining_body_violations"] == 0


def test_reference_fit_is_one_undoable_step_and_null_returns_to_the_bound_fitter():
    mesh = _outfit()
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
        assert mesh_native_core.undo_native_mesh_editor_session(session, timeout_seconds=15.0) is not None
        assert _state(session)["refit"]["reference_body"] is None
        undone = _snapshot(mesh, session)
        for index in (1, 2, 3):
            assert undone.submeshes[index].vertices == pytest.approx(mesh.submeshes[index].vertices)
        assert mesh_native_core.redo_native_mesh_editor_session(session, timeout_seconds=15.0) is not None
        assert _state(session)["refit"]["reference_body"]["label"] == LABEL
        redone = _snapshot(mesh, session)
        for index in (1, 2, 3):
            assert redone.submeshes[index].vertices == pytest.approx(fitted.submeshes[index].vertices)
        _command(session, "morph_set_reference_body", {"reference_body": None})
        assert _state(session)["refit"]["reference_body"] is None


def test_rebind_keeps_the_reference_and_reset_and_bake_drop_it():
    mesh = _outfit()
    with _bound(mesh) as session:
        _fit(session)
        _command(session, "morph_bind", {"garment_submesh_indices": [1, 2, 3]})
        assert _state(session)["refit"]["reference_body"]["label"] == LABEL
        _command(session, "morph_reset")
        assert _state(session)["refit"]["reference_body"] is None
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
        _command(session, "morph_bake")
        state = _state(session)
        assert state["refit"]["reference_body"] is None
        # Bake keeps the fitted shape; it is not transferred a second time.
        baked = _snapshot(mesh, session)
        for index in (1, 2, 3):
            assert baked.submeshes[index].vertices == pytest.approx(fitted.submeshes[index].vertices)


def test_reference_body_survives_a_version_5_runtime_snapshot():
    mesh = _outfit()
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
        descriptor = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(session)
        assert descriptor and descriptor["version"] == 5
        target = _open(fitted)
        try:
            assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, descriptor)
            restored = _state(target)["refit"]["reference_body"]
            assert restored["label"] == LABEL
            assert restored["face_count"] == len(_arm(AUTHORED_RADIUS).faces)
        finally:
            mesh_native_core.close_native_mesh_editor_session(target)
            mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor)



def _pulled(session, pull, parts=(1, 2, 3)):
    settings = [{**row, "skin_pull_percent": pull} for row in _settings() if row["submesh_index"] in parts]
    _command(session, "morph_set_reference_body", {
        "reference_body": _reference(), "garment_submesh_indices": list(parts), "garment_settings": settings,
    })
    return _state(session)["refit"]["reference_body"]["last_fit"]


def test_pull_to_skin_closes_the_authored_gap_and_layers_move_in_together():
    mesh = _outfit()
    results = {}
    for pull in (0., 100.):
        with _bound(mesh) as session:
            last = _pulled(session, pull)
            fitted = _snapshot(mesh, session)
            sleeve, outer = np.median(_radii(fitted.submeshes[1])), np.median(_radii(fitted.submeshes[2]))
            results[pull] = (sleeve - DRIVER_RADIUS, outer - sleeve, last["pulled_to_skin"], fitted)
    # 0% keeps the outfit's own 5 mm; 100% closes it down to the clearance, and
    # the outer layer comes in with the sleeve, keeping its spacing above it.
    assert results[0.][0] == pytest.approx(.005, abs=1.5e-3) and results[0.][2] == 0
    assert results[100.][0] < .0015 and results[100.][2] > 0
    assert results[100.][1] == pytest.approx(results[0.][1], abs=1e-3)
    _assert_rigid(mesh, results[100.][3])
    assert np.median(_radii(results[100.][3].submeshes[1])) >= DRIVER_RADIUS


def _assert_rigid(mesh, fitted):
    before, after = np.asarray(mesh.submeshes[3].vertices), np.asarray(fitted.submeshes[3].vertices)
    for a in range(len(before)):
        for b in range(a):
            assert np.linalg.norm(after[a] - after[b]) == pytest.approx(np.linalg.norm(before[a] - before[b]), abs=1e-6)


def test_pull_to_skin_leaves_cloth_hanging_well_clear_of_the_body():
    # A loose band 6 cm off the arm: beyond the pull's reach, so it keeps its drape.
    loose = _refit_tube_part("loose", AUTHORED_RADIUS + .06, 0., (.15, .2, .25, .3, .35), 32)
    mesh = _mesh(_arm(DRIVER_RADIUS), loose)
    fitted = {}
    for pull in (0., 100.):
        session = _open(mesh)
        try:
            _command(session, "morph_upload", {"profile": {
                "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
            }})
            _command(session, "morph_set_driver", {"submesh_indices": [0]})
            _command(session, "morph_bind", {"garment_submesh_indices": [1]})
            _command(session, "morph_set_reference_body", {
                "reference_body": _reference(), "garment_submesh_indices": [1],
                "garment_settings": [{"submesh_index": 1, "mode": "surface", "clearance_percent": .1,
                                      "skin_pull_percent": pull}],
            })
            fitted[pull] = np.asarray(_snapshot(mesh, session).submeshes[1].vertices, float)
        finally:
            mesh_native_core.close_native_mesh_editor_session(session)
    np.testing.assert_allclose(fitted[100.], fitted[0.], atol=1e-9)


def test_pull_to_skin_is_kept_per_part_and_island_and_survives_a_snapshot():
    mesh = _outfit()
    with _bound(mesh) as session:
        _pulled(session, 40.)
        rows = {row["submesh_index"]: row for row in _state(session)["refit"]["garment_settings"]}
        assert rows[1]["skin_pull_percent"] == 40.
        descriptor = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(session)
        target = _open(_snapshot(mesh, session))
        try:
            assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, descriptor)
            restored = {row["submesh_index"]: row for row in _state(target)["refit"]["garment_settings"]}
            assert restored[2]["skin_pull_percent"] == 40.
        finally:
            mesh_native_core.close_native_mesh_editor_session(target)
            mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor)
        with pytest.raises(AssertionError):
            _command(session, "morph_configure_refit", {"garment_submesh_indices": [1], "skin_pull_percent": 101.})


def test_an_unmarked_closed_dagger_on_cloth_fits_rigidly_through_the_reference():
    from tests.test_mesh_refit_layer_boundaries_native import _combined_part

    cloth = _refit_tube_part("cloth", .13, 0., (.1, .15, .2, .25, .3, .35, .4), 32)
    # The closed blade of test_mesh_refit_attached_details_native, sharing its cloth Part.
    outline = ((.18, 0.), (.25, -.012), (.27, -.025), (.29, -.025), (.29, .025), (.27, .025), (.25, .012))
    vertices = [(x, y, z) for x in (.131, .138) for y, z in outline]
    n = len(outline)
    faces = [(0, i + 1, i) for i in range(1, n - 1)] + [(n, n + i, n + i + 1) for i in range(1, n - 1)]
    for i in range(n):
        j = (i + 1) % n
        faces += [(i, j, n + j), (i, n + j, n + i)]
    blade = _part("dagger", vertices, faces, material="cloth", texture="")
    mesh = _mesh(_arm(DRIVER_RADIUS), _combined_part("cloth and dagger", (cloth, blade)))
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1]})
        _command(session, "morph_set_reference_body", {
            "reference_body": _reference(), "garment_submesh_indices": [1], "garment_settings": [
                {"submesh_index": 1, "mode": "surface", "clearance_percent": .1, "tightness_percent": 100.}],
        })
        fitted = _snapshot(mesh, session)
        last = _state(session)["refit"]["reference_body"]["last_fit"]
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)
    assert last["automatic_rigid_islands"] == 1 and last["rigid_groups"] == 1
    before = np.asarray(vertices)
    after = np.asarray(fitted.submeshes[1].vertices[len(cloth.vertices):])
    assert np.max(np.abs(np.linalg.norm(before[:, None] - before[None, :], axis=2)
                         - np.linalg.norm(after[:, None] - after[None, :], axis=2))) < 1e-7
    # It still follows the fatter body outward with the cloth around it.
    assert after[:, 0].mean() > before[:, 0].mean() + .01


def test_cloth_beside_an_open_body_rim_is_not_pushed_through_it():
    # A body PAC's head has the face cut out, so a hood in front of it is
    # closest to the open rim. Here a cap sits 3 mm above the open end of the
    # arm, its edge 5 mm inside the rim: nothing defines it as inside.
    rings, segments, height = 4, 32, .503
    vertices = [(0., height, 0.)] + [(r * math.cos(i * 2. * math.pi / segments), height, r * math.sin(i * 2. * math.pi / segments))
                                     for r in (.025, .05, .075)[:rings] for i in range(segments)]
    faces = [(0, 1 + (i + 1) % segments, 1 + i) for i in range(segments)]
    for ring in range(2):
        for i in range(segments):
            a, b = 1 + ring * segments + i, 1 + ring * segments + (i + 1) % segments
            faces += [(a, b, b + segments), (a, b + segments, a + segments)]
    cap = _part("cap", vertices, faces, material="cloth", texture="")
    mesh = _mesh(_arm(DRIVER_RADIUS), cap)
    driver = np.asarray(mesh.submeshes[0].vertices, float).ravel().tolist()
    # The authored body is the same arm closed at the top by a fan over its own
    # rim, so the cap is clearly outside it and is not exempt from clearance.
    top = len(mesh.submeshes[0].vertices) - 64
    authored_faces = [tuple(face) for face in mesh.submeshes[0].faces]
    authored_faces += [(top, top + i + 1, top + i) for i in range(1, 63)]
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1]})
        # Authored on this very body, so the transfer itself leaves the cap in place.
        _command(session, "morph_set_reference_body", {
            "reference_body": {"label": LABEL, "source_positions": driver, "fitted_positions": driver,
                               "faces": np.asarray(authored_faces).ravel().tolist()},
            "garment_submesh_indices": [1], "garment_settings": [
                {"submesh_index": 1, "mode": "surface", "clearance_percent": .1, "tightness_percent": 100.}],
        })
        fitted = np.asarray(_snapshot(mesh, session).submeshes[1].vertices)
        last = _state(session)["refit"]["reference_body"]["last_fit"]
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)
    assert last["open_driver_edges"] == 2 * 64
    assert np.abs(fitted - np.asarray(vertices)).max() < 5e-4


def test_an_arc_of_studs_splits_where_one_rigid_motion_would_sink_it_into_a_thicker_limb():
    # Eight studs 0.5 mm apart around the authored arm touch, so they form one
    # assembly. The driver arm is thicker: each stud moves outward in its own
    # direction, which no single rigid motion can do, so the merged arc would stay
    # inside the limb. It splits, and each stud follows the body on its own.
    vertices, faces = [], []
    step = math.radians(20)
    for k in range(8):
        centre = math.radians(-70) + k * step
        offset = len(vertices)
        vertices += [(r * math.cos(a), y, r * math.sin(a)) for r in (.0605, .0705) for y in (.24, .26)
                     for a in (centre - step / 2 + .005, centre + step / 2 - .005)]
        faces += [(offset + a, offset + b, offset + c) for a, b, c in (
            (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
            (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3))]
    studs = _part("studs", vertices, faces, material="metal", texture="")
    mesh = _mesh(_arm(DRIVER_RADIUS), studs)
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1]})
        _command(session, "morph_set_reference_body", {
            "reference_body": _reference(), "garment_submesh_indices": [1], "garment_settings": [
                {"submesh_index": 1, "mode": "rigid_component", "clearance_percent": .1, "tightness_percent": 100.}],
        })
        fitted = np.asarray(_snapshot(mesh, session).submeshes[1].vertices)
        last = _state(session)["refit"]["reference_body"]["last_fit"]
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)
    assert last["split_assemblies"] == 1 and last["rigid_groups"] == 8
    assert np.hypot(fitted[:, 0], fitted[:, 2]).min() >= DRIVER_RADIUS
    before = np.asarray(vertices)
    for k in range(8):
        stud_before, stud_after = before[k * 8:(k + 1) * 8], fitted[k * 8:(k + 1) * 8]
        assert np.abs(np.linalg.norm(stud_before[:, None] - stud_before[None], axis=2)
                      - np.linalg.norm(stud_after[:, None] - stud_after[None], axis=2)).max() < 1e-7


def test_the_body_does_not_come_through_the_faces_of_a_coarse_sleeve():
    # A hexagonal sleeve clears the authored arm with every face. The transfer
    # carries its corners out with the thicker driver arm, but each flat face
    # spans the curve between two corners, so without the skin rows the driver
    # comes about 2 mm through the middle of every face while each corner keeps
    # its clearance.
    sleeve = _refit_tube_part("sleeve", .07, 0., tuple(.1 + i * .05 for i in range(7)), 6)
    mesh = _mesh(_arm(DRIVER_RADIUS), sleeve)
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1]})
        _command(session, "morph_set_reference_body", {
            "reference_body": _reference(), "garment_submesh_indices": [1], "garment_settings": [
                {"submesh_index": 1, "mode": "surface", "clearance_percent": .1, "tightness_percent": 100.}],
        })
        fitted = _snapshot(mesh, session).submeshes[1]
        last = _state(session)["refit"]["reference_body"]["last_fit"]
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)
    assert last["skin_constraints"] > 0
    corners = np.asarray(fitted.vertices, float)[np.asarray(fitted.faces)]
    steps = np.linspace(0., 1., 11)
    weights = np.array([(u, v, 1. - u - v) for u in steps for v in steps if u + v <= 1. + 1e-9])
    samples = np.einsum("wk,fkd->fwd", weights, corners).reshape(-1, 3)
    # Away from the open hems, where the arm is beside the sleeve rather than under it.
    inner = (samples[:, 1] > .11) & (samples[:, 1] < .39)
    assert np.hypot(samples[inner, 0], samples[inner, 2]).min() >= DRIVER_RADIUS - 2e-4


def _weighted_scene():
    # The arm is weighted to bone 0 below 0.2, bone 1 above 0.3 and blends between.
    # The sleeve and a stud sitting across the blend start on bone 2.
    arm = _arm(DRIVER_RADIUS)
    rows = []
    for _x, y, _z in arm.vertices:
        upper = min(max((y - .2) / .1, 0.), 1.)
        rows.append(((0,), (1.,)) if upper == 0. else ((1,), (1.,)) if upper == 1. else ((0, 1), (1. - upper, upper)))
    arm.bone_indices, arm.bone_weights = [row[0] for row in rows], [row[1] for row in rows]
    sleeve = _refit_tube_part("sleeve", .065, 0., (.1, .15, .2, .25, .3, .35, .4), 32)
    vertices = [(x, y, z) for x in (.0605, .0705) for y in (.2, .3) for z in (-.01, .01)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    stud = _part("stud", vertices, faces, material="metal", texture="")
    for part in (sleeve, stud):
        part.bone_indices, part.bone_weights = [(2,)] * len(part.vertices), [(1.,)] * len(part.vertices)
    return _mesh(arm, sleeve, stud)


def _weight_transfer(mesh, capacity=6):
    return {"driver_bones": [{"submesh_index": 0, "bones": [0, 1, 2]}],
            "garments": [{"submesh_index": index, "slots": [0, 1, 2],
                          "capacities": [capacity] * len(mesh.submeshes[index].vertices)} for index in (1, 2)]}


@contextmanager
def _weighted_fit(mesh, transfer):
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1, 2]})
        _command(session, "morph_set_reference_body", {
            "reference_body": _reference(), "garment_submesh_indices": [1, 2], "weight_transfer": transfer,
            "garment_settings": [
                {"submesh_index": 1, "mode": "surface", "clearance_percent": .1, "tightness_percent": 100.},
                {"submesh_index": 2, "mode": "rigid_component", "clearance_percent": .1, "tightness_percent": 100.}],
        })
        yield session
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)


def _rows(part):
    return [dict(zip(indices, weights)) for indices, weights in zip(part.bone_indices, part.bone_weights)]


def test_fit_gives_cloth_near_the_body_its_weights_and_a_rigid_piece_one_set():
    mesh = _weighted_scene()
    with _weighted_fit(mesh, _weight_transfer(mesh)) as session:
        fitted = _snapshot(mesh, session)
        weights = _state(session)["refit"]["reference_body"]["last_fit"]["weights"]
    assert weights["changed_parts"] == [1, 2] and weights["dropped_bone_mass"] == 0
    sleeve = _rows(fitted.submeshes[1])
    for (_x, y, _z), row in zip(mesh.submeshes[1].vertices, sleeve):
        assert len(row) <= 6 and sum(row.values()) == pytest.approx(1.)
        # The body's share follows the arm beneath: bone 0 low, bone 1 high.
        if y <= .15:
            assert row.get(0, 0.) > .3 and 1 not in row
        if y >= .35:
            assert row.get(1, 0.) > .3 and 0 not in row
    stud = _rows(fitted.submeshes[2])
    assert all(row == stud[0] for row in stud) and stud[0].get(2, 0.) < 1.
    # The driver keeps its own weights.
    assert fitted.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices


def test_weights_undo_with_the_fit_reset_restores_them_and_bake_keeps_them():
    mesh = _weighted_scene()
    own = _rows(mesh.submeshes[1])
    with _weighted_fit(mesh, _weight_transfer(mesh)) as session:
        fitted = _rows(_snapshot(mesh, session).submeshes[1])
        assert fitted != own
        assert mesh_native_core.undo_native_mesh_editor_session(session, timeout_seconds=15.0) is not None
        assert _rows(_snapshot(mesh, session).submeshes[1]) == own
        assert mesh_native_core.redo_native_mesh_editor_session(session, timeout_seconds=15.0) is not None
        assert _rows(_snapshot(mesh, session).submeshes[1]) == fitted
        _command(session, "morph_reset")
        assert _rows(_snapshot(mesh, session).submeshes[1]) == own
    with _weighted_fit(mesh, _weight_transfer(mesh)) as session:
        _command(session, "morph_set_reference_body", {"reference_body": None})
        assert _rows(_snapshot(mesh, session).submeshes[1]) == own
    with _weighted_fit(mesh, _weight_transfer(mesh)) as session:
        _command(session, "morph_bake")
        baked = _rows(_snapshot(mesh, session).submeshes[1])
        assert baked == fitted
        _command(session, "morph_reset")
        assert _rows(_snapshot(mesh, session).submeshes[1]) == baked


def test_a_restored_snapshot_still_gives_back_the_own_weights_on_reset():
    mesh = _weighted_scene()
    own = _rows(mesh.submeshes[1])
    with _weighted_fit(mesh, _weight_transfer(mesh)) as session:
        fitted = _snapshot(mesh, session)
        descriptor = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(session)
    target = _open(fitted)
    try:
        assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, descriptor)
        _command(target, "morph_reset")
        assert _rows(_snapshot(fitted, target).submeshes[1]) == own
    finally:
        mesh_native_core.close_native_mesh_editor_session(target)
        mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor)


def test_cloth_made_not_to_follow_the_authored_body_keeps_its_weights():
    mesh = _weighted_scene()
    authored = len(_arm(AUTHORED_RADIUS).vertices)

    def transfer(sleeve_lift):
        # One test pose: the authored arm stays put; the sleeve, as authored, lifts by sleeve_lift.
        table = _weight_transfer(mesh)
        for row in table["garments"]:
            count = len(mesh.submeshes[row["submesh_index"]].vertices)
            row["motion"] = [0., sleeve_lift if row["submesh_index"] == 1 else 0., 0.] * count
        table["motion_poses"] = 1
        table["reference_motion"] = [0.] * (3 * authored)
        return table

    # As authored, the sleeve moved with the arm beneath it: it takes the driver's weights.
    with _weighted_fit(mesh, transfer(0.)) as session:
        assert _rows(_snapshot(mesh, session).submeshes[1]) != _rows(mesh.submeshes[1])
    # A sleeve that left the authored arm 5 cm behind was made not to follow it: it keeps its own.
    with _weighted_fit(mesh, transfer(.05)) as session:
        assert _rows(_snapshot(mesh, session).submeshes[1]) == _rows(mesh.submeshes[1])


def test_rows_keep_each_vertex_capacity_and_nothing_changes_without_a_table():
    mesh = _weighted_scene()
    with _weighted_fit(mesh, _weight_transfer(mesh, capacity=1)) as session:
        rows = _rows(_snapshot(mesh, session).submeshes[1])
    assert all(len(row) == 1 and next(iter(row.values())) == pytest.approx(1.) for row in rows)
    with _weighted_fit(mesh, None) as session:
        assert _rows(_snapshot(mesh, session).submeshes[1]) == _rows(mesh.submeshes[1])


def test_reference_body_requires_a_binding_and_matching_arrays():
    mesh = _outfit()
    session = _open(mesh)
    try:
        assert mesh_native_core.native_mesh_editor_session_command(
            "morph_set_reference_body", session, {"reference_body": _reference()}, timeout_seconds=15.0) is None
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)
    with _bound(mesh) as session:
        broken = dict(_reference(), fitted_positions=_reference()["fitted_positions"][:-3])
        assert mesh_native_core.native_mesh_editor_session_command(
            "morph_set_reference_body", session, {"reference_body": broken}, timeout_seconds=15.0) is None
        assert _state(session)["refit"]["reference_body"] is None
