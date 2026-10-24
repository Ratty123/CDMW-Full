"""Full Tightness fits curved waist sections and their flexible outer layers."""
import numpy as np
import pytest

from tests.test_mesh_refit_layer_boundaries_native import _fitted_mesh
from tests.test_mesh_refit_tightening_native import _assert_no_surface_crossings, _bound, _mesh, _refit_tube_part
from tests.test_native_mesh_editor_morph_refit import _part, _snapshot, _state, mesh_native_core


def _curved_waist():
    heights = (0., .9, 1., 1.05, 1.1, 1.15, 1.2, 1.4, 2.)
    radii = (.12, .12, .12, .09, .06, .07, .09, .12, .12)
    body = _refit_tube_part("curved waist", 1., 0., heights, 64, True)
    body.vertices = [(x * np.interp(y, heights, radii), y, z * np.interp(y, heights, radii))
                     for x, y, z in body.vertices]
    return body, heights, radii


@pytest.mark.parametrize("case", ("cloth", "belt", "rigid-dagger", "removed-dagger"))
@pytest.mark.parametrize("scale,up", ((1., 1), (.1, 0), (10., 2)))
def test_broad_waist_wrap_follows_the_body_at_each_height(case, scale, up):
    body, heights, radii = _curved_waist()
    rows = (1.01, 1.04, 1.07, 1.10, 1.13, 1.16, 1.19)
    cloth = _refit_tube_part("waistcloth", .15, 0., rows, 32)
    parts = [cloth]
    if case != "cloth":
        parts.append(_refit_tube_part("flexible belt", .18, 0., rows, 32))
    settings = {}
    if case in ("rigid-dagger", "removed-dagger"):
        outline = ((1.02, 0.), (1.10, -.012), (1.17, -.02), (1.17, .02), (1.10, .012))
        vertices = [(x, y, z) for x in (.181, .188) for y, z in outline]
        n = len(outline)
        faces = [(0, i + 1, i) for i in range(1, n - 1)]
        faces += [(n, n + i, n + i + 1) for i in range(1, n - 1)]
        for i in range(n):
            j = (i + 1) % n
            faces += [(i, j, n + j), (i, n + j, n + i)]
        parts.append(_part("dagger", vertices, faces if case == "rigid-dagger" else [], material="metal", texture=""))
        settings["garment_settings"] = [{"submesh_index": p, "tightness_percent": 100.,
                                         "clearance_percent": .1,
                                         "mode": "rigid_component" if p == 3 else "surface"}
                                        for p in (1, 2, 3)]
    mesh = _mesh(body, *parts)
    for part in mesh.submeshes:
        part.vertices = [tuple(scale * p[(axis + 1 - up) % 3] for axis in range(3)) for p in part.vertices]
    selected = tuple(range(1, len(parts) + 1)) if case != "removed-dagger" else (1, 2)
    if case == "removed-dagger":
        settings = {}
    fitted = _fitted_mesh(mesh, (0,), selected, **settings)
    def normalized(part):
        return np.asarray(part.vertices)[:, [(axis + up - 1) % 3 for axis in range(3)]] / scale
    inner = normalized(fitted.submeshes[1])
    gaps = np.hypot(inner[:, 0], inner[:, 2]) - np.interp(inner[:, 1], heights, radii)
    assert gaps.min() > 0.
    # Clearance and smoothing over the concave waist allow a small standoff.
    assert gaps.max() < .008, (float(gaps.min()), float(gaps.max()))
    assert inner[:, 1] == pytest.approx(np.repeat(rows, 32), abs=.002)
    if case != "cloth":
        outer = normalized(fitted.submeshes[2])
        gaps = np.hypot(outer[:, 0], outer[:, 2]) - np.hypot(inner[:, 0], inner[:, 2])
        assert gaps.min() > .0003
        assert gaps.max() < .004
    if case in ("rigid-dagger", "removed-dagger"):
        before, after = normalized(mesh.submeshes[3]), normalized(fitted.submeshes[3])
        distances = lambda points: np.linalg.norm(points[:, None] - points[None, :], axis=2)
        assert np.max(np.abs(distances(before) - distances(after))) < 1e-7
        if case == "removed-dagger":
            assert np.array_equal(before, after)
        else:
            assert after[:, 0].mean() < .15
            for support in (0, 1, 2):
                _assert_no_surface_crossings(fitted.submeshes[support], fitted.submeshes[3])


def test_broad_wrap_does_not_bulge_toward_nearby_inward_facing_arms():
    body, heights, radii = _curved_waist()
    arms = [_refit_tube_part("arm", .035, x, (.7, .9, 1.1, 1.3, 1.5), 32, True)
            for x in (-.26, .26)]
    rows = (1.01, 1.04, 1.07, 1.10, 1.13, 1.16, 1.19)
    cloth = _refit_tube_part("waistcloth", .15, 0., rows, 32)
    fitted = _fitted_mesh(_mesh(body, *arms, cloth), (0, 1, 2), (3,))
    points = np.asarray(fitted.submeshes[3].vertices).reshape(7, 32, 3)
    radius = np.hypot(points[:, :, 0], points[:, :, 2])
    gaps = radius - np.interp(points[:, :, 1], heights, radii)
    assert gaps.min() > 0.
    assert gaps.max() < .008
    # The complete circumference must be smooth, including between views.
    radial_bend = np.roll(radius, 1, axis=1) - 2 * radius + np.roll(radius, -1, axis=1)
    assert np.max(np.abs(radial_bend)) < .001


@pytest.mark.parametrize("scale,up", ((1., 1), (.1, 0), (10., 2)))
@pytest.mark.parametrize("closed", (False, True), ids=("turned-open-rim", "solid-wall"))
@pytest.mark.parametrize("layout", ("whole", "material-seam", "pinned-return"))
def test_sloping_rim_keeps_its_authored_thickness_while_layers_fit(scale, up, closed, layout):
    body, heights, radii = _curved_waist()
    rows = (1.01, 1.04, 1.07, 1.10, 1.13, 1.16, 1.19)
    segments = 32
    cloth = _refit_tube_part("cloth with turned rim", .15, 0., rows, segments)
    outer = (len(rows) - 1) * segments
    inner = len(cloth.vertices)
    for s in range(segments):
        angle = 2 * np.pi * s / segments
        # A sloping return samples a different body height from its outer edge.
        cloth.vertices.append((.142 * np.cos(angle), 1.184, .142 * np.sin(angle)))
    for s in range(segments):
        a, b = outer + s, outer + (s + 1) % segments
        c, d = inner + s, inner + (s + 1) % segments
        cloth.faces += [(a, c, d), (a, d, b)]
    if closed:
        back = _refit_tube_part("lining", .142, 0., rows[:-1] + (1.184,), segments)
        offset = len(cloth.vertices)
        cloth.vertices += back.vertices[:-segments]
        remap = list(range(offset, offset + len(back.vertices) - segments)) + list(range(inner, inner + segments))
        cloth.faces += [tuple(remap[i] for i in reversed(face)) for face in back.faces]
        for s in range(segments):
            a, b = s, (s + 1) % segments
            cloth.faces += [(a, b, offset + b), (a, offset + b, offset + a)]
    cloth = _part(cloth.name, cloth.vertices, cloth.faces, material="cloth", texture="")
    belt = _refit_tube_part("outer cloth", .18, 0., rows[:-1], segments)
    parts = [cloth]
    if layout == "material-seam":
        split = 2 * segments * (len(rows) - 1)
        parts = [_part(name, cloth.vertices, faces, material=name, texture="")
                 for name, faces in (("cloth", cloth.faces[:split]), ("rim", cloth.faces[split:]))]
    source = _mesh(body, *parts, belt)
    for part in source.submeshes:
        part.vertices = [tuple(scale * p[(axis + 1 - up) % 3] for axis in range(3)) for p in part.vertices]
    settings = {}
    if layout == "pinned-return":
        mobile = [i for i in range(len(cloth.vertices)) if not inner <= i < inner + segments]
        settings["vertex_masks"] = [{"submesh_index": 1, "vertex_indices": mobile, "weights": [1.] * len(mobile)}]
        # Pinning the oversized inner return while tightening its outer skin
        # would invert the hem. Refuse atomically instead of moving the pins or
        # publishing an inside-out rim with the correct unsigned thickness.
        with _bound(source) as session:
            state = _state(session)
            before = _snapshot(source, session)
            assert mesh_native_core.native_mesh_editor_session_command("morph_configure_refit", session, {
                "garment_submesh_indices": [1, 2], "tightness_percent": 100., "clearance_percent": .1, **settings,
            }) is None
            assert "pinned cloth rim" in mesh_native_core.last_native_mesh_core_job_error()
            assert _state(session) == state
            assert [p.vertices for p in _snapshot(source, session).submeshes] == [p.vertices for p in before.submeshes]
        return
    fitted = _fitted_mesh(source, (0,), tuple(range(1, len(parts) + 2)), **settings)
    if layout == "material-seam":
        assert fitted.submeshes[1].vertices == fitted.submeshes[2].vertices
    before, after = [np.asarray(mesh.submeshes[1].vertices) / scale for mesh in (source, fitted)]
    width = lambda points: np.linalg.norm(points[outer:outer + segments] - points[inner:inner + segments], axis=1)
    assert width(after) == pytest.approx(width(before), abs=2e-5)
    points = after[:, [(axis + up - 1) % 3 for axis in range(3)]]
    gaps = np.hypot(points[:outer, 0], points[:outer, 2]) - np.interp(points[:outer, 1], heights, radii)
    assert gaps.min() > 0.
    # The outer face must leave room for the authored 8 mm inward return.
    # Away from that return, an open sheet still fits as closely as thin cloth.
    assert gaps.max() < .018
    if not closed:
        assert gaps[:4 * segments].max() < .008
    final_cloth = _part("cloth", fitted.submeshes[1].vertices, cloth.faces, material="cloth", texture="")
    for a, b in ((fitted.submeshes[0], final_cloth), (final_cloth, fitted.submeshes[-1]), (final_cloth, final_cloth)):
        _assert_no_surface_crossings(a, b)
