"""Refit keeps layer spacing and body continuity across Part boundaries."""
import math

import pytest

from tests.test_mesh_refit_tightening_native import _arm, _fit, _mesh, _sleeve
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

    # Fixed before testing the solver change: retain at least 95% of the .01
    # authored gap at every interior sample. Packing may change a gap by at most
    # .0002 (2% of that gap), allowing numerical variation without hiding collapse.
    assert all(min(gaps) >= .0095
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
