"""Fit cloth across missing body surfaces without copying the body's holes."""

import math

import pytest

from tests.test_mesh_refit_tightening_native import (
    _arm, _bound, _fit, _mesh, _refit_tube_part, _snapshot,
)


def _front_opening(part, low, high):
    kept, rim = [], set()
    for face in part.faces:
        points = [part.vertices[i] for i in face]
        center = tuple(sum(p[c] for p in points) / 3 for c in range(3))
        if low < center[1] < high and center[2] < -.065:
            rim.update(face)
        else:
            kept.append(face)
    part.faces = kept
    used = {i for face in kept for i in face}
    return sorted(rim & used)


@pytest.mark.parametrize("rotated", (False, True))
def test_face_cover_keeps_its_eye_opening_over_a_missing_body_face(rotated):
    heights = (0., 1., 1.06, 1.14, 1.22, 1.30, 1.38, 1.42, 1.46, 1.54, 1.62, 1.70, 1.8)
    body = _refit_tube_part("incomplete body", .09, 0., heights, 32, True)
    _front_opening(body, 1.22, 1.62)
    hood = _refit_tube_part("cover", .12, 0., heights[2:-1], 32)
    rim = _front_opening(hood, 1.42, 1.46)
    # Remove unused vertices, as an imported mesh need not retain the deleted face.
    for part in (body, hood):
        used = sorted({i for face in part.faces for i in face})
        remap = {old: new for new, old in enumerate(used)}
        if part is hood:
            rim = [remap[i] for i in rim]
        part.vertices = [part.vertices[i] for i in used]
        part.faces = [tuple(remap[i] for i in face) for face in part.faces]
        for attribute in ("uvs", "normals", "tangents", "bone_indices", "bone_weights", "source_vertex_map"):
            values = getattr(part, attribute)
            setattr(part, attribute, [values[i] for i in used])
        part.vertex_count, part.face_count = len(part.vertices), len(part.faces)
        if rotated:
            part.vertices = [(z, x, y) for x, y, z in part.vertices]
    mesh = _mesh(body, hood)
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
    height_axis = 2 if rotated else 1
    opening = [fitted.submeshes[1].vertices[i][height_axis] for i in rim]
    assert max(opening) - min(opening) < .07
    assert min(opening) > 1.40
    assert max(opening) < 1.48
    assert fitted.submeshes[0].vertices == body.vertices
    for attribute in ("faces", "uvs", "bone_indices", "bone_weights", "source_vertex_map"):
        assert getattr(fitted.submeshes[1], attribute) == getattr(hood, attribute)


@pytest.mark.parametrize("rings", (2, 3))
@pytest.mark.parametrize("body_length", (.5, 2.))
def test_narrow_band_tightens_without_needing_an_interior_vertex_row(rings, body_length):
    body = _arm()
    body.vertices = [(x, y * body_length / .5, z) for x, y, z in body.vertices]
    band = _refit_tube_part(
        "band", .10, 0., tuple(.2 + .02 * i / (rings - 1) for i in range(rings)), 32,
    )
    mesh = _mesh(body, band)
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session).submeshes[1]
    # A remote extension of the body must not make this unchanged band rigid.
    clearance = .001 * math.sqrt(body_length ** 2 + 2 * .12 ** 2)
    assert max(math.hypot(x, z) for x, _, z in fitted.vertices) < .06 + 2 * clearance + .002
    assert min(math.hypot(x, z) for x, _, z in fitted.vertices) > .06
    assert [y for _, y, _ in fitted.vertices] == pytest.approx(
        [y for _, y, _ in band.vertices], abs=.002,
    )
    assert fitted.faces == band.faces


def test_open_band_rim_follows_a_tapering_body():
    body = _arm()
    body.vertices = [(x * (1.5 - 2 * y), y, z * (1.5 - 2 * y))
                     for x, y, z in body.vertices]
    band = _refit_tube_part("waist wrap", .12, 0., (.1, .15, .2, .25, .3, .35, .4), 32)
    mesh = _mesh(body, band)
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session).submeshes[1]
    for ring, height in ((0, .1), (6, .4)):
        radii = [math.hypot(x, z) for x, _, z in fitted.vertices[ring * 32:(ring + 1) * 32]]
        body_radius = .06 * (1.5 - 2 * height)
        assert min(radii) > body_radius
        assert max(radii) < body_radius + .005
