"""Hard ornaments retain authored surface joins without welding their vertices."""
import math

import pytest

from tests.test_mesh_refit_tightening_native import _arm, _bound, _fit, _mesh
from tests.test_native_mesh_editor_morph_refit import (
    _command, _part, _snapshot, _state, mesh_native_core,
)


def _ornaments(close=False):
    first = _part("pendant", [(-.025, .2, .13), (.025, .2, .13),
                              (.025, .3, .13), (-.025, .3, .13)],
                  [(0, 1, 2), (0, 2, 3)], material="metal", texture="")
    second = _part("attachment", [(x, y, .12 + x) for x, y in
                                   ((-.035, .24), (.035, .24), (.035, .26), (-.035, .26))],
                   [(0, 1, 2), (0, 2, 3)], material="trim", texture="")
    if close:
        # A small authored gap, with no matching seam or shared vertices.
        second.vertices = [(.0251, .24, .13), (.0451, .24, .13),
                           (.0451, .26, .13), (.0251, .26, .13)]
    return first, second


def _assert_rigid(original, actual):
    for a in range(len(original)):
        for b in range(a):
            assert math.dist(actual[a], actual[b]) == pytest.approx(
                math.dist(original[a], original[b]), abs=1e-7)


@pytest.mark.parametrize("packed", (False, True), ids=("material-parts", "one-part"))
@pytest.mark.parametrize("close", (False, True), ids=("overlapping-join", "small-join-gap"))
def test_joined_rigid_shells_keep_shape_and_spacing_while_fitting(packed, close):
    first, second = _ornaments(close)
    original = first.vertices + second.vertices
    if packed:
        parts = [_part("assembly", original,
                       first.faces + [tuple(i + 4 for i in face) for face in second.faces],
                       material="metal", texture="")]
    else:
        parts = [first, second]
    mesh = _mesh(_arm(), *parts)
    with _bound(mesh) as session:
        _fit(session, tuple(range(1, len(mesh.submeshes))), mode="rigid_component")
        result = _snapshot(mesh, session)
        _fit(session, tuple(range(1, len(mesh.submeshes))), mode="rigid_component")
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [
            p.vertices for p in result.submeshes]
    actual = [point for part in result.submeshes[1:] for point in part.vertices]
    assert max(math.dist(a, b) for a, b in zip(original, actual)) > .02
    # Cross-piece distances also stay fixed: no detached joins, new collisions,
    # enlarged rings or tilted pendants hidden by per-piece rigidity checks.
    _assert_rigid(original, actual)
    for start in (0, 4):
        assert tuple(actual[start + 1][axis] - actual[start][axis] for axis in range(3)) == pytest.approx(
            tuple(original[start + 1][axis] - original[start][axis] for axis in range(3)), abs=1e-7)
    for part in result.submeshes[1:]:
        samples = list(part.vertices)
        for face in part.faces:
            triangle = [part.vertices[i] for i in face]
            samples.append(tuple(sum(v[c] for v in triangle) / 3 for c in range(3)))
            samples.extend(tuple((a[c] + b[c]) / 2 for c in range(3))
                           for a, b in zip(triangle, triangle[1:] + triangle[:1]))
        assert min(math.hypot(x, z) for x, _, z in samples) > .06
    assert result.submeshes[0].vertices == mesh.submeshes[0].vertices
    for before, after in zip(mesh.submeshes, result.submeshes):
        assert before.faces == after.faces


def test_close_separate_rigid_shells_keep_independent_protection():
    parts = [_part("plate", [(-.02, .2, z), (.02, .2, z), (.02, .3, z), (-.02, .3, z)],
                   [(0, 1, 2), (0, 2, 3)], material="metal", texture="")
             for z in (.13, .131)]
    mesh = _mesh(_arm(), *parts)
    with _bound(mesh) as session:
        _command(session, "morph_configure_refit", {
            "garment_submesh_indices": [1, 2], "garment_settings": [
                {"submesh_index": i, "mode": "rigid_component", "tightness_percent": 100.,
                 "clearance_percent": .1, "vertex_mask":
                     {"vertex_indices": [], "weights": []} if i == 2 else None}
                for i in (1, 2)
            ]})
        fitted = _snapshot(mesh, session)
    assert fitted.submeshes[2].vertices == parts[1].vertices
    assert max(math.dist(a, b) for a, b in
               zip(parts[0].vertices, fitted.submeshes[1].vertices)) > .0005


def _upload_field(session, part, deltas, *, stage="base"):
    _command(session, "morph_upload", {"profile": {
        "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
        "definitions": [{"definition_id": "control", "label": "Control",
                         "min_percent": 0., "max_percent": 100., "default_percent": 0.}],
        "fields": [{"definition_id": "control", "stage": stage, "submesh_index": part,
                    "vertex_indices": list(range(len(deltas))), "deltas": deltas}],
    }})


def test_joined_rigid_assembly_can_still_rotate_with_the_body():
    mesh = _mesh(_arm(), *_ornaments())
    angle = math.radians(40)
    deltas = [[x * math.cos(angle) + z * math.sin(angle) - x, 0.,
               z * math.cos(angle) - x * math.sin(angle) - z]
              for x, _, z in mesh.submeshes[0].vertices]
    with _bound(mesh) as session:
        _upload_field(session, 0, deltas)
        _fit(session, (1, 2), tightness=0., clearance_percent=0., mode="rigid_component")
        _command(session, "morph_change", {
            "definition_id": "control", "value": 100., "phase": "end", "change_id": "turn"})
        result = _snapshot(mesh, session)
    original = [p for part in mesh.submeshes[1:] for p in part.vertices]
    actual = [p for part in result.submeshes[1:] for p in part.vertices]
    _assert_rigid(original, actual)
    assert max(math.dist(a, b) for a, b in zip(original, actual)) > .03
    assert abs(actual[1][2] - actual[0][2]) > .01


def test_protected_piece_cannot_be_dragged_by_its_rigid_assembly():
    mesh = _mesh(_arm(), *_ornaments())
    with _bound(mesh) as session:
        before = _state(session)
        assert mesh_native_core.native_mesh_editor_session_command("morph_configure_refit", session, {
            "garment_submesh_indices": [1, 2], "mode": "rigid_component",
            "tightness_percent": 100., "clearance_percent": .1,
            "vertex_masks": [{"submesh_index": 2, "vertex_indices": [], "weights": []}],
        }) is None
        assert "uniform vertex masks" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session) == before
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [
            p.vertices for p in mesh.submeshes]


def test_post_fit_correction_cannot_detach_a_rigid_assembly_piece():
    mesh = _mesh(_arm(), *_ornaments())
    with _bound(mesh) as session:
        _upload_field(session, 2, [[.01, 0., 0.]] * 4, stage="post_refit")
        _fit(session, (1, 2), mode="rigid_component")
        before = _state(session)
        fitted = _snapshot(mesh, session)
        assert mesh_native_core.native_mesh_editor_session_command("morph_change", session, {
            "definition_id": "control", "value": 100., "phase": "end", "change_id": "detach",
        }) is None
        assert "rigid assembly" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session) == before
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [
            p.vertices for p in fitted.submeshes]


def _flexible_band_and_pendant():
    body = _part("body", [(-.2, 0., 0.), (.2, 0., 0.), (.2, .5, 0.), (-.2, .5, 0.)],
                 [(0, 1, 2), (0, 2, 3)], material="skin", texture="")
    band = _part("flexible band", [(-.05, .3, .04), (.05, .3, .04),
                                   (.05, .32, .04), (-.05, .32, .04)],
                 [(0, 1, 2), (0, 2, 3)], material="cloth", texture="")
    pendant = _part("pendant", [(-.01, .15, .04), (.01, .15, .04),
                                (.01, .3, .04), (-.01, .3, .04)],
                    [(0, 1, 2), (0, 2, 3)], material="metal", texture="")
    return _mesh(body, band, pendant)


def _midpoint(part, first, second):
    return tuple((a + b) / 2 for a, b in zip(part.vertices[first], part.vertices[second]))


@pytest.mark.parametrize("tightness", (0., 50., 100.))
def test_rigid_pendant_tracks_its_flexible_attachment_during_body_changes(tightness):
    mesh = _flexible_band_and_pendant()
    with _bound(mesh) as session:
        # A nonuniform body change moves the band farther sideways than the
        # pendant's centre. Averaging body targets alone detaches their join.
        _upload_field(session, 0, [[.5 * y, 0., 0.] for _, y, _ in mesh.submeshes[0].vertices])
        _command(session, "morph_configure_refit", {
            "garment_submesh_indices": [1, 2], "garment_settings": [
                {"submesh_index": i, "mode": "surface" if i == 1 else "rigid_component",
                 "tightness_percent": tightness, "clearance_percent": .1}
                for i in (1, 2)],
        })
        before = _snapshot(mesh, session)
        _command(session, "morph_change", {
            "definition_id": "control", "value": 100., "phase": "end", "change_id": "shear"})
        fitted = _snapshot(mesh, session)
        assert _midpoint(fitted.submeshes[2], 2, 3) == pytest.approx(
            _midpoint(fitted.submeshes[1], 0, 1), abs=2e-5)
        _assert_rigid(mesh.submeshes[2].vertices, fitted.submeshes[2].vertices)
        assert fitted.submeshes[1].vertices != before.submeshes[1].vertices
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [p.vertices for p in before.submeshes]
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [p.vertices for p in fitted.submeshes]


@pytest.mark.parametrize("tightness", (50., 100.))
def test_rigid_necklace_assembly_tracks_flexible_fit_on_a_sloping_body(tightness):
    mesh = _flexible_band_and_pendant()
    mesh.submeshes[0].vertices = [(x, y, .2 * y) for x, y, _ in mesh.submeshes[0].vertices]
    for part in mesh.submeshes[1:]:
        part.vertices = [(x, y, .15) for x, y, _ in part.vertices]
    pendant = mesh.submeshes[2]
    ring = _part("ring", [(-.014, .282, .15), (.014, .282, .15),
                          (.014, .302, .15), (-.014, .302, .15)],
                 [(0, 1, 2), (0, 2, 3)], material="trim", texture="")
    mesh = _mesh(*mesh.submeshes, ring)
    with _bound(mesh) as session:
        _command(session, "morph_configure_refit", {
            "garment_submesh_indices": [1, 2, 3], "garment_settings": [
                {"submesh_index": i, "mode": "surface" if i == 1 else "rigid_component",
                 "tightness_percent": tightness, "clearance_percent": .1}
                for i in (1, 2, 3)],
        })
        fitted = _snapshot(mesh, session)
        assert _midpoint(fitted.submeshes[2], 2, 3) == pytest.approx(
            _midpoint(fitted.submeshes[1], 0, 1), abs=5e-5)
        _assert_rigid(pendant.vertices + ring.vertices,
                      fitted.submeshes[2].vertices + fitted.submeshes[3].vertices)
        assert fitted.submeshes[2].vertices[0][2] < fitted.submeshes[2].vertices[3][2] - .01
        assert fitted.submeshes[0].vertices == mesh.submeshes[0].vertices


@pytest.mark.parametrize("intensity,mask", ((50., None), (100., .5), (50., .5), (0., None)))
def test_flexible_attachment_does_not_apply_follow_strength_twice(intensity, mask):
    mesh = _flexible_band_and_pendant()
    with _bound(mesh) as session:
        _upload_field(session, 0, [[.5 * y, 0., 0.] for _, y, _ in mesh.submeshes[0].vertices])
        _command(session, "morph_configure_refit", {
            "garment_submesh_indices": [1, 2], "garment_settings": [
                {"submesh_index": i, "mode": "surface" if i == 1 else "rigid_component",
                 "intensity_percent": intensity, "clearance_percent": 0.,
                 "vertex_mask": None if mask is None else {
                     "vertex_indices": list(range(4)), "weights": [mask] * 4}}
                for i in (1, 2)],
        })
        _command(session, "morph_change", {
            "definition_id": "control", "value": 100., "phase": "end", "change_id": "strength"})
        fitted = _snapshot(mesh, session)
        expected = (.15 * intensity / 100. * (1. if mask is None else mask), .3, .04)
        assert _midpoint(fitted.submeshes[1], 0, 1) == pytest.approx(expected, abs=1e-7)
        assert _midpoint(fitted.submeshes[2], 2, 3) == pytest.approx(expected, abs=1e-7)
        _assert_rigid(mesh.submeshes[2].vertices, fitted.submeshes[2].vertices)


@pytest.mark.parametrize("case", ("skipped", "different-intensity", "protected", "distant", "nearby-edge", "nearby-layer"))
def test_unrelated_or_independently_configured_cloth_does_not_capture_the_necklace(case):
    mesh = _flexible_band_and_pendant()
    if case in ("distant", "nearby-edge"):
        distance = 1. if case == "distant" else .005
        mesh.submeshes[1].vertices = [(x, y + distance, z) for x, y, z in mesh.submeshes[1].vertices]
    elif case == "nearby-layer":
        # Cloth behind an ornament is contact geometry, not an authored join.
        mesh.submeshes[1].vertices = [(x, y, z - .003) for x, y, z in mesh.submeshes[1].vertices]
    results = []
    for enabled in (False, True):
        with _bound(mesh) as session:
            _upload_field(session, 0, [[.5 * y, 0., 0.] for _, y, _ in mesh.submeshes[0].vertices])
            band_settings = {"submesh_index": 1, "mode": "surface", "clearance_percent": 0.,
                             "enabled": enabled and case != "skipped"}
            if case == "different-intensity":
                band_settings["intensity_percent"] = 50.
            elif case == "protected":
                band_settings["vertex_mask"] = {"vertex_indices": [], "weights": []}
            _command(session, "morph_configure_refit", {
                "garment_submesh_indices": [1, 2], "garment_settings": [band_settings,
                    {"submesh_index": 2, "mode": "rigid_component", "clearance_percent": 0.}],
            })
            _command(session, "morph_change", {
                "definition_id": "control", "value": 100., "phase": "end", "change_id": case})
            results.append(_snapshot(mesh, session).submeshes[2].vertices)
    assert results[0] == results[1]


@pytest.mark.parametrize("offset", (0., .015), ids=("centred", "saved-off-centre"))
def test_unattached_rigid_plate_clears_a_symmetric_body_without_sideways_drift(offset):
    plate = _part("plate", [(-.045, .2, .13), (.045, .2, .13),
                            (.045, .3, .13), (-.045, .3, .13)],
                  [(0, 1, 2), (0, 2, 3)], material="metal", texture="")
    plate.vertices = [(x + offset, y, z) for x, y, z in plate.vertices]
    mesh = _mesh(_arm(), plate)
    with _bound(mesh) as session:
        _fit(session, mode="rigid_component")
        fitted = _snapshot(mesh, session).submeshes[1]
    _assert_rigid(plate.vertices, fitted.vertices)
    assert sum(v[0] for v in fitted.vertices) / len(fitted.vertices) == pytest.approx(0., abs=2e-5)
    samples = fitted.vertices + [tuple(sum(fitted.vertices[i][axis] for i in face) / 3
                                       for axis in range(3)) for face in fitted.faces]
    assert min(math.hypot(x, z) for x, _, z in samples) > .06


@pytest.mark.parametrize("gap", (0., .003), ids=("touching", "nearby"))
def test_nearby_headwrap_cannot_slide_a_rigid_necklace_around_the_body(gap):
    z = .1 - gap
    headwrap = _part("headwrap", [(-.045, .3, z), (-.025, .3, z),
                                 (-.025, .34, z), (-.045, .34, z)],
                     [(0, 1, 2), (0, 2, 3)], material="cloth", texture="")
    vertices, faces = [], []
    for left, right, bottom, top in ((-.04, -.03, .2, .4), (.03, .04, .2, .4),
                                      (-.04, .04, .19, .21)):
        offset = len(vertices)
        vertices.extend(((left, bottom, .10), (right, bottom, .10),
                         (right, top, .10), (left, top, .10)))
        faces.extend(((offset, offset + 1, offset + 2), (offset, offset + 2, offset + 3)))
    necklace = _part("necklace", vertices, faces, material="metal", texture="")
    mesh = _mesh(_arm(), headwrap, necklace)
    with _bound(mesh) as session:
        request = {"garment_submesh_indices": [1, 2], "garment_settings": [
            {"submesh_index": i, "mode": "surface" if i == 1 else "rigid_component",
             "tightness_percent": 100., "clearance_percent": .1} for i in (1, 2)]}
        _command(session, "morph_configure_refit", request)
        fitted = _snapshot(mesh, session)
        _assert_rigid(necklace.vertices, fitted.submeshes[2].vertices)
        assert sum(v[0] for v in fitted.submeshes[2].vertices) / len(vertices) == pytest.approx(0., abs=2e-5)
        assert fitted.submeshes[1].vertices != headwrap.vertices
        assert min(math.hypot(x, z) for x, _, z in fitted.submeshes[2].vertices) > .06
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [p.vertices for p in mesh.submeshes]
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        _command(session, "morph_configure_refit", request)
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [p.vertices for p in fitted.submeshes]


@pytest.mark.parametrize("tightness,weight", ((0., 1.), (50., 1.), (100., .5), (100., 0.)))
def test_rigid_centring_respects_tightness_and_zero_influence(tightness, weight):
    plate = _part("offset plate", [(-.03, .2, .13), (.06, .2, .13),
                                   (.06, .3, .13), (-.03, .3, .13)],
                  [(0, 1, 2), (0, 2, 3)], material="metal", texture="")
    mesh = _mesh(_arm(), plate)
    with _bound(mesh) as session:
        _fit(session, mode="rigid_component", tightness=tightness, vertex_masks=[{
            "submesh_index": 1, "vertex_indices": list(range(4)), "weights": [weight] * 4,
        }])
        fitted = _snapshot(mesh, session).submeshes[1]
    _assert_rigid(plate.vertices, fitted.vertices)
    assert sum(v[0] for v in fitted.vertices) / 4 == pytest.approx(
        .015 * (1. - tightness / 100. * weight), abs=2e-5)
    if tightness == 0. or weight == 0.:
        assert fitted.vertices == plate.vertices
