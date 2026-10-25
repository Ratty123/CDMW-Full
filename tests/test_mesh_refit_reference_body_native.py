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
