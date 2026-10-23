"""Clear local body intersections without tailoring loose cloth to the legs."""
import numpy as np
import pytest

from tests.test_mesh_refit_layer_boundaries_native import _combined_part
from tests.test_mesh_refit_tightening_native import (
    _arm, _assert_no_surface_crossings, _bound, _fit, _mesh, _refit_tube_part, _sleeve, _snapshot,
)
from tests.test_native_mesh_editor_morph_refit import _command, _open, _state, mesh_native_core


@pytest.mark.parametrize("contact", ("clear", "bodice", "sleeves"))
@pytest.mark.parametrize("packed,rotated", ((False, False), (True, False), (True, True)))
def test_clearance_preserves_skirt_volume_and_trim_while_repairing_local_contact(contact, packed, rotated):
    body = _combined_part("body", [
        _refit_tube_part("torso", .12, 0., (.95, 1.1, 1.3, 1.5, 1.7), 48, True),
        *[_refit_tube_part("leg", .055, x, (0., .3, .6, .9, 1.), 32, True) for x in (-.07, .07)],
        *[_refit_tube_part("arm", .05, x, (.95, 1.1, 1.3, 1.5, 1.65), 32, True) for x in (-.29, .29)],
    ])
    heights = (.1, .3, .6, .85, 1., 1.1, 1.2, 1.4, 1.6)
    bodice_radius = .10 if contact == "bodice" else .15
    radii = (.33, .30, .26, .22, .18, .16, bodice_radius, bodice_radius, bodice_radius)
    dress = _refit_tube_part("same fabric across bodice and skirt", 1., 0., heights, 32)
    dress.vertices = [(x * radii[heights.index(y)], y, z * radii[heights.index(y)])
                      for x, y, z in dress.vertices]
    sleeves = [_refit_tube_part("same fabric sleeves", .035 if contact == "sleeves" else .075,
                               x, (1.05, 1.2, 1.35, 1.5), 24) for x in (-.29, .29)]
    cord = _refit_tube_part("hanging cord", .003, .03, (.2, .4, .6, .8), 8)
    cord.vertices = [(x, y, z-.35) for x, y, z in cord.vertices]
    garments = [_combined_part("all cloth in one material", [dress, *sleeves, cord])] if packed else [dress, *sleeves, cord]
    if rotated:
        for p in (body, *garments):
            p.vertices = [(z, x, y) for x, y, z in p.vertices]
    mesh = _mesh(body, *garments)
    with _bound(mesh) as session:
        _fit(session, tuple(range(1, len(mesh.submeshes))), tightness=0.)
        fitted = _snapshot(mesh, session)
    assert fitted.submeshes[0].vertices == body.vertices
    before = np.concatenate([np.asarray(p.vertices) for p in garments])
    after = np.concatenate([np.asarray(p.vertices) for p in fitted.submeshes[1:]])
    if rotated:
        before, after = before[:, [1, 2, 0]], after[:, [1, 2, 0]]
    # The same connected Part includes the fitted bodice and unsupported skirt.
    # Neither material names nor island splits may turn that skirt into leggings.
    lower_skirt = np.arange(4 * 32)
    assert np.max(np.linalg.norm(after[lower_skirt]-before[lower_skirt], axis=1)) < .0002
    assert np.ptp(after[:32, 0]) == pytest.approx(np.ptp(before[:32, 0]), abs=.0002)
    assert np.ptp(after[:32, 2]) == pytest.approx(np.ptp(before[:32, 2]), abs=.0002)
    cord_start = len(dress.vertices) + sum(len(p.vertices) for p in sleeves)
    assert np.max(np.linalg.norm(after[cord_start:]-before[cord_start:], axis=1)) < .0002
    if contact == "clear":
        assert np.max(np.linalg.norm(after-before, axis=1)) < .0002
    else:
        assert np.max(np.linalg.norm(after-before, axis=1)) > .01
    for old, new in zip(garments, fitted.submeshes[1:]):
        for channel in ("faces", "uvs", "bone_indices", "bone_weights", "name", "material"):
            assert getattr(old, channel) == getattr(new, channel)
        _assert_no_surface_crossings(body, new)


def test_clearance_only_fit_rejects_a_post_refit_field_that_reintroduces_body_intersections():
    mesh = _mesh(_arm(), _sleeve(radius=.13))
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
            "definitions": [{"definition_id": "shrink", "label": "Shrink", "category": "Cloth",
                             "min_percent": 0., "max_percent": 100., "default_percent": 0.}],
            "fields": [{"definition_id": "shrink", "stage": "post_refit", "submesh_index": 1,
                        "vertex_indices": list(range(len(mesh.submeshes[1].vertices))),
                        "deltas": [[-.8*x, 0., -.8*z] for x, y, z in mesh.submeshes[1].vertices]}],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1]})
        _fit(session, tightness=0.)
        before, state = _snapshot(mesh, session), _state(session)
        reply = mesh_native_core.native_mesh_editor_session_command("morph_change", session, {
            "definition_id": "shrink", "value": 100., "phase": "end", "change_id": "invalid-post-refit",
        }, timeout_seconds=15.)
        assert reply is None
        assert "cannot clear the body" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session) == state
        assert _snapshot(mesh, session).submeshes[1].vertices == before.submeshes[1].vertices
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)


@pytest.mark.parametrize("segments", (24, 48))
@pytest.mark.parametrize("tilted", (False, True))
@pytest.mark.parametrize("rolled", (False, True), ids=("plain", "rolled"))
@pytest.mark.parametrize("scale,rotated", ((.25, False), (3., True)))
def test_clearance_keeps_an_open_hem_below_a_sloping_hip(segments, tilted, rolled, scale, rotated):
    heights = (0., .3, .45, .6, .75, .9, 1.2)
    radii = (.18, .22, .21, .18, .14, .13, .13)
    body = _refit_tube_part("body", 1., 0., heights, 48, True)
    body.vertices = [(x * radii[heights.index(y)], y, z * radii[heights.index(y)])
                     for x, y, z in body.vertices]
    hem_height = .45
    garment_heights = ((hem_height,) if rolled else ()) + (hem_height, .55, .65, .75, .85, 1.)
    garment = _refit_tube_part("open shirt", .16, 0., garment_heights, segments)
    if rolled:
        # A folded-in rim ends in a horizontal annulus. Its immediate face
        # normal does not identify the length direction of the whole shirt.
        garment.vertices[:segments] = [(x * .96, y, z * .96) for x, y, z in garment.vertices[:segments]]
    if tilted:
        garment.vertices = [(x, y + .02 * x / .16 * max(0., (.65 - y) / .2), z)
                            for x, y, z in garment.vertices]
    original = np.asarray(garment.vertices)
    axis = np.asarray((1., 2., 3.)) / np.sqrt(14.)
    skew = np.asarray(((0., -axis[2], axis[1]), (axis[2], 0., -axis[0]), (-axis[1], axis[0], 0.)))
    rotation = np.eye(3) + np.sin(.7) * skew + (1. - np.cos(.7)) * skew @ skew if rotated else np.eye(3)
    translation = np.asarray((.12, -.35, .2))
    for part in (body, garment):
        part.vertices = (np.asarray(part.vertices) @ rotation.T * scale + translation).tolist()
    mesh = _mesh(body, garment)
    with _bound(mesh) as session:
        _fit(session, tightness=0.)
        fitted = _snapshot(mesh, session)
        _fit(session, tightness=0.)
        np.testing.assert_allclose(_snapshot(mesh, session).submeshes[1].vertices,
                                   fitted.submeshes[1].vertices, atol=1e-7, rtol=0.)
    points = (np.asarray(fitted.submeshes[1].vertices) - translation) @ rotation / scale
    # Contact should expand this hem around the hip, not slide the edge toward
    # the narrower waist until the intersection vanishes.
    assert np.max(np.abs(points[:segments, 1] - original[:segments, 1])) < .002
    _assert_no_surface_crossings(body, fitted.submeshes[1])


def test_clearance_lifts_a_collar_past_a_body_cap_without_widening_it():
    body = _arm(radius=.12)
    collar = _refit_tube_part("collar over shoulder cap", .06, 0., (.49, .5, .51, .53, .55), 32)
    mesh = _mesh(body, collar)
    with _bound(mesh) as session:
        _fit(session, tightness=0.)
        fitted = _snapshot(mesh, session)
    points = np.asarray(fitted.submeshes[1].vertices)
    assert points[:, 1].min() > .5005
    np.testing.assert_allclose(np.linalg.norm(points[:, (0, 2)], axis=1), .06, atol=.001, rtol=0.)
    assert fitted.submeshes[0].vertices == body.vertices
    _assert_no_surface_crossings(body, fitted.submeshes[1])
