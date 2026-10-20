"""Snug fitting through the resident native protocol, without character rules."""
from contextlib import contextmanager
from copy import deepcopy
import math

import pytest

from tests.test_native_mesh_editor_morph_refit import (
    ParsedMesh, _command, _open, _part, _refit_tube_part, _snapshot, _state, mesh_native_core,
)


def _mesh(*parts):
    return ParsedMesh(path="snug-fit.pac", format="pac", submeshes=list(parts),
                      total_vertices=sum(len(p.vertices) for p in parts),
                      total_faces=sum(len(p.faces) for p in parts))


def _sleeve(offset=0.0, segments=32, radius=.1):
    return _refit_tube_part("sleeve", radius, offset, (.1, .15, .2, .25, .3, .35, .4), segments)


def _arm(radius=.06):
    return _refit_tube_part("body", radius, 0., (0., .1, .2, .3, .4, .5), 64, True)


@contextmanager
def _bound(mesh):
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
            "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": list(range(1, len(mesh.submeshes)))})
        yield session
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)


def _fit(session, garments=(1,), tightness=100., **settings):
    return _command(session, "morph_configure_refit", {
        "garment_submesh_indices": list(garments), "clearance_percent": .1,
        "tightness_percent": tightness, **settings,
    })


@pytest.mark.parametrize("offset", (0., .06))
@pytest.mark.parametrize("body_radius", (.06, .09))
def test_snug_fit_contracts_loose_side_and_clears_the_other(offset, body_radius):
    mesh = _mesh(_arm(body_radius), _sleeve(offset, radius=.13))
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
        for ring in range(7):
            points = fitted.submeshes[1].vertices[ring*32:(ring+1)*32]
            assert max(math.hypot(x, z) for x, _, z in points) < body_radius + .02
            winding = sum(math.atan2(a[0]*b[2]-a[2]*b[0], a[0]*b[0]+a[2]*b[2])
                          for a, b in zip(points, points[1:]+points[:1]))
            assert winding == pytest.approx(2*math.pi)
            for a, b in zip(points, points[1:]+points[:1]):
                assert math.hypot((a[0]+b[0])/2, (a[2]+b[2])/2) >= body_radius
        assert fitted.submeshes[0].vertices == mesh.submeshes[0].vertices
        for attr in ("faces", "uvs", "bone_weights", "bone_indices", "name", "material"):
            assert getattr(fitted.submeshes[1], attr) == getattr(mesh.submeshes[1], attr)


def test_tessellation_taper_ellipse_and_folded_opening():
    radii = []
    for segments in (24, 48):
        body, garment = _arm(), _sleeve(segments=segments)
        body.vertices = [(x*(.6+y), y, z*(1.1-.4*y)) for x, y, z in body.vertices]
        garment.vertices = [(x*(1.15 if y == .1 else 1), y, z*(1.15 if y == .1 else 1))
                            for x, y, z in garment.vertices]
        mesh = _mesh(body, garment)
        with _bound(mesh) as session:
            _fit(session)
            positions = _snapshot(mesh, session).submeshes[1].vertices
        # The opening remains flared; lower and upper sections inherit body taper.
        rings = [positions[i*segments:(i+1)*segments] for i in range(7)]
        width = [max(v[0] for v in ring)-min(v[0] for v in ring) for ring in rings]
        depth = [max(v[2] for v in ring)-min(v[2] for v in ring) for ring in rings]
        assert width[0] > width[1] + .012
        assert width[5] > width[1] + .01
        assert depth[3] > width[3] + .008
        radii.append((width[3], depth[3]))
    assert radii[0] == pytest.approx(radii[1], abs=.004)


@pytest.mark.parametrize("segments", (24, 48))
@pytest.mark.parametrize("rotated", (False, True))
def test_clearance_keeps_a_rounded_cover_from_developing_a_point(segments, rotated):
    def body_surface(x, y):
        return -.07 - .05 * math.exp(-(x / .035) ** 2 - ((y - 1.35) / .055) ** 2)

    def patch(name, xs, ys, surface, closed=False):
        vertices = [(x, y, surface(x, y)) for y in ys for x in xs]
        faces = []
        width = len(xs)
        for row in range(len(ys) - 1):
            for column in range(width - 1):
                a = row * width + column
                b, c, d = a + 1, a + width, a + width + 1
                faces.extend(((a, c, b), (b, c, d)))
        if closed:
            count = len(vertices)
            vertices.extend((x, y, .08) for x, y, _ in vertices.copy())
            boundary = {}
            for face in faces:
                for a, b in zip(face, face[1:] + face[:1]):
                    key = tuple(sorted((a, b)))
                    if key in boundary:
                        del boundary[key]
                    else:
                        boundary[key] = (a, b)
            faces.extend(tuple(count + v for v in face[::-1]) for face in faces.copy())
            for a, b in boundary.values():
                faces.extend(((b, a, a + count), (b, a + count, b + count)))
        if rotated:
            vertices = [(z, x, y) for x, y, z in vertices]
        return _part(name, vertices, faces, material=name, texture="")

    body = patch("rounded support", [i * .01 - .22 for i in range(45)],
                 [i * .01 for i in range(171)], body_surface, closed=True)
    garment = patch("rounded cover", [i * .36 / segments - .18 for i in range(segments + 1)],
                    [1.17 + i * .36 / segments for i in range(segments + 1)],
                    lambda x, y: -.10 - .06 * math.exp(-(x / .07) ** 2 - ((y - 1.35) / .09) ** 2))
    mesh = _mesh(body, garment)
    with _bound(mesh) as session:
        _fit(session, clearance_percent=0.)
        conformed = _snapshot(mesh, session)
        _fit(session)
        fitted = _snapshot(mesh, session)
    def undo_rotation(point):
        return (point[1], point[2], point[0]) if rotated else point

    before = [undo_rotation(p) for p in garment.vertices]
    after = [undo_rotation(p) for p in fitted.submeshes[1].vertices]

    def tip_turn(points):
        start = (segments // 2) * (segments + 1)
        row = points[start:start + segments + 1]
        directions = []
        for a, b in zip(row, row[1:]):
            delta = tuple(y - x for x, y in zip(a, b))
            length = math.sqrt(sum(x * x for x in delta))
            directions.append(tuple(x / length for x in delta))
        return max(math.acos(max(-1., min(1., sum(x * y for x, y in zip(a, b)))))
                   for a, b in zip(directions, directions[1:]))

    # The body was already safely inside the cover. Tightening may follow the
    # bulge, but clearance must not replace a rounded tip with a narrow peak.
    assert min(body_surface(x, y) - z for x, y, z in before) > .025
    conformed_points = [undo_rotation(p) for p in conformed.submeshes[1].vertices]
    assert tip_turn(after) < tip_turn(conformed_points) * 1.25
    assert sum(b[2] - a[2] for a, b in zip(before, after)) / len(after) > .02
    for face in garment.faces:
        point = tuple(sum(after[i][axis] for i in face) / 3. for axis in range(3))
        assert point[2] < body_surface(point[0], point[1]) + .0005
    assert fitted.submeshes[0].vertices == body.vertices


def test_layers_material_seams_and_protection_are_retained():
    sleeve = _sleeve()
    first = _part("front", sleeve.vertices, sleeve.faces[:192], material="front", texture="")
    second = _part("back", sleeve.vertices, sleeve.faces[192:], material="back", texture="")
    # Shared vertices are intentionally duplicated across material Parts.
    outer = _sleeve(radius=.11)
    mesh = _mesh(_arm(), first, second, outer)
    with _bound(mesh) as session:
        _fit(session, (1, 2, 3), vertex_masks=[{
            "submesh_index": 1, "vertex_indices": list(range(1, len(sleeve.vertices))),
            "weights": [1.]*(len(sleeve.vertices)-1),
        }])
        fitted = _snapshot(mesh, session)
        assert fitted.submeshes[1].vertices == fitted.submeshes[2].vertices
        assert fitted.submeshes[1].vertices[0] == sleeve.vertices[0]
        for a, b in zip(fitted.submeshes[1].vertices[64:160], fitted.submeshes[3].vertices[64:160]):
            assert math.hypot(b[0], b[2])-math.hypot(a[0], a[2]) > .005


def test_layers_starting_inside_a_larger_body_keep_their_spacing():
    mesh = _mesh(_arm(.08),_sleeve(radius=.06),_sleeve(radius=.07))
    with _bound(mesh) as session:
        _fit(session,(1,2))
        fitted = _snapshot(mesh,session)
        for inner,outer in zip(fitted.submeshes[1].vertices,fitted.submeshes[2].vertices):
            assert math.hypot(inner[0],inner[2]) > .08
            assert math.hypot(outer[0],outer[2])-math.hypot(inner[0],inner[2]) > .005


@pytest.mark.parametrize("constraint", ("free", "protected", "inactive"))
def test_quantized_panel_seams_share_displacement(constraint):
    body = _arm()
    body.vertices = [(x * (.6 + 2*y), y, z * (.6 + 2*y)) for x, y, z in body.vertices]
    sleeve = _sleeve(radius=.13)

    def panel(name, faces, offset):
        used = sorted({vertex for face in faces for vertex in face})
        lookup = {vertex: i for i, vertex in enumerate(used)}
        vertices = [(sleeve.vertices[i][0] + offset, sleeve.vertices[i][1], sleeve.vertices[i][2])
                    for i in used]
        return _part(name, vertices, [tuple(lookup[i] for i in face) for face in faces],
                     material=name, texture=""), lookup

    first, a = panel("lower panel", sleeve.faces[:192], 0.)
    second, b = panel("upper panel", sleeve.faces[192:], .000006)
    seam = sorted(a.keys() & b.keys())
    mesh = _mesh(body, first, second)
    settings = {}
    if constraint == "protected":
        settings["vertex_masks"] = [{"submesh_index": 2,
            "vertex_indices": list(range(1, len(second.vertices))),
            "weights": [1.] * (len(second.vertices) - 1)}]
    with _bound(mesh) as session:
        _fit(session, (1,) if constraint == "inactive" else (1, 2), **settings)
        if constraint == "protected":
            effective = _command(session, "morph_state", {
                "include_effective_vertex_masks": True, "submesh_indices": [1, 2],
            })["effective_vertex_masks"]
            assert effective[0]["weights"][a[seam[0]]] == 0.
            assert effective[1]["weights"][0] == 0.
        fitted = _snapshot(mesh, session)
    for original in seam:
        delta_a = tuple(x-y for x, y in zip(fitted.submeshes[1].vertices[a[original]], first.vertices[a[original]]))
        delta_b = tuple(x-y for x, y in zip(fitted.submeshes[2].vertices[b[original]], second.vertices[b[original]]))
        assert delta_a == pytest.approx(delta_b, abs=4e-6)
    if constraint == "protected":
        assert fitted.submeshes[2].vertices[0] == second.vertices[0]
        assert fitted.submeshes[1].vertices[a[seam[0]]] == first.vertices[a[seam[0]]]
    if constraint == "inactive":
        assert fitted.submeshes[2].vertices == second.vertices
    assert min(math.hypot(x, z) for x, _, z in fitted.submeshes[1].vertices) < .1


def test_close_parallel_opening_edges_do_not_become_a_panel_seam():
    inner, outer = _sleeve(radius=.13), _sleeve(radius=.130006)
    mesh = _mesh(_arm(), inner, outer)
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
    assert fitted.submeshes[2].vertices == outer.vertices
    assert max(math.hypot(x, z) for x, _, z in fitted.submeshes[1].vertices) < .1


@pytest.mark.parametrize("fold_depth", (.005, .023))
def test_folded_hem_moves_with_the_skirt_instead_of_pinning_its_corners(fold_depth):
    body = _refit_tube_part("legs", .05, -.09, (0., .1, .2, .4, .6, 1.), 64, True)
    other = _refit_tube_part("leg", .05, .09, (0., .1, .2, .4, .6, 1.), 64, True)
    offset = len(body.vertices)
    body.faces += [tuple(i + offset for i in face) for face in other.faces]
    body.vertices += other.vertices
    # The first three rings turn back on themselves at the open, pleated hem.
    # Nearest points on two legs produce a varying field across that small fold.
    heights = (.14, .12, .1, .2, .35, .55, .8)
    skirt = _refit_tube_part("skirt", .23, 0., heights, 48)
    skirt.vertices = []
    for ring, (height, radius) in enumerate(zip(heights, (.23, .235, .24, .22, .20, .18, .17))):
        for vertex in range(48):
            angle = 2 * math.pi * vertex / 48
            r = radius + fold_depth * math.cos(6 * angle + ring * .3)
            skirt.vertices.append((r * math.cos(angle), height, r * math.sin(angle)))
    mesh = _mesh(body, skirt)
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session).submeshes[1]
    # All of the folded opening travels inward; isolated pinned corners used to
    # retain a radius above .23 while the adjacent skirt narrowed to about .14.
    assert max(math.hypot(x, z) for x, _, z in fitted.vertices[:144]) < .17
    for vertex in range(48):
        opening, fold, adjacent = (fitted.vertices[ring * 48 + vertex] for ring in range(3))
        assert opening[1] > fold[1] > adjacent[1]
        assert math.dist(opening, adjacent) > .02
    opening = fitted.vertices[:48]
    winding = sum(math.atan2(a[0]*b[2]-a[2]*b[0], a[0]*b[0]+a[2]*b[2])
                  for a, b in zip(opening, opening[1:] + opening[:1]))
    assert winding == pytest.approx(2 * math.pi)
    assert fitted.faces == skirt.faces
    assert fitted.uvs == skirt.uvs


@pytest.mark.parametrize("split_body_seams", (False, True))
def test_hem_follows_the_leg_instead_of_dropping_onto_nearby_feet(split_body_seams):
    silhouettes = []
    for segments in (24, 48):
        vertices, faces = [], []
        for x in (-.09, .09):
            leg = _refit_tube_part("leg", .05, x, (0., .05, .1, .15, .25, .4, 1.), segments, True)
            # A foot extends toward the loose skirt and is closer than the calf.
            # Coarse triangles and duplicated seam vertices must not hide the calf.
            offset = len(vertices)
            vertices += [(xx, y, z * (1 + 2.5 * max(0., 1 - y / .16)) + .1 * max(0., 1 - y / .16))
                         for xx, y, z in leg.vertices]
            faces += [tuple(i + offset for i in face) for face in leg.faces]
        if split_body_seams:
            vertices = [vertices[i] for face in faces for i in face]
            faces = [(i, i + 1, i + 2) for i in range(0, len(vertices), 3)]
        body = _part("legs", vertices, faces, material="body", texture="")
        skirt = _refit_tube_part("skirt", .23, 0., (.17, .20, .24, .35, .55, .8), 48)
        mesh = _mesh(body, skirt)
        with _bound(mesh) as session:
            _fit(session)
            fitted = _snapshot(mesh, session)
        hem = fitted.submeshes[1].vertices[:48]
        assert min(y for _, y, _ in hem) > .155
        assert max(math.hypot(x, z) for x, _, z in hem) < .15
        assert fitted.submeshes[1].faces == skirt.faces
        assert fitted.submeshes[0].vertices == body.vertices
        silhouettes.append(hem)
    for coarse, dense in zip(*silhouettes):
        assert coarse == pytest.approx(dense, abs=.003)


@pytest.mark.parametrize("arm_offset", (.12, .15))
def test_layered_sleeve_clears_a_larger_arm_and_torso_without_spiking(arm_offset):
    body = _refit_tube_part("torso", .12, 0., (.28, .35, .45, .6), 48, True)
    arm = _refit_tube_part("arm", .075, arm_offset, (0., .1, .2, .3, .4, .5), 48, True)
    offset = len(body.vertices)
    body.faces += [tuple(i + offset for i in face) for face in arm.faces]
    body.vertices += arm.vertices
    heights = (.05, .1, .15, .2, .25, .3, .35)
    sleeve = _refit_tube_part("sleeve", .065, arm_offset, heights, 32)
    trim = _refit_tube_part("trim", .068, arm_offset, heights, 48)
    mesh = _mesh(body, sleeve, trim)
    with _bound(mesh) as session:
        _fit(session, (1, 2))
        fitted = _snapshot(mesh, session)
    for before, after in zip(mesh.submeshes[1:], fitted.submeshes[1:]):
        samples = list(after.vertices)
        for face in after.faces:
            triangle = [after.vertices[i] for i in face]
            samples.append(tuple(sum(v[c] for v in triangle) / 3 for c in range(3)))
            samples.extend(tuple((a[c] + b[c]) / 2 for c in range(3))
                           for a, b in zip(triangle, triangle[1:] + triangle[:1]))
        for x, y, z in samples:
            assert not (.28 < y < .6 and math.hypot(x, z) < .12)
            assert not (0. < y < .5 and math.hypot(x - arm_offset, z) < .075)
        # The opening can slide around the combined volume; the lower sleeve
        # still hugs the arm instead of inheriting a uniform maximum inflation.
        assert max(math.hypot(x - arm_offset, z) for x, _, z in after.vertices) < .115
        assert max(math.hypot(x - arm_offset, z) for x, _, z in after.vertices[:64]) < .085
        assert after.faces == before.faces
        assert after.uvs == before.uvs
        assert after.bone_weights == before.bone_weights


@pytest.mark.parametrize("segments", (24, 48))
def test_overlapping_folded_layers_share_fit_without_inflating_or_spiking(segments):
    lining = _sleeve(radius=.1, segments=32)
    panel = _sleeve(radius=.108, segments=segments)
    # Different tessellation and crossing folds model authored overlapping trim,
    # where imposing one hard layer order throughout would be contradictory.
    panel.vertices = [(x * (1 + .11 * math.sin(4 * math.atan2(z, x) + y * 10)), y,
                       z * (1 + .11 * math.sin(4 * math.atan2(z, x) + y * 10)))
                      for x, y, z in panel.vertices]
    mesh = _mesh(_arm(), lining, panel)
    with _bound(mesh) as session:
        _fit(session, (1, 2))
        fitted = _snapshot(mesh, session)
        for before, after in zip(mesh.submeshes[1:], fitted.submeshes[1:]):
            radii = [math.hypot(x, z) for x, _, z in after.vertices]
            assert sum(radii) / len(radii) < .08
            assert min(radii) > .06
            assert after.faces == before.faces
            edges = {tuple(sorted((f[c], f[(c + 1) % 3]))) for f in before.faces for c in range(3)}
            for a, b in edges:
                ratio = math.dist(after.vertices[a], after.vertices[b]) / math.dist(before.vertices[a], before.vertices[b])
                assert .3 < ratio < 1.6
            # The open rings retain their topology, height and winding.
            assert min(v[1] for v in after.vertices) == pytest.approx(.1, abs=.003)
            assert max(v[1] for v in after.vertices) == pytest.approx(.4, abs=.003)
        folded_ring = fitted.submeshes[2].vertices[3 * segments:4 * segments]
        folded_radii = [math.hypot(x, z) for x, _, z in folded_ring]
        assert max(folded_radii) - min(folded_radii) > .018


def test_repeat_percentage_reset_bake_and_history_are_neutral_based():
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        _fit(session, tightness=0.)
        original = _snapshot(mesh, session).submeshes[1].vertices
        assert original == mesh.submeshes[1].vertices
        _fit(session)
        full = _snapshot(mesh, session).submeshes[1].vertices
        _fit(session)
        assert _snapshot(mesh, session).submeshes[1].vertices == full
        _fit(session, tightness=50.)
        half = _snapshot(mesh, session).submeshes[1].vertices
        for a, b, c in zip(original, full, half):
            assert c == pytest.approx(tuple((x+y)/2 for x, y in zip(a, b)), abs=3e-4)
        _command(session, "morph_reset")
        assert _snapshot(mesh, session).submeshes[1].vertices == original
        assert _state(session)["refit"]["garment_settings"][0]["tightness_percent"] == 0.
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert _snapshot(mesh, session).submeshes[1].vertices == half
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        _fit(session)
        _command(session, "morph_bake")
        assert _snapshot(mesh, session).submeshes[1].vertices == full
        assert _state(session)["refit"]["garment_settings"][0]["tightness_percent"] == 0.
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert _state(session)["refit"]["garment_settings"][0]["tightness_percent"] == 100.
        assert _snapshot(mesh, session).submeshes[1].vertices == full
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        _command(session, "morph_reset")
        assert _snapshot(mesh, session).submeshes[1].vertices == full


def test_rigid_components_tighten_independently_of_follow_intensity():
    plate = _part("plate", [(x, y, .13) for x, y in ((-.01,.2),(.01,.2),(.01,.3),(-.01,.3))],
                  [(0,1,2),(0,2,3)], material="plate", texture="")
    mesh = _mesh(_arm(), plate)
    with _bound(mesh) as session:
        _fit(session, mode="rigid_component", intensity_percent=0.)
        fitted = _snapshot(mesh, session).submeshes[1].vertices
        assert max(v[2] for v in fitted) < .07
        for a in range(4):
            for b in range(4):
                assert math.dist(fitted[a], fitted[b]) == pytest.approx(math.dist(plate.vertices[a], plate.vertices[b]), abs=1e-7)


def test_rigid_material_parts_with_quantized_seams_move_as_one_piece():
    parts = []
    for name, left, right in (("left", -.02, 0.), ("right", .000006, .020006)):
        parts.append(_part(name, [(left, .2, .13), (right, .2, .13),
                                  (right, .3, .13), (left, .3, .13)],
                           [(0, 1, 2), (0, 2, 3)], material=name, texture=""))
    mesh = _mesh(_arm(), *parts)
    with _bound(mesh) as session:
        _fit(session, (1, 2), mode="rigid_component")
        fitted = _snapshot(mesh, session)
    original = [point for part in parts for point in part.vertices]
    actual = [point for part in fitted.submeshes[1:] for point in part.vertices]
    assert max(point[2] for point in actual) < .075
    # Preserve the whole accessory, including dimensions across its material seam.
    for a in range(len(original)):
        for b in range(len(original)):
            assert math.dist(actual[a], actual[b]) == pytest.approx(
                math.dist(original[a], original[b]), abs=1e-7)
    assert fitted.submeshes[0].vertices == mesh.submeshes[0].vertices


def test_selected_fit_keeps_the_seam_with_an_inactive_material_part():
    sleeve = _sleeve()
    parts = []
    for positive in (True,False):
        faces = [f for f in sleeve.faces if (sum(sleeve.vertices[i][0] for i in f)>=0) == positive]
        indices = sorted({i for f in faces for i in f})
        mapping = {v:i for i,v in enumerate(indices)}
        parts.append(_part(str(positive),[sleeve.vertices[i] for i in indices],
                           [tuple(mapping[i] for i in f) for f in faces], material="cloth",texture=""))
    shared = set(parts[0].vertices)&set(parts[1].vertices)
    assert shared
    mesh = _mesh(_arm(),*parts)
    with _bound(mesh) as session:
        _fit(session, (1,))
        fitted = _snapshot(mesh,session)
        assert fitted.submeshes[2].vertices == parts[1].vertices
        assert fitted.submeshes[1].vertices != parts[0].vertices
        for i,point in enumerate(parts[0].vertices):
            if point in shared:
                assert fitted.submeshes[1].vertices[i] == pytest.approx(point,abs=1e-8)


@pytest.mark.parametrize("tightness", (0., 100.))
def test_body_slider_following_remains_correct(tightness):
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        # A translation morph makes the body-following contract measurable
        # independently of changes in silhouette or signed clearance.
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a"*64,
            "definitions": [{"definition_id":"move", "label":"Move", "min_percent":0., "max_percent":100., "default_percent":0.}],
            "fields": [{"definition_id":"move", "submesh_index":0,
                        "vertex_indices":list(range(len(mesh.submeshes[0].vertices))),
                        "deltas":[[0., .03, 0.]]*len(mesh.submeshes[0].vertices)}],
        }})
        _fit(session, tightness=tightness)
        before = _snapshot(mesh, session)
        _command(session, "morph_change", {"definition_id":"move", "value":100., "phase":"end", "change_id":"move-fit"})
        after = _snapshot(mesh, session)
        for a, b in zip(before.submeshes[1].vertices, after.submeshes[1].vertices):
            assert b == pytest.approx((a[0],a[1]+.03,a[2]), abs=1e-6)


def test_unreliable_fit_fails_without_partial_settings_or_geometry():
    garment = _sleeve()
    garment.vertices = [(x+3.,y,z) for x,y,z in garment.vertices]
    mesh = _mesh(_arm(), _sleeve(), garment)
    with _bound(mesh) as session:
        before = _state(session)
        report = mesh_native_core.native_mesh_editor_session_command("morph_configure_refit", session, {
            "garment_submesh_indices": [1,2], "tightness_percent": 100., "clearance_percent": .1,
        })
        assert report is None
        assert "Part 2" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)["refit"] == before["refit"]
        assert _snapshot(mesh, session).submeshes[1].vertices == mesh.submeshes[1].vertices


@pytest.mark.parametrize("command", ("morph_change", "morph_apply_preset"))
def test_failed_body_change_with_active_fit_is_atomic(command):
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        _command(session, "morph_upload", {"profile": {
            "profile_id":"fit", "name":"Fit", "topology_fingerprint":"a"*64,
            "definitions":[{"definition_id":"move", "label":"Move", "min_percent":0., "max_percent":100., "default_percent":0.}],
            "fields":[{"definition_id":"move", "submesh_index":0,
                       "vertex_indices":list(range(len(mesh.submeshes[0].vertices))),
                       "deltas":[[.08,0.,0.]]*len(mesh.submeshes[0].vertices)}],
        }})
        _fit(session, vertex_masks=[{"submesh_index":1,"vertex_indices":[],"weights":[]}])
        before = _state(session)
        positions = _snapshot(mesh, session)
        arguments = ({"definition_id":"move", "value":100., "phase":"end", "change_id":"blocked"}
                     if command == "morph_change" else {"values":{"move":100.}, "preset_id":"blocked"})
        assert mesh_native_core.native_mesh_editor_session_command(command, session, arguments) is None
        assert "Part 1" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session) == before
        after = _snapshot(mesh, session)
        assert [p.vertices for p in after.submeshes] == [p.vertices for p in positions.submeshes]


def test_rigid_fit_checks_face_interior_and_rejects_a_pinned_collision():
    plate = _part("plate", [(x,y,.05) for x,y in ((-.08,.2),(.08,.2),(.08,.3),(-.08,.3))],
                  [(0,1,2),(0,2,3)], material="plate", texture="")
    mesh = _mesh(_arm(), plate)
    with _bound(mesh) as session:
        _fit(session, mode="rigid_component", intensity_percent=0.)
        fitted = _snapshot(mesh, session).submeshes[1].vertices
        assert sum(p[2] for p in fitted)/4 > .06
        assert math.dist(fitted[0],fitted[2]) == pytest.approx(math.dist(plate.vertices[0],plate.vertices[2]),abs=1e-7)
        _command(session,"morph_reset")
        before = _state(session)
        assert mesh_native_core.native_mesh_editor_session_command("morph_configure_refit", session, {
            "garment_submesh_indices":[1], "mode":"rigid_component", "tightness_percent":100.,
            "clearance_percent":.1, "vertex_masks":[{"submesh_index":1,"vertex_indices":[],"weights":[]}],
        }) is None
        assert "rigid component cannot clear" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)==before


def test_post_fit_correction_cannot_publish_a_body_intersection():
    mesh = _mesh(_arm(),_sleeve())
    with _bound(mesh) as session:
        _command(session,"morph_upload",{"profile":{
            "profile_id":"fit","name":"Fit","topology_fingerprint":"a"*64,
            "definitions":[{"definition_id":"correct","label":"Correct","min_percent":0.,"max_percent":100.,"default_percent":0.}],
            "fields":[{"definition_id":"correct","stage":"post_refit","submesh_index":1,
                       "vertex_indices":list(range(len(mesh.submeshes[1].vertices))),
                       "deltas":[[0.,0.,.05]]*len(mesh.submeshes[1].vertices)}],
        }})
        _fit(session)
        before = _state(session)
        positions = _snapshot(mesh,session).submeshes[1].vertices
        assert mesh_native_core.native_mesh_editor_session_command("morph_change",session,{
            "definition_id":"correct","value":100.,"phase":"end","change_id":"blocked-correction",
        }) is None
        assert "Part 1" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)==before
        assert _snapshot(mesh,session).submeshes[1].vertices==positions


def test_post_fit_correction_cannot_reverse_authored_layer_order():
    mesh = _mesh(_arm(), _sleeve(), _sleeve(radius=.11))
    with _bound(mesh) as session:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
            "definitions": [{"definition_id": "cross", "label": "Cross",
                             "min_percent": 0., "max_percent": 100., "default_percent": 0.}],
            "fields": [{"definition_id": "cross", "stage": "post_refit", "submesh_index": 1,
                        "vertex_indices": list(range(len(mesh.submeshes[1].vertices))),
                        "deltas": [[x * .2, 0., z * .2] for x, _, z in mesh.submeshes[1].vertices]}],
        }})
        _fit(session, (1, 2))
        before = _state(session)
        positions = _snapshot(mesh, session)
        assert mesh_native_core.native_mesh_editor_session_command("morph_change", session, {
            "definition_id": "cross", "value": 100., "phase": "end", "change_id": "cross-layer",
        }) is None
        assert "layer separation" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session) == before
        assert [p.vertices for p in _snapshot(mesh, session).submeshes] == [p.vertices for p in positions.submeshes]


def test_post_fit_correction_cannot_stretch_a_rigid_component():
    plate = _part("plate",[(x,y,.13) for x,y in ((-.01,.2),(.01,.2),(.01,.3),(-.01,.3))],
                  [(0,1,2),(0,2,3)],material="plate",texture="")
    mesh = _mesh(_arm(),plate)
    with _bound(mesh) as session:
        _command(session,"morph_upload",{"profile":{
            "profile_id":"fit","name":"Fit","topology_fingerprint":"a"*64,
            "definitions":[{"definition_id":"stretch","label":"Stretch","min_percent":0.,"max_percent":100.,"default_percent":0.}],
            "fields":[{"definition_id":"stretch","stage":"post_refit","submesh_index":1,
                       "vertex_indices":list(range(4)),"deltas":[[x,0.,0.] for x,_,_ in plate.vertices]}],
        }})
        _fit(session,mode="rigid_component")
        before=_state(session)
        assert mesh_native_core.native_mesh_editor_session_command("morph_change",session,{
            "definition_id":"stretch","value":100.,"phase":"end","change_id":"blocked-stretch",
        }) is None
        assert "rigid component dimensions" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)==before


def test_native_snapshot_v2_replacement_and_v1_defaults():
    import hashlib
    import json
    from pathlib import Path
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        _fit(session, tightness=73.)
        fitted = _snapshot(mesh, session)
        descriptor = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(session)
        assert descriptor and descriptor["version"] == 2
        target = _open(fitted)
        try:
            assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, descriptor)
            assert _state(target)["refit"]["garment_settings"][0]["tightness_percent"] == 73.
            # A genuine v1 document has no tightness field. Its geometry is retained.
            path = Path(descriptor["path"])
            document = json.loads(path.read_text(encoding="utf-8"))
            document["version"] = 1
            for item in document["runtime"]["refit"]["garment_settings"]:
                item.pop("tightness_percent")
            document["retained_bytes"] = len(json.dumps(document["runtime"]).encode())
            raw = json.dumps(document).encode()
            path.write_bytes(raw)
            legacy = dict(descriptor, version=1, sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw),
                          retained_bytes=document["retained_bytes"])
            assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, legacy)
            assert _state(target)["refit"]["garment_settings"][0]["tightness_percent"] == 0.
            descriptor = legacy
        finally:
            mesh_native_core.close_native_mesh_editor_session(target)
            mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor)
