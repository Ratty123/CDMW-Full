"""Full Tightness fits curved waist sections and their flexible outer layers."""
import numpy as np
import pytest

from tests.test_mesh_refit_layer_boundaries_native import _fitted_mesh
from tests.test_mesh_refit_tightening_native import _assert_no_surface_crossings, _mesh, _refit_tube_part
from tests.test_native_mesh_editor_morph_refit import _part


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
