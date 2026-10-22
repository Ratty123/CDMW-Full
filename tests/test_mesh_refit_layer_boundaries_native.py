"""Refit keeps layer spacing and body continuity across Part boundaries."""
import math

import numpy as np
import pytest

from tests.test_mesh_refit_tightening_native import _arm, _assert_no_surface_crossings, _fit, _mesh, _sleeve
from tests.test_native_mesh_editor_morph_refit import (
    _command, _open, _part, _refit_tube_part, _snapshot, mesh_native_core,
)


def _combined_part(name, parts):
    vertices, faces = [], []
    for part in parts:
        offset = len(vertices)
        vertices.extend(part.vertices)
        faces.extend(tuple(index + offset for index in face) for face in part.faces)
    return _part(name, vertices, faces, material="cloth", texture="")


def _fitted_mesh(mesh, drivers, garments, **settings):
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "boundaries", "name": "Boundaries",
            "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": list(drivers)})
        _command(session, "morph_bind", {"garment_submesh_indices": list(garments)})
        _fit(session, garments, **settings)
        fitted = _snapshot(mesh, session)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)

    for index in drivers:
        assert fitted.submeshes[index].vertices == mesh.submeshes[index].vertices
    for before, after in zip(mesh.submeshes, fitted.submeshes):
        for attribute in ("faces", "uvs", "bone_weights", "bone_indices", "name", "material"):
            assert getattr(after, attribute) == getattr(before, attribute)
    return fitted


def _interior_gaps(layers):
    # Rings at y=.20, .25 and .30 are away from the two open sleeve rims.
    return [
        [math.hypot(outer[0], outer[2]) - math.hypot(inner[0], inner[2])
         for inner, outer in zip(inner_layer[64:160], outer_layer[64:160])]
        for inner_layer, outer_layer in zip(layers, layers[1:])
    ]


@pytest.mark.parametrize("tightness", (0., 50., 100.))
def test_flexible_belt_takes_up_layer_slack_without_crossing_the_wrap(tightness):
    inner, belt = _sleeve(radius=.10), _sleeve(radius=.13)
    mesh = _mesh(_arm(), inner, belt)
    fitted = _fitted_mesh(mesh, (0,), (1, 2), tightness=tightness)
    layers = [part.vertices for part in fitted.submeshes[1:]]
    gaps = _interior_gaps(layers)[0]
    if tightness == 0.:
        assert fitted.submeshes[1].vertices == inner.vertices
        assert fitted.submeshes[2].vertices == belt.vertices
    else:
        # The requested fit should remove slack, while keeping real separation.
        assert min(gaps) > .0003
        assert max(gaps) < (.019 if tightness == 50. else .003)
        for part in fitted.submeshes[1:]:
            for face in part.faces:
                corners = [part.vertices[i] for i in face]
                samples = corners + [tuple(sum(v[c] for v in corners) / 3 for c in range(3))]
                assert min(math.hypot(x, z) for x, _, z in samples) > .06


@pytest.mark.parametrize("solid,short_band", ((False, False), (True, False), (True, True)),
                         ids=("sheet", "solid-trim", "short-solid-band"))
def test_coarse_belt_faces_clear_the_wrap_even_when_their_corners_started_outside(solid, short_band):
    # The eight-sided belt's chords cut the finer wrap despite clear corners.
    heights = (.22, .24, .26) if short_band else (.1, .15, .2, .25, .3, .35, .4)
    outer = _refit_tube_part("belt", .105, 0., heights, 8)
    if solid:
        back = _refit_tube_part("belt back", .103, 0., heights, 8)
        count = len(outer.vertices)
        outer.vertices += back.vertices
        outer.faces += [tuple(count + i for i in reversed(face)) for face in back.faces]
        for row, reverse in ((0, False), (len(heights) - 1, True)):
            for i in range(8):
                a, b = row * 8 + i, row * 8 + (i + 1) % 8
                caps = ((a, b, count + b), (a, count + b, count + a))
                outer.faces += [tuple(reversed(face)) if reverse else face for face in caps]
        outer = _part("solid belt", outer.vertices, outer.faces, material="belt", texture="")
    mesh = _mesh(_arm(), _sleeve(radius=.10), outer)
    fitted = _fitted_mesh(mesh, (0,), (1, 2))
    wrap = fitted.submeshes[1]
    triangles = np.asarray(wrap.vertices)[np.asarray(wrap.faces)]
    edge1, edge2 = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    belt = fitted.submeshes[2]
    assert max(math.hypot(x, z) for x, _, z in belt.vertices) < .075
    if short_band:
        wall = len(belt.vertices) // 2
        thickness = [math.dist(a, b) for a, b in zip(belt.vertices[:wall], belt.vertices[wall:])]
        # Keep distinct skins within the existing twofold clearance-strain bound.
        assert min(thickness) > .0005 and max(thickness) < .004, (min(thickness), max(thickness))
    # An eight-sided shell needs extra room at its corners for its straight
    # chords to enclose the finer wrap. That is geometry, rather than slack.
    maximum_gap = .002 + .06 * (1. / math.cos(math.pi / 8) - 1.) + (.002 if solid else 0.)
    for face in belt.faces:
        corners = [belt.vertices[i] for i in face]
        if not .19 < sum(v[1] for v in corners) / 3 < .31:
            continue
        samples = corners + [tuple((a[c] + b[c]) / 2 for c in range(3))
                             for a, b in zip(corners, corners[1:] + corners[:1])]
        samples.append(tuple(sum(v[c] for v in corners) / 3 for c in range(3)))
        for point in samples:
            # Both layers can bend. Compare the actual wrap at this ray rather
            # than demanding the belt circumscribe the wrap's largest radius.
            origin = np.asarray((0., point[1], 0.))
            direction = np.asarray(point) - origin
            h = np.cross(direction, edge2)
            determinant = np.sum(edge1 * h, axis=1)
            valid = np.abs(determinant) > 1e-13
            inverse = np.zeros_like(determinant)
            inverse[valid] = 1. / determinant[valid]
            offset = origin - triangles[:, 0]
            u = inverse * np.sum(offset * h, axis=1)
            q = np.cross(offset, edge1)
            v = inverse * np.sum(direction * q, axis=1)
            distance = inverse * np.sum(edge2 * q, axis=1)
            hits = valid & (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1. + 1e-8) & (distance > 0.)
            assert hits.any()
            gap = (1. - distance[hits].max()) * np.linalg.norm(direction)
            assert .0002 < gap < maximum_gap
            assert math.hypot(point[0], point[2]) > .06


def test_crossing_hanging_ribbons_keep_their_authored_fold():
    body = _part("body", [(-.2, 0., 0.), (.2, 0., 0.), (.2, .5, 0.), (-.2, .5, 0.)],
                 [(0, 1, 2), (0, 2, 3)], material="skin", texture="")
    vertices, faces = [], []
    for y, z in ((.1, .08), (.2, .105), (.3, .075), (.4, .08)):
        vertices.extend(((-.02, y, z), (.02, y, z)))
    for row in range(3):
        a = row * 2
        faces.extend(((a, a + 1, a + 3), (a, a + 3, a + 2)))
    folded = _part("folded ribbon", vertices, faces, material="cloth", texture="")
    outer = _part("crossing ribbon", [(-.025, .1, .09), (.025, .1, .09),
                                      (.025, .4, .09), (-.025, .4, .09)],
                  [(0, 1, 2), (0, 2, 3)], material="cloth", texture="")
    fitted = _fitted_mesh(_mesh(body, folded, outer), (0,), (1, 2))
    assert max(z for _, _, z in fitted.submeshes[1].vertices) - min(
        z for _, _, z in fitted.submeshes[1].vertices) > .015
    assert all(z > 0. for part in fitted.submeshes[1:] for _, _, z in part.vertices)


def test_tight_waist_band_retains_its_height_contour_on_a_tapered_body():
    body = _arm()
    body.vertices = [(x * (1. + y), y, z * (1. + .3 * y)) for x, y, z in body.vertices]
    band = _refit_tube_part("waist band", .13, 0., (.22, .24, .26), 32)
    band.vertices = [(x, y + .004 * x / .13, z) for x, y, z in band.vertices]
    fitted = _fitted_mesh(_mesh(body, band), (0,), (1,))
    shifts = [after[1] - before[1] for before, after in zip(band.vertices, fitted.submeshes[1].vertices)]
    assert max(shifts) - min(shifts) < 2e-5
    assert max(math.hypot(x, z) for x, _, z in fitted.submeshes[1].vertices) < .09


def _waist_rope(radius=.131, thickness=.002, segments=32):
    sides = 8
    vertices = []
    for segment in range(segments):
        angle = 2. * math.pi * segment / segments
        for side in range(sides):
            section = 2. * math.pi * side / sides
            r = radius + thickness * math.cos(section)
            vertices.append((r * math.cos(angle), .24 + thickness * math.sin(section),
                             r * math.sin(angle)))
    faces = []
    for segment in range(segments):
        for side in range(sides):
            a = segment * sides + side
            b = ((segment + 1) % segments) * sides + side
            c = ((segment + 1) % segments) * sides + (side + 1) % sides
            d = segment * sides + (side + 1) % sides
            faces.extend(((a, b, c), (a, c, d)))
    return _part("rope detail", vertices, faces, material="trim", texture="")


@pytest.mark.parametrize("hanging_tail", (False, True))
def test_thin_rope_remains_visible_above_a_snug_fitted_waist_band(hanging_tail):
    body = _arm()
    body.vertices = [(x * (1. + y), y, z * (1. + .3 * y)) for x, y, z in body.vertices]
    band = _refit_tube_part("waist band", .13, 0., (.20, .24, .28), 32)
    if hanging_tail:
        tail = _part("hanging tail", [(-.1302, y, z) for y in (-.16, .05, .15, .24)
                                      for z in (-.04, .04)],
                     [(a, a + 1, a + 3) for a in (0, 2, 4)]
                     + [(a, a + 3, a + 2) for a in (0, 2, 4)], material="cloth", texture="")
        # Exported trim can retain duplicate skins. Its area must not make the
        # tail's independent leg-following field a backing for the waist rope.
        tail.faces *= 2
        band = _combined_part("band and tail", (band, tail))
    rope = _waist_rope()
    mesh = _mesh(body, _sleeve(), band, rope)
    fitted = _fitted_mesh(mesh, (0,), (1, 2, 3))
    band_points, rope_points = [np.asarray(p.vertices) for p in fitted.submeshes[2:]]
    # The source rope is partly inset in the band. Preserve its visible outer
    # profile; merely keeping both pieces outside the cloth misses this bug.
    for segment in range(32):
        band_radius = np.linalg.norm(band_points[32 + segment, (0, 2)])
        section = rope_points[segment * 8:(segment + 1) * 8]
        radii = np.linalg.norm(section[:, (0, 2)], axis=1)
        assert radii.max() - band_radius > .0015
        assert radii.max() - radii.min() > .003
    assert max(np.linalg.norm(band_points[:96, (0, 2)], axis=1)) < .09


def test_rope_follows_both_adjoining_band_panels_after_rebinding():
    panels = []
    for start, radius in ((0., .13), (180., .1304)):
        angles = [math.radians(start + step * 10.) for step in range(23)]
        vertices = [(radius * math.cos(a), y, radius * math.sin(a))
                    for y in (.20, .24, .28) for a in angles]
        faces = []
        for row in range(2):
            for column in range(22):
                a = row * 23 + column
                faces.extend(((a, a + 23, a + 24), (a, a + 24, a + 1)))
        panels.append(_part("adjoining band panel", vertices, faces, material="cloth", texture=""))
    band = _combined_part("overlapping front and back", panels)
    mesh = _mesh(_arm(), _sleeve(), band, _waist_rope(thickness=.0015))
    fitted = _fitted_mesh(mesh, (0,), (1, 2, 3))
    v = np.asarray(fitted.submeshes[2].vertices)
    triangles = v[np.asarray(band.faces)]
    e1, e2 = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    for point in np.asarray(fitted.submeshes[3].vertices)[::8]:
        origin = np.asarray((0., point[1], 0.))
        direction = point - origin
        h = np.cross(direction, e2)
        determinant = np.einsum("ij,ij->i", e1, h)
        valid = np.abs(determinant) > 1e-13
        inverse = np.zeros_like(determinant)
        inverse[valid] = 1. / determinant[valid]
        offset = origin - triangles[:, 0]
        u = inverse * np.einsum("ij,ij->i", offset, h)
        q = np.cross(offset, e1)
        z = inverse * (q @ direction)
        distance = inverse * np.einsum("ij,ij->i", e2, q)
        hits = valid & (u >= -1e-8) & (z >= -1e-8) & (u + z <= 1. + 1e-8) & (distance > 0.)
        assert hits.any()
        assert (1. - distance[hits].max()) * np.linalg.norm(direction) > .0005


def test_attached_tubular_trim_turns_with_a_sloping_backing():
    body = _arm()
    body.vertices = [(x * (.5 + 5 * y), y, z * (.5 + 5 * y)) for x, y, z in body.vertices]
    rope = _waist_rope()
    # A short tubular detail near the +X tangent, including its inset side.
    used = [segment * 8 + side for segment in (31, 0, 1) for side in range(8)]
    remap = {vertex: local for local, vertex in enumerate(used)}
    trim = _part("tubular trim", [rope.vertices[i] for i in used],
                 [tuple(remap[i] for i in face) for face in rope.faces
                  if all(i in remap for i in face)], material="trim", texture="")
    band = _refit_tube_part("band backing", .13, 0., (.20, .24, .28), 32)
    fitted = _fitted_mesh(_mesh(body, band, trim), (0,), (1, 2))
    points = np.asarray(fitted.submeshes[2].vertices)
    thickness = points[8] - points[12]
    # The cone's outward normal tilts down with slope -.3. A fixed world-space
    # offset would leave this cross-section horizontal and bury its lower side.
    assert -.4 < thickness[1] / thickness[0] < -.2
    assert np.linalg.norm(thickness) == pytest.approx(.004, abs=.00015)


def test_touching_compact_knot_islands_share_one_backing_motion():
    body = _arm()
    body.vertices = [(x * (.5 + 5 * y), y, z * (.5 + 5 * y)) for x, y, z in body.vertices]
    rope = _waist_rope(segments=64)
    used = list(range(16))
    trim = _part("short knot strand", [rope.vertices[i] for i in used],
                 [face for face in rope.faces if all(i in used for i in face)],
                 material="trim", texture="")
    other = _part("touching strand", [(x, y + .001, z + .002) for x, y, z in trim.vertices],
                  trim.faces, material="trim", texture="")
    knot = _combined_part("unwelded knot", (trim, other))
    band = _refit_tube_part("band backing", .13, 0., (.20, .24, .28), 32)
    fitted = _fitted_mesh(_mesh(body, band, knot), (0,), (1, 2))
    before, after = np.asarray(knot.vertices), np.asarray(fitted.submeshes[2].vertices)
    source_distances = np.linalg.norm(before[:, None] - before[None, :], axis=2)
    fitted_distances = np.linalg.norm(after[:, None] - after[None, :], axis=2)
    assert np.max(np.abs(source_distances - fitted_distances)) < 1e-8
    assert np.max(np.linalg.norm(after - before, axis=1)) > .005


@pytest.mark.parametrize("repeated_draw_faces", (False, True))
def test_open_rolled_band_edges_do_not_cross_their_own_surface(repeated_draw_faces):
    profile = ((-.02, .130), (-.014, .137), (-.017, .132),
               (.014, .130), (.017, .136), (.02, .130))
    segments = 16
    vertices = [(radius * math.cos(2 * math.pi * s / segments),
                 .24 + height + .002 * math.sin(2 * math.pi * s / segments),
                 radius * math.sin(2 * math.pi * s / segments))
                for height, radius in profile for s in range(segments)]
    faces = []
    for row in range(len(profile) - 1):
        for s in range(segments):
            a, b = row * segments + s, row * segments + (s + 1) % segments
            faces.extend(((a, b, b + segments), (a, b + segments, a + segments)))
    if repeated_draw_faces:
        faces *= 2
    band = _part("open rolled band", vertices, faces, material="cloth", texture="")
    _assert_no_surface_crossings(band, band)
    fitted = _fitted_mesh(_mesh(_arm(), band), (0,), (1,))
    after = fitted.submeshes[1]
    _assert_no_surface_crossings(after, after)
    _assert_no_surface_crossings(fitted.submeshes[0], after)
    assert max(math.hypot(x, z) for x, _, z in after.vertices) < .09


def test_partial_waist_band_protection_keeps_the_pinned_vertex():
    band = _refit_tube_part("waist band", .13, 0., (.22, .24, .26), 32)
    fitted = _fitted_mesh(_mesh(_arm(), band), (0,), (1,), vertex_masks=[{
        "submesh_index": 1, "vertex_indices": list(range(1, len(band.vertices))),
        "weights": [1.] * (len(band.vertices) - 1),
    }])
    assert fitted.submeshes[1].vertices[0] == band.vertices[0]
    assert fitted.submeshes[1].vertices[32:] != band.vertices[32:]


@pytest.mark.parametrize("layer_count", (2, 3), ids=("two-layers", "three-layers"))
def test_disconnected_layers_keep_spacing_when_packed_in_one_part(layer_count):
    gap_results = {}
    for packed in (False, True):
        sleeves = [_sleeve(radius=.10 + layer * .01) for layer in range(layer_count)]
        vertices_per_layer = len(sleeves[0].vertices)
        garments = [_combined_part("nested sleeves", sleeves)] if packed else sleeves
        mesh = _mesh(_arm(), *garments)
        fitted = _fitted_mesh(mesh, (0,), tuple(range(1, len(mesh.submeshes))))
        if packed:
            positions = fitted.submeshes[1].vertices
            layers = [positions[index * vertices_per_layer:(index + 1) * vertices_per_layer]
                      for index in range(layer_count)]
        else:
            layers = [part.vertices for part in fitted.submeshes[1:]]
        # Returning unchanged garment positions must not satisfy the spacing check.
        assert max(math.hypot(x, z) for x, _, z in layers[0][64:160]) < .08
        gap_results[packed] = _interior_gaps(layers)

    metrics = {
        "one_part" if packed else "separate_parts": [
            {"min_gap": min(gaps), "mean_gap": sum(gaps) / len(gaps),
             "max_gap": max(gaps)}
            for gaps in adjacent_layers
        ]
        for packed, adjacent_layers in gap_results.items()
    }
    packing_difference = max(
        abs(packed_gap - separate_gap)
        for packed_gaps, separate_gaps in zip(gap_results[True], gap_results[False])
        for packed_gap, separate_gap in zip(packed_gaps, separate_gaps)
    )
    detail = f"layers={layer_count}, {metrics=}, {packing_difference=}"

    # Tightness takes up the .01 authored slack, but must retain a real gap.
    # Packing may change that gap by at most .0002, rather than collapsing
    # disconnected islands merely because they share a material Part.
    assert all(min(gaps) >= .0004 and max(gaps) < .002
               for adjacent_layers in gap_results.values() for gaps in adjacent_layers), detail
    assert packing_difference <= .0002, detail


def _body_with_split_calf_seams(upper_offset):
    vertices, faces = [], []
    for x in (-.09, .09):
        leg = _refit_tube_part("leg", .05, x, (0., .05, .1, .15, .25, .4, 1.), 24, True)
        offset = len(vertices)
        # Identical foot shape to the existing hem-following regression. The foot
        # is closer to a loose hem than the calf but is the wrong fitting surface.
        vertices.extend((xx, y, z * (1 + 2.5 * max(0., 1 - y / .16))
                         + .1 * max(0., 1 - y / .16)) for xx, y, z in leg.vertices)
        faces.extend(tuple(index + offset for index in face) for face in leg.faces)

    parts = []
    for upper in (False, True):
        selected = [face for face in faces
                    if (sum(vertices[index][1] for index in face) / 3. >= .15) == upper]
        used = sorted({index for face in selected for index in face})
        remap = {index: local for local, index in enumerate(used)}
        shift = upper_offset if upper else 0.
        positions = [(vertices[index][0] + shift, vertices[index][1], vertices[index][2])
                     for index in used]
        parts.append(_part("upper body" if upper else "lower body", positions,
                           [tuple(remap[index] for index in face) for face in selected],
                           material="body", texture=""))
    return parts


def _calf_test_skirt(half_step):
    skirt = _refit_tube_part("skirt", .23, 0., (.17, .20, .24, .35, .55, .8), 48)
    if half_step:
        # Half a segment keeps the circular skirt centered while avoiding
        # samples exactly equidistant from the two disconnected legs.
        angle = math.pi / 48
        cosine, sine = math.cos(angle), math.sin(angle)
        skirt.vertices = [(x * cosine - z * sine, y, x * sine + z * cosine)
                          for x, y, z in skirt.vertices]
    return skirt


@pytest.mark.parametrize("half_step", (False, True), ids=("symmetric-hem", "offset-samples"))
def test_near_matching_body_seams_keep_the_hem_on_the_calf(half_step):
    results = {}
    for upper_offset in (0., .000001, .000006):
        body_parts = _body_with_split_calf_seams(upper_offset)
        mesh = _mesh(*body_parts, _calf_test_skirt(half_step))
        fitted = _fitted_mesh(mesh, (0, 1), (2,))
        results[upper_offset] = fitted.submeshes[2].vertices

    exact = results[0.]
    metrics = {
        offset: {
            "min_hem_y": min(y for _, y, _ in positions[:48]),
            "max_hem_radius": max(math.hypot(x, z) for x, _, z in positions[:48]),
            "max_vertex_displacement": max(math.dist(before, after)
                                           for before, after in zip(exact, positions)),
        }
        for offset, positions in results.items()
    }
    # Keep the existing .155 hem-height and .15 radius contracts. A precision-size
    # body seam offset must not switch the hem onto the feet.
    assert all(result["min_hem_y"] > .155 for result in metrics.values()), metrics
    assert all(result["max_hem_radius"] < .15 for result in metrics.values()), metrics
    if half_step:
        # The original symmetric witness has vertices on the legs' medial plane.
        # Tiny translations legitimately change their closest disconnected leg,
        # so that witness checks the hem rather than demanding a fixed leg choice.
        # Offset samples isolate seam continuity for the full-geometry comparison.
        # The unchanged .001 tolerance is 0.1% of the synthetic body's height.
        assert all(result["max_vertex_displacement"] <= .001
                   for result in metrics.values()), metrics


def test_ambiguous_body_seam_candidates_do_not_create_a_connection():
    results = {}
    for offset in (.000006, .0001):
        lower, upper_positive = _body_with_split_calf_seams(offset)
        _, upper_negative = _body_with_split_calf_seams(-offset)
        mesh = _mesh(lower, upper_positive, upper_negative, _calf_test_skirt(True))
        fitted = _fitted_mesh(mesh, (0, 1, 2), (3,))
        results[offset] = fitted.submeshes[3].vertices

    near, outside_tolerance = results[.000006], results[.0001]
    metrics = {
        "near_min_hem_y": min(y for _, y, _ in near[:48]),
        "outside_tolerance_min_hem_y": min(y for _, y, _ in outside_tolerance[:48]),
        "max_vertex_displacement": max(math.dist(a, b) for a, b in zip(near, outside_tolerance)),
    }
    # Both near upper Parts offer a compatible reversed edge for each lower rim
    # edge. Neither match is unique. Keep the same disconnected behavior as the
    # control outside matching tolerance instead of guessing a body connection.
    # This asserts conservative matching, not fit quality for overlapping bodies.
    assert metrics["max_vertex_displacement"] <= .001, metrics


def test_close_parallel_layer_rims_in_one_part_keep_independent_masks():
    inner, outer = _sleeve(radius=.13), _sleeve(radius=.130006)
    packed = _combined_part("close layers", (inner, outer))
    mesh = _mesh(_arm(), packed)
    # Close, equally directed boundary edges are separate layers, not a seam.
    # A false seam would propagate the protected outer island's zero influence
    # to the inner rim. Layer links may still legitimately limit how far the
    # movable island travels, so inspect effective masks rather than its radius.
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "close rims", "name": "Close rims",
            "topology_fingerprint": "a" * 64, "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": [1]})
        _fit(session, (1,), vertex_masks=[{
            "submesh_index": 1, "vertex_indices": list(range(len(inner.vertices))),
            "weights": [1.] * len(inner.vertices),
        }])
        effective = _command(session, "morph_state", {
            "include_effective_vertex_masks": True, "submesh_indices": [1],
        })["effective_vertex_masks"]
        assert len(effective) == 1
        assert effective[0]["weights"] == [1.] * len(inner.vertices) + [0.] * len(outer.vertices)
        fitted = _snapshot(mesh, session)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)
    outer_after = fitted.submeshes[1].vertices[len(inner.vertices):]
    assert outer_after == outer.vertices
    assert fitted.submeshes[0].vertices == mesh.submeshes[0].vertices
    for attribute in ("faces", "uvs", "bone_weights", "bone_indices", "name", "material"):
        assert getattr(fitted.submeshes[1], attribute) == getattr(packed, attribute)
